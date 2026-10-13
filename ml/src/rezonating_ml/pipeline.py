"""The pack pipeline (D-021): the stages a ``pack.json`` names, chunked and stateful.

Stages, in order:

1. ``decimate``: the D-016 FIR + ÷2 (:class:`rezonating_ml.dsp.Decimator2`) when the input runs at twice the pack
   rate (the 2 kSPS ``adc_raw`` recordings of D-020 for a 1 kSPS pack); ``bypassed`` when the input already runs
   at the pack rate (the live ``adc_dec`` stream, or the 2000 Hz ADXL355 for the appliance pack).
2. ``dsp``: the pack's ``dsp`` list as biquads (:func:`rezonating_ml.dsp.filter_chain_from_pack`).
3. ``trigger``: STA/LTA (:class:`rezonating_ml.trigger.StaLta`) for ``type: sta_lta``; other trigger types are
   ``not_available`` for now.
4. ``features``: ``footstep_v1`` (:func:`rezonating_ml.features.footstep_v1`) on ``filtered[start:end]`` of every
   reported window with ``n_invalid == 0``; windows with ``n_invalid > 0`` are skipped and counted
   (``n_windows_skipped_invalid``). Another feature set name is ``not_available`` (output ``None``), as is any
   feature set when the trigger stage is not available.
5. ``model``: an in-memory classifier passed to :func:`build_pipeline` (``predict``, ``predict_proba`` and
   ``classes_``, e.g. :func:`rezonating_ml.baseline.train_baseline_model`), run once per feature window, the way the
   node runs it. Without one the stage is ``not_available`` (output ``None``): the pack names ``model.tflite``,
   and TFLite export and inference come later.

The Lab greys out the ``not_available`` stages from :attr:`Pipeline.stages`.

``Pipeline.process(chunk)`` takes any chunk size (including 0) and returns only the new output; at the end of the
stream, :meth:`Pipeline.finish` reports the event windows still open. Concatenating the chunk outputs and the
``finish()`` output (:func:`concat_outputs`) is byte-identical to :func:`run_pipeline` on the whole input, because
every stage computes each output sample with the same float32 operations whatever the chunking.

Indices: ``decimated``, ``filtered``, ``ratio`` and the events are in pack-rate samples from the start of the
stream; ``PipelineOutput.start_index`` is the index of the chunk's first output sample.
:meth:`Pipeline.to_input_index` maps a pack-rate index back to the input stream (``2k - 30`` when decimating).

Event windows (every event is accounted for)
--------------------------------------------
``events`` come in the chunk that holds their onset (``n_invalid`` still ``None``). ``windows`` repeats **every**
event exactly once, with ``n_invalid`` set (:func:`rezonating_ml.trigger.window_n_invalid`): in the chunk where its
window ``[start, end)`` is complete, or in the ``finish()`` output when the stream ends first; samples past the end
of the stream count as invalid there, as samples before index 0 always do. The features stage reads ``windows``
and skips those with ``n_invalid > 0`` (:mod:`rezonating_ml.trigger`). Counters, at any time:
``n_events == n_windows + n_windows_pending``; ``n_windows_invalid`` of the reported windows are skipped, and
``n_windows_cut`` of those were cut by the end of the stream. After ``finish()``, ``n_windows_pending == 0``.

Lost samples and the mask contract
----------------------------------
``process(chunk, valid)`` takes one bool per input sample (``False`` = lost). The decimator holds the previous
good sample inside the FIR and marks every output whose FIR window held a lost sample as invalid
(``tools/lab/PROTOCOL.md``, ``adc_dec``); the ``dsp`` filters and the trigger skip invalid samples (no state
update, output 0, never "low" or "high"). ``PipelineOutput.valid`` says which pack-rate samples are valid.

The one thing a mask must guarantee is **coverage: every lost sample is marked** ``False``. The two directions are
not alike. A lost sample marked valid is fed in as data: a zero-filled gap becomes a step through the high-pass and
can trigger a false event. A good sample marked lost only costs data: the outputs it reaches are invalid and a window
over it is skipped and counted. On the node the mask is exact (the firmware knows which samples it lost). For a
recording, :func:`zero_fill_mask` rebuilds it from the WAV and the sidecar's ``loss`` total, and says which
guarantee it could establish (:class:`ZeroFillMask`).

The sample rates are nominal. The ADC 15 Click clock is off by up to about 1.65 %, so a recording's measured
rate (sidecar) differs slightly; the filters are designed for the nominal rate, as on the node.
"""

