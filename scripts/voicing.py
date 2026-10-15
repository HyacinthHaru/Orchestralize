#!/usr/bin/env python3
"""Chord-tone voicing search, independent of song/key/genre.

Voices are high to low; caller chooses range, rhythm, density and restrictions.
Source melody should not be passed through this search. Pitches are concert MIDI.
"""
from itertools import product


def choose_voicing(pcs, voices, previous=None, occupied=None, min_gap=0,
                   motion_weight=.7, duplicate_weight=6, resolutions=None):
    """voices: [{id, low, high, target, sample_family}].

    previous: {id: pitch}; occupied: {(sample_family, pitch): overlap_weight};
    resolutions: {(previous_pitch_class, new_pitch_class): bonus}.
    min_gap can be zero for unison or larger for open divisi.
    """
    pcs = set(pcs)
    if not pcs or any(not isinstance(pc, int) or not 0 <= pc < 12 for pc in pcs):
        raise ValueError("Expected nonempty pitch classes 0..11")
    previous, occupied, resolutions = previous or {}, occupied or {}, resolutions or {}
    candidates = [[n for n in range(v["low"], v["high"] + 1) if n % 12 in pcs] for v in voices]
    count = 1
    for values in candidates:
        count *= len(values)
    if count > 2000000:
        raise ValueError("Split into musical voice groups or narrow ranges before exhaustive search")
    best = None
    for pitches in product(*candidates):
        if any(a - b < min_gap for a, b in zip(pitches, pitches[1:])):
            continue
        cost = 0
        for voice, pitch in zip(voices, pitches):
            old = previous.get(voice["id"], pitch)
            cost += abs(pitch - voice["target"]) + motion_weight * abs(pitch - old)
            cost += duplicate_weight * occupied.get((voice.get("sample_family", voice["id"]), pitch), 0)
            cost -= resolutions.get((old % 12, pitch % 12), 0)
        candidate = (cost, pitches)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise ValueError("No voicing fits the declared ranges/order/spacing")
    return dict(zip((v["id"] for v in voices), best[1]))
