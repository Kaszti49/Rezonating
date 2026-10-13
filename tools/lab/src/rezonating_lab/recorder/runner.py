"""The protocol runner: walks a recording through the steps of a protocol (``protocol.py``).

The server owns this state (a browser reload or a second tab sees the same step and counters). It is driven by the
recorder, which calls it under its own lock:

* a mark **starts** (Space, the phone, or the page's button): the label, person, pace and shoes come from the current
  step (:meth:`ProtocolRunner.tags_for_start`), and :meth:`started` remembers the mark;
* a mark **ends**: :meth:`ended` counts it as one pass of the step; when the step has all its passes the runner moves
  to the next step on its own;
* a **timed** step (the 60 s silence) starts its countdown with the mark's start; the recorder ends the mark when the
  countdown is over (its timer calls :meth:`countdown_due`). Space cannot end it early: cancel it instead.
* next / back / skip / goto move by hand. They are refused while a mark is open (end it, or cancel the countdown).

Step status: ``pending`` (not reached), ``active`` (current), ``done`` (all passes), ``incomplete`` (left with fewer),
``skipped`` (left with Skip). Deleting a counted label takes it off its step's counter.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .protocol import PlanStep, Protocol


class RunnerError(Exception):
    """A runner request was refused. ``code`` and ``message`` are the API error (HTTP ``http``)."""

    def __init__(self, code: str, message: str, http: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http = http


@dataclass
class StepState:
    plan: PlanStep
    marks: list[int] = field(default_factory=list)  # ids of the counted (closed) labels
    status: str = "pending"

    @property
    def done(self) -> int:
        return len(self.marks)

    @property
    def complete(self) -> bool:
        return self.done >= self.plan.target


class ProtocolRunner:
    """One protocol run inside one recording. Not thread-safe on its own: the recorder holds its lock around calls."""

    def __init__(
        self,
        protocol: Protocol,
        persons: list[str],
        now: Callable[[], float] = time.monotonic,
        timed_scale: float = 1.0,
    ) -> None:
        if timed_scale <= 0:
            raise ValueError("timed_scale must be positive")
        self.protocol = protocol
        self.persons = list(persons)
        self.steps = [StepState(p) for p in protocol.expand(self.persons)]
        self._now = now
        self.timed_scale = timed_scale
        self.current: int | None = 0
        self.steps[0].status = "active"
        self.open_mark: int | None = None  # a mark started on the current step and not ended yet
        self.countdown_t0: float | None = None  # monotonic start of a running countdown

    # ------------------------------------------------------------------------------------ queries

    @property
    def step(self) -> StepState | None:
        return None if self.current is None else self.steps[self.current]

    @property
    def finished(self) -> bool:
        return self.current is None

    @property
    def counting_down(self) -> bool:
        return self.countdown_t0 is not None

    def duration_s(self, st: StepState) -> float | None:
        """The countdown length actually used (``duration_s / timed_scale``; the scale is 1 except in tests)."""
        d = st.plan.duration_s
        return None if d is None else d / self.timed_scale

    def countdown_remaining_s(self) -> float | None:
        st = self.step
        if self.countdown_t0 is None or st is None:
            return None
        dur = self.duration_s(st) or 0.0
        return max(0.0, dur - (self._now() - self.countdown_t0))

    @property
    def state(self) -> str:
        if self.finished:
            return "finished"
        if self.counting_down:
            return "countdown"
        if self.open_mark is not None:
            return "marking"
        return "ready"

    # -------------------------------------------------------------------------------------- marks

    def tags_for_start(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """The label fields of a mark that starts now. ``overrides`` (from the request) may only repeat them."""
        st = self.step
        if st is None:
            raise RunnerError(
                "runner_finished",
                "The protocol is complete. Go back to a step to add passes, or stop the runner to mark by hand.",
            )
        if st.complete:
            raise RunnerError(
                "step_complete",
                f"Step {st.plan.id} already has its {st.plan.target} of {st.plan.target} "
                f"{'passes' if st.plan.kind == 'passes' else 'label'}. Delete a label of it to redo one, or go to "
                "another step.",
            )
        tags = st.plan.tags()
        clash = [k for k, v in overrides.items() if v is not None and k in tags and tags[k] != v]
        if clash:
            raise RunnerError(
                "runner_owns_label",
                f"The protocol runner sets {', '.join(clash)} from the current step; stop the runner to set them by hand.",
            )
        return tags

    def started(self, mark_id: int) -> float | None:
        """A mark started on the current step. Returns the countdown length (s) when the step is timed."""
        st = self.step
        assert st is not None
        self.open_mark = mark_id
        if st.plan.kind == "timed":
            self.countdown_t0 = self._now()
            return self.duration_s(st)
        return None

    def check_end(self, mark_id: int, by_timer: bool) -> None:
        """Refuse ending a countdown's mark by hand (Space or phone): the timed label must last its full time."""
        if self.counting_down and mark_id == self.open_mark and not by_timer:
            rem = self.countdown_remaining_s() or 0.0
            raise RunnerError(
                "countdown_running",
                f"The {self.step.plan.label if self.step else ''} countdown is running ({rem:.0f} s left). "
                "Wait for it, or cancel it.",
            )

    def ended(self, mark_id: int) -> bool:
        """A mark ended. If it is this step's, count it; move on when the step is complete. True when counted."""
        if mark_id != self.open_mark:
            return False  # a mark from before the runner started
        st = self.step
        assert st is not None
        self.open_mark = None
        self.countdown_t0 = None
        st.marks.append(mark_id)
        if st.complete:
            self._leave("next")
        return True

    def deleted(self, mark_id: int) -> bool:
        """A label was deleted. Returns True when the runner changed (open mark dropped, or a counter went down)."""
        if mark_id == self.open_mark:
            self.open_mark = None
            self.countdown_t0 = None
            return True
        for i, st in enumerate(self.steps):
            if mark_id in st.marks:
                st.marks.remove(mark_id)
                if i != self.current and st.status == "done" and not st.complete:
                    st.status = "incomplete"
                return True
        return False

    def cancel_countdown(self) -> int:
        """Stop a running countdown. Returns the id of its open mark, which the recorder then deletes."""
        if not self.counting_down or self.open_mark is None:
            raise RunnerError("no_countdown", "No countdown is running.")
        mark_id = self.open_mark
        self.open_mark = None
        self.countdown_t0 = None
        return mark_id

    def countdown_due(self, mark_id: int) -> bool:
        """The timer fired: True when ``mark_id`` is still the running countdown (the recorder then ends it)."""
        return self.counting_down and self.open_mark == mark_id

    # --------------------------------------------------------------------------------- navigation

    def _busy(self) -> None:
        if self.counting_down:
            raise RunnerError("countdown_running", "A countdown is running: wait for it, or cancel it first.")
        if self.open_mark is not None:
            raise RunnerError("mark_open", "A pass is being marked: end it (Space) first.")

    def _leave(self, how: str) -> None:
        """Leave the current step (``next``, ``skip`` or ``back``/``goto``) and set its status."""
        st = self.step
        if st is None:
            return
        if st.complete:
            st.status = "done"
        elif how == "skip":
            st.status = "skipped"
        elif how == "next" or st.done > 0:
            st.status = "incomplete"
        else:
            st.status = "pending"
        nxt = (self.current or 0) + 1 if how in ("next", "skip") else None
        if nxt is not None:
            self._enter(nxt if nxt < len(self.steps) else None)

    def _enter(self, index: int | None) -> None:
        self.current = index
        if index is not None:
            self.steps[index].status = "active"

    def next(self) -> None:
        self._busy()
        if self.finished:
            raise RunnerError("runner_finished", "The protocol is complete; there is no next step.")
        self._leave("next")

    def skip(self) -> None:
        self._busy()
        if self.finished:
            raise RunnerError("runner_finished", "The protocol is complete; there is no step to skip.")
        self._leave("skip")

    def back(self) -> None:
        self._busy()
        if self.current == 0:
            raise RunnerError("runner_first_step", "This is the first step.")
        target = len(self.steps) - 1 if self.current is None else self.current - 1
        self.goto(target)

    def goto(self, index: int) -> None:
        self._busy()
        if not 0 <= index < len(self.steps):
            raise RunnerError("not_found", f"No step {index}; the steps are 0 to {len(self.steps) - 1}.", http=404)
        if index == self.current:
            return
        self._leave("goto")
        self._enter(index)

    # -------------------------------------------------------------------------------------- views

    def _counts(self, steps: list[StepState]) -> dict[str, int]:
        passes = [s for s in steps if s.plan.kind == "passes"]
        return {"done": sum(s.done for s in passes), "target": sum(s.plan.target for s in passes)}

    def view(self) -> dict[str, Any]:
        """The ``runner`` event / ``GET /api/record/runner`` (WEB_API.md section 10)."""
        st = self.step
        countdown = None
        if self.counting_down and st is not None:
            countdown = {
                "duration_s": round(self.duration_s(st) or 0.0, 3),
                "remaining_s": round(self.countdown_remaining_s() or 0.0, 3),
                "mark": self.open_mark,
            }
        return {
            "active": True,
            "protocol": self.protocol.name,
            "title": self.protocol.title,
            "persons": self.persons,
            "state": self.state,
            "current": self.current,
            "open_mark": self.open_mark,
            "countdown": countdown,
            "overall": self._counts(self.steps),
            "per_person": {p: self._counts([s for s in self.steps if s.plan.person == p]) for p in self.persons},
            "steps": [self._step_view(s) for s in self.steps],
        }

    def _step_view(self, s: StepState) -> dict[str, Any]:
        p = s.plan
        return {
            "index": p.index,
            "key": p.key,
            "id": p.id,
            "kind": p.kind,
            "label": p.label,
            "person": p.person,
            "pace": p.pace,
            "shoes": p.shoes,
            "target": p.target,
            "done": s.done,
            "duration_s": None if p.duration_s is None else round(self.duration_s(s) or 0.0, 3),
            "status": s.status,
            "instructions": p.instructions,
        }

    def summary(self) -> dict[str, Any]:
        """What the recording's result keeps of the run (WEB_API.md 9.7 ``runner``)."""
        return {
            "protocol": self.protocol.name,
            "finished": self.finished,
            "overall": self._counts(self.steps),
            "per_person": {p: self._counts([s for s in self.steps if s.plan.person == p]) for p in self.persons},
            "steps": [
                {"key": s.plan.key, "done": s.done, "target": s.plan.target, "status": s.status} for s in self.steps
            ],
        }


def runner_off() -> dict[str, Any]:
    """The ``runner`` view when no runner is active."""
    return {
        "active": False,
        "protocol": None,
        "title": None,
        "persons": [],
        "state": "off",
        "current": None,
        "open_mark": None,
        "countdown": None,
        "overall": None,
        "per_person": {},
        "steps": [],
    }
