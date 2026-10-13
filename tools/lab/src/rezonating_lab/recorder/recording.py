"""The recorder: one recording session from the form to the validated files.

Flow (D-017, D-019, D-020):

1. ``start(form)``: check the data root, the node and the form; reserve ``YYYY-MM-DD_<site>_<room>_<nn>`` by creating
   its folder in the data root; open one WAV per stream in local staging; STOP everything on the node, then START
   ``adc_raw`` and ``accel``; start the phone-marker listener.
2. While recording, DATA packets reach :class:`~rezonating_lab.recorder.capture.StreamCapture` through the device
   thread's tap (a queue, no disk), and marks arrive through :meth:`Recorder.mark` (keyboard) or the marker listener
   (phone). Marks are stamped on arrival by the server.
3. ``stop()``: STOP, drain, close the files, fit the real sample rate, place the marks, write and validate the v1
   sidecars, move the session to the data root, and copy only the validated sidecars to ``sidecar_dir/<session>/``.

If the link dies mid-recording the same finishing steps run with ``rzlab: loss=incomplete`` in the notes.
"""

from __future__ import annotations

import contextlib
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rezonating_ml import io

from ..server.device import DeviceError, DeviceManager
from . import labels as lab
from .capture import StreamCapture
from .config import ConfigError, LabConfig, check_data_root, check_staging_dir
from .forms import (
    DEFAULT_PROTOCOL,
    PSEUDONYM_RE,
    RECORDABLE_STREAMS,
    LabelOverrides,
    LabelState,
    SessionForm,
    list_protocols,
)
from .marker import (
    MarkerApp,
    MarkerHostError,
    MarkerServer,
    MarkRefused,
    TokenStore,
    choose_bind,
    describe_marker,
    is_wildcard,
    marker_hosts,
    resolve_bind,
)
from .naming import SessionNameError, reserve_session, slugify
from .protocol import ProtocolError, check_listed, load_named
from .runner import ProtocolRunner, RunnerError, runner_off
from .sidecars import (
    LINK_BY_KIND,
    SensorProblem,
    build_sidecar,
    channel_entries,
    file_stem,
    head_defaults,
    measured_rate,
    notes_text,
    utc_string,
)
from .validate import validate_session_folder

PROGRESS_PERIOD_S = 1.0
START_TIMEOUT_S = 15.0
STOP_TIMEOUT_S = 20.0

STATES = ("idle", "starting", "recording", "stopping", "finalizing")


RIGCHECK_RUNNING = "Rig checks are running. Wait for them or cancel them (Device page), then start the recording."


class RecordError(DeviceError):
    """A recorder request was refused. Shaped like every other API error (``code``, ``message``) plus ``details``."""

    def __init__(self, code: str, message: str, http: int = 409, details: list[dict] | None = None) -> None:
        super().__init__(code, message, http=http)
        self.details = details

    def to_dict(self) -> dict:
        d = super().to_dict()
        if self.details:
            d["details"] = self.details
        return d


class _Plan:
    """One recorded stream: the node's description, the sidecar channels, the capture."""

    def __init__(self, stream: dict, channels: list[dict], cap: StreamCapture, stem: str) -> None:
        self.stream = stream
        self.channels = channels
        self.cap = cap
        self.stem = stem