from __future__ import annotations

import json
import os
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from .dsp import DECIM_FACTOR, Decimator2, dec_to_raw_index, filter_chain_from_pack
from .features import N_FEATURES, N_FFT, footstep_v1
from .trigger import Event, StaLta, StaLtaParams

__all__ = [
    "NOT_AVAILABLE",
    "STAGE_NAMES",
    "LostSampleMismatch",
    "ModelOutput",
    "Pipeline",
    "PipelineOutput",
    "Stage",
    "ZeroFillMask",
    "build_pipeline",
    "concat_outputs",
    "run_pipeline",
    "sidecar_lost_total",
    "valid_from_zero_fill",
    "zero_fill_mask",
]

OK = "ok"
BYPASSED = "bypassed"
NOT_AVAILABLE = "not_available"
STAGE_NAMES = ("decimate", "dsp", "trigger", "features", "model")


@dataclass(frozen=True)
class Stage:
    """Status of one stage: ``ok``, ``bypassed`` (passes samples through) or ``not_available`` (output ``None``)."""

    name: str
    status: str
    detail: str

    @property
    def available(self) -> bool:
        return self.status != NOT_AVAILABLE


@dataclass(frozen=True)
class ModelOutput:
    """Model stage output for the feature windows of one output, in ``feature_windows`` order.

    ``classes``: the model's ``classes_`` as strings (the columns of ``proba``); ``labels``: ``(k,)`` the predicted
    class per window (``model.predict``), as strings; ``proba``: ``(k, len(classes))`` float32
    (``model.predict_proba``).
    """

    classes: tuple[str, ...]
    labels: tuple[str, ...]
    proba: np.ndarray

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ModelOutput):
            return NotImplemented
        return (
            self.classes == other.classes
            and self.labels == other.labels
            and self.proba.dtype == other.proba.dtype
            and self.proba.shape == other.proba.shape
            and self.proba.tobytes() == other.proba.tobytes()
        )

    __hash__ = None  # type: ignore[assignment]


@dataclass(frozen=True)
class PipelineOutput:
    """Output of one :meth:`Pipeline.process` call (or of the batch call).

    ``decimated``, ``filtered`` and ``ratio`` are ``(m,)`` float32 at the pack rate, aligned with each other and
    starting at pack-rate index ``start_index``; ``valid`` is ``(m,)`` bool (``False``: a lost input sample reached
    this sample; ``filtered`` and ``ratio`` are 0 there, ``decimated`` holds the hold-previous FIR value the node
    computes but does not send). ``events``: trigger events whose onset is in this chunk (``n_invalid`` is
    ``None``); ``windows``: events whose window ``[start, end)`` became complete in this chunk, with ``n_invalid``
    set (in the :meth:`Pipeline.finish` output: the windows the end of the stream cut, with no samples).
    ``ratio``, ``events`` and ``windows`` are ``None`` when the trigger stage is not available.
    ``features``: ``(k, N_FEATURES)`` float32, one row per ``feature_windows`` entry: the windows of ``windows``
    with ``n_invalid == 0``, in the same order (columns: :data:`rezonating_ml.features.FEATURE_NAMES`).
    ``model``: the model stage output for those rows. Each of these is ``None`` when its stage is not available
    (see ``stages``).
    """

    start_index: int
    decimated: np.ndarray
    valid: np.ndarray
    filtered: np.ndarray
    ratio: np.ndarray | None
    events: tuple[Event, ...] | None
    windows: tuple[Event, ...] | None
    features: np.ndarray | None
    feature_windows: tuple[Event, ...] | None
    model: ModelOutput | None
    stages: tuple[Stage, ...]

    def stage(self, name: str) -> Stage:
        return next(s for s in self.stages if s.name == name)


def _load_pack(pack_json: Mapping[str, Any] | str | os.PathLike[str]) -> Mapping[str, Any]:
    if isinstance(pack_json, Mapping):
        return pack_json
    with Path(pack_json).open(encoding="utf-8") as f:
        return json.load(f)


