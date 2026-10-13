"""STA/LTA event trigger (D-021), stateful and chunkable, float32 like the firmware.

Runs on the pack-rate signal after the ``dsp`` filters (1 kSPS for footstep-id). Sample indices are pack-rate
indices counted from the start of the stream (``n = 0, 1, ...``). The global index and the refractory end
(``quiet_until``) are **64-bit** integers in the firmware (``u64`` sample indices as in D-018), so they never wrap;
Python ints are unbounded.

**Build requirement (firmware):** compile with ``-ffp-contract=off`` (see :mod:`rezonating_ml.dsp`).

Characteristic function and averages (recursive STA/LTA, Withers et al. 1998), per sample, float32::

    cf  = x*x
    sta = d_sta*sta + c_sta*cf        c = 1.0f / N   (float32 division),  d = 1.0f - c
    lta = d_lta*lta + c_lta*cf        each product rounded, then the sum: fl(fl(d*s) + fl(c*cf))
    ratio = sta / lta   if lta > 0 else 0

``N_sta = round(sta_ms * fs / 1000)``, ``N_lta`` likewise; ``sta`` and ``lta`` start at 0.

Trigger rule (a three-state machine, carried across chunks):

- **warm-up**: no event while ``n < N_lta`` (the LTA has not settled; it starts at 0, so the ratio is too high).
- **wait-low**: after warm-up and after every refractory period, the ratio must first be seen *below* ``ratio``
  (``ratio[n] < on``) before the trigger arms. A ratio that is already high when warm-up or refractory ends is
  not a new event.
- **armed**: the first ``n`` with ``ratio[n] >= on`` is an onset. Event: ``onset = n``,
  ``start = onset - N_pre``, ``end = onset + N_post`` (half-open window ``[start, end)``, ``N_pre + N_post``
  samples). Then **refractory** until ``n >= max(end, onset + 1)``, then wait-low again.

So two onsets are always at least ``N_post`` samples apart, and a ratio that stays high gives one event, not
many. There is no separate trigger-off ratio (the pack has none): after a step up in background level the ratio
falls below ``ratio`` once the LTA catches up, and STA noise may then trigger again.
An event is reported in the chunk that contains its onset; its ``end`` may lie beyond the samples seen so far.

Invalid (lost) samples, ``valid[n] == False``: skipped entirely. ``sta``/``lta`` do not advance, the ratio there is
reported as 0, and they count neither as "low" nor as "high" for the state machine; warm-up and refractory are
still measured in sample indices (time), lost or not.

Events whose window holds invalid samples: the trigger reports an event at its onset, before the samples up to
``end`` exist, so :class:`StaLta` leaves ``Event.n_invalid`` as ``None`` (not known yet). The pipeline
(:class:`rezonating_ml.pipeline.Pipeline`) fills it in (:func:`window_n_invalid`) once the window ``[start, end)``
is complete, or when the stream ends first: the number of pack-rate samples in the window that are invalid or
don't exist, i.e. indices before 0 and, once the stream has ended, indices at or past its end. **Rules:** every
event is reported exactly once with ``n_invalid`` set (a window the end of the stream cut is reported then, never
dropped silently); the features stage computes features only for windows with ``n_invalid == 0`` and counts the
others as skipped. The firmware does the same: a window with a lost or missing sample is never classified, and
the skip is counted, including the windows still open when a stream stops.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np
from scipy import signal

__all__ = [
    "Event",
    "StaLta",
    "StaLtaParams",
    "close_windows",
    "detect_events",
    "events_from_ratio",
    "window_n_invalid",
]

_WAIT_LOW = 0
_ARMED = 1


@dataclass(frozen=True)
class Event:
    """One trigger event, in pack-rate sample indices. ``[start, end)`` is the window around the onset.

    ``n_invalid``: invalid (lost) pack-rate samples in ``[start, end)``; ``None`` while the window is not complete
    (as the trigger emits it), set by the pipeline once it is (see the module docstring for the rule).
    """

    onset: int
    start: int
    end: int
    n_invalid: int | None = None

    def as_dict(self) -> dict[str, int]:
        d = {"onset": self.onset, "start": self.start, "end": self.end}
        if self.n_invalid is not None:
            d["n_invalid"] = self.n_invalid
        return d


@dataclass(frozen=True)
class StaLtaParams:
    """STA/LTA settings as written in a pack's ``trigger`` object (``type: sta_lta``)."""

    sta_ms: float
    lta_ms: float
    ratio: float
    pre_ms: float = 0.0
    post_ms: float = 0.0

    @classmethod
    def from_pack(cls, trigger: Mapping[str, object]) -> StaLtaParams:
        if trigger.get("type") != "sta_lta":
            raise ValueError(f"trigger type {trigger.get('type')!r} is not sta_lta")
        try:
            return cls(
                sta_ms=float(trigger["sta_ms"]),  # type: ignore[arg-type]
                lta_ms=float(trigger["lta_ms"]),  # type: ignore[arg-type]
                ratio=float(trigger["ratio"]),  # type: ignore[arg-type]
                pre_ms=float(trigger.get("pre_ms", 0.0)),  # type: ignore[arg-type]
                post_ms=float(trigger.get("post_ms", 0.0)),  # type: ignore[arg-type]
            )
        except KeyError as e:
            raise ValueError(f"sta_lta trigger is missing {e.args[0]!r}") from None

    def samples(self, fs_hz: float) -> dict[str, int]:
        """Window lengths in samples at ``fs_hz``: ``n_sta``, ``n_lta``, ``n_pre``, ``n_post``."""

        def n(ms: float) -> int:
            return int(round(ms * fs_hz / 1000.0))

        out = {"n_sta": n(self.sta_ms), "n_lta": n(self.lta_ms), "n_pre": n(self.pre_ms), "n_post": n(self.post_ms)}
        if out["n_sta"] < 1 or out["n_lta"] <= out["n_sta"]:
            raise ValueError(f"need 1 <= n_sta < n_lta, got {out}")
        return out


