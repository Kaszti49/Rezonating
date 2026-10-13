"""Simulated people: a seeded gait model per pseudonym (P1, P2, ...) and a walker that follows a protocol.

Used live by ``rzlab sim --walkers P1,P2 --protocol walk-pass-v1`` (the node walks the protocol itself, so the
recorder and its protocol runner can rehearse a session) and offline by ``rzlab sim-dataset`` (dataset.py).

The model is plausible, not physical, and holds no pack maths. One footstep at the ADC input is

    w(d) = a * [ e^(-d/tau) * (sin(2 pi f1 d) + r2 * sin(2 pi f2 d + 0.7))              heel strike
               + rt * e^(-(d-dt)/tau) * sin(2 pi 1.2 f1 (d-dt) + 1.3) * [d >= dt] ]     toe-off, dt later

with ``tau = 1 / (2 pi f1 zeta)``. Each person has a centre for every parameter; pace, shoes, the floor, the day
and the position along the walk line change it; every step adds its own jitter. ``difficulty`` (0..1) scales how
far apart the persons' centres are: 0 = far apart, 1 = everyone is the same person (chance level). The jitter
does not scale, so the default 0.5 keeps a baseline classifier well above chance but below 100 %.

Person centres are drawn independently per (seed, person, parameter) (:func:`make_profile`), so P1 is the same
walker in every session of one seed and the parameters are not correlated across persons. A person also walks a
little differently in every session (:func:`session_drift`: mood, fatigue, other shoes of the same kind), drawn per
(person, session) and not scaled by difficulty. Without it a split by session would score like a split by window.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from .scenarios import AdcSignal, ScenarioConfig, Step

PACES = ("slow", "normal", "fast")
DEFAULT_DIFFICULTY = 0.5
WALK_LINE_M = 4.0  # walk-pass-v1: the marked line past the sensors
PASS_PAUSE_S = 3.0  # walk-pass-v1: stop, wait 3 s
LINE_START_M = -1.0  # the line runs from x = -1 m to x = +3 m ...
LINE_Y_M = 0.5  # ... 0.5 m beside the sensors
SENSOR_X_M = (0.0, 2.0)  # ch0 and ch1 positions along the line (the sidecar's position_m)
WAVE_SPEED_M_S = 250.0  # floor wave speed: the delay between the two sensors
ATTEN_R0_M = 0.8  # amplitude falls as 1 / (1 + (r / R0)^1.5)
MARK_LEAD_S = 0.4  # a pass label starts this long before the first step (Space pressed, then walk)
MARK_TAIL_S = 0.6  # and ends this long after the last step
STEP_GAP_S = 4.0  # between two protocol steps (reading the next instruction)

# Population centre of each parameter (normal pace, shoes on, reference floor) and the relative spread of the
# persons' centres at difficulty 0. ``jit``: per-step relative standard deviation (does not scale with difficulty).
POPULATION: dict[str, tuple[float, float, float]] = {
    #               centre  person spread  per-step jitter
    "cadence_hz": (1.85, 0.12, 0.0),  # steps per second; per-step timing jitter is cadence_jitter below
    "step_len_m": (0.72, 0.10, 0.0),
    "f1_hz": (36.0, 0.28, 0.06),
    "zeta": (0.11, 0.35, 0.12),
    "f2_ratio": (2.6, 0.15, 0.04),
    "r2": (0.45, 0.45, 0.15),
    "toe_s": (0.10, 0.30, 0.10),
    "rt": (0.35, 0.45, 0.15),
    "amp_v": (0.0015, 0.30, 0.22),  # heel-strike peak at 0 m, before gain
}
CADENCE_JITTER = (0.03, 0.03)  # relative std of the step interval: 0.03 .. 0.06 per person
LR_ASYM = (0.80, 0.18)  # the weaker foot's amplitude: 0.80 .. 0.98 of the stronger one

# Multipliers by pace and by shoes off (shoes off: softer, higher-frequency, shorter contact).
PACE_FACTORS: dict[str, dict[str, float]] = {
    "slow": {"cadence_hz": 0.75, "step_len_m": 0.85, "amp_v": 0.70, "f1_hz": 0.97},
    "normal": {},
    "fast": {"cadence_hz": 1.25, "step_len_m": 1.12, "amp_v": 1.40, "f1_hz": 1.05, "toe_s": 0.85},
}
SHOES_OFF_FACTORS = {"amp_v": 0.60, "f1_hz": 1.40, "zeta": 0.80, "r2": 1.30, "toe_s": 0.85, "rt": 0.80}
# Session effects: a floor shifts the resonance and the coupling; a day moves them a little (sensor re-placed).
FLOOR_SPREAD = {"f1_hz": 0.10, "zeta": 0.20, "amp_v": 0.30}
DAY_SPREAD = {"f1_hz": 0.02, "amp_v": 0.10}
# Per-(person, session) drift: the relative half-width of a uniform multiplier, the same for every step of that
# person in that session. Does not scale with difficulty (a person is never exactly the same twice). Sized so that a
# split by window scores clearly above a split by session (README); at half these values the per-step jitter hides
# the drift and the two splits score alike.
SESSION_DRIFT = {
    "cadence_hz": 0.08,
    "step_len_m": 0.06,
    "f1_hz": 0.08,
    "zeta": 0.12,
    "f2_ratio": 0.04,
    "r2": 0.20,
    "toe_s": 0.08,
    "rt": 0.20,
    "amp_v": 0.24,
}
_PROFILE_SALT = 0x9E1C
_PERSON_RE = re.compile(r"^P(\d+)$")


def person_number(person: str) -> int:
    m = _PERSON_RE.match(person)
    if not m:
        raise ValueError(f"person must be a pseudonym P1, P2, ... (got {person!r})")
    return int(m.group(1))


def _stable_hash(text: str) -> int:
    """A process-independent hash (Python's ``hash`` of a str changes between runs)."""
    h = 2166136261
    for b in text.encode():
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


@dataclass(frozen=True)
class GaitProfile:
    """One simulated person's centre (normal pace, shoes on, reference floor)."""

    person: str
    cadence_hz: float
    cadence_jitter: float
    step_len_m: float
    f1_hz: float
    zeta: float
    f2_ratio: float
    r2: float
    toe_s: float
    rt: float
    amp_v: float
    lr_asym: float

    def as_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _person_u(seed: int, k: int, j: int) -> float:
    """A uniform draw in [0, 1) for parameter ``j`` of person number ``k``: independent per (seed, person, parameter),
    so adding a parameter or a person never moves the others."""
    return float(np.random.default_rng(np.random.SeedSequence([seed, _PROFILE_SALT, k, j])).random())


def make_profile(person: str, seed: int, difficulty: float = DEFAULT_DIFFICULTY) -> GaitProfile:
    """The gait of ``person`` for ``seed``. ``difficulty`` 0 = persons far apart, 1 = all the same."""
    if not 0.0 <= difficulty <= 1.0:
        raise ValueError("difficulty must be between 0 and 1")
    k = person_number(person)
    scale = 1.0 - difficulty
    vals: dict[str, float] = {}
    for j, (name, (centre, spread, _jit)) in enumerate(POPULATION.items()):
        vals[name] = centre * (1.0 + scale * spread * (2.0 * _person_u(seed, k, j) - 1.0))
    n = len(POPULATION)
    return GaitProfile(
        person=person,
        cadence_jitter=CADENCE_JITTER[0] + CADENCE_JITTER[1] * _person_u(seed, k, n),
        lr_asym=LR_ASYM[0] + LR_ASYM[1] * _person_u(seed, k, n + 1),
        **vals,
    )


def session_drift(profile: GaitProfile, rng: np.random.Generator) -> GaitProfile:
    """``profile`` as walked in one session: every :data:`SESSION_DRIFT` parameter times its own uniform factor.
    ``rng`` is the session's (person, session) generator; draws in :data:`SESSION_DRIFT` order."""
    factors = {name: 1.0 + half * float(rng.uniform(-1.0, 1.0)) for name, half in SESSION_DRIFT.items()}
    return replace(profile, **{name: getattr(profile, name) * f for name, f in factors.items()})


@dataclass(frozen=True)
class SiteEffect:
    """Multipliers for one session's floor and day (1.0 = the reference floor)."""

    floor: str = "lab"
    f1: float = 1.0
    zeta: float = 1.0
    gain: float = 1.0

    @staticmethod
    def make(floor: str, day: int, seed: int) -> SiteEffect:
        fr = np.random.default_rng(np.random.SeedSequence([seed, _stable_hash(floor)]))
        dr = np.random.default_rng(np.random.SeedSequence([seed, _stable_hash(floor), day + 1]))
        f = 1.0 + FLOOR_SPREAD["f1_hz"] * fr.uniform(-1, 1)
        z = 1.0 + FLOOR_SPREAD["zeta"] * fr.uniform(-1, 1)
        g = 1.0 + FLOOR_SPREAD["amp_v"] * fr.uniform(-1, 1)
        f *= 1.0 + DAY_SPREAD["f1_hz"] * dr.uniform(-1, 1)
        g *= 1.0 + DAY_SPREAD["amp_v"] * dr.uniform(-1, 1)
        return SiteEffect(floor, float(f), float(z), float(g))


@dataclass
class WalkStep(Step):
    """A footstep of a simulated person (``t_s``: onset at x_m, seconds since acquisition start)."""

    person: str = ""
    pace: str = "normal"
    shoes: bool = True
    pass_n: int = 0  # pass number within the session (0-based)
    plan_key: str = ""  # protocol step, e.g. "P1/normal-shoes-on"
    x_m: float = 0.0  # position along the walk line
    f1_hz: float = 36.0
    tau_s: float = 0.04
    f2_hz: float = 90.0
    r2: float = 0.4
    toe_s: float = 0.1
    rt: float = 0.3

    def truth_fields(self) -> dict:
        return {"person": self.person, "pace": self.pace, "shoes": self.shoes, "pass": self.pass_n}

    @property
    def length_s(self) -> float:
        return self.toe_s + 8.0 * self.tau_s

    def channel_gain_delay(self, ch: int) -> tuple[float, float]:
        r = math.hypot(self.x_m - SENSOR_X_M[ch], LINE_Y_M)
        return 1.0 / (1.0 + (r / ATTEN_R0_M) ** 1.5), r / WAVE_SPEED_M_S

    def wave(self, d: np.ndarray) -> np.ndarray:
        """Volts at the source for times ``d`` (s, >= 0) since onset, before distance attenuation."""
        env = np.exp(-d / self.tau_s)
        heel = env * (np.sin(2 * np.pi * self.f1_hz * d) + self.r2 * np.sin(2 * np.pi * self.f2_hz * d + 0.7))
        dt = d - self.toe_s
        toe = np.where(
            dt >= 0,
            self.rt * np.exp(-np.maximum(dt, 0) / self.tau_s) * np.sin(2 * np.pi * 1.2 * self.f1_hz * dt + 1.3),
            0,
        )
        return self.amp_v * (heel + toe)


@dataclass(frozen=True)
class Mark:
    """One label the walker's protocol produces (what a person at the keyboard would mark)."""

    t0_s: float
    t1_s: float
    label: str
    plan_key: str
    person: str | None = None
    pace: str | None = None
    shoes: bool | None = None


@dataclass
class WalkSchedule:
    steps: list[WalkStep] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    end_s: float = 0.0

    def passes(self) -> list[Mark]:
        return [m for m in self.marks if m.person is not None]


def _jit(rng: np.random.Generator, rel: float) -> float:
    return max(0.3, 1.0 + rel * float(rng.standard_normal())) if rel > 0 else 1.0


def build_schedule(
    plan: Sequence,
    profiles: dict[str, GaitProfile],
    seed: int,
    *,
    start_s: float = 0.0,
    site: SiteEffect | None = None,
    passes_scale: float = 1.0,
) -> WalkSchedule:
    """Walk a protocol plan (``Protocol.expand(persons)``: items with kind, label, person, pace, shoes, target,
    duration_s, key). Timed steps become one mark of ``duration_s`` with no footsteps; a passes step becomes
    ``target`` passes (times ``passes_scale``, at least 1) of N steps along the 4 m line with a 3 s pause after
    each. Deterministic for a given seed."""
    site = site or SiteEffect()
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x57A1]))
    sched = WalkSchedule()
    t = start_s
    n_pass = 0
    for ps in plan:
        if ps.kind != "passes":
            dur = float(ps.duration_s or 0.0)
            sched.marks.append(Mark(t, t + dur, ps.label, ps.key))
            t += dur + STEP_GAP_S
            continue
        if ps.person is None or ps.person not in profiles:
            raise ValueError(f"protocol step {ps.key}: no simulated walker for person {ps.person!r}")
        prof = profiles[ps.person]
        pace = ps.pace or "normal"
        shoes = True if ps.shoes is None else bool(ps.shoes)
        pf = PACE_FACTORS[pace]
        sf = {} if shoes else SHOES_OFF_FACTORS

        def centre(name: str, prof: GaitProfile = prof, pf: dict = pf, sf: dict = sf) -> float:
            return getattr(prof, name) * pf.get(name, 1.0) * sf.get(name, 1.0)

        cadence = centre("cadence_hz")
        step_len = centre("step_len_m")
        n_steps = max(2, round(WALK_LINE_M / step_len))
        n_target = max(1, round(ps.target * passes_scale))
        for _ in range(n_target):
            forward = n_pass % 2 == 0
            t_first = t + MARK_LEAD_S
            ts = t_first
            for i in range(n_steps):
                frac = (i + 0.5) / n_steps
                x = LINE_START_M + WALK_LINE_M * (frac if forward else 1.0 - frac)
                f1 = centre("f1_hz") * site.f1 * _jit(rng, POPULATION["f1_hz"][2])
                zeta = centre("zeta") * site.zeta * _jit(rng, POPULATION["zeta"][2])
                side = 1.0 if i % 2 == 0 else prof.lr_asym
                sched.steps.append(
                    WalkStep(
                        n=len(sched.steps),
                        t_s=ts,
                        amp_v=centre("amp_v") * site.gain * side * _jit(rng, POPULATION["amp_v"][2]),
                        person=prof.person,
                        pace=pace,
                        shoes=shoes,
                        pass_n=n_pass,
                        plan_key=ps.key,
                        x_m=x,
                        f1_hz=f1,
                        tau_s=1.0 / (2 * np.pi * f1 * zeta),
                        f2_hz=f1 * centre("f2_ratio") * _jit(rng, POPULATION["f2_ratio"][2]),
                        r2=centre("r2") * _jit(rng, POPULATION["r2"][2]),
                        toe_s=centre("toe_s") * _jit(rng, POPULATION["toe_s"][2]),
                        rt=centre("rt") * _jit(rng, POPULATION["rt"][2]),
                    )
                )
                if i < n_steps - 1:
                    ts += _jit(rng, prof.cadence_jitter) / cadence
            sched.marks.append(Mark(t, ts + MARK_TAIL_S, ps.label, ps.key, prof.person, pace, shoes))
            n_pass += 1
            t = ts + MARK_TAIL_S + PASS_PAUSE_S
        t += STEP_GAP_S
    sched.end_s = t
    return sched


