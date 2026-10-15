#!/usr/bin/env python3
"""Content-lock complete named dependency trees without storing machine paths."""
import argparse
import fnmatch
import hashlib
import importlib.metadata
import platform
from pathlib import Path
import sys

from project import load, save


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inventory(roots, exclusions, output):
    result = {}
    for name, root in roots.items():
        if not root.exists():
            raise ValueError(f"Missing dependency root: {name}")
        entries = [root] if root.is_file() else sorted(root.rglob("*"))
        files = {}
        for entry in entries:
            if not entry.is_file() or entry.resolve() == output.resolve():
                continue
            key = entry.name if root.is_file() else entry.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(key, pattern) for pattern in exclusions):
                continue
            files[key] = {"bytes": entry.stat().st_size, "sha256": sha256(entry)}
        result[name] = files
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["snapshot", "verify", "doctor"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--root", action="append", default=[], help="Logical-name=local-directory-or-file; mappings are not stored")
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()
    if args.command == "doctor":
        names = ("numpy", "scipy", "soundfile", "mido", "music21", "verovio", "torch", "torchcrepe", "librosa")
        packages = {}
        for name in names:
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = None
        save(args.output, {"python": sys.version, "platform": platform.system(), "architecture": platform.machine(), "packages": packages})
        return
    roots = {}
    for mapping in args.root:
        name, value = mapping.split("=", 1)
        if name in roots:
            parser.error("Duplicate logical root")
        roots[name] = Path(value)
    if not roots:
        parser.error("Supply at least one --root")
    exclusions = args.exclude
    if args.command == "verify":
        expected = load(args.output)
        if set(expected["roots"]) != set(roots):
            parser.error("Supply exactly the named roots recorded in the lock")
        exclusions = expected["exclusions"]
    files = inventory(roots, exclusions, args.output)
    if args.command == "snapshot":
        save(args.output, {"schema_version": 1, "algorithm": "sha256", "exclusions": exclusions, "roots": files})
        print(sum(len(items) for items in files.values()), "files locked")
    else:
        differences = []
        for root, items in expected["roots"].items():
            current = files[root]
            for name in sorted(set(items) | set(current)):
                if items.get(name) != current.get(name):
                    differences.append(f"{root}/{name}")
        if differences:
            print("Dependency changes:\n" + "\n".join(differences))
            raise SystemExit(1)
        print("All dependency files match")


if __name__ == "__main__":
    main()
