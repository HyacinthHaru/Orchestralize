#!/usr/bin/env python3
"""Observable portable-pipeline checks using original music, never the case-song notes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import numpy as np
import soundfile as sf
import mido

from project import duration, export_midi, identity_digest, load, portable_relative, save, seconds, validate
from render import render_dsp
from audio import mix, audio_metrics
from voicing import choose_voicing


def original_project(transpose=0, palette="electronic"):
    project = load(SKILL / "assets/templates/project.json")
    project.update(title="Original portable test study", seed=72)
    project["timing"] = {"tempo_map": [{"beat": 0, "bpm": 112}, {"beat": 8, "bpm": 90}, {"beat": 14, "bpm": 136}, {"beat": 19, "bpm": 104}],
                         "meter_map": [{"beat": 0, "numerator": 4, "denominator": 4}, {"beat": 8, "numerator": 3, "denominator": 4}, {"beat": 14, "numerator": 5, "denominator": 8}, {"beat": 19, "numerator": 4, "denominator": 4}],
                         "end_beat": 23, "offset_seconds": .1, "tail_seconds": 1}
    melody = [(0, 60, 1), (1, 64, .5), (1.5, 67, .5), (2, 62, 2),
              (4, 64, .75), (4.75, 67, .25), (5, 67, 1), (6, 71, .5), (6.5, 69, 1.5),
              (8, 69, 1), (9, 72, 1), (10, 76, 1), (11, 74, 1), (12, 71, 2),
              (14, 65, 1.5), (15.5, 64, 1), (16.5, 67, 1), (17.5, 62, 1.5),
              (19, 64, 1), (20, 62, 1), (21, 60, 2)]
    events = [{"id": f"s{i}", "pitch": pitch, "start": start, "duration": dur, "kind": "theme"} for i, (start, pitch, dur) in enumerate(melody)]
    chords = [(0, 4, "C", [0, 4, 7], 0), (4, 8, "Am7", [9, 0, 4, 7], 9),
              (8, 11, "Fmaj9", [5, 9, 0, 4, 7], 5), (11, 14, "G7/D", [7, 11, 2, 5], 2),
              (14, 16.5, "Dm7", [2, 5, 9, 0], 2), (16.5, 19, "G7", [7, 11, 2, 5], 7), (19, 23, "Cmaj9", [0, 4, 7, 11, 2], 0)]
    harmony = [{"id": f"h{i}", "start": start, "end": end, "concert_symbol": symbol, "source_label": symbol, "pcs": pcs, "bass_pc": bass}
               for i, (start, end, symbol, pcs, bass) in enumerate(chords)]
    project["identity"].update(reviewed=True, transpose_semitones=transpose, events=events, harmony=harmony,
                               form=[{"id": "theme", "start": 0, "end": 8, "label": "Theme"}, {"id": "response", "start": 8, "end": 19, "label": "Response"}, {"id": "close", "start": 19, "end": 23, "label": "Close"}])
    project["style"] = {"name": palette, "intent": "Test only: different electronic palettes, not acoustic sound-quality certification"}
    lead_patch = "dx_ep" if palette == "plucked" else "fm_lead"
    backing_patch = "analog_ensemble" if palette == "ensemble" else "warm_pad"
    def part(id, name, patch, role):
        return {"id": id, "name": name, "role": role, "instrument": {"backend": "dsp", "patch": patch, "range": [24, 108], "gm_program": 0, "polyphonic": True},
                "notes": [], "cc": [], "mix": {"gain_db": -5, "pan": 0}}
    lead = part("lead", "Theme", lead_patch, "melody")
    for event in events:
        lead["notes"].append({"id": f"n_{event['id']}", "source_id": event["id"], "source_primary": True,
                              "pitch": event["pitch"] + transpose, "start": event["start"], "duration": event["duration"], "velocity": 83,
                              "performance": {"gate_ratio": .93}})
    lead["cc"] = [{"beat": 0, "number": 11, "value": 90}, {"beat": 19, "number": 11, "value": 108}]
    project["parts"] = [lead]
    voices = [{"id": f"inner{i}", "low": low + transpose, "high": high + transpose, "target": target + transpose}
              for i, (low, high, target) in enumerate([(64, 77, 72), (55, 69, 64), (48, 62, 55)])]
    inner = {v["id"]: part(v["id"], v["id"], backing_patch, "harmony") for v in voices}
    bass = part("bass", "Bass", "sub_bass", "bass")
    previous = {}
    for chord in harmony:
        voiced = choose_voicing([(pc + transpose) % 12 for pc in chord["pcs"]], voices, previous, min_gap=2)
        previous = voiced
        for id, pitch in voiced.items():
            inner[id]["notes"].append({"id": f"{id}_{chord['id']}", "pitch": pitch, "start": chord["start"], "duration": chord["end"] - chord["start"], "velocity": 65,
                                       "harmony_id": chord["id"], "constraint": "chord_tone"})
        pcs = (chord["bass_pc"] + transpose) % 12
        pitch = min([n for n in range(30, 55) if n % 12 == pcs], key=lambda n: abs(n - 41))
        bass["notes"].append({"id": f"bass_{chord['id']}", "pitch": pitch, "start": chord["start"], "duration": chord["end"] - chord["start"], "velocity": 74,
                               "harmony_id": chord["id"], "constraint": "bass"})
    project["parts"].extend(inner.values())
    project["parts"].append(bass)
    project["mix"].update(effects=[{"id": "space", "type": "plate", "parameters": {"decay_seconds": .45, "predelay_ms": 12}, "return_db": -4}], master_gain_db=0)
    for index, p in enumerate(project["parts"]):
        p["mix"].update(pan=(index - 2) * .15, sends_db={"space": -14})
    return project


class MusicalContractTests(unittest.TestCase):
    def test_another_song_with_different_form(self):
        p = original_project()
        p["timing"].update(end_beat=7, tempo_map=[{"beat": 0, "bpm": 87}], meter_map=[{"beat": 0, "numerator": 7, "denominator": 8}])
        source = [{"id": f"modal{i}", "pitch": pitch, "start": start, "duration": dur, "kind": "theme"}
                  for i, (start, pitch, dur) in enumerate([(0, 62, .5), (.5, 65, 1), (1.5, 69, 2), (3.5, 67, .5), (4, 65, 1), (5, 62, 2)])]
        p["identity"].update(events=source, harmony=[], form=[{"id": "one", "start": 0, "end": 7, "label": "Asymmetric modal phrase"}])
        p["parts"] = [p["parts"][0]]
        p["parts"][0]["notes"] = [{"id": f"m_{e['id']}", "source_id": e["id"], "source_primary": True,
                                   "pitch": e["pitch"], "start": e["start"], "duration": e["duration"], "velocity": 75} for e in source]
        p["parts"][0]["cc"] = []
        self.assertTrue(validate(p, final=True)["ok"])
        audio = render_dsp(p["parts"][0], p, round(duration(p) * 48000))
        self.assertGreater(np.max(np.abs(audio)), .001)
        self.assertEqual(validate(p)["source_events"], 6)

    def test_portable_asset_paths(self):
        self.assertTrue(portable_relative("assets/library/patch.sfz"))
        for path in ("/machine/library.sfz", "C:\\library\\patch.sfz", "..\\patch.sfz", "../patch.sfz"):
            self.assertFalse(portable_relative(path))

    def test_variable_timing_and_meters(self):
        p = original_project()
        self.assertAlmostEqual(seconds(p, 14), .1 + 8 * 60 / 112 + 6 * 60 / 90)
        self.assertAlmostEqual(seconds(p, 19) - seconds(p, 14), 5 * 60 / 136)
        self.assertTrue(validate(p, final=True)["ok"])
        self.assertEqual(validate(p)["density"]["max_active_pitched_parts"], 5)

    def test_different_keys_and_palettes(self):
        for shift, palette in [(0, "electronic"), (2, "ensemble"), (-3, "plucked")]:
            p = original_project(shift, palette)
            self.assertTrue(validate(p, final=True)["ok"], validate(p)["errors"])
            frames = round(duration(p) * 48000)
            audio = render_dsp(p["parts"][0], p, frames)
            self.assertEqual(audio.shape, (frames, 2))
            self.assertGreater(float(np.max(np.abs(audio))), .001)
            self.assertTrue(np.isfinite(audio).all())

    def test_identity_damage_and_repeated_attacks(self):
        p = original_project()
        p["identity"]["locked_digest"] = identity_digest(p)
        for field, value in [("pitch", 61), ("start", .125), ("duration", .75)]:
            changed = deepcopy(p)
            changed["parts"][0]["notes"][0][field] = value
            self.assertFalse(validate(changed)["ok"])
        changed = deepcopy(p)
        changed["parts"][0]["notes"].pop(6)  # Same pitch as previous attack, still independently required.
        self.assertFalse(validate(changed)["ok"])
        changed = deepcopy(p)
        changed["timing"]["tempo_map"][0]["bpm"] = 120
        self.assertFalse(validate(changed)["ok"])
        p["identity"]["events"][0]["pitch"] += 1
        self.assertFalse(validate(p)["ok"])

    def test_range_monophony_and_slash_bass(self):
        p = original_project()
        p["parts"][1]["instrument"]["range"] = [0, 20]
        self.assertFalse(validate(p)["ok"])
        p = original_project()
        p["parts"][1]["instrument"]["polyphonic"] = False
        note = deepcopy(p["parts"][1]["notes"][0])
        note["id"] = "overlap"
        p["parts"][1]["notes"].append(note)
        self.assertFalse(validate(p)["ok"])
        p = original_project()
        p["identity"]["harmony"][3]["bass_pc"] = 4  # Slash bass outside original G7 pcs remains valid.
        p["parts"][-1]["notes"][3]["pitch"] = 40
        self.assertTrue(validate(p)["ok"])

    def test_octave_doubling_and_determinism(self):
        p = original_project()
        double = deepcopy(p["parts"][0])
        double["id"] = "double"
        for note in double["notes"]:
            note.update(id=note["id"] + "_double", source_primary=False, octave_shift=12, pitch=note["pitch"] + 12)
        p["parts"].append(double)
        self.assertTrue(validate(p)["ok"])
        frames = round(duration(p) * 48000)
        first = render_dsp(p["parts"][0], p, frames)
        second = render_dsp(p["parts"][0], p, frames)
        self.assertTrue(np.array_equal(first, second))
        p["seed"] += 1
        self.assertFalse(np.array_equal(first, render_dsp(p["parts"][0], p, frames)))

    def test_multiport_midi_with_tempo_and_cc(self):
        p = original_project()
        p["parts"][0]["cc"].append({"beat": 0, "number": 1, "value": 90})
        for i in range(35):
            part = deepcopy(p["parts"][1])
            part["id"] = f"extra{i}"
            p["parts"].append(part)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arrangement.mid"
            report = export_midi(p, path)
            addresses = [(a["port"], a["channel_zero_based"]) for a in report["addresses"]]
            self.assertEqual(len(addresses), len(set(addresses)))
            midi = mido.MidiFile(path)
            self.assertEqual(len([e for e in midi.tracks[0] if e.type == "set_tempo"]), 4)
            self.assertEqual(len([e for e in midi.tracks[0] if e.type == "time_signature"]), 4)
            self.assertEqual(sum(e.type == "note_on" for e in midi.tracks[1]), len(p["parts"][0]["notes"]))
            self.assertFalse(any(e.type == "control_change" and e.control == 1 and e.value != 0 for t in midi.tracks for e in t))


class PipelineTests(unittest.TestCase):
    def test_cli_full_render_mix_and_moved_asset_lock(self):
        with tempfile.TemporaryDirectory(prefix="orchestralize-test-") as directory:
            root = Path(directory)
            p = original_project(2, "ensemble")
            save(root / "project.json", p)
            def run(script, *args, success=True):
                result = subprocess.run([sys.executable, str(SKILL / "scripts" / script), *map(str, args)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                return result
            run("project.py", "freeze", root / "project.json")
            run("project.py", "validate", root / "project.json", "--final")
            run("render.py", root / "project.json", root / "raw")
            run("audio.py", "mix", root / "project.json", root / "raw", root / "audio")
            report = load(root / "audio/mix_report.json")
            self.assertLess(report["reconstruction_max_abs_error"], 1e-7)
            self.assertLessEqual(report["master"]["true_peak_4x_estimate_dbfs"], -1 + .001)
            self.assertFalse(report["master"]["silent"])
            assets = root / "assets/include/nested"
            assets.mkdir(parents=True)
            (assets / "sample.bin").write_bytes(b"test-sample")
            run("lock.py", "snapshot", root / "lock.json", "--root", f"asset={root / 'assets'}", "--root", f"song={root / 'project.json'}")
            moved = root / "moved"
            shutil.copytree(root / "assets", moved)
            run("lock.py", "verify", root / "lock.json", "--root", f"asset={moved}", "--root", f"song={root / 'project.json'}")
            (moved / "include/nested/sample.bin").write_bytes(b"changed-sample")
            run("lock.py", "verify", root / "lock.json", "--root", f"asset={moved}", "--root", f"song={root / 'project.json'}", success=False)
            self.assertNotIn(str(root), (root / "lock.json").read_text())

    @unittest.skipUnless(os.environ.get("ORCHESTRALIZE_TEST_SFIZZ"), "Optional native sfizz adapter not supplied")
    def test_native_sfz_real_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            t = np.arange(48000) / 48000
            sf.write(root / "probe.wav", np.sin(2 * np.pi * 261.625565 * t).astype(np.float32) * .15, 48000, subtype="FLOAT")
            (root / "probe.sfz").write_text("<region> sample=probe.wav key=60 ampeg_release=0.04\n")
            p = original_project()
            note = {"id": "probe", "pitch": 60, "start": 0, "duration": 1, "velocity": 90}
            p["identity"]["events"] = []
            p["parts"] = [{"id": "probe", "name": "Native probe", "instrument": {"backend": "sfz", "sfz": "probe.sfz", "range": [60, 60]}, "notes": [note]}]
            save(root / "project.json", p)
            result = subprocess.run([sys.executable, str(SKILL / "scripts/render.py"), str(root / "project.json"), str(root / "raw"), "--sfizz-renderer", os.environ["ORCHESTRALIZE_TEST_SFIZZ"]], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            audio, rate = sf.read(root / "raw/probe.wav", always_2d=True)
            self.assertEqual(audio.shape, (round(duration(p) * 48000), 2))
            self.assertGreater(np.max(np.abs(audio)), .001)
            self.assertEqual(rate, 48000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
