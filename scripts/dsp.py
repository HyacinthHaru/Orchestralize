#!/usr/bin/env python3
"""Reusable fixed-gain electronic voice kernels, extracted from the reference production.

Concert MIDI pitch in; 48 kHz float stereo out. These are electronic presets,
not sampled acoustic instruments. Scheduling, timing, mixing and effects live
outside this module. Per-note seeds are supplied by the project renderer.
"""
from __future__ import annotations
import argparse
import functools
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

SR = 48000
TABLE_SIZE = 8192
PRESET_PATH = Path(__file__).parents[1] / 'assets' / 'synth_presets.json'
PRESETS = json.loads(PRESET_PATH.read_text())['presets']


def _frequency(pitch):
    return 440.0 * 2.0 ** ((float(pitch) - 69.0) / 12.0)


def _seed(*items):
    raw = '|'.join(map(str, items)).encode()
    return int.from_bytes(hashlib.blake2s(raw, digest_size=4).digest(), 'little')


@functools.lru_cache(maxsize=1800)
def _table(wave, pitch, cutoff, pulse_width=0.5):
    freq = _frequency(pitch)
    max_h = min(240, max(1, int(0.43 * SR / (freq * 1.012))))
    spectrum = np.zeros(TABLE_SIZE // 2 + 1, np.complex128)
    for h in range(1, max_h + 1):
        # Butterworth-like musical low pass plus a smooth antialiasing shoulder.
        roll = 1.0 / math.sqrt(1.0 + (h * freq / cutoff) ** 6)
        nyq = min(1.0, max(0.0, (0.46 * SR - h * freq) / (0.07 * SR)))
        if wave == 'saw':
            amp = (-1.0 if h % 2 == 0 else 1.0) * roll * nyq / h
            spectrum[h] = -0.5j * amp * TABLE_SIZE
        elif wave == 'pulse':
            # A zero-mean pulse, including the phase of its Fourier series.
            spectrum[h] = (np.exp(-2j * np.pi * h * pulse_width) - 1) / (2j * np.pi * h) * TABLE_SIZE * roll * nyq
        elif wave == 'triangle' and h % 2:
            amp = (-1.0 if (h - 1) // 2 % 2 else 1.0) * roll * nyq / (h * h)
            spectrum[h] = -0.5j * amp * TABLE_SIZE
    table = np.fft.irfft(spectrum, n=TABLE_SIZE).astype(np.float32)
    peak = max(float(np.max(np.abs(table))), 1e-9)
    table /= peak
    return table


def _lookup(table, phase):
    x = np.remainder(phase, 1.0) * TABLE_SIZE
    i = x.astype(np.int32)
    frac = (x - i).astype(np.float32)
    return table[i] * (1 - frac) + table[(i + 1) % TABLE_SIZE] * frac


def _adsr(t, gate, p, art=''):
    attack = float(p.get('attack', .01))
    if art.lower().startswith('stacc'):
        gate *= .80
        attack = min(attack, .02)
    # Short notes retain an audible attack without extending their written gate.
    attack = min(attack, max(.004, gate * .25))
    decay, sustain = float(p.get('decay', .2)), float(p.get('sustain', .7))
    attack_curve = np.sin(.5 * np.pi * np.minimum(t / attack, 1)) ** 2
    decay_curve = sustain + (1 - sustain) * np.exp(-np.maximum(t - attack, 0) * 3 / max(decay, .001))
    env = attack_curve * decay_curve
    release = float(p.get('release', .25))
    gate_value = math.sin(.5 * math.pi * min(gate / attack, 1)) ** 2 * (sustain + (1 - sustain) * math.exp(-max(gate - attack, 0) * 3 / max(decay, .001)))
    ix = t >= gate
    if np.any(ix):
        tail = np.maximum(0, 1 - (t[ix] - gate) / max(release, .001))
        env[ix] = gate_value * tail ** 2
    return env.astype(np.float32)


def _pan(mono, pan):
    angle = (np.clip(pan, -1, 1) + 1) * np.pi / 4
    return np.column_stack((mono * np.cos(angle), mono * np.sin(angle))).astype(np.float32)


def _filter(x, low=None, high=None, sr=SR):
    if low and high:
        sos = signal.butter(2, [low, high], btype='bandpass', fs=sr, output='sos')
    elif low:
        sos = signal.butter(2, low, btype='highpass', fs=sr, output='sos')
    else:
        sos = signal.butter(2, high, btype='lowpass', fs=sr, output='sos')
    return signal.sosfilt(sos, x).astype(np.float32)


def _analog(pitch, t, p, rng, brightness):
    freq = _frequency(pitch)
    out = np.zeros((len(t), 2), np.float32)
    osc_count = int(p.get('oscillators', 3))
    cents = np.linspace(-p['detune_cents'], p['detune_cents'], osc_count)
    dark = _table(p['wave'], pitch, p['cutoff_dark'], p.get('pulse_width', .5))
    bright = _table(p['wave'], pitch, p['cutoff_bright'], p.get('pulse_width', .5))
    tri = _table('triangle', pitch, max(1800, p['cutoff_dark']), .5)
    if p.get('filter_decay'):
        b = brightness * (.32 + .68 * np.exp(-t / p['filter_decay']))
    else:
        b = brightness * (.91 + .09 * np.sin(2 * np.pi * .19 * t + rng.uniform(0, 2 * np.pi)))
    b = np.asarray(b, np.float32)
    for j, detune in enumerate(cents):
        osc_freq = freq * 2 ** (detune / 1200)
        lfo_hz = p.get('lfo_hz', .25) * rng.uniform(.8, 1.2)
        lfo_cents = p.get('lfo_cents', 0)
        lfo_phase = rng.uniform(0, 2 * np.pi)
        # Integrate the tiny frequency modulation so it cannot change mean tuning.
        phase_mod = -osc_freq * (2 ** (lfo_cents / 1200) - 1) / (2 * np.pi * lfo_hz) * np.cos(2 * np.pi * lfo_hz * t + lfo_phase)
        phase = osc_freq * t + phase_mod + rng.uniform(0, 1)
        mono = (1 - b) * _lookup(dark, phase) + b * _lookup(bright, phase)
        mix_tri = p.get('triangle', 0)
        mono = mono * (1 - mix_tri) + _lookup(tri, phase + .1) * mix_tri
        pan = (2 * j / max(osc_count - 1, 1) - 1) * p.get('width', .5)
        out += _pan(mono, pan) / math.sqrt(osc_count)
    if p.get('sub'):
        # Fundamental reinforcement, not a second sub-octave below the written bass.
        sub = np.sin(2 * np.pi * freq * t + rng.uniform(0, 2 * np.pi)) * p['sub']
        out += _pan(sub, 0)
    return out


def _fm(pitch, n, p, rng, brightness):
    # Four times oversampling avoids foldback from the decaying FM index.
    rate = SR * 4
    t = np.arange(n * 4, dtype=np.float64) / rate
    freq = _frequency(pitch)
    phase = rng.uniform(0, 2 * np.pi)
    ratio = p['fm_ratio']
    # Upper notes receive a smaller index, retaining the fundamental and soft tone.
    index = p['fm_index'] * (.45 + .55 * brightness) * min(1, 2600 / freq)
    mod_env = index * np.exp(-t / p['fm_decay'])
    mono = np.sin(2 * np.pi * freq * t + phase + mod_env * np.sin(2 * np.pi * freq * ratio * t))
    # A second, quiet tine, still harmonically tied to the requested note.
    layer = p.get('fm_layer', .1) * np.exp(-t / max(.13, p['fm_decay'] * .65))
    mono += layer * np.sin(2 * np.pi * freq * 3 * t + .65 * mod_env * np.sin(2 * np.pi * freq * t + .2))
    mono = signal.resample_poly(mono, 1, 4, window=('kaiser', 9.0))[:n].astype(np.float32)
    out = _pan(mono, 0)
    # Independent stereo side is a quiet, close-tuned sine rather than a mono delay.
    ts = np.arange(n, dtype=np.float64) / SR
    side = np.sin(2 * np.pi * freq * 2 ** (.8 / 1200) * ts + phase + .2) * .09 * p.get('width', .5)
    out[:, 0] += side
    out[:, 1] -= side
    return out


def _choir(pitch, t, p, rng, brightness):
    freq = _frequency(pitch)
    out = np.zeros((len(t), 2), np.float32)
    max_h = min(96, int(.42 * SR / (freq * 1.01)))
    # Broad vowel formants; subdued upper bands keep the pad behind the lead.
    h = np.arange(1, max_h + 1)
    hf = h * freq
    weight = (.8 * np.exp(-.5 * ((hf - 560) / 300) ** 2) + .45 * np.exp(-.5 * ((hf - 1150) / 470) ** 2) + .14 * np.exp(-.5 * ((hf - 2400) / 600) ** 2)) / h ** .65
    weight[0] += .38
    weight /= max(np.sum(weight ** 2) ** .5, 1)
    for detune, pan in [(-5.5, -.85), (0, 0), (5.1, .85)]:
        spectrum = np.zeros(TABLE_SIZE // 2 + 1, np.complex128)
        # Common harmonic phase models a voiced source; note phases remain random.
        spectrum[h] = -.5j * weight * TABLE_SIZE
        tab = np.fft.irfft(spectrum, n=TABLE_SIZE).astype(np.float32)
        f = freq * 2 ** (detune / 1200)
        phase = f * t + rng.uniform(0, 1) + .015 * np.sin(2 * np.pi * .23 * t + rng.uniform(0, 6.28))
        mono = _lookup(tab, phase) * (.91 + .09 * np.sin(2 * np.pi * .31 * t + rng.uniform(0, 6.28)))
        out += _pan(mono, pan) / math.sqrt(3)
    return out


def _drum(pitch, p, vel, rng):
    kind = p['drum']
    length = p.get('release', .3)
    t = np.arange(int((length + .015) * SR), dtype=np.float64) / SR
    noise = rng.standard_normal(len(t)).astype(np.float32)
    if kind == 'kick':
        # Smooth 808-like pitch fall, with a short high click tucked under its body.
        f0 = 47 + max(-6, min(8, pitch - 36)) * .55
        phase = 2 * np.pi * (f0 * t + 68 * .017 * (1 - np.exp(-t / .017)))
        body = np.sin(phase) * np.exp(-t / .105)
        click = _filter(noise, high=1700) * np.exp(-t / .006) * .16
        mono = body + click
    elif kind == 'snare':
        body = (.7 * np.sin(2 * np.pi * 184 * t) + .32 * np.sin(2 * np.pi * 321 * t + .4)) * np.exp(-t / .039)
        snare = _filter(noise, low=1200, high=8500) * np.exp(-t / .067) * .87
        mono = body + snare
    elif kind.startswith('hat'):
        metal = np.zeros(len(t))
        for f in [3820, 5137, 6173, 7349, 9293, 10973]:
            metal += np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
        metal = _filter(metal / math.sqrt(6), low=4500, high=14000)
        tau = .021 if kind == 'hat_closed' else .105
        mono = (metal * .45 + _filter(noise, low=6500, high=15500) * .5) * np.exp(-t / tau)
    elif kind == 'clap':
        band = _filter(noise, low=850, high=6500)
        bursts = np.zeros(len(t))
        for at, level in [(0, 1), (.011, .85), (.023, .75), (.036, .65)]:
            bursts += np.where(t >= at, level * np.exp(-np.maximum(t - at, 0) / .007), 0)
        bursts += .4 * np.where(t >= .038, np.exp(-np.maximum(t - .038, 0) / .055), 0)
        mono = band * bursts
    else:
        f0 = 95 * 2 ** ((pitch - 45) / 12)
        phase = 2 * np.pi * (f0 * t + f0 * .45 * .022 * (1 - np.exp(-t / .022)))
        mono = np.sin(phase) * np.exp(-t / .09) + _filter(noise, high=1400) * np.exp(-t / .015) * .18
    # Fade the first few samples; exact onset is retained while avoiding DC clicks.
    mono *= np.minimum(1, t / .0008)
    mono *= np.maximum(0, 1 - np.maximum(t - length * .8, 0) / (length * .2 + .015))
    return _pan(mono.astype(np.float32), 0) * p['amplitude'] * (vel / 100) ** 1.12


def synth_note(pitch, gate_seconds, velocity, patch, seed=1, art='', brightness=None):
    """Generate one stereo note at fixed native gain; pitch is concert MIDI."""
    p = dict(PRESETS[patch]) if isinstance(patch, str) else dict(patch)
    rng = np.random.default_rng(seed)
    if p['engine'] == 'drum':
        return _drum(pitch, p, velocity, rng).astype(np.float32)
    n = max(2, int(math.ceil((max(gate_seconds, .005) + p.get('release', .2)) * SR)))
    t = np.arange(n, dtype=np.float64) / SR
    bright = np.clip(p.get('brightness', .6) if brightness is None else brightness, .05, .95)
    if p['engine'] == 'analog':
        out = _analog(pitch, t, p, rng, bright)
    elif p['engine'] == 'fm':
        out = _fm(pitch, n, p, rng, bright)
    elif p['engine'] == 'choir':
        out = _choir(pitch, t, p, rng, bright)
    elif p['engine'] == 'sub':
        phase = rng.uniform(0, 2 * np.pi)
        freq = _frequency(pitch)
        mono = np.sin(2 * np.pi * freq * t + phase) + .12 * np.sin(4 * np.pi * freq * t + phase * .5)
        out = _pan(mono, 0)
    elif p['engine'] == 'chime':
        freq = _frequency(pitch)
        mono = np.zeros(n)
        for ratio, amp, decay in [(1, 1, 1.5), (2, .24, .8), (3, .11, .46), (4, .04, .3)]:
            if freq * ratio < SR * .43:
                mono += amp * np.sin(2 * np.pi * freq * ratio * t + rng.uniform(0, 6.28)) * np.exp(-t / decay)
        out = _pan(mono, 0)
    else:
        raise ValueError(f"Unknown engine {p['engine']!r}")
    envelope = _adsr(t, gate_seconds, p, art)
    level = p['amplitude'] * (max(1, velocity) / 100) ** .94
    out *= envelope[:, None] * level
    # All tonal output is DC- and rumble-free; bass fundamental remains intact.
    out = signal.sosfilt(signal.butter(2, 18, btype='highpass', fs=SR, output='sos'), out, axis=0).astype(np.float32)
    return out

