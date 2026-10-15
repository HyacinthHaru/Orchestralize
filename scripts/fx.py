#!/usr/bin/env python3
"""Reusable wet-only effects extracted from the reference production.

Frame count is preserved. The caller must allocate the desired effect tail and
set tempo-related delay explicitly. These presets are optional electronic
colours, not a universal mixing recipe.
"""
from __future__ import annotations
import argparse
import functools
import json
import math
from pathlib import Path

import numpy as np
from scipy import signal
import soundfile as sf

DEFAULT_SR = 48000
BLOCK = 262144


def _stereo(y):
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        y = np.column_stack((y, y))
    if y.ndim != 2 or y.shape[1] != 2:
        raise ValueError('Expected mono or stereo audio with frames on axis 0')
    return y


def _band(y, sr, low, high, order=2):
    high = min(high, sr * .46)
    sos = signal.butter(order, [low, high], btype='bandpass', fs=sr, output='sos')
    return signal.sosfilt(sos, y, axis=0).astype(np.float32)


def _fractional_delay(y, sr, delay_seconds, depth_seconds=0, rate_hz=.23,
                      phase=0, flutter_seconds=0, flutter_hz=4.3, flutter_phase=0):
    """Fractional, slowly modulated delay using bounded cubic interpolation blocks."""
    y = np.asarray(y, np.float32)
    n = len(y)
    out = np.zeros(n, np.float32)
    for start in range(0, n, BLOCK):
        end = min(start + BLOCK, n)
        frames = np.arange(start, end, dtype=np.float64)
        time = frames / sr
        delay = delay_seconds + depth_seconds * np.sin(2 * np.pi * rate_hz * time + phase)
        if flutter_seconds:
            delay += flutter_seconds * np.sin(2 * np.pi * flutter_hz * time + flutter_phase)
        src = frames - delay * sr
        i = np.floor(src).astype(np.int64)
        frac = (src - i).astype(np.float32)
        valid = (i >= 1) & (i + 2 < n)
        iv, fv = i[valid], frac[valid]
        xm1, x0, x1, x2 = y[iv-1], y[iv], y[iv+1], y[iv+2]
        # Catmull-Rom interpolation: good high frequency response at these tiny sweeps.
        v = x0 + .5 * fv * (x1 - xm1 + fv * (2*xm1 - 5*x0 + 4*x1 - x2 + fv * (3*(x0-x1) + x2 - xm1)))
        out[start:end][valid] = v
    return out


def chorus_return(y, sr=DEFAULT_SR, base_ms=18, depth_ms=2.2, rates=(.23, .31)):
    """Two independent modulated voices per stereo side, with no dry component."""
    y = _stereo(y)
    out = np.zeros_like(y)
    mid = (y[:, 0] + y[:, 1]) * .5
    # First voice mostly retains each source side; the second lightly fills centre.
    for channel in range(2):
        first = _fractional_delay(y[:, channel], sr, base_ms * .001, depth_ms * .001,
                                  rates[channel % len(rates)], phase=channel * 2.13 + .4)
        second = _fractional_delay(mid, sr, (base_ms + 7) * .001, depth_ms * .00067,
                                   rates[(channel + 1) % len(rates)] * .91,
                                   phase=channel * 2.71 + 2.2)
        out[:, channel] = first * .34 + second * .24
    return _band(out, sr, 150, 9500)


def tape_delay_return(y, sr=DEFAULT_SR, delay_seconds=.375,
                      feedback=.30, repeats=4):
    """Dotted-eighth echo with progressively darker repeats and subtle tape motion."""
    y = _stereo(y)
    if not 0 <= feedback < 1:
        raise ValueError('feedback must be in [0, 1)')
    if delay_seconds <= .005:
        raise ValueError('delay_seconds must be greater than 5 ms')
    out = np.zeros_like(y)
    filtered = _band(y, sr, 350, 5500)
    for repeat in range(1, int(repeats) + 1):
        if repeat > 1:
            # Repeated passage through the tape/filter path; no makeup gain.
            filtered = _band(filtered, sr, 350, max(2200, 5500 - (repeat-1)*600))
        level = .72 * feedback ** (repeat - 1)
        for channel in range(2):
            # Tiny wow and flutter, at most 0.155 ms total displacement.
            delayed = _fractional_delay(filtered[:, channel], sr, delay_seconds * repeat,
                                         depth_seconds=.00013, rate_hz=.27 + .013*repeat,
                                         phase=channel * 1.7 + repeat * .71,
                                         flutter_seconds=.000025, flutter_hz=4.1 + repeat*.31,
                                         flutter_phase=channel * 2.1 + repeat * .2)
            # Quiet cross-channel bleed supplies an old stereo tape character.
            out[:, channel] += delayed * level * .9
            out[:, 1-channel] += delayed * level * .1
    return out.astype(np.float32, copy=False)