class Pipeline:
    """One channel of a pack's pipeline. Build it with :func:`build_pipeline`."""

    def __init__(self, pack: Mapping[str, Any], input_fs_hz: float = 2000.0, model: Any = None) -> None:
        self.pack_id = str(pack.get("id", ""))
        self.fs_hz = float(pack["requires"]["sample_rate_hz"])
        self.input_fs_hz = float(input_fs_hz)
        stages: list[Stage] = []

        if self.input_fs_hz == self.fs_hz:
            self._decimator: Decimator2 | None = None
            stages.append(Stage("decimate", BYPASSED, f"input already at the pack rate ({self.fs_hz:g} Hz)"))
        elif self.input_fs_hz == DECIM_FACTOR * self.fs_hz == 2000.0:
            self._decimator = Decimator2()
            stages.append(Stage("decimate", OK, "D-016 63-tap FIR + ÷2, 2000 Hz -> 1000 Hz"))
        else:
            raise ValueError(
                f"input at {self.input_fs_hz:g} Hz for a {self.fs_hz:g} Hz pack: only the D-016 2000 -> 1000 Hz "
                "decimator or no decimation is supported"
            )

        self._chain = filter_chain_from_pack(pack.get("dsp", []), self.fs_hz)
        if self._chain.sections:
            names = ", ".join(f"{c.kind} {c.f_hz:g} Hz" for c in self._chain.sections)
            stages.append(Stage("dsp", OK, f"Butterworth biquads: {names}"))
        else:
            stages.append(Stage("dsp", BYPASSED, "pack names no dsp filters"))

        trigger = pack.get("trigger")
        self._trigger: StaLta | None = None
        if trigger is None:
            stages.append(Stage("trigger", NOT_AVAILABLE, "pack names no trigger"))
        elif trigger.get("type") == "sta_lta":
            self._trigger = StaLta(StaLtaParams.from_pack(trigger), self.fs_hz)
            p = self._trigger.params
            stages.append(
                Stage(
                    "trigger",
                    OK,
                    f"STA/LTA sta {p.sta_ms:g} ms, lta {p.lta_ms:g} ms, ratio {p.ratio:g}, "
                    f"window -{p.pre_ms:g}/+{p.post_ms:g} ms",
                )
            )
        else:
            stages.append(
                Stage("trigger", NOT_AVAILABLE, f"trigger type {trigger.get('type')!r} is not implemented yet")
            )

        stages.append(self._features_stage(pack.get("features")))
        stages.append(self._model_stage(pack.get("model"), model, stages[-1].available))
        self.stages = tuple(stages)
        self.reset()

    def _features_stage(self, name: Any) -> Stage:
        self._features_on = False
        if not name:
            return Stage("features", NOT_AVAILABLE, "pack names no features")
        if name != "footstep_v1":
            return Stage("features", NOT_AVAILABLE, f"feature set {name!r} is not implemented")
        if self._trigger is None:
            return Stage(
                "features", NOT_AVAILABLE, "footstep_v1 needs event windows: the trigger stage is not available"
            )
        n_win = self._trigger.n_pre + self._trigger.n_post
        if not 2 <= n_win <= N_FFT:
            return Stage(
                "features", NOT_AVAILABLE, f"footstep_v1 takes 2..{N_FFT}-sample windows, the pack's is {n_win}"
            )
        self._features_on = True
        return Stage(
            "features",
            OK,
            f"footstep_v1: {N_FEATURES} features on filtered[start:end] ({n_win} samples) of each window with "
            "n_invalid == 0; the others are skipped and counted",
        )

    def _model_stage(self, pack_model: Any, model: Any, features_ok: bool) -> Stage:
        self._model: Any = None
        if model is None:
            named = f"pack names {pack_model}" if pack_model else "pack names no model"
            return Stage("model", NOT_AVAILABLE, f"no model loaded ({named}; TFLite export comes later)")
        missing = [a for a in ("predict", "predict_proba", "classes_") if not hasattr(model, a)]
        if missing:
            raise TypeError(f"model needs predict, predict_proba and classes_ (a fitted classifier); missing {missing}")
        n_in = getattr(model, "n_features_in_", N_FEATURES)
        if n_in != N_FEATURES:
            raise ValueError(f"model takes {n_in} features, footstep_v1 gives {N_FEATURES}")
        if not features_ok:
            return Stage("model", NOT_AVAILABLE, "a model is loaded but the features stage is not available")
        self._model = model
        self._classes = tuple(str(c) for c in model.classes_)
        return Stage(
            "model",
            OK,
            f"{type(model).__name__} (in memory, not {pack_model or 'a pack model'}), classes {list(self._classes)}",
        )

    def reset(self) -> None:
        """Back to the start of a stream (zero filter history, trigger in warm-up)."""
        if self._decimator is not None:
            self._decimator.reset()
        self._chain.reset()
        if self._trigger is not None:
            self._trigger.reset()
        self.n_in = 0  # input samples consumed
        self.n_out = 0  # pack-rate samples produced
        self.n_lost_in = 0  # input samples marked lost
        self.n_invalid_out = 0  # pack-rate samples marked invalid
        self.n_events = 0  # events the trigger emitted
        self.n_windows = 0  # event windows reported (complete, or cut by finish())
        self.n_windows_invalid = 0  # reported windows with n_invalid > 0 (features skip them)
        self.n_windows_cut = 0  # of those, windows the end of the stream cut (finish())
        self.n_windows_featured = 0  # windows with n_invalid == 0 the features stage computed features for
        self.n_windows_skipped_invalid = 0  # windows with n_invalid > 0 the features stage skipped
        self._hist = np.zeros(0, dtype=np.float32)  # filtered samples from pack-rate index _hist_start on
        self._hist_start = 0
        self._pending: list[Event] = []  # events whose window is not complete yet
        self._invalid_runs: list[tuple[int, int]] = []  # [a, b) pack-rate runs a pending or future window may hold
        self._finished = False

    @property
    def n_windows_pending(self) -> int:
        """Events whose window ``[start, end)`` is not complete yet (reported later, or by :meth:`finish`)."""
        return len(self._pending)

    def to_input_index(self, k: int | np.ndarray) -> int | np.ndarray:
        """Input-stream index that pack-rate sample ``k`` describes (``2k - 30`` when decimating, else ``k``)."""
        return dec_to_raw_index(k) if self._decimator is not None else k

    def process(self, chunk: np.ndarray, valid: np.ndarray | None = None) -> PipelineOutput:
        """Feed ``chunk: (n,)`` input samples (ADC codes or volts, any numeric dtype; cast to float32).

        ``valid: (n,) bool`` marks lost input samples (``False``); ``None`` means all good.
        """
        if self._finished:
            raise RuntimeError("the stream has ended (finish() was called); call reset() to start a new one")
        x = np.asarray(chunk)
        if x.ndim != 1:
            raise ValueError(f"expected a 1-D chunk (one channel), got shape {x.shape}")
        x = x.astype(np.float32, copy=False)
        if valid is not None:
            valid = np.asarray(valid)
            if valid.shape != x.shape or valid.dtype != bool:
                raise ValueError(f"valid must be a bool array of shape {x.shape}, got {valid.dtype} {valid.shape}")
        start = self.n_out
        if self._decimator is not None:
            dec, ok = self._decimator.process_valid(x, valid)
        else:
            dec = x.copy()
            ok = valid.copy() if valid is not None else np.ones(x.size, dtype=bool)
        mask = None if ok.all() else ok  # same values either way; skips the masking work when nothing is lost
        filt = self._chain.process(dec, mask)
        ratio: np.ndarray | None = None
        events: tuple[Event, ...] | None = None
        windows: tuple[Event, ...] | None = None
        self.n_in += x.size
        self.n_out += dec.size
        self.n_lost_in += 0 if valid is None else int((~valid).sum())
        self.n_invalid_out += int((~ok).sum())
        if self._trigger is not None:
            r, ev = self._trigger.process(filt, mask)
            ratio, events = r, tuple(ev)
            if self._features_on:
                self._hist = np.concatenate([self._hist, filt])
            windows = self._close_windows(ev, ok, start, self._trigger.n_pre)
        features, feature_windows, model = self._run_features(windows)
        return PipelineOutput(
            start, dec, ok, filt, ratio, events, windows, features, feature_windows, model, self.stages
        )

    def _run_features(
        self, windows: tuple[Event, ...] | None
    ) -> tuple[np.ndarray | None, tuple[Event, ...] | None, ModelOutput | None]:
        """Features (and model) for the reported windows with ``n_invalid == 0``; count the skipped ones.

        Each window is computed on its own, from ``filtered`` history, so the result does not depend on chunking.
        """
        if not self._features_on or windows is None:
            return None, None, None
        good = tuple(w for w in windows if w.n_invalid == 0)
        self.n_windows_skipped_invalid += len(windows) - len(good)
        self.n_windows_featured += len(good)
        feats = np.zeros((len(good), N_FEATURES), dtype=np.float32)
        for i, w in enumerate(good):
            a = w.start - self._hist_start
            if a < 0 or w.end - self._hist_start > self._hist.size:  # cannot happen: history covers open windows
                raise AssertionError(f"filtered history [{self._hist_start}, ...) does not cover window {w}")
            feats[i] = footstep_v1(self._hist[a : w.end - self._hist_start], self.fs_hz)
        # Keep the filtered samples a pending or future window can still need (a future onset is >= n_out).
        keep_from = min([e.start for e in self._pending] + [self.n_out - self._trigger.n_pre])  # type: ignore[union-attr]
        if keep_from > self._hist_start:
            cut = min(keep_from - self._hist_start, self._hist.size)
            self._hist = self._hist[cut:].copy()
            self._hist_start += cut
        return feats, good, self._predict(feats)

    def _predict(self, feats: np.ndarray) -> ModelOutput | None:
        """Run the model one window at a time (as the node does; a batch call could round differently)."""
        if self._model is None:
            return None
        n_cls = len(self._classes)
        proba = np.zeros((feats.shape[0], n_cls), dtype=np.float32)
        labels = []
        for i in range(feats.shape[0]):
            row = feats[i : i + 1]
            proba[i] = np.asarray(self._model.predict_proba(row), dtype=np.float64)[0].astype(np.float32)
            labels.append(str(np.asarray(self._model.predict(row))[0]))
        return ModelOutput(self._classes, tuple(labels), proba)

    def finish(self) -> PipelineOutput:
        """End of the stream: report every pending window, cut, and stop accepting samples until :meth:`reset`.

        Returns an output with no samples (``start_index == n_out``) whose ``windows`` are the events whose window
        ``[start, end)`` runs past the end, with the samples past the end counted in ``n_invalid`` (so it is
        always > 0 and the features stage skips them). They are counted in ``n_windows_invalid`` and
        ``n_windows_cut``. Calling it again returns no windows. The firmware does the same when a stream stops.
        """
        has_trigger = self._trigger is not None
        cut = tuple(replace(e, n_invalid=self._count_invalid(e.start, e.end, self.n_out)) for e in self._pending)
        self._pending, self._invalid_runs, self._finished = [], [], True
        self._count_windows(cut)
        self.n_windows_cut += len(cut)
        features, feature_windows, model = self._run_features(cut if has_trigger else None)
        self._hist = np.zeros(0, dtype=np.float32)
        empty = np.zeros(0, dtype=np.float32)
        return PipelineOutput(
            start_index=self.n_out,
            decimated=empty,
            valid=np.zeros(0, dtype=bool),
            filtered=empty.copy(),
            ratio=empty.copy() if has_trigger else None,
            events=() if has_trigger else None,
            windows=cut if has_trigger else None,
            features=features,
            feature_windows=feature_windows,
            model=model,
            stages=self.stages,
        )

    def _close_windows(self, new_events: list[Event], ok: np.ndarray, start: int, n_pre: int) -> tuple[Event, ...]:
        """Track invalid runs, return the events whose window is complete now, with ``n_invalid`` counted."""
        if not ok.all():
            bad = np.flatnonzero(~ok)
            cut = np.flatnonzero(np.diff(bad) != 1)
            run_a = np.concatenate([bad[:1], bad[cut + 1]]) + start
            run_b = np.concatenate([bad[cut], bad[-1:]]) + start + 1
            self._invalid_runs.extend(zip(run_a.tolist(), run_b.tolist(), strict=True))
        self.n_events += len(new_events)
        self._pending.extend(new_events)
        done = [e for e in self._pending if e.end <= self.n_out]
        self._pending = [e for e in self._pending if e.end > self.n_out]
        closed = tuple(replace(e, n_invalid=self._count_invalid(e.start, e.end)) for e in done)
        self._count_windows(closed)
        # A future event has onset >= n_out, so its window starts at >= n_out - n_pre.
        keep_from = min([e.start for e in self._pending] + [self.n_out - n_pre])
        self._invalid_runs = [(a, b) for a, b in self._invalid_runs if b > keep_from]
        return closed

    def _count_windows(self, windows: tuple[Event, ...]) -> None:
        self.n_windows += len(windows)
        self.n_windows_invalid += sum(1 for e in windows if e.n_invalid)

    def _count_invalid(self, a: int, b: int, stream_end: int | None = None) -> int:
        """Invalid pack-rate samples in ``[a, b)``. Indices before 0, and from ``stream_end`` on when the stream has
        ended, count as invalid (no sample there): the rule of :func:`rezonating_ml.trigger.window_n_invalid`.
        """
        n = max(0, min(b, 0) - a)
        if stream_end is not None:
            n += max(0, b - max(a, stream_end))
            b = min(b, stream_end)
        for ra, rb in self._invalid_runs:
            n += max(0, min(rb, b) - max(ra, a))
        return n