def _ema_coeffs(n: int) -> tuple[np.ndarray, np.ndarray]:
    c = np.float32(1.0) / np.float32(n)
    d = np.float32(np.float32(1.0) - c)
    # lfilter with b = [c, 0], a = [1, -d] computes exactly fl(fl(d*y) + fl(c*x)) in float32 (checked in tests).
    return np.array([c, 0.0], dtype=np.float32), np.array([1.0, -d], dtype=np.float32)


class StaLta:
    """Stateful STA/LTA ratio and trigger; see the module docstring for the exact rules.

    State: ``sta``, ``lta`` (float32), the global sample index, the trigger state and the refractory end.
    """

    def __init__(self, params: StaLtaParams, fs_hz: float) -> None:
        self.params = params
        self.fs_hz = float(fs_hz)
        s = params.samples(self.fs_hz)
        self.n_sta, self.n_lta, self.n_pre, self.n_post = s["n_sta"], s["n_lta"], s["n_pre"], s["n_post"]
        self.on = np.float32(params.ratio)
        self._b_sta, self._a_sta = _ema_coeffs(self.n_sta)
        self._b_lta, self._a_lta = _ema_coeffs(self.n_lta)
        self.reset()

    def reset(self) -> None:
        self._z_sta = np.zeros(1, dtype=np.float32)
        self._z_lta = np.zeros(1, dtype=np.float32)
        self.n_seen = 0
        self._state = _WAIT_LOW
        self._quiet_until = self.n_lta  # no wait-low check (and no event) before this index

    def ratio(self, x: np.ndarray) -> np.ndarray:
        """Advance the averages over ``x: (n,)`` float32 and return the ratio trace ``(n,)`` float32.

        Does not run the trigger state machine; use :meth:`process` for that.
        """
        x = np.asarray(x)
        if x.ndim != 1:
            raise ValueError(f"expected a 1-D chunk, got shape {x.shape}")
        x = x.astype(np.float32, copy=False)
        if x.size == 0:
            return x.copy()
        cf = x * x
        sta, self._z_sta = signal.lfilter(self._b_sta, self._a_sta, cf, zi=self._z_sta)
        lta, self._z_lta = signal.lfilter(self._b_lta, self._a_lta, cf, zi=self._z_lta)
        sta = sta.astype(np.float32, copy=False)
        lta = lta.astype(np.float32, copy=False)
        out = np.zeros_like(sta)
        np.divide(sta, lta, out=out, where=lta > 0)
        return out

    def process(self, x: np.ndarray, valid: np.ndarray | None = None) -> tuple[np.ndarray, list[Event]]:
        """Feed filtered samples ``x: (n,)``; return ``(ratio (n,) float32, events whose onset is in this chunk)``.

        ``valid: (n,) bool`` marks lost samples (``False``); they are skipped (see the module docstring).
        """
        x = np.asarray(x)
        if x.ndim != 1:
            raise ValueError(f"expected a 1-D chunk, got shape {x.shape}")
        n = x.size
        base = self.n_seen
        if valid is None:
            ok_idx = np.arange(n, dtype=np.int64)
            r = rc = self.ratio(x)
        else:
            v = np.asarray(valid)
            if v.shape != (n,) or v.dtype != bool:
                raise ValueError(f"valid must be a bool array of shape ({n},), got {v.dtype} {v.shape}")
            ok_idx = np.flatnonzero(v).astype(np.int64)
            rc = self.ratio(x[ok_idx])
            r = np.zeros(n, dtype=np.float32)
            r[ok_idx] = rc
        events = self._step(rc, base + ok_idx)
        self.n_seen += n
        return r, events

    def _step(self, rc: np.ndarray, g_idx: np.ndarray) -> list[Event]:
        """Run the trigger state machine over valid ratio samples ``rc`` at global indices ``g_idx`` (increasing)."""
        events: list[Event] = []
        i = 0
        m = rc.size
        while i < m:
            if g_idx[i] < self._quiet_until:
                i = int(np.searchsorted(g_idx, self._quiet_until, side="left"))
                continue
            if self._state == _WAIT_LOW:
                low = np.flatnonzero(rc[i:] < self.on)
                if low.size == 0:
                    break
                i += int(low[0])
                self._state = _ARMED  # rc[i] is low, so it cannot also be the onset
                i += 1
                continue
            high = np.flatnonzero(rc[i:] >= self.on)
            if high.size == 0:
                break
            i += int(high[0])
            onset = int(g_idx[i])
            events.append(Event(onset=onset, start=onset - self.n_pre, end=onset + self.n_post))
            self._state = _WAIT_LOW
            self._quiet_until = onset + max(self.n_post, 1)
            i += 1
        return events


