#!/usr/bin/env python3
"""Render portable projects to aligned raw stems; never substitute missing instruments."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf

import dsp
from project import duration, load, portable_relative, save, seconds, validate

SR = 48000


def relative(root, value):
    path = Path(value)
    if not portable_relative(value):
        raise ValueError(f"Expected project-relative path: {value}")
    return root / path


def note_times(project, note):
    perf = note.get("performance", {})
    start = seconds(project, note["start"]) + perf.get("offset_seconds", 0)
    gate = (seconds(project, note["start"] + note["duration"]) - seconds(project, note["start"])) * perf.get("gate_ratio", 1)
    if start < 0:
        raise ValueError("Performance offset places a note before the audio origin")
    return start, gate


def control(part, project, number, times, default):
    entries = {seconds(project, cc["beat"]): cc["value"] for cc in part.get("cc", []) if cc["number"] == number}
    if not entries:
        return np.full_like(np.asarray(times, float), default)
    # Before the first event use the explicit instrument default, not a future value.
    entries.setdefault(0.0, default)
    knots = sorted(entries)
    return np.interp(times, knots, [entries[t] for t in knots])


def render_dsp(part, project, frames):
    inst = part["instrument"]
    preset = dict(dsp.PRESETS[inst["patch"]])
    preset.update(inst.get("config", {}))
    out = np.zeros((frames, 2), np.float32)
    for note in sorted(part["notes"], key=lambda n: (n["start"], n["id"])):
        start, gate = note_times(project, note)
        frame = round(start * SR)
        raw = f"{project.get('seed', 1)}|{part['id']}|{note['id']}|{inst['patch']}".encode()
        seed = int.from_bytes(hashlib.blake2s(raw, digest_size=4).digest(), "little")
        cc1 = float(control(part, project, 1, start, inst.get("default_cc1", 64)))
        brightness = preset.get("brightness", .6) * (.74 + .35 * cc1 / 127)
        audio = dsp.synth_note(note["pitch"], gate, note.get("velocity", 80), preset, seed, note.get("articulation", ""), brightness)
        length = min(len(audio), frames - frame)
        if length > 0:
            out[frame:frame + length] += audio[:length]
    for start in range(0, frames, SR * 8):
        end = min(start + SR * 8, frames)
        expression = control(part, project, 11, np.arange(start, end) / SR, inst.get("default_cc11", 100)) / 100
        out[start:end] *= expression.astype(np.float32)[:, None]
    return out


def render_sfz(part, project, root, destination, renderer, frames):
    if not renderer:
        raise ValueError("SFZ part needs --sfizz-renderer; see references/dependencies.md")
    instrument = part["instrument"]
    events = []
    for number, value in instrument.get("initial_cc", {}).items():
        events.append((0, "C", int(number), int(value)))
    for cc in part.get("cc", []):
        events.append((round(seconds(project, cc["beat"]) * SR), "C", cc["number"], cc["value"]))
    for note in part["notes"]:
        start, gate = note_times(project, note)
        pitch = note["pitch"] + instrument.get("trigger_transpose", 0)
        if not 0 <= pitch < 128:
            raise ValueError("Sampler trigger outside MIDI range")
        events.extend([(round(start * SR), "N", pitch, note.get("velocity", 80)),
                       (round((start + gate) * SR), "F", pitch, 0)])
    events.sort(key=lambda e: (e[0], {"F": 0, "C": 1, "N": 2}[e[1]]))
    tsv = destination.with_suffix(".tsv")
    tsv.write_text("".join(f"{frame}\t{kind}\t{a}\t{b}\n" for frame, kind, a, b in events))
    completed = subprocess.run([str(renderer), str(relative(root, instrument["sfz"])), str(tsv), str(destination), str(SR), str(frames)],
                               check=True, capture_output=True, text=True)
    destination.with_suffix(".render.log").write_text(completed.stdout + completed.stderr)
    audio, rate = sf.read(destination, dtype="float32", always_2d=True)
    if rate != SR or audio.shape != (frames, 2):
        raise ValueError("Unexpected native renderer format/frame count")
    return audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sfizz-renderer", type=Path)
    parser.add_argument("--only", nargs="+")
    args = parser.parse_args()
    project = load(args.project)
    report = validate(project)
    if not report["ok"]:
        raise ValueError(report["errors"])
    frames = round(duration(project) * SR)
    args.output.mkdir(parents=True, exist_ok=True)
    rendered = []
    for part in project["parts"]:
        if args.only and part["id"] not in args.only:
            continue
        destination = args.output / f"{part['id']}.wav"
        inst = part["instrument"]
        if inst["backend"] == "dsp":
            audio = render_dsp(part, project, frames)
        elif inst["backend"] == "sfz":
            audio = render_sfz(part, project, args.project.parent, destination, args.sfizz_renderer, frames)
        else:
            audio, rate = sf.read(relative(args.project.parent, inst["file"]), dtype="float32", always_2d=True)
            if rate != SR or audio.shape != (frames, 2):
                raise ValueError("External raw stem must already be aligned, stereo, 48 kHz and full-length")
        if not np.isfinite(audio).all():
            raise ValueError(f"Non-finite audio: {part['id']}")
        peak = float(np.max(np.abs(audio)))
        if part["notes"] and peak < 1e-8:
            raise ValueError(f"Silent nonempty part: {part['id']}")
        sf.write(destination, audio, SR, subtype="FLOAT")
        rendered.append({"id": part["id"], "file": destination.name, "frames": frames, "peak": peak, "backend": inst["backend"]})
        print(part["id"], flush=True)
    if not rendered:
        raise ValueError("No parts selected")
    save(args.output / "render_report.json", {"sample_rate": SR, "stems": rendered, "seed": project.get("seed", 1)})


if __name__ == "__main__":
    main()