class LostSampleMismatch(ValueError):
    """The zero-filled frames and the sidecar's ``loss`` total don't support a mask (see :func:`zero_fill_mask`)."""


def sidecar_lost_total(loss: Mapping[str, Any]) -> int:
    """Total lost frames from a sidecar ``loss`` object: ``device + link + host`` (all are zeros in the WAV)."""
    return sum(int(loss[k]) for k in ("device", "link", "host"))


@dataclass(frozen=True)
class ZeroFillMask:
    """A recording's lost-frame mask rebuilt by :func:`zero_fill_mask`, and what it is known to guarantee.

    ``valid``: ``(n_frames,)`` bool, ``False`` = marked lost; only all-zero frames are ever marked.
    ``covers_all_lost``: proven (from premises P1 and P2) that every lost frame is marked, the guarantee the
    pipeline needs; ``False`` when only the count backs the mask (single-channel ``min_run`` runs), on a mismatch
    with ``strict=False``, or when nothing was checked (no ``expected_lost``).
    ``n_surplus``: with ``covers_all_lost``, the real frames marked lost (all-zero data, which can't be told from a
    loss without the gap positions; 0 = the mask is exact); ``None`` otherwise.
    ``n_zero_frames``: all-zero frames in the file; ``n_marked``: frames marked lost.
    """

    valid: np.ndarray
    min_run: int
    n_zero_frames: int
    n_marked: int
    expected_lost: int | None
    covers_all_lost: bool
    n_surplus: int | None