def detect_events(
    x: np.ndarray, params: StaLtaParams, fs_hz: float, valid: np.ndarray | None = None
) -> tuple[np.ndarray, list[Event]]:
    """Batch call: run a fresh :class:`StaLta` over ``x: (n,)``; returns ``(ratio, events)``."""
    return StaLta(params, fs_hz).process(x, valid)


def events_from_ratio(ratio: np.ndarray, params: StaLtaParams, fs_hz: float) -> list[Event]:
    """The trigger rule alone, on a given ratio trace ``(n,)`` from index 0 (e.g. one the firmware computed)."""
    r = np.asarray(ratio, dtype=np.float32)
    return StaLta(params, fs_hz)._step(r, np.arange(r.size, dtype=np.int64))


def window_n_invalid(event: Event, valid: np.ndarray) -> int:
    """``n_invalid`` of ``event``'s window in a stream that ended after ``valid.size`` pack-rate samples.

    ``valid: (n,) bool`` is the whole stream's pack-rate mask. Counts the samples of ``[start, end)`` that are
    invalid, before index 0, or at index ``n`` or later (no sample there). The reference for the incremental
    count in :class:`rezonating_ml.pipeline.Pipeline` and for the firmware.
    """
    v = np.asarray(valid, dtype=bool)
    a, b, n = event.start, event.end, v.size
    lo, hi = max(a, 0), min(b, n)
    inside = int(np.count_nonzero(~v[lo:hi])) if hi > lo else 0
    return inside + max(0, min(b, 0) - a) + max(0, b - max(a, n))


def close_windows(events: Sequence[Event], valid: np.ndarray) -> list[Event]:
    """Each event with ``n_invalid`` set by :func:`window_n_invalid`: what the pipeline reports in ``windows``
    over a whole stream (with :meth:`~rezonating_ml.pipeline.Pipeline.finish`), as a batch call.
    """
    return [replace(e, n_invalid=window_n_invalid(e, valid)) for e in events]
