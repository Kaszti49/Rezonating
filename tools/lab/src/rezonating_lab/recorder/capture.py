"""Streams one node stream to a WAV file while it arrives.

The device thread calls :meth:`StreamCapture.on_data` for every DATA packet. That call only puts the packet on a
bounded queue and never touches the disk. A writer thread takes packets off the queue and writes them with
``rezonating_ml.io.WavWriter``; a gap in the sample indices is written as zeros so every sample stays at its true
place (D-019). Nothing here does signal maths.

The WAV starts at ``base``, the first index of the sending window (``win_first`` of the first STATUS that belongs to
our START) and ends at the window end, so its length is exactly the window length: received samples plus the ones
counted as lost.
"""

from __future__ import annotations

import queue
import threading
import time
from array import array
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rezonating_ml.io import WavWriter

QUEUE_PACKETS = 20000  # about 13 MB of adc_raw; disk stalls longer than ~13 minutes drop packets (counted)
MAX_GAP_S = 600.0  # a jump larger than this in the sample index is a broken packet, not a loss to pad
FLUSH_EVERY_S = 2.0
_END = object()


@dataclass
class CaptureResult:
    base: int
    end: int  # one past the last index of the file
    frames: int
    wav_path: Path
    data_samples: int  # samples of real packet data in the file; the rest of the file is zeros (lost, or dropped here)
    first_samples: np.ndarray  # int64, every DATA packet received (also those the writer could not take)
    t_dev_us: np.ndarray
    duplicate_samples: int
    rejected_packets: int  # broken packets: index jump above MAX_GAP_S, or below the base
    overflow_packets: int  # not queued because the writer fell behind
    error: str | None  # the writer failed (disk full...): the file is incomplete