def _zero_runs(zero: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate([[False], zero, [False]]).astype(np.int8)))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True))


def zero_fill_mask(
    codes: np.ndarray,
    min_run: int | None = None,
    expected_lost: int | None = None,
    strict: bool = True,
) -> ZeroFillMask:
    """Rebuild a recording's lost-frame mask from its zero-filled frames and the sidecar's ``loss`` total.

    ``codes: (n_frames, n_channels)`` int32, the whole WAV (preferred), or ``(n,)`` one channel. Run it on the
    whole file, not chunk by chunk (a run split across chunks would be measured in pieces).

    Premises (``tools/lab/PROTOCOL.md`` section 6; the Lab recorder enforces both):

    - **P1** every lost frame is in the WAV as a frame of zeros on every channel (``io.WavWriter.write_zeros``);
    - **P2** the sidecar total ``E`` (:func:`sidecar_lost_total`) is the number of lost frames: each lost sample
      sits in exactly one counter, and zeros the recorder wrote that no node counter explains go to ``host``.
      Coverage needs only "never fewer than the lost frames", which holds even when the recorder flags counters
      above the zeros it wrote; ``n_surplus`` assumes the equality.

    The sidecar (schema v1) has the count, not the positions, so the lost frames are some ``E`` of the ``Z``
    all-zero frames (a real frame can be all zeros too). The mask follows from that, case by case:

    - ``E == 0``: nothing was lost; no frame is marked. Exact.
    - ``E == Z``: every all-zero frame was lost; all are marked. Exact.
    - ``0 < E < Z`` and every all-zero frame lies in a run of at least ``min_run`` (always so with ``min_run=1``):
      every all-zero frame is marked. **Covers** every loss, plus ``n_surplus = Z - E`` real frames.
    - ``0 < E < Z`` otherwise: the runs of at least ``min_run`` all-zero frames are marked, if they total exactly
      ``E``. Backed by the count only (not proven: a real run of zeros could offset a missed shorter loss), so
      ``covers_all_lost`` is ``False`` and a ``UserWarning`` says so: check ``covers_all_lost`` before trusting it.
    - anything else (``E > Z``: lost frames that are not zeros; or the runs above don't total ``E``):
      :class:`LostSampleMismatch` with ``strict=True``, else a ``UserWarning`` and the ``min_run`` runs as mask.

    ``min_run`` defaults to 1 with two or more channels, so every case there either covers or raises. A single
    channel defaults to 8, because a live head alone hits 0 by chance so often that marking every zero would drop
    most of the data; pass ``min_run=1`` to get coverage anyway, at the cost of ``n_surplus`` frames. Without
    ``expected_lost`` the ``min_run`` runs are returned unchecked: always pass it for a recording, or a short loss
    can be missed and look like a footstep.
    """
    return _zero_fill_mask(codes, min_run, expected_lost, strict, stacklevel=3)


