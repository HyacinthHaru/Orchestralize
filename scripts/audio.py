#!/usr/bin/env python3
"""Print reproducible linear mix stems and measure audio; musical taste needs audition."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
from scipy import signal
import soundfile as sf

import fx
from project import duration, load, save, seconds, validate

SR = 48000


def amplitude(db):
    return 10 ** (float(db) / 20)


def db(value):
    return float(20 * np.log10(max(float(value), 1e-12)))


def audio_metrics(audio, rate):
    if not np.isfinite(audio).all():
        raise ValueError("Non-finite audio")
    peak = float(np.max(np.abs(audio)))
    true_peak = peak
    # Independent blocks with overlap keep memory bounded and avoid counting artificial edge transients.
    block, overlap = rate * 8, 256
    for start in range(0, len(audio), block):
        left, right = max(0, start - overlap), min(len(audio), start + block + overlap)
        up = signal.resample_poly(audio[left:right], 4, 1, axis=0)
        core = up[(start - left) * 4:(min(start + block, len(audio)) - left) * 4]
        if len(core):
            true_peak = max(true_peak, float(np.max(np.abs(core))))
    corr = None
    if audio.shape[1] == 2 and np.std(audio[:, 0]) > 1e-10 and np.std(audio[:, 1]) > 1e-10:
        corr = float(np.corrcoef(audio.T)[0, 1])
    return {"frames": len(audio), "sample_rate": rate, "channels": audio.shape[1],
            "seconds": len(audio) / rate, "finite": True, "silent": peak < 1e-8,
            "sample_peak_dbfs": db(peak), "true_peak_4x_estimate_dbfs": db(true_peak),
            "rms_dbfs": db(np.sqrt(np.mean(np.asarray(audio, np.float64) ** 2))), "stereo_correlation": corr}


def ffmpeg_loudness(path):
    command = shutil.which("ffmpeg")
    if not command:
        return {"available": False, "reason": "ffmpeg missing; LUFS and standards-based true peak not measured"}
    result = subprocess.run([command, "-hide_banner", "-nostats", "-i", str(path), "-af",
                             "loudnorm=I=-23:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True, check=True)
    begin, end = result.stderr.rfind("{"), result.stderr.rfind("}")
    if begin < 0 or end < begin:
        raise ValueError("ffmpeg returned no loudness measurement")
    data = json.loads(result.stderr[begin:end + 1])
    return {"available": True, "input_measurements": data}


def read_stem(path, frames):
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    if rate != SR or audio.shape != (frames, 2) or not np.isfinite(audio).all():
        raise ValueError(f"Stem format/alignment error: {path.name}")
    return audio


def automation(project, entries, frames):
    knots = {seconds(project, e["beat"]): float(e["db"]) for e in entries}
    knots.setdefault(0, 0)
    times = sorted(knots)
    curve = np.empty(frames, np.float32)
    for start in range(0, frames, SR * 8):
        end = min(frames, start + SR * 8)
        curve[start:end] = 10 ** (np.interp(np.arange(start, end) / SR, times, [knots[t] for t in times]) / 20)
    return curve


def mix(project, stem_dir, output):
    report = validate(project)
    if not report["ok"]:
        raise ValueError(report["errors"])
    frames = round(duration(project) * SR)
    output.mkdir(parents=True, exist_ok=True)
    printed = output / "printed_stems"
    printed.mkdir(exist_ok=True)
    effects = project.get("mix", {}).get("effects", [])
    if len({e["id"] for e in effects}) != len(effects):
        raise ValueError("Duplicate effect bus IDs")
    sends = {e["id"]: np.zeros((frames, 2), np.float32) for e in effects}
    premaster = np.zeros((frames, 2), np.float32)
    fade = np.ones(frames, np.float32)
    endpoints = project.get("mix", {}).get("fade_seconds")
    if endpoints:
        start, end = endpoints
        if not 0 <= start < end <= frames / SR:
            raise ValueError("Invalid fade_seconds")
        fade = np.clip((end - np.arange(frames) / SR) / (end - start), 0, 1).astype(np.float32)
    names = []
    for part in project["parts"]:
        audio = read_stem(stem_dir / f"{part['id']}.wav", frames)
        settings = part.get("mix", {})
        low, high = settings.get("highpass_hz"), settings.get("lowpass_hz")
        if low or high:
            cutoff = [low, high] if low and high else low or high
            kind = "bandpass" if low and high else "highpass" if low else "lowpass"
            audio = signal.sosfilt(signal.butter(2, cutoff, btype=kind, fs=SR, output="sos"), audio, axis=0).astype(np.float32)
        pan = float(settings.get("pan", 0))
        theta = (pan + 1) * math.pi / 4
        # Stereo balance: centre preserves the existing stereo level.
        audio *= np.array([math.cos(theta), math.sin(theta)], np.float32) * math.sqrt(2) * amplitude(settings.get("gain_db", 0))
        if settings.get("gain_automation"):
            audio *= automation(project, settings["gain_automation"], frames)[:, None]
        for bus, send_db in settings.get("sends_db", {}).items():
            if bus not in sends:
                raise ValueError(f"Unknown send bus {bus}")
            sends[bus] += audio * amplitude(send_db)
        audio *= fade[:, None]
        name = f"part_{part['id']}.wav"
        sf.write(printed / name, audio, SR, subtype="FLOAT")
        names.append(name)
        premaster += audio
    functions = {"plate": fx.plate_return, "gated_room": fx.gated_room_return,
                 "chorus": fx.chorus_return, "tape_delay": fx.tape_delay_return}
    for effect in effects:
        if effect["type"] not in functions:
            raise ValueError(f"Unknown effect {effect['type']}")
        if not all(c.isalnum() or c in "-_" for c in effect["id"]):
            raise ValueError("Unsafe effect ID")
        wet = functions[effect["type"]](sends[effect["id"]], sr=SR, **effect.get("parameters", {}))
        wet *= amplitude(effect.get("return_db", 0)) * fade[:, None]
        name = f"fx_{effect['id']}.wav"
        sf.write(printed / name, wet, SR, subtype="FLOAT")
        names.append(name)
        premaster += wet
    sf.write(output / "premaster.wav", premaster, SR, subtype="FLOAT")
    master = premaster.copy()
    config = project.get("mix", {})
    if config.get("tape_drive_db") is not None:
        master = fx.tape_saturate(master, drive_db=config["tape_drive_db"], sr=SR)
    master *= amplitude(config.get("master_gain_db", 0))
    before = audio_metrics(master, SR)
    ceiling = float(config.get("true_peak_ceiling_dbfs", -1))
    attenuation = min(0, ceiling - before["true_peak_4x_estimate_dbfs"])
    master *= amplitude(attenuation)
    sf.write(output / "master.wav", master, SR, subtype="PCM_24")
    # Reread the actually printed files; do not validate only in-memory targets.
    reconstructed = np.zeros_like(premaster)
    for name in names:
        reconstructed += read_stem(printed / name, frames)
    error = float(np.max(np.abs(reconstructed - read_stem(output / "premaster.wav", frames))))
    report = {"printed_stems": names, "stem_semantics": "post part-EQ/gain/pan, FX returns and final fade; sum equals linear premaster",
              "master_semantics": "optional tape, fixed gain and one global peak-protection attenuation; no automatic LUFS normalization",
              "reconstruction_max_abs_error": error, "peak_protection_gain_db": attenuation,
              "master": audio_metrics(master, SR), "loudness": ffmpeg_loudness(output / "master.wav")}
    save(output / "mix_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    qa = sub.add_parser("qa")
    qa.add_argument("audio", type=Path)
    qa.add_argument("report", type=Path)
    recipe = sub.add_parser("mix")
    recipe.add_argument("project", type=Path)
    recipe.add_argument("stems", type=Path)
    recipe.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "mix":
        report = mix(load(args.project), args.stems, args.output)
    else:
        audio, rate = sf.read(args.audio, dtype="float32", always_2d=True)
        report = audio_metrics(audio, rate)
        report["loudness"] = ffmpeg_loudness(args.audio)
        save(args.report, report)
        if report["silent"]:
            raise SystemExit("Silent audio")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