@functools.lru_cache(maxsize=12)
def _gated_ir(sr, gate_ms):
    n = max(64, int(round(gate_ms * .001 * sr)))
    t = np.arange(n, dtype=np.float64) / sr
    rng = np.random.default_rng(198707)
    ir = np.zeros((n, 2), np.float32)
    # A dense short chamber follows audible early reflections, then is gated.
    for channel in range(2):
        noise = rng.standard_normal(n).astype(np.float32)
        rise = np.minimum(1, np.maximum(0, (t - .008) / .025))
        envelope = rise * np.exp(-np.maximum(0, t-.008) / .105)
        diffuse = noise * envelope * .015 * math.sqrt(48000 / sr)
        taps = [(7.3, .20), (11.7, .16), (18.9, .14), (27.1, .10),
                (37.7, .09), (51.3, .075), (70.1, .055), (93.7, .04)]
        for at, level in taps:
            offset = (channel * 1.9 + (1 if channel else -1) * at * .037) * .001
            ix = int(round((at * .001 + offset) * sr))
            if ix < n:
                diffuse[ix] += level * (-1 if (ix + channel) % 3 == 0 else 1)
        ir[:, channel] = _band(diffuse[:, None], sr, 170, 7400)[:, 0]
    # Filter before tapering so the gate has a strict endpoint.
    tail = min(n, max(8, int(.015 * sr)))
    taper = np.cos(np.linspace(0, np.pi/2, tail)) ** 2
    ir[-tail:] *= taper.astype(np.float32)[:, None]
    ir[-1] = 0
    return ir


@functools.lru_cache(maxsize=12)
def _plate_ir(sr, decay_seconds, predelay_ms):
    # RT60 is decay_seconds; the longer IR lets its exponential tail finish softly.
    pre = int(round(predelay_ms * .001 * sr))
    body_n = int(math.ceil(decay_seconds * 1.35 * sr))
    t = np.arange(body_n, dtype=np.float64) / sr
    rng = np.random.default_rng(198404)
    ir = np.zeros((pre + body_n, 2), np.float32)
    common = rng.standard_normal(body_n).astype(np.float32)
    rise = 1 - np.exp(-t / .022)
    envelope = np.exp(-6.90775527898 * t / decay_seconds) * rise
    for channel in range(2):
        independent = rng.standard_normal(body_n).astype(np.float32)
        bed = (independent * .85 + common * .20) * envelope * .018 * math.sqrt(48000 / sr)
        # Small early reflections produce presence without a large concert-hall bloom.
        for at, level in [(3.1,.15), (8.7,.11), (16.9,.085), (29.3,.06), (44.9,.045)]:
            ix = int(round((at + channel * (1.1 + at * .043)) * .001 * sr))
            if ix < body_n:
                bed[ix] += level * (-1 if (channel + int(at)) % 2 else 1)
        bed = _band(bed[:, None], sr, 220, 6000)[:, 0]
        tail_n = min(body_n, int(.04 * sr))
        bed[-tail_n:] *= np.cos(np.linspace(0, np.pi/2, tail_n)).astype(np.float32) ** 2
        ir[pre:, channel] = bed
    return ir


def _convolve_return(y, ir):
    y = _stereo(y)
    out = np.zeros_like(y)
    # Overlap-add bounds working memory for 281-second masters and short IRs.
    for channel in range(2):
        direct = signal.oaconvolve(y[:, channel], ir[:, channel], mode='full')[:len(y)]
        # The opposite channel shares the room with slightly different reflections.
        cross = signal.oaconvolve(y[:, 1-channel], ir[:, channel], mode='full')[:len(y)]
        out[:, channel] = direct * .86 + cross * .14
    return out


def gated_room_return(y, sr=DEFAULT_SR, gate_ms=190):
    """A wet-only 80s short chamber, gently closed during the final 15 ms."""
    if not 40 <= gate_ms <= 500:
        raise ValueError('gate_ms must be between 40 and 500')
    return _convolve_return(y, _gated_ir(int(sr), float(gate_ms)))


def plate_return(y, sr=DEFAULT_SR, decay_seconds=1.6, predelay_ms=20):
    """A clear generated stereo studio plate with 220 Hz / 6 kHz IR filtering."""
    if not .15 <= decay_seconds <= 8 or predelay_ms < 0:
        raise ValueError('Expected decay in .15–8 seconds and nonnegative predelay')
    return _convolve_return(y, _plate_ir(int(sr), float(decay_seconds), float(predelay_ms)))


def tape_saturate(y, drive_db=1.5, sr=DEFAULT_SR):
    """Optional mild, 2x oversampled, amplitude-preserving soft tape transfer.

    This returns the processed signal, not a parallel wet bus. Tanh's small-signal
    gain is compensated by the fixed drive factor, never by measured RMS.
    """
    y = _stereo(y)
    drive = 10 ** (drive_db / 20)
    # Process with overlapped blocks, trimming only resampler guard samples.
    out = np.zeros_like(y)
    guard = 96
    for start in range(0, len(y), BLOCK):
        end = min(start + BLOCK, len(y))
        a, b = max(0, start-guard), min(len(y), end+guard)
        up = signal.resample_poly(y[a:b], 2, 1, axis=0, window=('kaiser', 9.0))
        shaped = np.tanh(up * drive) / drive
        down = signal.resample_poly(shaped, 1, 2, axis=0, window=('kaiser', 9.0))
        out[start:end] = down[start-a:end-a]
    return out