def _zero_fill_mask(
    codes: np.ndarray, min_run: int | None, expected_lost: int | None, strict: bool, stacklevel: int
) -> ZeroFillMask:
    """:func:`zero_fill_mask`, warning with ``stacklevel`` (so the warning points at the public caller)."""
    c = np.asarray(codes)
    if c.ndim == 1:
        zero, n_ch = c == 0, 1
    elif c.ndim == 2:
        zero, n_ch = np.all(c == 0, axis=1), c.shape[1]
    else:
        raise ValueError(f"expected (n_frames, n_channels) or one channel (n,), got shape {c.shape}")
    if min_run is None:
        min_run = 1 if n_ch >= 2 else 8
    if min_run < 1:
        raise ValueError("min_run must be >= 1")
    if expected_lost is not None and expected_lost < 0:
        raise ValueError("expected_lost must be >= 0")
    in_runs = np.zeros(zero.size, dtype=bool)
    for a, b in _zero_runs(zero):
        if b - a >= min_run:
            in_runs[a:b] = True
    n_zero, n_runs, e = int(zero.sum()), int(in_runs.sum()), expected_lost

    def result(lost: np.ndarray, covers: bool, surplus: int | None) -> ZeroFillMask:
        return ZeroFillMask(~lost, min_run, n_zero, int(lost.sum()), e, covers, surplus)

    if e is None:
        return result(in_runs, False, None)
    if e == 0:  # P2: nothing was lost; every all-zero frame is real data
        return result(np.zeros(zero.size, dtype=bool), True, 0)
    if e <= n_zero and (n_runs == n_zero or e == n_zero):  # P1: the lost frames are among the all-zero ones
        return result(zero, True, n_zero - e)
    if e < n_zero and n_runs == e:
        warnings.warn(
            f"the mask is backed by the count only: runs of >= {min_run} all-zero frames total the sidecar's {e} "
            f"lost frames, but {n_zero - n_runs} all-zero frames in shorter runs are left valid ({n_ch} channel(s)), "
            "so a real zero run could offset a missed short loss (covers_all_lost is False). min_run=1 covers every "
            f"loss and marks {n_zero - e} real frames as lost",
            stacklevel=stacklevel,
        )
        return result(in_runs, False, None)
    if e > n_zero:
        msg = (
            f"the sidecar loss totals {e} frames but the file has only {n_zero} all-zero frames: some lost frames "
            "are not zeros (a damaged file or wrong loss counters), so no mask can be trusted"
        )
    else:
        missed = "a loss is left unmarked and can look like a footstep" if n_runs < e else "the mask is ambiguous"
        msg = (
            f"runs of >= {min_run} all-zero frames mark {n_runs} lost frames, the sidecar loss totals {e} "
            f"({n_zero - n_runs} of the {n_zero} all-zero frames sit in shorter runs, over {n_ch} channel(s)): "
            f"{missed}. min_run=1 marks every all-zero frame, which covers every loss and marks "
            f"{n_zero - e} real frames as lost"
        )
    if strict:
        raise LostSampleMismatch(msg)
    warnings.warn(msg, stacklevel=stacklevel)
    return result(in_runs, False, None)