def render_steps(volts: np.ndarray, rate_hz: float, steps: Sequence[WalkStep], first_idx: int = 0) -> None:
    """Add ``steps`` to ``volts`` (n, 2) float64, whose row j is sample ``first_idx + j`` at ``rate_hz``."""
    n = volts.shape[0]
    for st in steps:
        for ch in range(volts.shape[1]):
            gain, delay = st.channel_gain_delay(ch)
            t_on = st.t_s + delay
            i0 = max(first_idx, math.ceil(t_on * rate_hz))
            i1 = min(first_idx + n, math.floor((t_on + st.length_s) * rate_hz) + 1)
            if i1 <= i0:
                continue
            d = np.arange(i0, i1) / rate_hz - t_on
            volts[i0 - first_idx : i1 - first_idx, ch] += gain * st.wave(d)


class WalkerAdcSignal(AdcSignal):
    """The live simulator's ADC signal when people walk a protocol (``rzlab sim --walkers``). The schedule starts
    ``start_s`` after the acquisition starts; after its end only the noise floor remains."""

    def __init__(self, cfg: ScenarioConfig, acq_id: int, schedule: WalkSchedule, shorted: bool = False) -> None:
        super().__init__(cfg, acq_id, shorted=shorted)
        self._steps = list(schedule.steps)
        self.schedule = schedule
        self._max_len_s = max((s.length_s for s in schedule.steps), default=0.0) + 0.05

    @classmethod
    def factory(
        cls,
        persons: Sequence[str],
        plan: Sequence,
        *,
        seed: int,
        difficulty: float = DEFAULT_DIFFICULTY,
        start_s: float = 10.0,
    ) -> Callable[..., WalkerAdcSignal]:
        profiles = {p: make_profile(p, seed, difficulty) for p in persons}
        schedule = build_schedule(plan, profiles, seed, start_s=start_s)

        def make(cfg: ScenarioConfig, acq_id: int, shorted: bool = False) -> WalkerAdcSignal:
            return cls(cfg, acq_id, schedule, shorted=shorted)

        make.schedule = schedule  # type: ignore[attr-defined]
        return make

    def _extend(self, until_s: float) -> None:
        return None  # the whole schedule is known up front

    def _add_steps(self, volts: np.ndarray, t: np.ndarray) -> None:
        t_a, t_b = float(t[0]), float(t[-1])
        while self._active_from < len(self._steps) and self._steps[self._active_from].t_s + self._max_len_s < t_a:
            self._active_from += 1
        live = []
        for st in self._steps[self._active_from :]:
            if st.t_s > t_b:
                break
            live.append(st)
        if live:
            render_steps(volts, self._rate_hz, live, self._first_idx)

    def block(self, first_idx: int, n: int, rate_hz: float, gains: tuple[int, int]) -> tuple[np.ndarray, list[Step]]:
        self._rate_hz, self._first_idx = rate_hz, first_idx  # _add_steps renders by index, exactly like the base
        return super().block(first_idx, n, rate_hz, gains)
