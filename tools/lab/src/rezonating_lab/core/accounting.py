"""Loss accounting per stream (PROTOCOL.md section 6).

Received sample indices live in an interval set (sorted, disjoint, merged half-open ranges), so hours of
contiguous data at 2 kSPS cost one interval, and every gap costs one more.

For a sending window ``[win_first, win_end)``::

    missing  = (win_end - win_first) - received in the window
    device   = win_device          (STATUS)
    link     = win_link            (STATUS)
    host_gap = missing - device - link

``host_gap`` counts samples that were sent but never arrived. It is never negative; a negative value is a
protocol bug and is flagged in ``LossReport.protocol_bug``.

In the live view the window tail after the last received index is still in flight (``pending``). Device and
link losses may sit inside that tail, and the PC cannot tell how many, so subtracting all of them from the
holes before the tail can undercount: the live ``host_gap`` is then a lower bound
(``host_gap_exact`` is False) and ``host_gap_max`` is the upper bound. After a final STATUS the tail is empty
and the numbers are exact.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass


# Added to the sidecar's ``notes`` when a recording ended without a final STATUS (PROTOCOL.md section 6).
LOSS_INCOMPLETE_NOTE = "rzlab: loss=incomplete"


class IntervalSet:
    """Sorted disjoint half-open ranges ``[start, end)`` of integers."""

    def __init__(self) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []
        self._count = 0

    def __len__(self) -> int:
        """Number of integers in the set."""
        return self._count

    @property
    def n_intervals(self) -> int:
        return len(self._starts)

    def intervals(self) -> list[tuple[int, int]]:
        return list(zip(self._starts, self._ends, strict=False))

    def max_end(self) -> int | None:
        return self._ends[-1] if self._ends else None

    def add(self, start: int, end: int) -> int:
        """Add ``[start, end)``; return how many integers were new."""
        if end <= start:
            return 0
        starts, ends = self._starts, self._ends
        # Fast path: append after, or extend, the last interval (in-order data).
        if not starts or start > ends[-1]:
            starts.append(start)
            ends.append(end)
            self._count += end - start
            return end - start
        if start == ends[-1]:
            ends[-1] = end
            self._count += end - start
            return end - start
        # General path: merge with every interval that touches [start, end].
        lo = bisect_left(ends, start)  # first interval whose end >= start
        hi = bisect_right(starts, end)  # one past the last interval whose start <= end
        if lo >= hi:
            starts.insert(lo, start)
            ends.insert(lo, end)
            self._count += end - start
            return end - start
        new_start = min(start, starts[lo])
        new_end = max(end, ends[hi - 1])
        old = sum(ends[k] - starts[k] for k in range(lo, hi))
        starts[lo:hi] = [new_start]
        ends[lo:hi] = [new_end]
        added = (new_end - new_start) - old
        self._count += added
        return added

    def count_in(self, lo: int, hi: int) -> int:
        """How many integers of the set lie in ``[lo, hi)``."""
        if hi <= lo or not self._starts:
            return 0
        first = bisect_right(self._ends, lo)  # first interval ending after lo
        total = 0
        for k in range(first, len(self._starts)):
            s = self._starts[k]
            if s >= hi:
                break
            total += min(self._ends[k], hi) - max(s, lo)
        return total

    def last_below(self, hi: int) -> int | None:
        """Largest member of the set that is < ``hi``."""
        k = bisect_left(self._starts, hi) - 1
        if k < 0:
            return None
        return min(self._ends[k], hi) - 1


@dataclass
class LossReport:
    win_first: int
    win_end: int
    received: int  # indices received inside the window
    missing: int  # window length - received
    device: int
    link: int
    host_gap: int  # exact unless host_gap_exact is False: then "at least this many"
    pending: int  # live view only: window tail not yet arrived, not counted as lost
    incomplete: bool  # no final STATUS arrived; the last STATUS was used
    protocol_bug: bool  # host_gap < 0
    host_gap_exact: bool = True  # False: live view with device/link losses that may sit in the pending tail
    host_gap_max: int = 0  # upper bound of host_gap (equals host_gap when exact)

    @property
    def window(self) -> int:
        return self.win_end - self.win_first

    @property
    def sidecar_note(self) -> str | None:
        """Text for the sidecar ``notes`` field, or None when the numbers are complete."""
        return LOSS_INCOMPLETE_NOTE if self.incomplete else None


class StreamAccounting:
    """Received indices of one stream plus the latest window numbers from STATUS."""

    def __init__(self) -> None:
        self.received = IntervalSet()
        self.duplicates = 0
        self.packets = 0
        self._win: tuple[int, int, int, int] | None = None  # win_first, win_end, win_device, win_link

    def reset(self) -> None:
        """Forget everything: call when a new sending window starts from an idle node (indices restart at 0)."""
        self.__init__()

    def on_data(self, first_sample: int, n: int) -> None:
        added = self.received.add(first_sample, first_sample + n)
        self.duplicates += n - added
        self.packets += 1

    def on_status(self, win_first: int, win_end: int, win_device: int, win_link: int) -> None:
        self._win = (win_first, win_end, win_device, win_link)

    @property
    def has_window(self) -> bool:
        return self._win is not None

    @property
    def window(self) -> tuple[int, int, int, int] | None:
        """``(win_first, win_end, win_device, win_link)`` of the latest STATUS that belongs to our window."""
        return self._win

    def report(self, mode: str = "live") -> LossReport | None:
        """Loss numbers for the latest STATUS window.

        ``mode``:
        * ``"live"``: the window tail after the last received index is shown as ``pending`` and is not lost;
          ``host_gap`` is clamped at 0 (a STATUS can overtake queued DATA).
        * ``"final"``: the numbers from the final STATUS of a STOP. ``host_gap`` is exact.
        * ``"incomplete"``: the session ended without a final STATUS. The last STATUS defines the window;
          everything not attributed counts as ``host_gap``.
        """
        if self._win is None:
            return None
        if mode not in ("live", "final", "incomplete"):
            raise ValueError(mode)
        win_first, win_end, device, link = self._win
        window = max(0, win_end - win_first)
        received = self.received.count_in(win_first, win_end)
        missing = window - received
        pending = 0
        if mode == "live":
            last = self.received.last_below(win_end)
            tail_start = win_first if last is None or last < win_first else last + 1
            pending = max(0, win_end - tail_start)
        holes = missing - pending  # holes before the last received index (the whole window when not live)
        host_gap = holes - device - link
        bug = host_gap < 0
        host_gap_max = host_gap
        exact = True
        if mode == "live":
            # Device/link losses inside the pending tail are subtracted here although they are not in
            # ``holes``: a lower bound. The other extreme is that all of them sit in the tail.
            exact = pending == 0 or device + link == 0
            host_gap = max(0, host_gap)
            host_gap_max = host_gap if exact else max(host_gap, holes)
            bug = False
        return LossReport(
            win_first=win_first,
            win_end=win_end,
            received=received,
            missing=missing,
            device=device,
            link=link,
            host_gap=host_gap,
            pending=pending,
            incomplete=mode == "incomplete",
            protocol_bug=bug,
            host_gap_exact=exact,
            host_gap_max=host_gap_max,
        )