def valid_from_zero_fill(
    codes: np.ndarray,
    min_run: int | None = None,
    expected_lost: int | None = None,
    strict: bool = True,
) -> np.ndarray:
    """``zero_fill_mask(...).valid``: the ``(n_frames,)`` bool mask alone (``False`` = lost); see
    :func:`zero_fill_mask` for the rules, the guarantees, when it raises :class:`LostSampleMismatch` and when it
    warns (the same ``UserWarning``s, pointing at your call: the mask alone can't say whether it covers every loss).
    """
    return _zero_fill_mask(codes, min_run, expected_lost, strict, stacklevel=3).valid


def build_pipeline(
    pack_json: Mapping[str, Any] | str | os.PathLike[str], input_fs_hz: float = 2000.0, model: Any = None
) -> Pipeline:
    """Build the pipeline a pack names.

    ``pack_json`` is the parsed ``pack.json`` or a path to it. ``input_fs_hz`` is the rate of the samples you will
    feed: 2000 Hz (``adc_raw`` recordings, D-020) decimates to a 1000 Hz pack; the pack rate itself skips the
    decimator. ``model``: an optional fitted classifier on the pack's features, with ``predict``,
    ``predict_proba`` and ``classes_`` (e.g. :func:`rezonating_ml.baseline.train_baseline_model`); ``None`` leaves
    the model stage ``not_available``. Raises ``TypeError`` / ``ValueError`` for a model without those or with
    another number of input features.
    """
    return Pipeline(_load_pack(pack_json), input_fs_hz=input_fs_hz, model=model)


