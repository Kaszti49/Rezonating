"""Per-stream sample ring buffer indexed by sample index (PROTOCOL.md sections 4.3 and 6).

A sample lives at ``index % capacity`` and carries a validity flag, so a lost sample stays a visible gap and
nothing after it shifts. Data may arrive in order with holes (device or link loss, corrupted frames), or a
little late; whatever is older than ``capacity`` samples is gone.

``epoch`` increases on every ``reset()``. A new sending window that starts from an idle node restarts the
sample indices at 0 (section 4.3), so the display must tell old indices from new ones.

One writer thread (the device manager) and readers on other threads share a lock; every method returns copies.
"""

from __future__ import annotations

import threading

import numpy as np


class SampleRing:
    def __init__(self, n_ch: int, capacity: int) -> None:
        if n_ch < 1 or capacity < 1:
            raise ValueError("n_ch and capacity must be at least 1")
        self.n_ch = n_ch
        self.capacity = capacity
        # Touch every page now (fill), so the resident size is constant from the start and a memory-growth
        # check in a soak run sees real leaks instead of the ring filling up.
        self._data = np.empty((capacity, n_ch), dtype=np.int32)
        self._data.fill(0)
        self._valid = np.zeros(capacity, dtype=bool)
        self._lock = threading.Lock()
        self.epoch = 0
        self._base: int | None = None  # first index written in this epoch
        self._head = 0  # one past the highest index written
        self.written = 0  # samples written in this epoch (valid ones)
        self.late_dropped = 0  # samples that arrived older than the ring holds

    # ------------------------------------------------------------------------------ state

    @property
    def head(self) -> int:
        """One past the newest index in the ring (0 when empty)."""
        return self._head

    @property
    def base(self) -> int | None:
        return self._base

    def oldest(self) -> int | None:
        """Lowest index still held, or None when empty."""
        with self._lock:
            return self._oldest()

    def _oldest(self) -> int | None:
        if self._base is None:
            return None
        return max(self._base, self._head - self.capacity)

    def reset(self) -> int:
        """Forget everything (a new window with restarted indices). Returns the new epoch."""
        with self._lock:
            self.epoch += 1
            self._base = None
            self._head = 0
            self.written = 0
            self._valid.fill(False)
            return self.epoch

    # ------------------------------------------------------------------------------ helpers

    def _spans(self, lo: int, hi: int) -> list[tuple[int, int, int]]:
        """Ring slices ``(ring_from, ring_to, offset_in_range)`` covering indices ``[lo, hi)``."""
        n = hi - lo
        a = lo % self.capacity
        b = a + n
        if b <= self.capacity:
            return [(a, b, 0)]
        return [(a, self.capacity, 0), (0, b - self.capacity, self.capacity - a)]

    def _clear_valid(self, lo: int, hi: int) -> None:
        if hi - lo >= self.capacity:
            self._valid.fill(False)
            return
        for a, b, _ in self._spans(lo, hi):
            self._valid[a:b] = False

    # ------------------------------------------------------------------------------- write

    def write(self, first_sample: int, samples: np.ndarray) -> None:
        """Store ``samples`` ((n, n_ch) int32) at indices ``first_sample ...``; holes before it become gaps."""
        n = int(samples.shape[0])
        if n == 0:
            return
        with self._lock:
            if self._base is None:
                self._base = first_sample
                self._head = first_sample
            cap = self.capacity
            end = first_sample + n
            oldest_kept = self._head - cap
            if end <= oldest_kept:
                self.late_dropped += n
                return
            if first_sample < oldest_kept:
                skip = oldest_kept - first_sample
                self.late_dropped += skip
                samples = samples[skip:]
                first_sample += skip
                n -= skip
            if first_sample > self._head:
                self._clear_valid(max(self._head, first_sample - cap), first_sample)
            if n > cap:  # a single packet larger than the ring: keep the newest part
                samples = samples[n - cap :]
                first_sample += n - cap
                n = cap
            for a, b, off in self._spans(first_sample, first_sample + n):
                self._data[a:b] = samples[off : off + (b - a)]
                self._valid[a:b] = True
            self._head = max(self._head, first_sample + n)
            self.written += n

    # -------------------------------------------------------------------------------- read

    def read(self, lo: int, hi: int) -> tuple[int, np.ndarray, np.ndarray]:
        """Samples ``[lo, hi)`` clipped to what the ring holds: ``(lo, data (m, n_ch) int32, valid (m,) bool)``.
        Gaps have ``valid == False`` and zero data."""
        with self._lock:
            return self._read(lo, hi)

    def _read(self, lo: int, hi: int) -> tuple[int, np.ndarray, np.ndarray]:
        oldest = self._oldest()
        if oldest is None:
            return lo, np.zeros((0, self.n_ch), np.int32), np.zeros(0, bool)
        lo = max(lo, oldest)
        hi = min(hi, self._head)
        if hi <= lo:
            return lo, np.zeros((0, self.n_ch), np.int32), np.zeros(0, bool)
        n = hi - lo
        data = np.empty((n, self.n_ch), np.int32)
        valid = np.empty(n, bool)
        for a, b, off in self._spans(lo, hi):
            data[off : off + (b - a)] = self._data[a:b]
            valid[off : off + (b - a)] = self._valid[a:b]
        data[~valid] = 0
        return lo, data, valid

    def read_last(self, n: int) -> tuple[int, np.ndarray, np.ndarray]:
        """The newest ``n`` indices (or fewer when the ring holds less)."""
        with self._lock:
            return self._read(self._head - n, self._head)

    def runs_since(self, cursor: int, max_frames: int = 8192) -> tuple[list[tuple[int, np.ndarray]], int, int]:
        """Valid contiguous runs in ``[cursor, head)`` as ``(first_sample, samples)``, each at most ``max_frames``
        long, the new cursor (= head) and the epoch the runs belong to. Gaps are not sent: the next run's
        ``first_sample`` jumps over them."""
        with self._lock:
            lo, data, valid = self._read(cursor, self._head)
            head = self._head
            epoch = self.epoch
        if len(valid) == 0:
            return [], max(cursor, head), epoch
        edges = np.flatnonzero(np.diff(np.concatenate(([0], valid.view(np.int8), [0]))))
        runs: list[tuple[int, np.ndarray]] = []
        for s, e in zip(edges[0::2].tolist(), edges[1::2].tolist(), strict=False):
            for p in range(s, e, max_frames):
                q = min(e, p + max_frames)
                runs.append((lo + p, data[p:q]))
        return runs, head, epoch