class StreamCapture:
    def __init__(
        self, stream_id: int, name: str, n_ch: int, nominal_hz: float, wav_path: Path, fs_header_hz: int
    ) -> None:
        self.stream_id = stream_id
        self.name = name
        self.n_ch = n_ch
        self.nominal_hz = nominal_hz
        self.wav_path = Path(wav_path)
        # The header rate is only known at the end (round of the measured rate); the file is written with the
        # nominal rate and rewritten by the finaliser (see Recorder), never read by anything before that.
        self._fs_header_hz = fs_header_hz
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_PACKETS)
        self._base: int | None = None
        self._base_set = threading.Event()
        self._abort = threading.Event()
        self._pts_first = array("q")
        self._pts_t = array("q")
        self._lock = threading.Lock()  # guards the counters below, which two threads touch
        self.frames_written = 0
        self.queued_packets = 0
        self.overflow_packets = 0
        self.rejected_packets = 0
        self.duplicate_samples = 0
        self.zero_filled = 0
        self.data_samples = 0  # samples of packet data written to the file (not zeros)
        self.last_index = -1  # highest index received
        self.error: str | None = None
        self._next_idx = 0
        self._end_target: int | None = None
        self._thread = threading.Thread(target=self._run, name=f"rzlab-rec-{name}", daemon=True)

    # ------------------------------------------------------------------------------- device thread

    def start(self) -> None:
        self._thread.start()

    @property
    def base(self) -> int | None:
        return self._base

    def set_base(self, base: int) -> None:
        """The first index of the window is known; the writer may start. Later calls are ignored."""
        if self._base is None:
            self._base = int(base)
            self._next_idx = self._base
            self._base_set.set()

    def on_data(self, first_sample: int, t_dev_us: int, samples: np.ndarray) -> None:
        """Queue one DATA packet. Never blocks: a full queue drops the packet and counts it."""
        self._pts_first.append(first_sample)
        self._pts_t.append(t_dev_us)
        n = len(samples)
        self.last_index = max(self.last_index, first_sample + n - 1)
        try:
            self._q.put_nowait((first_sample, samples))
        except queue.Full:
            self.overflow_packets += 1
        else:
            self.queued_packets += 1

    # ------------------------------------------------------------------------------ writer thread

    def _run(self) -> None:
        # Wait for the window start; packets queue up meanwhile (about one STATUS period of data).
        while not self._base_set.wait(0.1):
            pass
        if self._abort.is_set():
            return
        wav: WavWriter | None = None
        try:
            wav = WavWriter(self.wav_path, self.n_ch, self._fs_header_hz)
            last_flush = time.monotonic()
            max_gap = int(MAX_GAP_S * self.nominal_hz * 1.1)
            while True:
                item = self._q.get()
                if item is _END:
                    break
                if self.error is not None or self._abort.is_set():
                    continue  # keep draining so the device thread's queue never fills behind a dead writer
                first, samples = item
                n = len(samples)
                if first + n <= self._next_idx:
                    with self._lock:
                        self.duplicate_samples += n
                    continue
                if first < self._base:  # type: ignore[operator]
                    with self._lock:
                        self.rejected_packets += 1
                    continue
                if first < self._next_idx:  # overlaps what is written: keep the new tail only
                    cut = self._next_idx - first
                    with self._lock:
                        self.duplicate_samples += cut
                    samples, first = samples[cut:], self._next_idx
                gap = first - self._next_idx
                if gap > max_gap:
                    with self._lock:
                        self.rejected_packets += 1
                    continue
                try:
                    if gap:
                        wav.write_zeros(gap)
                        with self._lock:
                            self.zero_filled += gap
                    wav.write(np.ascontiguousarray(samples, dtype=np.int32))
                    with self._lock:
                        self.data_samples += len(samples)
                except Exception as exc:  # noqa: BLE001 - disk full, file removed, ...
                    self.error = f"writing {self.wav_path.name} failed: {exc}"
                    continue
                self._next_idx = first + len(samples)
                self.frames_written = wav.frames_written
                if time.monotonic() - last_flush >= FLUSH_EVERY_S:
                    wav.flush()  # also updates the header: a crash keeps what was written
                    last_flush = time.monotonic()
            if self.error is None and self._end_target is not None and self._next_idx < self._end_target:
                wav.write_zeros(self._end_target - self._next_idx)  # lost samples at the end keep their place
                self._next_idx = self._end_target
            self.frames_written = wav.frames_written
        except Exception as exc:  # noqa: BLE001
            self.error = self.error or f"{self.wav_path.name}: {exc}"
        finally:
            if wav is not None:
                try:
                    wav.close()
                except Exception as exc:  # noqa: BLE001
                    self.error = self.error or f"closing {self.wav_path.name} failed: {exc}"

    # ------------------------------------------------------------------------------------- finish

    def abort(self) -> None:
        """Stop without finishing the file (a recording that never started)."""
        self._abort.set()
        self._q.put(_END)
        self._base_set.set()
        self._thread.join(10)

    def finish(self, window_end: int | None, fallback_base: int | None = None) -> CaptureResult:
        """All packets are queued: write what is left, pad the end up to ``window_end``, close the file.

        ``fallback_base`` is used when no STATUS ever gave the window start: the lowest index received."""
        if self._base is None:
            pts = np.frombuffer(self._pts_first, dtype=np.int64) if len(self._pts_first) else None
            self.set_base(fallback_base if fallback_base is not None else (int(pts.min()) if pts is not None else 0))
        self._end_target = window_end
        self._q.put(_END)  # blocks only if the queue is full, i.e. never in practice: the writer drains it
        self._thread.join()
        end = max(self._next_idx, window_end or 0)
        first = np.frombuffer(self._pts_first, dtype=np.int64).copy() if len(self._pts_first) else np.empty(0, np.int64)
        t = np.frombuffer(self._pts_t, dtype=np.int64).copy() if len(self._pts_t) else np.empty(0, np.int64)
        order = np.argsort(first, kind="stable")
        assert self._base is not None
        return CaptureResult(
            base=self._base,
            end=end,
            frames=self.frames_written,
            data_samples=self.data_samples,
            wav_path=self.wav_path,
            first_samples=first[order],
            t_dev_us=t[order],
            duplicate_samples=self.duplicate_samples,
            rejected_packets=self.rejected_packets,
            overflow_packets=self.overflow_packets,
            error=self.error,
        )

    def stats(self) -> dict:
        return {
            "frames_written": self.frames_written,
            "queue_depth": self._q.qsize(),
            "overflow_packets": self.overflow_packets,
            "rejected_packets": self.rejected_packets,
            "duplicate_samples": self.duplicate_samples,
            "zero_filled": self.zero_filled,
            "data_samples": self.data_samples,
            "base": self._base,
            "last_index": self.last_index if self.last_index >= 0 else None,
            "error": self.error,
        }
