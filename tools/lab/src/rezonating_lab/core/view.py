"""Display-only maths for the Lab's scope, spectrum and spectrogram views.

These functions exist so the browser can draw what the ring buffers hold: min/max envelopes for a time window
squeezed into pixel columns, a Welch PSD, STFT columns and per-channel levels. They are **never** used by a
pack, a trigger, a feature or a recording (D-017: the Lab contains no signal maths that affects a pack; filters,
decimation, triggers and features come from ``rezonating_ml``). Nothing under ``rezonating_ml`` or any pack
code may import this module.

Gaps are first-class: every function takes an optional ``valid`` mask and never lets a missing sample into a
number. numpy only (no scipy), so the Lab stays light.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ------------------------------------------------------------------------------------------- envelope


@dataclass
class Envelope:
    edges: np.ndarray  # (columns + 1,) sample offsets into the input; column c covers [edges[c], edges[c+1])
    vmin: np.ndarray  # (columns, n_ch) float64, NaN where the column has no valid sample
    vmax: np.ndarray  # (columns, n_ch)
    n_valid: np.ndarray  # (columns,) valid samples in the column

    @property
    def columns(self) -> int:
        return int(self.vmin.shape[0])


def envelope(x: np.ndarray, columns: int, valid: np.ndarray | None = None) -> Envelope:
    """Min/max of ``x`` ((n,) or (n, n_ch)) in ``columns`` near-equal column bins.

    With fewer samples than columns every sample gets its own column. A column holding no valid sample is NaN
    (a gap). Min and max are exact: no averaging, so a one-sample spike never disappears in a wide window.
    """
    if columns < 1:
        raise ValueError("columns must be at least 1")
    x = np.asarray(x)
    if x.ndim == 1:
        x = x[:, None]
    n, n_ch = x.shape
    if n == 0:
        z = np.zeros((0, n_ch))
        return Envelope(np.zeros(1, np.int64), z, z.copy(), np.zeros(0, np.int64))
    cols = min(columns, n)
    edges = (np.arange(cols + 1, dtype=np.int64) * n) // cols  # strictly increasing since n >= cols
    xf = x.astype(np.float64)
    if valid is None or bool(np.all(valid)):
        vmin = np.minimum.reduceat(xf, edges[:-1], axis=0)
        vmax = np.maximum.reduceat(xf, edges[:-1], axis=0)
        return Envelope(edges, vmin, vmax, np.diff(edges))
    valid = np.asarray(valid, dtype=bool)
    vmin = np.minimum.reduceat(np.where(valid[:, None], xf, np.inf), edges[:-1], axis=0)
    vmax = np.maximum.reduceat(np.where(valid[:, None], xf, -np.inf), edges[:-1], axis=0)
    n_valid = np.add.reduceat(valid.astype(np.int64), edges[:-1])
    empty = n_valid == 0
    vmin[empty] = np.nan
    vmax[empty] = np.nan
    return Envelope(edges, vmin, vmax, n_valid)


# ------------------------------------------------------------------------------------------------ PSD


def hann_periodic(n: int) -> np.ndarray:
    """Periodic Hann window (the one scipy's spectral functions use)."""
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)


@dataclass
class Psd:
    freq_hz: np.ndarray  # (bins,)
    psd: np.ndarray  # (n_ch, bins), (input units)^2 / Hz, one-sided; NaN when no segment was usable
    n_segments: int
    nperseg: int


def welch_psd(
    x: np.ndarray,
    fs_hz: float,
    nperseg: int = 1024,
    overlap: float = 0.5,
    valid: np.ndarray | None = None,
    detrend: bool = True,
) -> Psd:
    """Welch PSD (Hann window, 50 % overlap, constant detrend, density scaling, one-sided).

    Segments that contain any invalid sample are skipped, so a gap costs the segments it touches and never
    contaminates the others. ``nperseg`` shrinks to the data length for a short window.
    """
    if fs_hz <= 0:
        raise ValueError("fs_hz must be positive")
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    n, n_ch = x.shape
    nperseg = int(min(nperseg, n))
    if nperseg < 8:
        return Psd(np.zeros(0), np.full((n_ch, 0), np.nan), 0, nperseg)
    step = max(1, int(round(nperseg * (1.0 - overlap))))
    starts = np.arange(0, n - nperseg + 1, step)
    if valid is not None:
        bad = np.concatenate(([0], np.cumsum(~np.asarray(valid, dtype=bool))))
        ok = (bad[starts + nperseg] - bad[starts]) == 0
        starts = starts[ok]
    win = hann_periodic(nperseg)
    scale = 1.0 / (fs_hz * float(np.sum(win * win)))
    nbins = nperseg // 2 + 1
    freq = np.fft.rfftfreq(nperseg, d=1.0 / fs_hz)
    if len(starts) == 0:
        return Psd(freq, np.full((n_ch, nbins), np.nan), 0, nperseg)
    acc = np.zeros((n_ch, nbins))
    offs = np.arange(nperseg)
    for chunk in range(0, len(starts), 128):
        s = starts[chunk : chunk + 128]
        seg = x[s[:, None] + offs[None, :]]  # (k, nperseg, n_ch)
        if detrend:
            seg = seg - seg.mean(axis=1, keepdims=True)
        spec = np.fft.rfft(seg * win[None, :, None], axis=1)
        acc += (spec.real**2 + spec.imag**2).sum(axis=0).T
    psd = acc * scale / len(starts)
    psd[:, 1:] *= 2.0  # one-sided
    if nperseg % 2 == 0:
        psd[:, -1] /= 2.0  # Nyquist is not doubled
    return Psd(freq, psd, int(len(starts)), nperseg)


