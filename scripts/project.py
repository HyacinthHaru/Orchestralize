#!/usr/bin/env python3
"""Portable musical contract, identity validation and MIDI export."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def identity_digest(project):
    identity = project["identity"]
    value = {key: identity[key] for key in ("events", "harmony", "form")}
    value["musical_timing"] = {key: project["timing"][key] for key in ("tempo_map", "meter_map", "end_beat")}
    return digest(value)


def seconds(project, beat):
    """Quarter-note beats to seconds; tempo changes are piecewise constant."""
    position = float(beat)
    if position < 0:
        raise ValueError("Use a nonnegative beat origin, including pickups")
    total = float(project["timing"].get("offset_seconds", 0))
    tempo = project["timing"]["tempo_map"]
    for index, item in enumerate(tempo):
        start = float(item["beat"])
        if position <= start:
            break
        stop = min(position, float(tempo[index + 1]["beat"]) if index + 1 < len(tempo) else position)
        total += (stop - start) * 60 / float(item["bpm"])
    return total


def duration(project):
    return seconds(project, project["timing"]["end_beat"]) + float(project["timing"].get("tail_seconds", 3))


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def portable_relative(value):
    if not isinstance(value, str) or not value:
        return False
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    return not posix.is_absolute() and not windows.anchor and ".." not in posix.parts and ".." not in windows.parts


def validate(project, final=False):
    errors, warnings = [], []
    def require(condition, message):
        if not condition:
            errors.append(message)
    require(project.get("schema_version") == 1, "Unsupported schema_version")
    timing = project.get("timing", {})
    end = timing.get("end_beat", 0)
    require(finite(end) and end > 0, "timing.end_beat must be positive")
    for key in ("offset_seconds", "tail_seconds"):
        require(finite(timing.get(key, 0)) and timing.get(key, 0) >= 0, f"timing.{key} must be nonnegative")
    for name in ("tempo_map", "meter_map"):
        entries = timing.get(name, [])
        require(bool(entries), f"Missing {name}")
        beats = [item.get("beat") for item in entries]
        require(all(finite(b) and 0 <= b <= end for b in beats), f"Invalid {name} positions")
        if beats and all(finite(b) for b in beats):
            require(beats[0] == 0 and all(a < b for a, b in zip(beats, beats[1:])), f"{name} must start at 0 and strictly increase")
    for item in timing.get("tempo_map", []):
        require(finite(item.get("bpm")) and 0 < item["bpm"] <= 1000, "Invalid BPM")
    for item in timing.get("meter_map", []):
        require(isinstance(item.get("numerator"), int) and item["numerator"] > 0, "Invalid meter numerator")
        require(item.get("denominator") in (1, 2, 4, 8, 16, 32, 64), "Invalid meter denominator")
    identity = project.get("identity", {})
    events = identity.get("events", [])
    by_id = {event.get("id"): event for event in events}
    require(len(by_id) == len(events) and None not in by_id, "Duplicate/missing source event IDs")
    def check_note(note, label):
        require(isinstance(note.get("pitch"), int) and 0 <= note["pitch"] <= 127, f"{label}: MIDI pitch must be 0..127")
        require(finite(note.get("start")) and note["start"] >= 0, f"{label}: invalid start")
        require(finite(note.get("duration")) and note["duration"] > 0, f"{label}: invalid duration")
        if finite(note.get("start")) and finite(note.get("duration")) and finite(end):
            require(note["start"] + note["duration"] <= end + 1e-7, f"{label}: extends beyond end_beat")
    for event in events:
        check_note(event, str(event.get("id")))
    for name in ("harmony", "form"):
        for item in identity.get(name, []):
            require(finite(item.get("start")) and finite(item.get("end")) and 0 <= item["start"] < item["end"] <= end,
                    f"Invalid {name} interval: {item.get('id')}")
            if name == "harmony":
                require(bool(item.get("pcs")) and all(isinstance(x, int) and 0 <= x < 12 for x in item["pcs"]), "Invalid chord pitch classes")
                require(item.get("bass_pc") is None or isinstance(item["bass_pc"], int) and 0 <= item["bass_pc"] < 12, "Invalid slash bass")
    transpose = identity.get("transpose_semitones", 0)
    require(isinstance(transpose, int), "transpose_semitones must be an integer")
    parts = project.get("parts", [])
    require(len({p.get("id") for p in parts}) == len(parts), "Duplicate part IDs")
    primary = Counter()
    note_ids = set()
    intervals = []
    for part in parts:
        part_id = part.get("id", "")
        require(bool(part_id) and all(c.isalnum() or c in "-_" for c in part_id), "Part IDs must be safe filename components")
        instrument = part.get("instrument", {})
        require(instrument.get("backend") in ("dsp", "sfz", "external"), f"{part_id}: unknown backend")
        for field in ("sfz", "file"):
            if field in instrument:
                require(portable_relative(instrument[field]), f"{part_id}: {field} must be a portable project-relative path")
        require(isinstance(instrument.get("gm_program", 0), int) and 0 <= instrument.get("gm_program", 0) < 128, f"{part_id}: invalid GM program")
        limits = instrument.get("range", [0, 127])
        require(len(limits) == 2 and all(isinstance(x, int) for x in limits) and 0 <= limits[0] <= limits[1] <= 127, f"{part_id}: invalid range")
        for cc in part.get("cc", []):
            require(finite(cc.get("beat")) and 0 <= cc["beat"] <= end, f"{part_id}: invalid CC beat")
            require(isinstance(cc.get("number"), int) and 0 <= cc["number"] < 128 and isinstance(cc.get("value"), int) and 0 <= cc["value"] < 128, f"{part_id}: invalid CC")
        pan = part.get("mix", {}).get("pan", 0)
        require(finite(pan) and -1 <= pan <= 1, f"{part_id}: pan outside -1..1")
        for note in part.get("notes", []):
            label = f"{part_id}/{note.get('id')}"
            require(note.get("id") not in note_ids and bool(note.get("id")), f"{label}: duplicate/missing note ID")
            note_ids.add(note.get("id"))
            check_note(note, label)
            require(isinstance(note.get("velocity", 80), int) and 1 <= note.get("velocity", 80) <= 127, f"{label}: invalid velocity")
            perf = note.get("performance", {})
            require(finite(perf.get("gate_ratio", 1)) and 0 < perf.get("gate_ratio", 1) <= 2, f"{label}: invalid gate_ratio")
            require(finite(perf.get("offset_seconds", 0)), f"{label}: invalid performance offset")
            if isinstance(note.get("pitch"), int) and len(limits) == 2:
                require(limits[0] <= note["pitch"] <= limits[1], f"{label}: outside declared sounding range")
            source_id = note.get("source_id")
            if source_id is not None:
                require(source_id in by_id, f"{label}: unknown source_id")
                if source_id in by_id:
                    source = by_id[source_id]
                    shift = note.get("octave_shift", 0)
                    require(isinstance(shift, int) and shift % 12 == 0, f"{label}: octave_shift must be a multiple of 12")
                    require(note.get("pitch") == source.get("pitch", -999) + transpose + shift, f"{label}: source pitch changed")
                    for field in ("start", "duration"):
                        require(finite(note.get(field)) and finite(source.get(field)) and abs(note[field] - source[field]) < 1e-7, f"{label}: source {field} changed")
                    if note.get("source_primary", False):
                        primary[source_id] += 1
            elif note.get("source_primary"):
                errors.append(f"{label}: source_primary without source_id")
            if note.get("harmony_id") is not None and note.get("constraint") in ("chord_tone", "bass"):
                chords = [h for h in identity.get("harmony", []) if h.get("id") == note["harmony_id"]]
                require(len(chords) == 1, f"{label}: unknown/ambiguous harmony_id")
                if len(chords) == 1 and isinstance(note.get("pitch"), int):
                    chord = chords[0]
                    original = chord["pcs"] if note["constraint"] == "chord_tone" else [chord.get("bass_pc")]
                    allowed = [(pc + transpose) % 12 for pc in original if pc is not None]
                    require(note["pitch"] % 12 in allowed, f"{label}: harmony constraint failed")
                    require(chord["start"] <= note["start"] and note["start"] + note["duration"] <= chord["end"] + 1e-7, f"{label}: chord-bound note crosses harmony interval; split or document suspension")
            if finite(note.get("start")) and finite(note.get("duration")) and not instrument.get("percussion", False):
                intervals.append((note["start"], note["start"] + note["duration"], part_id))
        if not part.get("notes"):
            warnings.append(f"{part_id}: empty part")
        if instrument.get("polyphonic") is False:
            ordered = sorted(part.get("notes", []), key=lambda n: n.get("start", 0))
            end_at = -1
            for note in ordered:
                if finite(note.get("start")) and finite(note.get("duration")):
                    require(note["start"] >= end_at - 1e-7, f"{part_id}: polyphony on a monophonic instrument")
                    end_at = max(end_at, note["start"] + note["duration"])
    if events and parts:
        require(all(primary[e] == 1 for e in by_id), "Each source event needs exactly one primary delivery (doublings must be non-primary)")
    if final:
        require(bool(identity.get("reviewed")), "Source blueprint has not been reviewed")
        require(bool(events) and bool(parts), "Final project requires source events and arranged parts")
    elif not identity.get("reviewed"):
        warnings.append("Draft: source blueprint is not reviewed")
    expected = identity.get("locked_digest")
    if expected:
        require(expected == identity_digest(project), "Locked source identity changed")
    for source in project.get("sources", []):
        path = source.get("path", "")
        require(portable_relative(path), "Source paths must be project-relative")
    changes = {}
    for start, stop, part_id in intervals:
        changes.setdefault(start, []).append((part_id, 1))
        changes.setdefault(stop, []).append((part_id, -1))
    points = sorted(changes)
    active = Counter()
    weighted, max_parts, max_notes = 0, 0, 0
    for index, start in enumerate(points):
        for part_id, delta in changes[start]:
            active[part_id] += delta
        count = sum(n > 0 for n in active.values())
        max_parts, max_notes = max(max_parts, count), max(max_notes, sum(active.values()))
        if index + 1 < len(points):
            weighted += count * (points[index + 1] - start)
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "source_events": len(events), "parts": len(parts), "arranged_notes": len(note_ids),
            "density": {"beat_weighted_active_pitched_parts": weighted / end if finite(end) and end > 0 else 0,
                        "max_active_pitched_parts": max_parts, "max_simultaneous_pitched_notes": max_notes}}


def export_midi(project, path, native=False):
    import mido
    # Beat zero is musical zero. Audio offset is documented separately, not an invented MIDI rest.
    midi = mido.MidiFile(type=1, ticks_per_beat=960)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    events = [(0, mido.MetaMessage("track_name", name=project.get("title", "Arrangement")))]
    for item in project["timing"]["tempo_map"]:
        events.append((round(item["beat"] * 960), mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(item["bpm"]))))
    for item in project["timing"]["meter_map"]:
        events.append((round(item["beat"] * 960), mido.MetaMessage("time_signature", numerator=item["numerator"], denominator=item["denominator"])))
    for item in project["identity"]["form"]:
        events.append((round(item["start"] * 960), mido.MetaMessage("marker", text=item.get("label", item["id"]))))
    def append(track, items):
        previous = 0
        for tick, message in sorted(items, key=lambda x: (x[0], 0 if x[1].type == "note_off" else 1)):
            track.append(message.copy(time=tick - previous))
            previous = tick
        track.append(mido.MetaMessage("end_of_track", time=0))
    append(conductor, events)
    melodic, drums = 0, 0
    addresses = []
    for part in project["parts"]:
        instrument = part["instrument"]
        if instrument.get("percussion", False):
            port, channel = drums, 9
            drums += 1
        else:
            port = melodic // 15
            channel = [c for c in range(16) if c != 9][melodic % 15]
            melodic += 1
        if port > 127:
            raise ValueError("More than 128 MIDI ports; split the arrangement into files")
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.extend([mido.MetaMessage("track_name", name=part["name"]), mido.MetaMessage("midi_port", port=port)])
        items = [(0, mido.Message("program_change", channel=channel, program=instrument.get("gm_program", 0)))]
        if native:
            for number, value in instrument.get("initial_cc", {}).items():
                items.append((0, mido.Message("control_change", channel=channel, control=int(number), value=int(value))))
        if not native:
            items.append((0, mido.Message("control_change", channel=channel, control=1, value=0)))
        safe_cc = instrument.get("gm_safe_cc", [11])
        for cc in part.get("cc", []):
            if native or cc["number"] in safe_cc:
                items.append((round(cc["beat"] * 960), mido.Message("control_change", channel=channel, control=cc["number"], value=cc["value"])))
        for note in part["notes"]:
            # Nominal musical timing; native sampler trigger transpose is separate from concert pitch.
            pitch = note["pitch"] + (instrument.get("trigger_transpose", 0) if native else 0)
            if not 0 <= pitch <= 127:
                raise ValueError("Native trigger pitch outside MIDI range")
            items.extend([(round(note["start"] * 960), mido.Message("note_on", channel=channel, note=pitch, velocity=note.get("velocity", 80))),
                          (round((note["start"] + note["duration"]) * 960), mido.Message("note_off", channel=channel, note=pitch, velocity=0))])
        append(track, items)
        addresses.append({"id": part["id"], "port": port, "channel_zero_based": channel})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    midi.save(path)
    return {"file": Path(path).name, "multiport": True, "timing": "nominal beats; audio offset/performance gates not applied", "addresses": addresses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("directory", type=Path)
    check = sub.add_parser("validate")
    check.add_argument("project", type=Path)
    check.add_argument("--final", action="store_true")
    check.add_argument("--report", type=Path)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("project", type=Path)
    midi = sub.add_parser("midi")
    midi.add_argument("project", type=Path)
    midi.add_argument("output", type=Path)
    midi.add_argument("--native", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        args.directory.mkdir(parents=True, exist_ok=True)
        target = args.directory / "project.json"
        if target.exists():
            parser.error("project.json exists; refusing to overwrite")
        save(target, load(Path(__file__).parents[1] / "assets/templates/project.json"))
        print(target)
        return
    project = load(args.project)
    report = validate(project, final=getattr(args, "final", False))
    if getattr(args, "report", None):
        save(args.report, report)
    if not report["ok"]:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    if args.command == "freeze":
        if not project["identity"].get("reviewed"):
            parser.error("Set reviewed only after source review, then freeze")
        project["identity"]["locked_digest"] = identity_digest(project)
        save(args.project, project)
        print(project["identity"]["locked_digest"])
    elif args.command == "midi":
        print(json.dumps(export_midi(project, args.output, args.native), indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
