"""Baseline person-ID classifier on ``footstep_v1`` and its evaluation (D-021).

Rules this module enforces (ml-training skill):

- The split is by **group** (session or person), never by window: no group is in both train and test.
  :func:`split_by_group` refuses any overlap.
- Every result carries a **majority-class baseline** computed on the same split; :class:`EvalResult` cannot be
  built without one, and ``flags`` say when the model does not beat it.
- Seeds are passed in; with the same inputs and seed the result is identical.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

__all__ = [
    "MODELS",
    "SPLITS",
    "EvalResult",
    "Scores",
    "evaluate",
    "make_model",
    "split_by_group",
    "train_baseline_model",
]

SPLITS = ("session", "person")
MODELS = ("logreg", "rf")
MIN_TEST_SAMPLES = 30


def split_by_group(
    groups: Sequence[Any] | np.ndarray,
    *,
    test_groups: Sequence[Any] | None = None,
    fraction: float | None = None,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Indices ``(train_idx, test_idx)`` such that no group appears on both sides.

    groups: (n_samples,), one group id per sample (session or person id).
    Give exactly one of ``test_groups`` (explicit list; every id must equal an existing id as given, with no
    truncation or rounding, and train must not be empty) or
    ``fraction`` (0 < fraction < 1: ``round(fraction * n_groups)`` groups, at least 1 and at most n_groups - 1,
    drawn with ``np.random.default_rng(seed)`` from the sorted unique ids).
    """
    g = np.asarray(groups)
    if g.ndim != 1 or g.size == 0:
        raise ValueError("groups must be a non-empty 1-D array")
    uniq = np.unique(g)
    if uniq.size < 2:
        raise ValueError(f"need at least 2 groups to split, got {uniq.size}")
    if (test_groups is None) == (fraction is None):
        raise ValueError("give exactly one of test_groups or fraction")
    if test_groups is not None:
        # Membership is checked on the ids as given, before any cast: casting to ``g.dtype`` would cut "S10" to
        # "S1" (fixed-width strings) or 1.7 to 1 (ints) and silently pick another group. ``tg`` is then taken
        # from ``uniq`` itself, so it never holds a converted id.
        want = list(test_groups)
        try:
            wanted = set(want)
            known = set(uniq.tolist())
        except TypeError as exc:
            raise ValueError(f"group ids must be hashable scalars: {exc}") from None
        unknown = [t for t in want if t not in known]
        if unknown:
            raise ValueError(f"test_groups not in groups: {unknown}")
        tg = uniq[np.fromiter((u in wanted for u in uniq.tolist()), dtype=bool, count=uniq.size)]
    else:
        if not 0.0 < float(fraction) < 1.0:
            raise ValueError(f"fraction must be in (0, 1), got {fraction}")
        n_test = min(max(int(round(fraction * uniq.size)), 1), uniq.size - 1)
        tg = np.sort(np.random.default_rng(seed).permutation(uniq)[:n_test])
    is_test = np.isin(g, tg)
    train_idx, test_idx = np.flatnonzero(~is_test), np.flatnonzero(is_test)
    if train_idx.size == 0 or test_idx.size == 0:
        raise ValueError("split leaves train or test empty")
    overlap = np.intersect1d(g[train_idx], g[test_idx])
    if overlap.size:  # cannot happen by construction; kept as the guard the rules ask for
        raise ValueError(f"groups in both train and test: {overlap.tolist()}")
    return train_idx, test_idx


def make_model(model: str, seed: int) -> Any:
    """A fresh scikit-learn estimator: ``logreg`` (standardise + logistic regression) or ``rf`` (random forest)."""
    if model == "logreg":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, random_state=seed))
    if model == "rf":
        return RandomForestClassifier(n_estimators=200, random_state=seed, n_jobs=1)
    raise ValueError(f"model must be one of {MODELS}, got {model!r}")


def train_baseline_model(X: np.ndarray, y: Sequence[Any] | np.ndarray, seed: int, model: str = "logreg") -> Any:
    """Fit :func:`make_model` on all of ``X``, ``y`` and return it, for the pipeline's model stage
    (:func:`rezonating_ml.pipeline.build_pipeline` ``model=``): it has ``predict``, ``predict_proba`` and
    ``classes_``.

    X: (n_samples, N_FEATURES), float32 ``footstep_v1`` rows; y: (n_samples,) labels. Deterministic for a given
    seed. This fits, it does not evaluate: a number about a model comes from :func:`evaluate` (group split and
    majority baseline), never from the data it was fitted on.
    """
    X = np.asarray(X)
    y = np.asarray(y)
    if X.ndim != 2 or X.shape[0] != y.shape[0] or X.shape[0] == 0:
        raise ValueError(f"need X (n, n_features) and y (n,) with n > 0, got X {X.shape}, y {y.shape}")
    if np.unique(y).size < 2:
        raise ValueError("need at least 2 classes to fit a classifier")
    return make_model(model, seed).fit(X, y)


@dataclass(frozen=True)
class Scores:
    """Metrics of one classifier on the test set. ``confusion`` rows = true, columns = predicted, ``labels`` order."""

    accuracy: float
    balanced_accuracy: float
    confusion: list[list[int]]
    per_class: dict[str, dict[str, float]]  # label -> precision, recall, f1, support
    per_group: dict[str, dict[str, float]]  # test group -> accuracy, n


