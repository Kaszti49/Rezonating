"""Guided rig checks for a freshly wired node ([[Wire the first rig]], Lab phase 4). Contract: WEB_API.md section 11.

Five checks, each with pass/fail, the measured numbers and named thresholds:

``adc``    the ADC answers: HELLO lists ``adc_raw`` and samples arrive after START.
``rate``   the ADC sample rate over 60 s (device time), from the DATA timestamps (``t_dev_us``), against nominal.
``noise``  the noise floor with the inputs shorted: RMS per channel in counts and in input-referred microvolts.
``tap``    the channel map: "tap the sensor at CH0", then CH1; the asked channel must have the larger peak.
``accel``  the ADXL355 at rest reads about 1 g on z and about 0 g on x and y.

One worker thread runs the checks; it uses only the device manager's public commands (START, STOP, the simulator's
``sim.tap``) and a DATA listener, so it never blocks the link thread. Streams the checks start are stopped at the
end; streams that were already running are left running. Steps that need a person (short the inputs, connect the
heads) wait for ``confirm``; on a simulator they are skipped and the tap is injected with ``SET sim.tap``.

The report is plain markdown for the build note, saved under ``<data root>/rigchecks/`` (never in the repo).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .. import __version__
from ..link import codec
from ..link.codec import Data
from ..recorder.config import LabConfig, check_data_root
from .device import DeviceError, DeviceManager

ADC_STREAM = codec.STREAM_ADC_RAW
ACCEL_STREAM = codec.STREAM_ACCEL
CHECK_IDS = ("adc", "rate", "noise", "tap", "accel")

# ---- thresholds (named so the report and the docs can quote them) ------------------------------------------------
ADC_ANSWER_TIMEOUT_S = 3.0  # wall seconds after START
ADC_ANSWER_MIN_SAMPLES = 100  # 50 ms at 2 kSPS: enough to know DRDY fires and frames arrive
RATE_CHECK_S = 60.0  # device seconds of DATA timestamps
# LTC6903 frequency error: 0.5 % typical, 1.1 % max at 25 degC, 1.65 % max over temperature. A rig check runs at room
# temperature, so a clock beyond the 25 degC maximum is out of spec or misprogrammed (wrong OCT/DAC word).
RATE_TOLERANCE_PCT = 1.1
NOISE_CHECK_S = 5.0  # device seconds of samples (counted at the nominal rate)
NOISE_SETTLE_S = 0.1  # samples dropped at the start (digital filter settling after START)
# PROVISIONAL: input-referred RMS limit per channel with the inputs shorted. Set it from the first real rig
# (ADS131M02 at gain 8 and 2 kSPS should be a few microvolts); the simulator sits at 6 uV.
NOISE_LIMIT_UV_RMS = 15.0
TAP_BASELINE_S = 0.3  # quiet signal before the prompt: mean and noise per channel
TAP_WAIT_S = 20.0  # wall seconds for the person to tap
TAP_PRE_S = 0.02  # the peak window starts this long before the first sample above threshold
TAP_WINDOW_S = 0.15  # and ends this long after it
TAP_GAP_S = 0.5  # pause between the CH0 and the CH1 tap (lets the first one ring out)
TAP_MIN_PEAK_V = 0.005  # PROVISIONAL: a tap must reach 5 mV at the ADC input (footsteps in the sim are ~1.5 mV)
TAP_MIN_SNR = 20.0  # and 20x the baseline RMS of that channel
TAP_MIN_RATIO = 2.0  # the asked channel's peak must be at least this many times the other channel's
ACCEL_CHECK_S = 2.0  # device seconds of samples (counted at the nominal rate)
ACCEL_Z_MIN_G = 0.9
ACCEL_Z_MAX_G = 1.1
ACCEL_XY_MAX_G = 0.1  # about 5.7 degrees of tilt
CONFIRM_TIMEOUT_S = 900.0  # a step that waits for a person gives up after 15 minutes
START_TIMEOUT_S = 6.0  # wall seconds for a START or STOP future
POLL_S = 0.05

THRESHOLDS = {
    "adc_answer_timeout_s": ADC_ANSWER_TIMEOUT_S,
    "adc_answer_min_samples": ADC_ANSWER_MIN_SAMPLES,
    "rate_check_s": RATE_CHECK_S,
    "rate_tolerance_pct": RATE_TOLERANCE_PCT,
    "noise_check_s": NOISE_CHECK_S,
    "noise_limit_uv_rms": NOISE_LIMIT_UV_RMS,
    "tap_wait_s": TAP_WAIT_S,
    "tap_min_peak_v": TAP_MIN_PEAK_V,
    "tap_min_snr": TAP_MIN_SNR,
    "tap_min_ratio": TAP_MIN_RATIO,
    "accel_check_s": ACCEL_CHECK_S,
    "accel_z_min_g": ACCEL_Z_MIN_G,
    "accel_z_max_g": ACCEL_Z_MAX_G,
    "accel_xy_max_g": ACCEL_XY_MAX_G,
}

TITLES = {
    "adc": "ADC answers",
    "rate": "Sample rate",
    "noise": "Noise floor (inputs shorted)",
    "tap": "Tap test (channel map)",
    "accel": "ADXL355 gravity",
}
GUIDES = {
    "adc": [
        "Connect the node (USB or Wi-Fi) on the Device page.",
        "Run: the check STARTs adc_raw and waits for samples.",
    ],
    "rate": [
        "Leave the node running; nothing to touch.",
        f"Run: the check fits {RATE_CHECK_S:g} s of DATA timestamps (device clock) and compares with 2000 Hz.",
        "Write the measured rate into the build note: it is the real rate of this LTC6903.",
    ],
    "noise": [
        "Short CH0 and CH1 inputs to AGND at the ADC 15 Click (a jumper per channel, heads disconnected).",
        "Press Continue when asked; keep the bench still while it measures.",
        "Remove the shorts afterwards.",
    ],
    "tap": [
        "Connect the sensor heads (inputs not shorted). Mark which head is CH0 and which is CH1.",
        "Press Continue when asked, then tap the head the prompt names, firmly, once.",
        "The check asks for CH0, then CH1.",
    ],
    "accel": [
        "Lay the ADXL355 flat and still, z axis up.",
        f"Run: the check averages {ACCEL_CHECK_S:g} s of x, y and z.",
    ],
}


class _Cancelled(Exception):
    pass


class _Abort(Exception):
    """The check cannot go on (link lost, a recording started, the node refused a command)."""


@dataclass
class CheckResult:
    passed: bool
    detail: str  # the measured numbers as one line of text (the report's "Measured" column)
    limit: str  # the threshold as text
    numbers: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckState:
    id: str
    state: str = "idle"  # idle | running | waiting | pass | fail | error | cancelled
    prompt: str | None = None
    detail: str | None = None
    limit: str | None = None
    numbers: dict[str, Any] = field(default_factory=dict)
    started: float | None = None
    finished: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": TITLES[self.id],
            "guide": GUIDES[self.id],
            "state": self.state,
            "prompt": self.prompt,
            "detail": self.detail,
            "limit": self.limit,
            "numbers": self.numbers,
            "started": self.started,
            "finished": self.finished,
        }


class _Collector:
    """DATA of one stream in arrival order (a DeviceManager data listener)."""

    def __init__(self, stream_id: int) -> None:
        self.stream_id = stream_id
        self._lock = threading.Lock()
        self._firsts: list[int] = []
        self._stamps: list[int] = []
        self._blocks: list[np.ndarray] = []
        self.n = 0

    def __call__(self, d: Data) -> None:
        if d.stream != self.stream_id:
            return
        with self._lock:
            self._firsts.append(d.first_sample)
            self._stamps.append(d.t_dev_us)
            self._blocks.append(d.samples)
            self.n += d.n

    def stamps(self) -> tuple[np.ndarray, np.ndarray]:
        """(first_sample, t_dev_us) of every packet."""
        with self._lock:
            return np.array(self._firsts, dtype=np.float64), np.array(self._stamps, dtype=np.float64)

    def span_s(self) -> float:
        with self._lock:
            return (self._stamps[-1] - self._stamps[0]) / 1e6 if len(self._stamps) > 1 else 0.0

    def samples(self, start: int = 0) -> np.ndarray:
        """Samples from arrival position ``start`` on, as float64 (n, n_ch)."""
        with self._lock:
            blocks = list(self._blocks)
        if not blocks:
            return np.zeros((0, 1))
        return np.concatenate(blocks).astype(np.float64)[start:]


def _fmt_signed(x: float, digits: int) -> str:
    return f"{x:+.{digits}f}"


class RigChecks:
    def __init__(
        self,
        mgr: DeviceManager,
        cfg: LabConfig,
        recording: Callable[[], bool] = lambda: False,
        sim_auto: bool = True,
        wall: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mgr = mgr
        self.cfg = cfg
        self._recording = recording
        self.sim_auto = sim_auto  # on a simulator: skip the "press Continue" steps and inject taps (sim.tap)
        self._wall = wall
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._confirm = threading.Event()
        self.checks = {cid: CheckState(cid) for cid in CHECK_IDS}
        self.current: str | None = None
        self.awaiting_confirm = False
        self.node: dict[str, Any] = {}
        self.session_started: datetime | None = None
        self.report_path: str | None = None
        self.report_error: str | None = None
        self._started_streams: set[int] = set()

    # ---------------------------------------------------------------------------------------- public

    @property
    def running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def view(self) -> dict:
        with self._lock:
            return {
                "type": "rigcheck",
                "running": self.running,
                "current": self.current,
                "awaiting_confirm": self.awaiting_confirm,
                "sim": self._is_sim(),
                "node": dict(self.node),
                "session_started": self.session_started.isoformat(timespec="seconds") if self.session_started else None,
                "report_path": self.report_path,
                "report_error": self.report_error,
                "checks": [c.to_dict() for c in self.checks.values()],
                "thresholds": THRESHOLDS,
            }

    def run(self, ids: list[str] | None = None, rate_s: float | None = None) -> dict:
        """Start the given checks (all of them, in order, when ``ids`` is None) on a worker thread."""
        wanted = list(CHECK_IDS) if not ids else list(dict.fromkeys(ids))
        unknown = [c for c in wanted if c not in CHECK_IDS]
        if unknown:
            raise DeviceError(
                "not_found", f"no such rig check: {', '.join(unknown)} (use {', '.join(CHECK_IDS)})", http=404
            )
        with self._lock:
            if self.running:
                raise DeviceError("rigcheck_running", "Rig checks are already running. Cancel them first.", http=409)
            if not self.mgr.connected:
                raise DeviceError("not_connected", "no node is connected", http=409)
            if self._recording():
                raise DeviceError("recording_active", "Cannot run rig checks while a recording runs.", http=409)
            hello = self.mgr.state().get("hello") or {}
            conn = self.mgr.state().get("connection") or {}
            node = {
                "node_id": hello.get("node_id"),
                "fw_version": hello.get("fw_version"),
                "link": conn.get("link"),
                "target": conn.get("target"),
            }
            if ids is None or node.get("node_id") != self.node.get("node_id") or self.session_started is None:
                # "Run all" or another node: a new report. Single checks add to the current one.
                self.checks = {cid: CheckState(cid) for cid in CHECK_IDS}
                self.session_started = datetime.now().astimezone()
                self.report_path = self.report_error = None
            self.node = node
            for cid in wanted:
                self.checks[cid] = CheckState(cid, state="idle")
            self._cancel.clear()
            self._confirm.clear()
            self._started_streams = set()
            self._thread = threading.Thread(
                target=self._worker, args=(wanted, rate_s), name="rzlab-rigcheck", daemon=True
            )
            self._thread.start()
        self._publish()
        return self.view()

    def confirm(self) -> dict:
        with self._lock:
            if not self.awaiting_confirm:
                raise DeviceError("no_prompt", "No rig check step is waiting for Continue.", http=409)
            self._confirm.set()
        return self.view()

    def cancel(self) -> dict:
        if not self.running:
            raise DeviceError("rigcheck_idle", "No rig check is running.", http=409)
        self._cancel.set()
        return self.view()

    def close(self) -> None:
        self._cancel.set()
        t = self._thread
        if t is not None:
            t.join(timeout=10)

    def wait(self, timeout_s: float | None = None) -> bool:
        """Block until the worker is done (tests). True when it finished."""
        t = self._thread
        if t is None:
            return True
        t.join(timeout_s)
        return not t.is_alive()

    # ------------------------------------------------------------------------------------- report

    def report_filename(self) -> str:
        started = self.session_started or datetime.now().astimezone()
        node = re.sub(r"[^\w.-]", "_", str(self.node.get("node_id") or "node"), flags=re.ASCII)
        return f"rigcheck_{started.strftime('%Y%m%d-%H%M%S')}_{node}.md"

    def report_markdown(self) -> str:
        with self._lock:
            checks = [self.checks[c] for c in CHECK_IDS]
            node = dict(self.node)
            started = self.session_started
        done = [c for c in checks if c.state in ("pass", "fail", "error")]
        passed = sum(1 for c in done if c.state == "pass")
        date = (started or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
        lines = [
            f"## Rig check {date}",
            "",
            f"- Date: {date}",
            f"- Node: {node.get('node_id') or 'unknown'}",
            f"- Firmware: {node.get('fw_version') or 'unknown'}"
            + (" (simulator)" if str(node.get("fw_version") or "").endswith("-sim") else ""),
            f"- Link: {node.get('link') or '?'} {node.get('target') or ''}".rstrip(),
            f"- Lab: rzlab {__version__}",
            f"- Result: {passed} of {len(done)} checks passed"
            + (f", {len(checks) - len(done)} not run" if len(done) < len(checks) else ""),
            "",
            "| Check | Verdict | Measured | Limit |",
            "| --- | --- | --- | --- |",
        ]
        for c in checks:
            verdict = {"pass": "PASS", "fail": "FAIL", "error": "ERROR", "cancelled": "cancelled"}.get(
                c.state, "not run"
            )
            lines.append(f"| {TITLES[c.id]} | {verdict} | {(c.detail or '').replace('|', '/')} | {c.limit or ''} |")
        lines.append("")
        return "\n".join(lines)

    def save_report(self) -> str | None:
        """Write the report to ``<data root>/rigchecks/``. Returns the path, or None (``report_error`` says why)."""
        status = check_data_root(self.cfg, probe_write=False)
        if not status.ok or status.path is None:
            with self._lock:
                self.report_error = status.message or "no usable data root"
                self.report_path = None
            return None
        folder = Path(status.path) / "rigchecks"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / self.report_filename()
            path.write_text(self.report_markdown(), encoding="utf-8")
        except OSError as exc:
            with self._lock:
                self.report_error = f"cannot write the report: {exc}"
                self.report_path = None
            return None
        with self._lock:
            self.report_path = str(path)
            self.report_error = None
        return str(path)

    # ------------------------------------------------------------------------------------- worker

    def _publish(self) -> None:
        self.mgr.publish(self.view())

    def _is_sim(self) -> bool:
        return str(self.node.get("fw_version") or "").endswith("-sim")

    def _set(self, cid: str, **kw: Any) -> None:
        with self._lock:
            st = self.checks[cid]
            for k, v in kw.items():
                setattr(st, k, v)
        self._publish()

    def _worker(self, ids: list[str], rate_s: float | None) -> None:
        fns: dict[str, Callable[[], CheckResult]] = {
            "adc": self._check_adc,
            "rate": lambda: self._check_rate(RATE_CHECK_S if rate_s is None else rate_s),
            "noise": self._check_noise,
            "tap": self._check_tap,
            "accel": self._check_accel,
        }
        try:
            for i, cid in enumerate(ids):
                if self._cancel.is_set():
                    for rest in ids[i:]:
                        self._set(rest, state="cancelled")
                    break
                with self._lock:
                    self.current = cid
                self._set(cid, state="running", started=time.time(), prompt=None)
                try:
                    res = fns[cid]()
                    self._set(
                        cid,
                        state="pass" if res.passed else "fail",
                        detail=res.detail,
                        limit=res.limit,
                        numbers=res.numbers,
                        prompt=None,
                        finished=time.time(),
                    )
                except _Cancelled:
                    self._set(cid, state="cancelled", prompt=None, finished=time.time())
                except (_Abort, DeviceError, TimeoutError) as exc:
                    msg = exc.message if isinstance(exc, DeviceError) else str(exc) or type(exc).__name__
                    self._set(cid, state="error", detail=msg, prompt=None, finished=time.time())
                finally:
                    with self._lock:
                        self.awaiting_confirm = False
        finally:
            self._stop_started()
            with self._lock:
                self.current = None
            if any(c.state in ("pass", "fail", "error") for c in self.checks.values()):
                self.save_report()
            # the thread is still alive here: publish "running": false explicitly
            ev = self.view()
            ev["running"] = False
            self.mgr.publish(ev)

    def _stop_started(self) -> None:
        mask = 0
        for sid in self._started_streams:
            mask |= 1 << sid
        self._started_streams = set()
        if mask and self.mgr.connected and not self.mgr.recording:
            try:
                self.mgr.stop_streams(mask).result(timeout=START_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - reported in the log, the results stand
                self.mgr.host_log(f"rig check: STOP after the checks failed: {exc!r}", 2)

    # ------------------------------------------------------------------------------------ helpers

    def _guard(self) -> None:
        if self._cancel.is_set():
            raise _Cancelled
        if not self.mgr.connected:
            raise _Abort("the node disconnected")
        if self.mgr.recording:
            raise _Abort("a recording started")

    def _wait_until(self, pred: Callable[[], bool], timeout_s: float) -> bool:
        deadline = self._wall() + timeout_s
        while True:
            self._guard()
            if pred():
                return True
            if self._wall() >= deadline:
                return False
            time.sleep(POLL_S)

    def _ask(self, cid: str, text: str) -> str:
        """A step that needs a person: wait for Continue. On a simulator it passes at once. Returns how it passed."""
        if self.sim_auto and self._is_sim():
            self._set(cid, prompt=f"{text} (simulator: skipped)")
            return "auto (simulator)"
        self._confirm.clear()
        with self._lock:
            self.awaiting_confirm = True
        self._set(cid, state="waiting", prompt=text + " Then press Continue.")
        try:
            if not self._wait_until(self._confirm.is_set, CONFIRM_TIMEOUT_S):
                raise _Abort("nobody pressed Continue")
        finally:
            with self._lock:
                self.awaiting_confirm = False
        self._set(cid, state="running", prompt=None)
        return "person"

    def _ensure(self, sid: int) -> None:
        if self.mgr.stream_running(sid):
            return
        self.mgr.start_streams(1 << sid).result(timeout=START_TIMEOUT_S)
        self._started_streams.add(sid)

    def _collect(self, sid: int) -> _Collector:
        col = _Collector(sid)
        self.mgr.add_data_listener(col)
        return col

    def _info(self, sid: int) -> dict:
        info = self.mgr.stream_info(sid)
        if info is None:
            raise _Abort(f"the node has no {codec.STREAM_NAMES.get(sid, sid)} stream")
        return info

    def _wait_samples(self, col: _Collector, n: int, nominal_hz: float, what: str) -> None:
        if not self._wait_until(lambda: col.n >= n, n / nominal_hz * 1.5 + 10.0):
            raise _Abort(f"{what}: only {col.n} of {n} samples arrived")

    # -------------------------------------------------------------------------------------- checks

    def _check_adc(self) -> CheckResult:
        limit = f">= {ADC_ANSWER_MIN_SAMPLES} samples within {ADC_ANSWER_TIMEOUT_S:g} s of START"
        hello = self.mgr.state().get("hello") or {}
        s = next((x for x in hello.get("streams", []) if x.get("id") == ADC_STREAM), None)
        if s is None:
            return CheckResult(False, "HELLO lists no adc_raw stream", limit, {"present": False})
        col = self._collect(ADC_STREAM)
        try:
            t0 = self._wall()
            self._ensure(ADC_STREAM)
            ok = self._wait_until(lambda: col.n >= ADC_ANSWER_MIN_SAMPLES, ADC_ANSWER_TIMEOUT_S)
            waited = self._wall() - t0
        finally:
            self.mgr.remove_data_listener(col)
        nums = {
            "present": True,
            "clock": s.get("clock"),
            "nominal_hz": s.get("nominal_hz"),
            "samples": col.n,
            "waited_s": round(waited, 3),
        }
        if ok:
            detail = f"adc_raw in HELLO (clock {s.get('clock')}), {col.n} samples within {waited:.2f} s"
        else:
            detail = (
                f"adc_raw in HELLO, but only {col.n} samples in {waited:.1f} s after START: the ADC does not answer"
            )
        return CheckResult(ok, detail, limit, nums)

    def _check_rate(self, duration_s: float) -> CheckResult:
        limit = f"within +/-{RATE_TOLERANCE_PCT:g} % of nominal (LTC6903 max at 25 degC)"
        info = self._info(ADC_STREAM)
        nominal = float(info["nominal_hz"])
        col = self._collect(ADC_STREAM)
        try:
            self._ensure(ADC_STREAM)
            self._set("rate", prompt=f"Measuring for {duration_s:g} s of device time; nothing to touch.")
            ok = self._wait_until(lambda: col.span_s() >= duration_s, duration_s * 1.5 + 10.0)
        finally:
            self.mgr.remove_data_listener(col)
        firsts, stamps = col.stamps()
        span = col.span_s()
        if not ok or len(firsts) < 3:
            raise _Abort(f"only {span:.1f} s of ADC data arrived (needed {duration_s:g} s)")
        x = firsts - firsts[0]
        y = stamps - stamps[0]
        slope_us, _ = np.polyfit(x, y, 1)
        rate = 1e6 / float(slope_us)
        err_pct = (rate / nominal - 1.0) * 100.0
        status_hz = None
        for st in (self.mgr.state().get("status") or {}).get("streams", []):
            if st.get("id") == ADC_STREAM:
                status_hz = st.get("rate_hz_status")
        passed = abs(err_pct) <= RATE_TOLERANCE_PCT
        nums = {
            "nominal_hz": nominal,
            "measured_hz": round(rate, 3),
            "error_pct": round(err_pct, 4),
            "span_s": round(span, 3),
            "samples": int(x[-1]) if len(x) else 0,
            "packets": len(firsts),
            "status_hz": status_hz,
            "limit_pct": RATE_TOLERANCE_PCT,
        }
        detail = (
            f"{rate:.2f} Hz vs {nominal:g} Hz nominal: {_fmt_signed(err_pct, 3)} % over {span:.1f} s "
            f"({len(firsts)} packets)"
        )
        if status_hz is not None:
            detail += f"; STATUS {status_hz:.1f} Hz"
        return CheckResult(passed, detail, limit, nums)

    def _check_noise(self) -> CheckResult:
        limit = f"<= {NOISE_LIMIT_UV_RMS:g} uV rms per channel, input-referred (provisional)"
        how = self._ask("noise", "Short CH0 and CH1 inputs to AGND (heads disconnected).")
        info = self._info(ADC_STREAM)
        nominal = float(info["nominal_hz"])
        col = self._collect(ADC_STREAM)
        settle = int(NOISE_SETTLE_S * nominal)
        n = int(NOISE_CHECK_S * nominal)
        try:
            self._ensure(ADC_STREAM)
            self._set("noise", prompt=f"Measuring the noise for {NOISE_CHECK_S:g} s; keep the bench still.")
            self._wait_samples(col, settle + n, nominal, "noise")
        finally:
            self.mgr.remove_data_listener(col)
        x = col.samples(settle)[:n]
        rms = x.std(axis=0)
        mean = x.mean(axis=0)
        volts = [u == "V" for u in info["units"]]
        uv = [float(r * info["scale"][i] * 1e6) if volts[i] else None for i, r in enumerate(rms)]
        passed = all(v is not None and v <= NOISE_LIMIT_UV_RMS for v in uv)
        parts = []
        for i, r in enumerate(rms):
            parts.append(
                f"CH{i} {uv[i]:.2f} uV rms ({r:.0f} counts)" if uv[i] is not None else f"CH{i} {r:.0f} counts rms"
            )
        detail = ", ".join(parts) + f", gain {info['gain']}, {n} samples"
        nums = {
            "rms_counts": [round(float(r), 2) for r in rms],
            "rms_uv": [None if v is None else round(v, 3) for v in uv],
            "mean_counts": [round(float(m), 1) for m in mean],
            "gain": info["gain"],
            "samples": int(x.shape[0]),
            "confirmed": how,
        }
        return CheckResult(passed, detail, limit, nums)

    def _check_tap(self) -> CheckResult:
        limit = (
            f"asked channel has the larger peak, >= {TAP_MIN_RATIO:g}x the other; tap >= {TAP_MIN_PEAK_V * 1e3:g} mV"
        )
        how = self._ask("tap", "Connect the sensor heads (inputs not shorted).")
        info = self._info(ADC_STREAM)
        if not all(u == "V" for u in info["units"]):
            raise _Abort("CONFIG gives no volt scale for adc_raw")
        scale = np.array(info["scale"], dtype=np.float64)
        nominal = float(info["nominal_hz"])
        col = self._collect(ADC_STREAM)
        taps: list[dict] = []
        try:
            self._ensure(ADC_STREAM)
            for ch in range(int(info["n_ch"])):
                if ch:
                    time.sleep(TAP_GAP_S)
                taps.append(self._one_tap(ch, col, scale, nominal))
        finally:
            self.mgr.remove_data_listener(col)
        passed = all(t["ok"] for t in taps)
        parts = []
        for t in taps:
            if t["detected"] is None:
                parts.append(f"CH{t['asked']} tap: none detected in {TAP_WAIT_S:g} s")
            else:
                pk = ", ".join(f"CH{i} {v * 1e3:.2f} mV" for i, v in enumerate(t["peak_v"]))
                parts.append(f"CH{t['asked']} tap: {pk} -> CH{t['detected']} ({t['ratio']:.1f}x)")
        nums = {"taps": taps, "confirmed": how, "injected": self.sim_auto and self._is_sim()}
        return CheckResult(passed, "; ".join(parts), limit, nums)

    def _one_tap(self, ch: int, col: _Collector, scale: np.ndarray, nominal: float) -> dict:
        n_base = max(16, int(TAP_BASELINE_S * nominal))
        start = col.n
        self._wait_samples(col, start + n_base, nominal, "tap baseline")
        base = col.samples(start)[:n_base]
        mean = base.mean(axis=0)
        noise = base.std(axis=0)
        thr = np.maximum(TAP_MIN_SNR * noise, TAP_MIN_PEAK_V / scale)  # counts, per channel
        scan_from = start + n_base
        self._set("tap", prompt=f"Tap the sensor at CH{ch}.")
        if self.sim_auto and self._is_sim():
            try:
                self.mgr.sim_tap(ch).result(timeout=START_TIMEOUT_S)
            except DeviceError as exc:
                raise _Abort(f"the simulator refused sim.tap: {exc.message}") from exc
        hit: list[int] = []

        def seen() -> bool:
            x = col.samples(scan_from)
            if not len(x):
                return False
            over = np.flatnonzero((np.abs(x - mean) > thr).any(axis=1))
            if len(over):
                hit.append(scan_from + int(over[0]))
                return True
            return False

        out: dict[str, Any] = {"asked": ch, "detected": None, "peak_v": None, "ratio": None, "ok": False}
        if not self._wait_until(seen, TAP_WAIT_S):
            return out
        k = hit[0]
        pre, post = int(TAP_PRE_S * nominal), int(TAP_WINDOW_S * nominal)
        self._wait_samples(col, k + post, nominal, "tap window")
        lo = max(0, k - pre)
        win = col.samples(lo)[: pre + post]
        peaks_v = (np.abs(win - mean).max(axis=0) * scale).astype(float)
        detected = int(np.argmax(peaks_v))
        other = np.delete(peaks_v, ch)
        ratio = float(peaks_v[ch] / max(float(other.max()) if len(other) else 0.0, 1e-12))
        out.update(
            detected=detected,
            peak_v=[round(float(v), 6) for v in peaks_v],
            ratio=round(ratio, 2),
            ok=detected == ch and ratio >= TAP_MIN_RATIO,
        )
        return out

    def _check_accel(self) -> CheckResult:
        limit = f"z {ACCEL_Z_MIN_G:g} to {ACCEL_Z_MAX_G:g} g, |x| and |y| <= {ACCEL_XY_MAX_G:g} g"
        info = self._info(ACCEL_STREAM)
        if not all(u == "g" for u in info["units"]):
            raise _Abort("CONFIG gives no g scale for accel")
        nominal = float(info["nominal_hz"])
        n = int(ACCEL_CHECK_S * nominal)
        col = self._collect(ACCEL_STREAM)
        try:
            self._ensure(ACCEL_STREAM)
            self._set("accel", prompt=f"Averaging {ACCEL_CHECK_S:g} s; keep the sensor still.")
            self._wait_samples(col, n, nominal, "accel")
        finally:
            self.mgr.remove_data_listener(col)
        x = col.samples(0)[:n]
        g = x.mean(axis=0) * np.array(info["scale"], dtype=np.float64)
        sd = x.std(axis=0) * np.array(info["scale"], dtype=np.float64)
        gx, gy, gz = (float(v) for v in g[:3])
        passed = ACCEL_Z_MIN_G <= gz <= ACCEL_Z_MAX_G and abs(gx) <= ACCEL_XY_MAX_G and abs(gy) <= ACCEL_XY_MAX_G
        detail = f"x {gx:+.3f} g, y {gy:+.3f} g, z {gz:+.3f} g (mean of {x.shape[0]} samples)"
        nums = {
            "mean_g": [round(gx, 4), round(gy, 4), round(gz, 4)],
            "std_g": [round(float(v), 5) for v in sd[:3]],
            "samples": int(x.shape[0]),
        }
        return CheckResult(passed, detail, limit, nums)