# ------------------------------------------------------------------------------------------- spectrogram


@dataclass
class Spectrogram:
    freq_hz: np.ndarray  # (bins,)
    center_index: np.ndarray  # (cols,) sample index at the middle of each column
    power_db: np.ndarray  # (cols, bins) float32, 10 log10 of the PSD in (units)^2/Hz; NaN where a gap touches
    nfft: int
    hop: int


def stft_db(
    x: np.ndarray,
    fs_hz: float,
    nfft: int = 256,
    hop: int | None = None,
    valid: np.ndarray | None = None,
    first_index: int = 0,
    max_columns: int | None = None,
) -> Spectrogram:
    """Short-time spectrum columns of one channel (1-D ``x``), Hann window, density scaling.

    ``hop`` defaults to ``nfft // 2``. With ``max_columns`` the hop grows until the column count fits. A column
    whose window touches an invalid sample is NaN. ``first_index`` is the sample index of ``x[0]`` so columns
    can be placed on the ring's index axis.
    """
    if fs_hz <= 0:
        raise ValueError("fs_hz must be positive")
    x = np.asarray(x, dtype=np.float64).ravel()
    n = len(x)
    nfft = int(min(nfft, n))
    if nfft < 8:
        return Spectrogram(np.zeros(0), np.zeros(0, np.int64), np.zeros((0, 0), np.float32), 0, 0)
    hop = max(1, nfft // 2 if hop is None else int(hop))
    if max_columns is not None and max_columns >= 1 and n > nfft:
        hop = max(hop, -(-(n - nfft) // max_columns))
    starts = np.arange(0, n - nfft + 1, hop)
    if max_columns is not None and len(starts) > max_columns:
        starts = starts[-max_columns:]
    win = hann_periodic(nfft)
    scale = 1.0 / (fs_hz * float(np.sum(win * win)))
    freq = np.fft.rfftfreq(nfft, d=1.0 / fs_hz)
    out = np.empty((len(starts), len(freq)), np.float32)
    offs = np.arange(nfft)
    for chunk in range(0, len(starts), 256):
        s = starts[chunk : chunk + 256]
        seg = x[s[:, None] + offs[None, :]]
        seg = seg - seg.mean(axis=1, keepdims=True)
        spec = np.fft.rfft(seg * win[None, :], axis=1)
        p = (spec.real**2 + spec.imag**2) * scale
        p[:, 1:] *= 2.0
        if nfft % 2 == 0:
            p[:, -1] /= 2.0
        out[chunk : chunk + len(s)] = 10.0 * np.log10(np.maximum(p, 1e-30))
    if valid is not None:
        bad = np.concatenate(([0], np.cumsum(~np.asarray(valid, dtype=bool))))
        out[(bad[starts + nfft] - bad[starts]) > 0] = np.nan
    centers = first_index + starts + nfft // 2
    return Spectrogram(freq, centers.astype(np.int64), out, nfft, hop)


# ---------------------------------------------------------------------------------------------- levels


@dataclass
class Levels:
    n: int  # valid samples used
    mean: float
    rms: float  # about zero, in the scaled unit (includes DC)
    std: float  # about the mean (the AC part)
    peak: float  # max |value|
    clipped: int  # valid samples at full scale (code >= full_scale - 1 or <= -full_scale)


def channel_levels(
    codes: np.ndarray, scale: np.ndarray, full_scale: int, valid: np.ndarray | None = None
) -> list[Levels]:
    """RMS, peak and clipping per channel of ``codes`` ((n, n_ch) integer codes); values are ``codes * scale``."""
    codes = np.asarray(codes)
    if codes.ndim == 1:
        codes = codes[:, None]
    n_ch = codes.shape[1]
    if valid is not None:
        codes = codes[np.asarray(valid, dtype=bool)]
    n = codes.shape[0]
    out: list[Levels] = []
    for c in range(n_ch):
        if n == 0:
            nan = float("nan")
            out.append(Levels(0, nan, nan, nan, nan, 0))
            continue
        v = codes[:, c].astype(np.float64) * float(scale[c])
        clipped = int(np.count_nonzero((codes[:, c] >= full_scale - 1) | (codes[:, c] <= -full_scale)))
        out.append(
            Levels(n, float(v.mean()), float(np.sqrt(np.mean(v * v))), float(v.std()), float(np.abs(v).max()), clipped)
        )
    return out
