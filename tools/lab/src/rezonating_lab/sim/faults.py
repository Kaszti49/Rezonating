"""Fault injection for the simulator. One independent random stream per fault kind, all from one seed,
so switching one fault on does not change the signal or the other faults."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FaultConfig:
    clock_error: float = 0.008  # ADC sample clock error as a fraction (LTC6903: +0.8 % by default)
    accel_clock_error: float = -0.002  # ADXL355 output data rate error (placeholder value)
    device_drop_rate: float = 0.0  # probability that one sample index is lost in acquisition
    link_drop_rate: float = 0.0  # probability that one DATA packet never reaches the transport
    corrupt_rate: float = 0.0  # probability that one DATA frame has a byte flipped on the wire
    # Rig faults (the rig checks of server/rigcheck.py must catch each one):
    swap_channels: bool = False  # ADC ch0 and ch1 swapped (wiring or firmware channel map)
    no_gravity: bool = False  # ADXL355 z shows no 1 g (wrong axis, wrong scale or a dead sensor)
    no_adc: bool = False  # the ADC never answers: its streams START but no sample is ever produced
    # Bench mode, not a fault: ADC inputs shorted to AGND, the channels read only their noise (noise-floor check).
    shorted_inputs: bool = False


class FaultInjector:
    def __init__(self, cfg: FaultConfig, seed: int) -> None:
        for name in ("device_drop_rate", "link_drop_rate", "corrupt_rate"):
            if not 0.0 <= getattr(cfg, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        self.cfg = cfg
        device_ss, link_ss, corrupt_ss = np.random.SeedSequence(seed).spawn(3)
        self._device = np.random.default_rng(device_ss)
        self._link = np.random.default_rng(link_ss)
        self._corrupt = np.random.default_rng(corrupt_ss)

    def device_dropped(self, n: int) -> np.ndarray:
        """Boolean mask (n,): True where the sample index is lost in acquisition."""
        if self.cfg.device_drop_rate <= 0.0:
            return np.zeros(n, dtype=bool)
        return self._device.random(n) < self.cfg.device_drop_rate

    def link_dropped(self) -> bool:
        return self.cfg.link_drop_rate > 0.0 and bool(self._link.random() < self.cfg.link_drop_rate)

    @staticmethod
    def corrupt_forced(wire: bytes) -> bytes:
        """Always alter one byte in the middle of ``wire`` (never to 0x00): for the control-frame test hook."""
        out = bytearray(wire)
        pos = (len(out) - 1) // 2  # the last byte is the 0x00 delimiter
        out[pos] = (out[pos] ^ 0x55) or (out[pos] ^ 0xAA)
        return bytes(out)

    def corrupt(self, wire: bytes) -> bytes | None:
        """Return ``wire`` with one byte altered (never to 0x00, never the delimiter), or None if untouched."""
        if self.cfg.corrupt_rate <= 0.0 or self._corrupt.random() >= self.cfg.corrupt_rate:
            return None
        out = bytearray(wire)
        pos = int(self._corrupt.integers(0, len(out) - 1))  # the last byte is the 0x00 delimiter
        while True:
            new = out[pos] ^ int(self._corrupt.integers(1, 256))
            if new != 0:
                break
        out[pos] = new
        return bytes(out)