class Recorder:
    def __init__(
        self,
        mgr: DeviceManager,
        cfg: LabConfig,
        now: Callable[[], datetime] = datetime.now,
        epoch_now: Callable[[], float] = time.time,
        timed_scale: float = 1.0,
    ) -> None:
        """``timed_scale`` shortens the protocol runner's timed steps (``duration_s / timed_scale``): tests only."""
        self.mgr = mgr
        self.cfg = cfg
        self._timed_scale = timed_scale
        self._now = now
        self._epoch_now = epoch_now
        self._lock = threading.RLock()
        self.state = "idle"
        self._done = threading.Event()
        self._done.set()
        self._listeners: list[Callable[[dict], None]] = []
        self.label_state = LabelState()
        self.last: dict | None = None
        # Set by the server once the rig checks exist (they are built after the recorder): True while checks run.
        self.rig_running: Callable[[], bool] = lambda: False
        self._reset_session()

    # ------------------------------------------------------------------------------------ state

    def _reset_session(self) -> None:
        self.form: SessionForm | None = None
        self._label_cache: dict[str, tuple[int, tuple[str, ...]]] = {}
        self.session: str | None = None
        self._ctx: dict | None = None
        self._plans: dict[int, _Plan] = {}
        self._data_folder: Path | None = None
        self._staging_folder: Path | None = None
        self.labels = lab.LabelBook()
        self._marker: MarkerServer | None = None
        self._marker_error: str | None = None
        self._t_start_host_us = 0
        self._epoch_ref = 0.0
        self._ticker_stop = threading.Event()
        self._ticker: threading.Thread | None = None
        self._closed_at_stop = 0
        self._ended_by = "stop"
        self._lost: tuple[dict[int, dict], str] | None = None  # (snapshot, reason) when the link died
        self.runner: ProtocolRunner | None = None
        self._countdown_timer: threading.Timer | None = None
        self._runner_summary: dict | None = None

    @property
    def active(self) -> bool:
        return self.state != "idle"

    @property
    def marker_error(self) -> str | None:
        return self._marker_error

    def add_state_listener(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_state_listener(self, fn: Callable[[dict], None]) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._listeners.remove(fn)

    def marker_state(self) -> dict:
        """The only thing the phone sees: whether a recording runs and whether a mark is open."""
        return {
            "recording": self.state == "recording",
            "marking": self.labels.open_mark() is not None,
            "n_labels": len(self.labels),
        }

    def _notify(self) -> None:
        state = self.marker_state()
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            with contextlib.suppress(Exception):
                fn(state)

    # --------------------------------------------------------------------------------- options

    def options(self) -> dict:
        """Everything the Record page needs before the form is sent."""
        status = check_data_root(self.cfg, probe_write=False)
        ctx = self.mgr.record_context()
        blockers: list[dict] = []
        if not status.ok:
            blockers.append({"code": status.error_code, "message": status.message})
        bad_staging = check_staging_dir(self.cfg)
        if bad_staging is not None:
            blockers.append({"code": bad_staging.error_code, "message": bad_staging.message})
        if ctx is None:
            blockers.append({"code": "not_connected", "message": "Connect to a node first (Device page)."})
        if self.state != "idle":
            blockers.append({"code": "recording_active", "message": "A recording is already running."})
        if self.rig_running():
            blockers.append({"code": "rigcheck_running", "message": RIGCHECK_RUNNING})
        if self.cfg.schema_path is None or not self.cfg.schema_path.is_file():
            blockers.append({"code": "no_schema", "message": "schemas/sidecar.schema.json was not found."})
        node = None
        if ctx is not None:
            streams = []
            for s in ctx["streams"].values():
                chans = []
                for ch in range(s["n_ch"]):
                    nc = s["channels"][ch] if ch < len(s["channels"]) else {}
                    chans.append(
                        {
                            "ch": ch,
                            "units": nc.get("units"),
                            "gain": nc.get("gain"),
                            "scale": nc.get("scale"),
                            "defaults": head_defaults(s, ch, ctx["heads"]),
                        }
                    )
                streams.append(
                    {
                        "name": s["name"],
                        "n_ch": s["n_ch"],
                        "nominal_hz": s["nominal_hz"],
                        "clock": s["clock"],
                        "recordable": s["name"] in RECORDABLE_STREAMS,
                        "channels": chans,
                    }
                )
            node = {
                "node_id": ctx["node_id"],
                "fw_version": ctx["fw_version"],
                "link": ctx["link_kind"],
                "simulated": ctx["fw_version"].endswith("-sim"),
                "streams": streams,
            }
        return {
            "state": self.state,
            "data_root": status.to_dict(),
            "protocols": list_protocols(self.cfg.repo_root),
            "default_protocol": DEFAULT_PROTOCOL,
            "person_pattern": PSEUDONYM_RE.pattern,
            "node": node,
            "label_state": self.label_state.model_dump(),
            "labels_allowed": self.labels_allowed(),
            "marker": {
                "bind": resolve_bind(self.cfg.marker_bind),
                "port": self.cfg.marker_port,
                "hosts": marker_hosts(self.cfg.marker_bind),
            },
            "can_start": not blockers,
            "blockers": blockers,
        }

    # ------------------------------------------------------------------------------------ start

    def start(self, form: SessionForm) -> dict:
        with self._lock:
            if self.state != "idle":
                raise RecordError("recording_active", "A recording is already running; stop it first.")
            if self.rig_running():
                raise RecordError("rigcheck_running", RIGCHECK_RUNNING)
            self.state = "starting"
            self._done.clear()
            self._reset_session()
        try:
            self._start(form)
        except BaseException:
            self._abort_start()
            with self._lock:
                self.state = "idle"
                self._done.set()
            raise
        self.mgr.publish(self.status())
        self._notify()
        return self.status()

    def _start(self, form: SessionForm) -> None:
        try:
            self.cfg.require_schema()
        except ConfigError as exc:
            raise RecordError(exc.code, exc.message) from exc
        root = check_data_root(self.cfg)
        if not root.ok:
            raise RecordError(root.error_code or "data_root", root.message or "The data root is not usable.")
        bad_staging = check_staging_dir(self.cfg)
        if bad_staging is not None:
            raise RecordError(
                bad_staging.error_code or "staging", bad_staging.message or "The staging folder is not usable."
            )
        ctx = self.mgr.record_context()
        if ctx is None:
            raise RecordError("not_connected", "No node is connected. Connect on the Device page first.")
        protocols = list_protocols(self.cfg.repo_root)
        if form.protocol not in protocols:
            raise RecordError(
                "invalid_request",
                f"unknown protocol; choose one of {', '.join(protocols)}",
                http=422,
                details=[{"loc": ["protocol"], "msg": f"unknown protocol; one of {', '.join(protocols)}"}],
            )
        allowed = self.label_list(form.protocol)
        runner = self._make_runner(form.protocol, form.persons) if form.runner else None
        try:
            bind = choose_bind(self.cfg.marker_bind, form.marker_host)
        except MarkerHostError as exc:
            raise RecordError(
                "bad_marker_host", str(exc), http=422, details=[{"loc": ["marker_host"], "msg": str(exc)}]
            ) from exc
        by_name = {s["name"]: s for s in ctx["streams"].values()}
        wanted = list(form.streams) if form.streams else [n for n in RECORDABLE_STREAMS if n in by_name]
        missing = [n for n in wanted if n not in by_name]
        if missing or not wanted:
            msg = f"the node has no {', '.join(missing)} stream" if missing else "the node has nothing to record"
            raise RecordError("invalid_request", msg, http=422, details=[{"loc": ["streams"], "msg": msg}])
        if self.label_state.person and form.persons and self.label_state.person not in form.persons:
            self.label_state = LabelState()  # a person from an earlier session; not in this one
        if self.label_state.label not in allowed:  # a label of another protocol: start from this one's list
            first = "walk" if "walk" in allowed else allowed[0]
            self.label_state = self.label_state.model_copy(update={"label": first})
        channels: dict[str, list[dict]] = {}
        try:
            for name in wanted:
                channels[name] = channel_entries(by_name[name], form, ctx["heads"])
        except SensorProblem as exc:
            raise RecordError(
                "invalid_request",
                "sensor positions are missing: " + exc.details[0]["msg"],
                http=422,
                details=exc.details,
            ) from exc
        today = self._now().date()
        try:
            session, data_folder, staging_folder = reserve_session(
                root_path(self.cfg), self.cfg.staging_dir, today, slugify(form.site), slugify(form.room)
            )
        except SessionNameError as exc:
            raise RecordError("session_name", str(exc)) from exc
        except OSError as exc:
            raise RecordError("data_root_not_writable", f"Cannot reserve the session folder: {exc}") from exc
        with self._lock:
            self.form, self.session, self._ctx = form, session, ctx
            self._data_folder, self._staging_folder = data_folder, staging_folder
        plans: dict[int, _Plan] = {}
        for name in wanted:
            s = by_name[name]
            stem = file_stem(name, session)
            cap = StreamCapture(
                s["id"], name, s["n_ch"], s["nominal_hz"], staging_folder / f"{stem}.wav", s["nominal_hz"]
            )
            plans[s["id"]] = _Plan(s, channels[name], cap, stem)
        self._plans = plans
        for p in plans.values():
            p.cap.start()
        mask = 0
        for sid in plans:
            mask |= 1 << sid
        try:
            self.mgr.record_start(self, mask).result(timeout=START_TIMEOUT_S)
        except Exception as exc:
            if isinstance(exc, DeviceError):
                raise
            raise RecordError("start_failed", f"The node did not start streaming: {exc}", http=502) from exc
        self._t_start_host_us = self.mgr.host_us()
        self._epoch_ref = self._epoch_now()
        if form.marker:
            self._start_marker(bind)
        with self._lock:
            self.state = "recording"
            self.runner = runner
        if runner is not None:
            self._publish_runner()
        self._ticker = threading.Thread(target=self._tick_loop, name="rzlab-rec-progress", daemon=True)
        self._ticker.start()

    def _abort_start(self) -> None:
        """Undo a start that failed: stop writers, delete staging, release the reserved name."""
        for p in self._plans.values():
            with contextlib.suppress(Exception):
                p.cap.abort()
        self._stop_marker()
        if self._staging_folder is not None:
            shutil.rmtree(self._staging_folder, ignore_errors=True)
        if self._data_folder is not None:
            with contextlib.suppress(OSError):
                self._data_folder.rmdir()  # only if empty: never removes a recording
        self._plans = {}

    # ---------------------------------------------------------------------------------- the tap

    def on_data(self, d: Any) -> None:
        plan = self._plans.get(d.stream)
        if plan is not None:
            plan.cap.on_data(d.first_sample, d.t_dev_us, d.samples)

    def on_status(self, mon: Any) -> None:
        for sid, plan in self._plans.items():
            if plan.cap.base is None:
                sm = mon.streams.get(sid)
                win = sm.acct.window if sm is not None else None
                if win is not None:
                    plan.cap.set_base(win[0])

    def on_link_lost(self, snapshot: dict[int, dict], reason: str) -> None:
        """Device thread: the recording ended without our STOP. Finish it on another thread."""
        with self._lock:
            self._lost = (snapshot, reason)
            if self.state != "recording":
                return  # stop() is already finishing the recording and will use this snapshot
            self.state = "stopping"
        self._ended_by = "link_lost"
        threading.Thread(
            target=self._finish_after_loss, args=(snapshot, reason), name="rzlab-rec-finalize", daemon=True
        ).start()

    def _finish_after_loss(self, snapshot: dict[int, dict], reason: str) -> None:
        try:
            self._quiesce()
            self._finalize(snapshot, f"the link was lost: {reason}")
        except Exception as exc:  # noqa: BLE001
            self._fail_finalize(exc)

    # ------------------------------------------------------------------------------------ marks

    def _edge(self, src: str, arrival_us: float, rtt_ms: float | None) -> lab.Edge:
        corrected = arrival_us - (rtt_ms * 500.0 if rtt_ms is not None else 0.0)  # half the round trip, in us
        allowance = lab.PHONE_ALLOWANCE_MS if src == "phone" else lab.KEY_ALLOWANCE_MS
        return lab.Edge(src, corrected, arrival_us, rtt_ms, allowance)

    def mark(
        self,
        edge: str,
        src: str,
        arrival_us: float,
        rtt_ms: float | None = None,
        overrides: LabelOverrides | None = None,
    ) -> dict:
        """Apply a mark edge. ``edge`` is ``start``, ``end`` or ``toggle``; ``arrival_us`` is the server's stamp.

        While the protocol runner is active the label fields come from its current step, a completed mark counts as
        one pass, and a timed step's mark is ended by the countdown, not by hand (WEB_API.md section 10)."""
        with self._lock:
            if self.state != "recording":
                raise RecordError("not_recording", "No recording is running; start one before marking.")
            e = self._edge(src, arrival_us, rtt_ms)
            open_mark = self.labels.open_mark()
            action = ("end" if open_mark else "start") if edge == "toggle" else edge
            runner = self.runner
            if action == "start":
                if open_mark is not None:
                    raise RecordError("mark_open", "A mark is already open; end it first.")
                update = overrides.model_dump(exclude_none=True) if overrides else {}
                if runner is not None:
                    try:
                        update = runner.tags_for_start(update)
                    except RunnerError as exc:
                        raise RecordError(exc.code, exc.message, exc.http) from exc
                st = self.label_state.model_copy(update=update)
                form = self.form
                self._check_listed(st.label, form.protocol if form else DEFAULT_PROTOCOL)
                if st.person and form and form.persons and st.person not in form.persons:
                    raise RecordError("invalid_request", "That pseudonym is not one of this session's persons.", 422)
                m = self.labels.start(e, st.label, st.person, st.pace, st.shoes)
                if runner is not None:
                    countdown_s = runner.started(m.id)
                    if countdown_s is not None:
                        self._arm_countdown(m.id, countdown_s)
            else:
                if open_mark is None:
                    raise RecordError("no_open_mark", "No mark is open; start one first.")
                if runner is not None:
                    try:
                        runner.check_end(open_mark.id, by_timer=False)
                    except RunnerError as exc:
                        raise RecordError(exc.code, exc.message, exc.http) from exc
                m = self.labels.end(e)
                if runner is not None:
                    runner.ended(m.id)
            view = self._mark_view(m)
        self.mgr.publish({"type": "label", "action": action, "mark": view, "n_labels": len(self.labels)})
        if runner is not None:
            self._publish_runner()
        self._notify()
        return {"action": action, "mark": view}

    # ----------------------------------------------------------------------------- protocol runner

    def _make_runner(self, protocol: str, persons: list[str]) -> ProtocolRunner:
        """Load ``docs/protocols/<protocol>.yaml`` and lay out its steps for these persons, or a 422."""
        try:
            proto = load_named(self.cfg.repo_root, protocol)
        except ProtocolError as exc:
            raise RecordError(
                "invalid_request",
                f"the protocol {protocol} cannot be run: " + "; ".join(exc.problems),
                http=422,
                details=[{"loc": ["protocol"], "msg": p} for p in exc.problems],
            ) from exc
        try:
            return ProtocolRunner(proto, persons, timed_scale=self._timed_scale)
        except ProtocolError as exc:
            raise RecordError(
                "invalid_request",
                "; ".join(exc.problems),
                http=422,
                details=[{"loc": ["persons"], "msg": p} for p in exc.problems],
            ) from exc

    def runner_view(self) -> dict:
        with self._lock:
            return self.runner.view() if self.runner is not None else runner_off()

    def runner_event(self) -> dict:
        return {"type": "runner", **self.runner_view()}

    def _publish_runner(self) -> None:
        """Build and publish the runner view under the lock, so views go out in the order the state changed: the
        countdown ticker can never publish a view older than the one the countdown's end published."""
        with self._lock:
            self.mgr.publish(self.runner_event())

    def _require_runner(self) -> ProtocolRunner:
        if self.state != "recording":
            raise RecordError("not_recording", "The protocol runner works while a recording runs.")
        if self.runner is None:
            raise RecordError("runner_off", "The protocol runner is not running; start it first.")
        return self.runner

    def runner_start(self, protocol: str | None = None) -> dict:
        """Start the runner in a running recording (the session's protocol and persons unless named)."""
        with self._lock:
            if self.state != "recording" or self.form is None:
                raise RecordError("not_recording", "The protocol runner works while a recording runs.")
            if self.runner is not None:
                raise RecordError("runner_active", "The protocol runner is already running; stop it first.")
            if self.labels.open_mark() is not None:
                raise RecordError("mark_open", "A mark is open; end it before starting the runner.")
            if protocol is not None and protocol != self.form.protocol:
                raise RecordError(
                    "protocol_mismatch",
                    f"This session records protocol {self.form.protocol!r}; the runner can only run that one "
                    f"(the sidecar's protocol field would not match {protocol!r}).",
                )
            self.runner = self._make_runner(self.form.protocol, list(self.form.persons))
            view = self.runner.view()
        self._publish_runner()
        return view

    def runner_stop(self) -> dict:
        """Leave the runner: marks take the label form's fields again. Refused while a pass or countdown is open."""
        with self._lock:
            runner = self._require_runner()
            try:
                runner._busy()
            except RunnerError as exc:
                raise RecordError(exc.code, exc.message, exc.http) from exc
            self.runner = None
            self._runner_summary = runner.summary()  # the result reports the last run, even one left by hand
            view = runner_off()
        self._publish_runner()
        return view

    def runner_move(self, action: str, index: int | None = None) -> dict:
        """``next``, ``back``, ``skip`` or ``goto`` (with ``index``)."""
        with self._lock:
            runner = self._require_runner()
            try:
                if action == "next":
                    runner.next()
                elif action == "back":
                    runner.back()
                elif action == "skip":
                    runner.skip()
                elif action == "goto" and index is not None:
                    runner.goto(index)
                else:  # pragma: no cover - the routes only pass these
                    raise RunnerError("invalid_request", f"unknown runner action {action!r}", 422)
            except RunnerError as exc:
                raise RecordError(exc.code, exc.message, exc.http) from exc
            view = runner.view()
        self._publish_runner()
        return view

    def runner_cancel(self) -> dict:
        """Cancel a running countdown: its open label is deleted and the step can be started again."""
        with self._lock:
            runner = self._require_runner()
            try:
                mark_id = runner.cancel_countdown()
            except RunnerError as exc:
                raise RecordError(exc.code, exc.message, exc.http) from exc
            self._disarm_countdown()
            self.labels.delete(mark_id)
            view = runner.view()
        self.mgr.publish({"type": "label", "action": "delete", "mark": {"id": mark_id}, "n_labels": len(self.labels)})
        self._publish_runner()
        self._notify()
        return view

    def _arm_countdown(self, mark_id: int, seconds: float) -> None:
        self._disarm_countdown()
        t = threading.Timer(seconds, self._countdown_fired, args=(mark_id,))
        t.daemon = True
        t.name = "rzlab-runner-countdown"
        self._countdown_timer = t
        t.start()

    def _disarm_countdown(self) -> None:
        t, self._countdown_timer = self._countdown_timer, None
        if t is not None:
            t.cancel()

    def _countdown_fired(self, mark_id: int) -> None:
        """Timer thread: the timed step is over, end its label now (stamped on the server clock)."""
        with self._lock:
            runner = self.runner
            if self.state != "recording" or runner is None or not runner.countdown_due(mark_id):
                return
            now = float(self.mgr.host_us())
            m = self.labels.end(lab.Edge("auto", now, now, None, lab.KEY_ALLOWANCE_MS))
            runner.ended(m.id)
            self._countdown_timer = None
            view = self._mark_view(m)
        self.mgr.publish({"type": "label", "action": "end", "mark": view, "n_labels": len(self.labels)})
        self._publish_runner()
        self._notify()

    def mark_from_phone(self, edge: str, arrival_us: float, rtt_ms: float) -> dict:
        """Called by the marker listener (any thread)."""
        try:
            out = self.mark(edge, "phone", arrival_us, rtt_ms)
        except RecordError as exc:
            raise MarkRefused(exc.code, exc.message) from exc
        return {"id": out["mark"]["id"]}

    def delete_label(self, mark_id: int) -> dict:
        with self._lock:
            if self.state != "recording":
                raise RecordError("not_recording", "Labels can only be removed while the recording runs.")
            m = self.labels.delete(mark_id)
            runner_changed = False
            if m is not None and self.runner is not None:
                was_countdown = self.runner.counting_down and self.runner.open_mark == mark_id
                runner_changed = self.runner.deleted(mark_id)
                if was_countdown:
                    self._disarm_countdown()
        if m is None:
            raise RecordError("not_found", f"No label with id {mark_id}.", http=404)
        self.mgr.publish({"type": "label", "action": "delete", "mark": {"id": mark_id}, "n_labels": len(self.labels)})
        if runner_changed:
            self._publish_runner()
        self._notify()
        return {"deleted": mark_id}

    def label_list(self, protocol: str) -> tuple[str, ...]:
        """The fixed label list of ``protocol`` (its YAML's ``labels`` plus the shared ones), or a 422."""
        path = (self.cfg.repo_root / "docs" / "protocols" / f"{protocol}.yaml") if self.cfg.repo_root else None
        try:
            stamp = path.stat().st_mtime_ns if path is not None else None
        except OSError:
            stamp = None
        cached = self._label_cache.get(protocol)
        if cached is not None and stamp is not None and cached[0] == stamp:
            return cached[1]
        try:
            labels = load_named(self.cfg.repo_root, protocol).labels
            if stamp is not None:
                self._label_cache[protocol] = (stamp, labels)
            return labels
        except ProtocolError as exc:
            raise RecordError(
                "invalid_request",
                f"the protocol {protocol} gives no label list: " + "; ".join(exc.problems),
                http=422,
                details=[{"loc": ["protocol"], "msg": p} for p in exc.problems],
            ) from exc

    def _check_listed(self, label: str, protocol: str) -> None:
        try:
            check_listed(label, self.label_list(protocol), protocol)
        except ValueError as exc:
            raise RecordError("invalid_label", str(exc), 422, details=[{"loc": ["label"], "msg": str(exc)}]) from exc

    def labels_allowed(self) -> list[str]:
        """The label list the label form offers: the current (or last) session's protocol, else the default one."""
        try:
            return list(self.label_list(self.form.protocol if self.form else DEFAULT_PROTOCOL))
        except RecordError:
            return []

    def set_label_state(self, st: LabelState) -> LabelState:
        form = self.form
        self._check_listed(st.label, form.protocol if form else DEFAULT_PROTOCOL)
        if st.person and form and form.persons and st.person not in form.persons and self.state != "idle":
            raise RecordError("invalid_request", "That pseudonym is not one of this session's persons.", 422)
        self.label_state = st
        return st

    def _mark_view(self, m: lab.Mark) -> dict:
        t0 = self._t_start_host_us

        def el(e: lab.Edge | None) -> float | None:
            return None if e is None else round((e.host_us - t0) / 1e6, 3)

        return {
            "id": m.id,
            "state": "open" if m.is_open else "closed",
            "label": m.label,
            "person": m.person,
            "pace": m.pace,
            "shoes": m.shoes,
            "src": m.start.src,
            "start_s": el(m.start),
            "end_s": el(m.end),
            "rtt_ms": m.start.rtt_ms,
        }

    def labels_list(self) -> list[dict]:
        return [self._mark_view(m) for m in self.labels.all()]

    # ---------------------------------------------------------------------------------- marker

    def _start_marker(self, bind: str) -> None:
        try:
            app = MarkerApp(TokenStore(), self, self.mgr.host_us)
            server = MarkerServer(app, bind, self.cfg.marker_port)
            server.start()
            self._marker = server
            if self.cfg.marker_host and not is_wildcard(bind) and self.cfg.marker_host != bind:
                self.mgr.host_log(
                    f"marker_host {self.cfg.marker_host} is ignored: the phone marker listens on {bind} only.", 2
                )
        except Exception as exc:  # noqa: BLE001 - the recording matters more than the phone
            self._marker, self._marker_error = None, f"The phone marker could not start: {exc}"
            self.mgr.host_log(self._marker_error, 2)

    def _stop_marker(self) -> None:
        marker, self._marker = self._marker, None
        if marker is not None:
            with contextlib.suppress(Exception):
                marker.stop()

    def marker_info(self, host: str | None = None) -> dict | None:
        """URL (with token) and QR code of the running marker, or None. For the loopback UI only.

        The URL names the address the listener is bound to. A ``host`` that is not that address is refused
        (400 ``bad_marker_host``) and logged: a QR code for an address nothing listens on cannot work."""
        marker = self._marker
        if marker is None:
            return None
        try:
            return describe_marker(marker.app.tokens.token, marker.port, marker.bind, self.cfg.marker_host, host)
        except MarkerHostError as exc:
            self.mgr.host_log(f"Marker address refused: {exc}", 2)
            raise RecordError("bad_marker_host", str(exc), http=400) from exc

    # ------------------------------------------------------------------------------------ status

    def _live_loss(self) -> dict[str, dict]:
        st = self.mgr.state().get("status") or {}
        return {s["name"]: s.get("loss") for s in st.get("streams", [])}

    def status(self) -> dict:
        """The ``recording`` event: state, progress of every file, label counters, marker, and the last result."""
        loss = self._live_loss() if self.state in ("recording", "stopping") else {}
        streams = []
        for plan in self._plans.values():
            stats = plan.cap.stats()
            base = stats["base"]
            last = stats["last_index"]
            streams.append(
                {
                    "stream": plan.stream["name"],
                    "file": f"{plan.stem}.wav",
                    "frames_written": stats["frames_written"],
                    "frames_received": (last + 1 - base) if base is not None and last is not None else 0,
                    "queue_depth": stats["queue_depth"],
                    "overflow_packets": stats["overflow_packets"],
                    "rejected_packets": stats["rejected_packets"],
                    "error": stats["error"],
                    "loss": loss.get(plan.stream["name"]),
                }
            )
        marker = self._marker
        elapsed = (self.mgr.host_us() - self._t_start_host_us) / 1e6 if self.state == "recording" else None
        return {
            "type": "recording",
            "state": self.state,
            "session": self.session,
            "protocol": self.form.protocol if self.form else None,
            "elapsed_s": None if elapsed is None else round(elapsed, 1),
            "streams": streams,
            "n_labels": len(self.labels),
            "marking": self.labels.open_mark() is not None,
            "label_state": self.label_state.model_dump(),
            "labels_allowed": self.labels_allowed(),
            "marker": None if marker is None else {"active": True, "port": marker.port},
            "marker_error": self._marker_error,
            "last": self.last,
        }

    def _tick_loop(self) -> None:
        while not self._ticker_stop.wait(PROGRESS_PERIOD_S):
            with contextlib.suppress(Exception):
                self.mgr.publish(self.status())
                with self._lock:  # checked and published under the lock: an ended countdown is never re-sent
                    runner = self.runner
                    if runner is not None and runner.counting_down:
                        self._publish_runner()  # the countdown's remaining seconds, for a page opened meanwhile

    # ------------------------------------------------------------------------------------- stop

    def _quiesce(self) -> None:
        """No more marks, no phone, no progress events, no runner; an open mark ends now."""
        self._stop_marker()
        self._ticker_stop.set()
        with self._lock:
            self._disarm_countdown()
            runner, self.runner = self.runner, None
            if runner is not None:
                self._runner_summary = runner.summary()
        if runner is not None:
            self._publish_runner()
        now = self.mgr.host_us()
        open_mark = self.labels.open_mark()
        if open_mark is not None:
            with contextlib.suppress(ValueError):
                self.labels.end(self._edge(open_mark.start.src, now, None))
                self._closed_at_stop += 1

    def stop(self) -> dict:
        """Stop recording and write the files. Returns the result (also in ``status()['last']``)."""
        with self._lock:
            if self.state in ("stopping", "finalizing"):
                wait = True
            elif self.state == "recording":
                self.state = "stopping"
                wait = False
            else:
                raise RecordError("not_recording", "No recording is running.")
        if wait:
            self._done.wait(STOP_TIMEOUT_S + 60)
            if self.last is None:
                raise RecordError("busy", "The recording is still being finished; try again in a moment.")
            return self.last
        self._notify()
        self._quiesce()
        mask = 0
        for sid in self._plans:
            mask |= 1 << sid
        try:
            out = self.mgr.record_stop(mask).result(timeout=STOP_TIMEOUT_S)
        except DeviceError as exc:
            # the node is not reachable any more: finish with what the link-loss hook saved (or nothing)
            lost = self._lost
            self._ended_by = "link_lost"
            out = {"snapshot": lost[0] if lost else {}, "stop_error": f"could not stop the node: {exc.message}"}
        try:
            return self._finalize(out["snapshot"], out["stop_error"])
        except Exception as exc:  # noqa: BLE001
            self._fail_finalize(exc)
            raise RecordError("finalize_failed", f"The files could not be finished: {exc}", http=500) from exc

    def _fail_finalize(self, exc: BaseException) -> None:
        self.last = {"ok": False, "session": self.session, "problems": [f"finishing the recording failed: {exc!r}"]}
        with self._lock:
            self.state = "idle"
            self._done.set()
        self.mgr.publish(self.status())

    # --------------------------------------------------------------------------------- finalise

    def _utc_of_first_frame(self, t_dev_us: int) -> str:
        off = self.mgr.clock_map.offset_at(self._t_start_host_us)
        host_first = t_dev_us - off.offset_us if off is not None else self._t_start_host_us
        return utc_string(self._epoch_ref + (host_first - self._t_start_host_us) / 1e6)

    def _finalize(self, snapshot: dict[int, dict], stop_error: str | None) -> dict:
        with self._lock:
            self.state = "finalizing"
        self.mgr.publish(self.status())
        schema = self.cfg.require_schema()
        form, ctx, session = self.form, self._ctx, self.session
        assert form is not None and ctx is not None and session is not None and self._staging_folder is not None
        problems: list[str] = []
        if stop_error:
            problems.append(stop_error)
        streams_out: list[dict] = []
        sidecar_paths: list[Path] = []
        marks = [m for m in self.labels.all() if not m.is_open]
        sim = ctx["fw_version"].endswith("-sim")
        for sid, plan in self._plans.items():
            snap = snapshot.get(sid)
            report = snap["report"] if snap else None
            res = plan.cap.finish(report.win_end if report else None, None)
            sprob: list[str] = []
            if res.error:
                sprob.append(res.error)
            if report is not None and res.base != report.win_first:
                sprob.append(f"file starts at index {res.base}, the sending window at {report.win_first}")
            rate, source, t_base = measured_rate(
                res.first_samples,
                res.t_dev_us,
                snap["rate_status_hz"] if snap else None,
                plan.stream["nominal_hz"],
                res.base,
            )
            fs_header = max(1, round(round(rate, 4)))
            io.set_wav_sample_rate(res.wav_path, fs_header)
            frames = res.end - res.base
            if res.frames != frames:
                sprob.append(f"the file holds {res.frames} frames, the window {frames}")
            if res.frames == 0:
                sprob.append("no samples were received")
            incomplete = report is None or report.incomplete
            if report is not None and report.protocol_bug:
                sprob.append("host gap came out negative: a protocol bug in the node or the lab")
            loss = {
                "device": report.device if report else 0,
                "link": report.link if report else 0,
                "host": max(0, report.host_gap) if report else 0,
            }
            # Every sample of the file that is not packet data is a zero and must sit in a loss counter (PROTOCOL.md
            # section 6). The monitor counts what arrived; what this recorder dropped afterwards (writer queue full,
            # rejected packet, write error) is in none of the node's counters, so it is added to the host loss.
            zeros_in_file = frames - res.data_samples
            dropped_here = 0
            if report is None:  # no STATUS ever arrived: nothing is attributed yet, so the zeros are host loss
                loss["host"] = max(0, zeros_in_file)
            else:
                dropped_here = zeros_in_file - (loss["device"] + loss["link"] + loss["host"])
            if dropped_here > 0:
                loss["host"] += dropped_here
            elif dropped_here < 0:
                sprob.append(f"the file holds {-dropped_here} fewer zeros than the loss counters report")
            tb = lab.StreamTimebase(res.base, res.frames, res.first_samples, res.t_dev_us, float(fs_header))
            entries: list[dict] = []
            clamped = 0
            for m in marks:
                r = lab.resolve(m, self.mgr.clock_map, tb)
                if r is None:
                    sprob.append(f"label {m.id} could not be placed (no clock or packet data)")
                    continue
                clamped += int(r.clamped)
                entries.append(lab.label_entry(m, r))
            extra: dict[str, str] = {"ended": self._ended_by}
            if sim:
                extra["source"] = "sim"
            for key, val in (
                ("dup_samples", res.duplicate_samples),
                ("rejected_packets", res.rejected_packets),
                ("writer_overflow_packets", res.overflow_packets),
                ("recorder_dropped_samples", max(dropped_here, 0)),
                ("labels_clamped", clamped),
                ("open_mark_closed_at_stop", self._closed_at_stop),
            ):
                if val:
                    extra[key] = str(val)
            if res.error:
                extra["write_error"] = "yes"
            doc = build_sidecar(
                session=session,
                node=ctx["node_id"],
                firmware=ctx["fw_version"],
                start_utc=self._utc_of_first_frame(t_base),
                stream=plan.stream,
                link=LINK_BY_KIND.get(ctx["link_kind"], "usb"),
                channels=plan.channels,
                protocol=form.protocol,
                base=res.base,
                t_dev_us=t_base,
                rate_hz=rate,
                loss=loss,
                notes=notes_text(form, frames=res.frames, rate_source=source, incomplete=incomplete, extra=extra),
                labels=entries,
            )
            json_path = self._staging_folder / f"{plan.stem}.json"
            try:
                io.save_sidecar(json_path, doc, schema)
                sidecar_paths.append(json_path)
            except ValueError as exc:
                sprob.append(str(exc))
            streams_out.append(
                {
                    "stream": plan.stream["name"],
                    "wav": f"{plan.stem}.wav",
                    "sidecar": f"{plan.stem}.json",
                    "frames": res.frames,
                    "duration_s": round(res.frames / fs_header, 3),
                    "sample_rate": doc["sample_rate"],
                    "sample_rate_measured": doc["sample_rate_measured"],
                    "rate_source": source,
                    "first_sample": res.base,
                    "loss": loss,
                    "incomplete": incomplete,
                    "labels": len(entries),
                    "problems": sprob,
                }
            )
            problems += [f"{plan.stream['name']}: {p}" for p in sprob]
        # validate in staging, then move to the data root, validate again, copy the sidecars
        staged = validate_session_folder(self._staging_folder, schema)
        validation = {"ok": staged.ok, "problems": staged.problems}
        stored, final_path, move_error = self._move_to_data_root()
        copied: list[str] = []
        skip_reason: str | None = None
        if stored == "data_root":
            final = validate_session_folder(Path(final_path), schema)
            validation = {"ok": final.ok, "problems": final.problems}
            copied, skip_reason = self._copy_sidecars(Path(final_path), sidecar_paths, final.ok, sim)
        else:
            problems.append(move_error or "the session could not be moved to the data root")
            skip_reason = "the session is still in staging"
        problems += validation["problems"]
        result = {
            "ok": not problems and not any(s["incomplete"] for s in streams_out) and validation["ok"],
            "session": session,
            "ended_by": self._ended_by,
            "stored": stored,
            "path": str(final_path),
            "streams": streams_out,
            "n_labels": len(marks),
            "runner": self._runner_summary,
            "sidecars_copied": copied,
            "sidecars_copy_skipped": skip_reason,
            "validation": validation,
            "problems": problems,
        }
        self.last = result
        with self._lock:
            self.state = "idle"
            self._done.set()
        self.mgr.publish(self.status())
        self._notify()
        return result

    def _move_to_data_root(self) -> tuple[str, str, str | None]:
        """Move the finished files from staging to the reserved data-root folder: recordings first, sidecars last
        (a sidecar in the data root means its recording is complete). Returns ``(stored, path, error)``."""
        staging, target = self._staging_folder, self._data_folder
        assert staging is not None and target is not None
        files = sorted(staging.iterdir(), key=lambda p: (p.suffix != ".wav", p.name))
        try:
            for f in files:
                shutil.move(str(f), str(target / f.name))
            staging.rmdir()
            return "data_root", str(target), None
        except OSError as exc:
            with contextlib.suppress(OSError):
                if not any(target.iterdir()):
                    target.rmdir()
            return "staging", str(staging), f"moving the session to the data root failed: {exc}"

    def _copy_sidecars(self, folder: Path, staged: list[Path], valid: bool, sim: bool) -> tuple[list[str], str | None]:
        """Copy ONLY the validated sidecars to ``sidecar_dir/<session>/``. Never a WAV, never another file."""
        dest_root = self.cfg.sidecar_dir
        if dest_root is None:
            return [], "no sidecar_dir is configured"
        if sim and not self.cfg.copy_sim_sidecars:
            return [], "simulated session: not copied (set RZ_COPY_SIM_SIDECARS=1 to copy it)"
        if not valid:
            return [], "the session did not validate"
        dest = dest_root / folder.name
        dest.mkdir(parents=True, exist_ok=True)
        out: list[str] = []
        for p in staged:
            src = folder / p.name
            if src.suffix != ".json" or not src.is_file():
                continue
            shutil.copyfile(src, dest / src.name)
            out.append(str(dest / src.name))
        return out, None

    # -------------------------------------------------------------------------------- shutdown

    def close(self) -> None:
        """Server shutdown: finish a running recording instead of losing it."""
        if self.state == "recording":
            with contextlib.suppress(Exception):
                self.stop()
        self._stop_marker()
        self._ticker_stop.set()
        self._disarm_countdown()


def root_path(cfg: LabConfig) -> Path:
    assert cfg.data_root is not None
    return cfg.data_root