@dataclass(frozen=True)
class EvalResult:
    """Model and majority-class baseline on the same group split. Refuses to exist without the baseline."""

    split: str
    model: str
    seed: int
    labels: list[str]
    train_groups: list[str]
    test_groups: list[str]
    n_train: int
    n_test: int
    scores: Scores
    baseline: Scores
    flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.baseline, Scores):
            raise ValueError("a result without a majority-class baseline is not a result")
        if set(self.train_groups) & set(self.test_groups):
            raise ValueError("train and test groups overlap")

    @property
    def beats_baseline(self) -> bool:
        return self.scores.balanced_accuracy > self.baseline.balanced_accuracy

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "beats_baseline": self.beats_baseline}

    def summary(self) -> str:
        return (
            f"{self.model} | split by {self.split}: train {self.train_groups} ({self.n_train}), "
            f"test {self.test_groups} ({self.n_test}) | accuracy {self.scores.accuracy:.3f}, "
            f"balanced {self.scores.balanced_accuracy:.3f} | majority baseline {self.baseline.accuracy:.3f}, "
            f"balanced {self.baseline.balanced_accuracy:.3f}"
            + (f" | flags: {'; '.join(self.flags)}" if self.flags else "")
        )


def _scores(y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray, labels: np.ndarray) -> Scores:
    p, r, f1, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    per_class = {
        str(lab): {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f1[i]), "support": int(s[i])}
        for i, lab in enumerate(labels)
    }
    per_group = {}
    for grp in np.unique(groups):
        m = groups == grp
        per_group[str(grp)] = {"accuracy": float(np.mean(y_true[m] == y_pred[m])), "n": int(m.sum())}
    return Scores(
        accuracy=float(accuracy_score(y_true, y_pred)),
        balanced_accuracy=float(balanced_accuracy_score(y_true, y_pred)),
        confusion=confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        per_class=per_class,
        per_group=per_group,
    )


def evaluate(
    X: np.ndarray,
    y: Sequence[Any] | np.ndarray,
    groups: Sequence[Any] | np.ndarray | Mapping[str, Sequence[Any] | np.ndarray],
    *,
    split: str = "session",
    seed: int = 0,
    model: str = "logreg",
    test_groups: Sequence[Any] | None = None,
    test_fraction: float | None = None,
    labels: Sequence[Any] | None = None,
) -> EvalResult:
    """Train ``model`` on a group split and score it next to a majority-class baseline on the same split.

    X: (n_samples, n_features), float32 (e.g. ``footstep_v1`` rows); y: (n_samples,) labels (P1, P2, ...).
    groups: (n_samples,) ids of the ``split`` kind, or a mapping ``{"session": ids, "person": ids}`` from which
    ``groups[split]`` is used. ``test_groups`` or ``test_fraction`` (default 0.25) choose the test groups
    (:func:`split_by_group`). Labels order (confusion matrix, per_class) is ``labels`` or the sorted unique y.

    Refuses: a split kind not in :data:`SPLITS`, overlap, and test labels never seen in training (a split by
    person cannot evaluate *person* identification; use ``split="session"`` for that).
    """
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    X = np.asarray(X)
    y = np.asarray(y)
    g = np.asarray(groups[split] if isinstance(groups, Mapping) else groups)
    if X.ndim != 2 or not (X.shape[0] == y.shape[0] == g.shape[0]):
        raise ValueError(f"shapes disagree: X {X.shape}, y {y.shape}, groups {g.shape}")
    if test_groups is None and test_fraction is None:
        test_fraction = 0.25
    tr, te = split_by_group(g, test_groups=test_groups, fraction=test_fraction, seed=seed)
    unseen = np.setdiff1d(y[te], y[tr])
    if unseen.size:
        raise ValueError(f"test labels never seen in training: {unseen.tolist()} (split by {split})")
    labs = np.asarray(labels) if labels is not None else np.unique(y)

    clf = make_model(model, seed).fit(X[tr], y[tr])
    base = DummyClassifier(strategy="most_frequent").fit(X[tr], y[tr])
    scores = _scores(y[te], clf.predict(X[te]), g[te], labs)
    baseline = _scores(y[te], base.predict(X[te]), g[te], labs)

    flags = []
    if scores.balanced_accuracy <= baseline.balanced_accuracy:
        flags.append("model does not beat the majority-class baseline (balanced accuracy)")
    if len(np.unique(g[te])) < 2:
        flags.append(f"only one test {split}: no spread across {split}s")
    if te.size < MIN_TEST_SAMPLES:
        flags.append(f"only {te.size} test samples (< {MIN_TEST_SAMPLES})")
    missing = np.setdiff1d(labs, y[te])
    if missing.size:
        flags.append(f"labels absent from test: {missing.tolist()}")

    return EvalResult(
        split=split,
        model=model,
        seed=seed,
        labels=[str(v) for v in labs],
        train_groups=[str(v) for v in np.unique(g[tr])],
        test_groups=[str(v) for v in np.unique(g[te])],
        n_train=int(tr.size),
        n_test=int(te.size),
        scores=scores,
        baseline=baseline,
        flags=flags,
    )
