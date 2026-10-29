#!/usr/bin/env python3
"""Prepare and verify private, immutable PBX release snapshots. Never deploys."""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {
        p.relative_to(root).as_posix(): sha256(p)
        for directory in ("config", "inventory", "secrets", "scripts")
        for p in sorted((root / directory).rglob("*"))
        if p.is_file() and p.name != ".lock"
    }


def verify(root):
    manifest = json.loads((root / "release.json").read_text())
    if manifest["version"] != 1 or files(root) != manifest["files"]:
        raise ValueError("Snapshot changed or is incomplete; prepare a new release")
    return manifest


def prepare(output, image, allow_dirty=False):
    if output.resolve() == ROOT or any(
        output.resolve().is_relative_to(ROOT / directory)
        for directory in ("config", "inventory", "secrets", "scripts")
    ):
        raise ValueError("Snapshot destination overlaps source inputs")
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    )
    if dirty and not allow_dirty:
        raise ValueError(
            "Commit the intended tooling/config defaults first (use --allow-dirty only for development tests)"
        )
    record = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image], text=True)
    )[0]
    output = output.resolve()
    if (
        output == ROOT
        or output.is_relative_to(ROOT / "config")
        or output.is_relative_to(ROOT / "inventory")
        or output.is_relative_to(ROOT / "secrets")
    ):
        raise ValueError(
            "Release destination must be outside live configuration and source stores"
        )
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT / "inventory/.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if output.exists():
            raise ValueError(
                "Release destination already exists; snapshots are immutable"
            )
        temporary = Path(tempfile.mkdtemp(prefix=".release-", dir=output.parent))
        try:
            for directory in ("config", "inventory", "secrets"):
                shutil.copytree(
                    ROOT / directory,
                    temporary / directory,
                    ignore=shutil.ignore_patterns(".lock", "__pycache__"),
                )
            # Never carry live symlinks into a supposedly immutable snapshot.
            (temporary / "scripts").mkdir()
            shutil.copy2(
                ROOT / "scripts/configure.py", temporary / "scripts/configure.py"
            )
            subprocess.run(
                [sys.executable, str(temporary / "scripts/configure.py"), "render"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            (temporary / "credentials.txt").unlink()
            manifest = {
                "version": 1,
                "image": record["Id"],
                "repo_digests": record.get("RepoDigests", []),
                "source_revision": source,
                "source_dirty": dirty,
                "files": files(temporary),
            }
            path = temporary / "release.json"
            path.write_text(json.dumps(manifest, indent=2) + "\n")
            path.chmod(0o600)
            os.rename(temporary, output)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    print(
        "Prepared private snapshot; validate it with the selected image before activation."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("output", type=Path)
    create.add_argument("--image", required=True)
    create.add_argument("--allow-dirty", action="store_true")
    check = commands.add_parser("verify")
    check.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.output, args.image, args.allow_dirty)
        else:
            verify(args.snapshot)
            print("Snapshot fingerprints verified.")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Do not include private input values, filenames within a release, or
        # renderer diagnostics in terminal/CI output.
        parser.exit(
            1,
            "Snapshot operation failed; check inputs, immutable destination, source cleanliness and local image availability.\n",
        )


if __name__ == "__main__":
    main()