def run_pipeline(
    pack_json: Mapping[str, Any] | str | os.PathLike[str],
    x: np.ndarray,
    input_fs_hz: float = 2000.0,
    valid: np.ndarray | None = None,
    model: Any = None,
) -> PipelineOutput:
    """Batch call: a fresh pipeline over the whole input ``x: (n,)``, then :meth:`Pipeline.finish` (the input is the
    whole stream, so every event is in ``windows``). ``valid``: see :meth:`Pipeline.process`; ``model``: see
    :func:`build_pipeline`.
    """
    pipe = build_pipeline(pack_json, input_fs_hz=input_fs_hz, model=model)
    return concat_outputs([pipe.process(x, valid), pipe.finish()])


def concat_outputs(outputs: Sequence[PipelineOutput]) -> PipelineOutput:
    """Join consecutive chunk outputs of one pipeline into one; with the :meth:`Pipeline.finish` output last, it
    equals :func:`run_pipeline` on the same samples.
    """
    if not outputs:
        raise ValueError("no outputs to join")
    first = outputs[0]
    has_trigger = first.ratio is not None
    has_features = first.features is not None
    has_model = first.model is not None

    def cat(arrays: list[np.ndarray]) -> np.ndarray:
        return np.concatenate(arrays).astype(np.float32, copy=False)

    return PipelineOutput(
        start_index=first.start_index,
        decimated=cat([o.decimated for o in outputs]),
        valid=np.concatenate([o.valid for o in outputs]).astype(bool, copy=False),
        filtered=cat([o.filtered for o in outputs]),
        ratio=cat([o.ratio for o in outputs]) if has_trigger else None,  # type: ignore[misc]
        events=tuple(e for o in outputs for e in (o.events or ())) if has_trigger else None,
        windows=tuple(e for o in outputs for e in (o.windows or ())) if has_trigger else None,
        features=np.concatenate([o.features for o in outputs]).astype(np.float32, copy=False)  # type: ignore[misc]
        if has_features
        else None,
        feature_windows=tuple(e for o in outputs for e in (o.feature_windows or ())) if has_features else None,
        model=ModelOutput(
            first.model.classes,  # type: ignore[union-attr]
            tuple(lab for o in outputs for lab in o.model.labels),  # type: ignore[union-attr]
            np.concatenate([o.model.proba for o in outputs]).astype(np.float32, copy=False),  # type: ignore[union-attr]
        )
        if has_model
        else None,
        stages=first.stages,
    )
