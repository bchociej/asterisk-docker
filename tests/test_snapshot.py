import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def snapshot_module():
    path = Path(__file__).resolve().parents[1] / "scripts/snapshot.py"
    spec = importlib.util.spec_from_file_location("snapshot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_detects_tampered_or_missing_inputs(snapshot_module, tmp_path):
    for directory in ("config", "inventory", "secrets", "scripts"):
        (tmp_path / directory).mkdir()
    secret = tmp_path / "secrets/phones.json"
    secret.write_text('{"synthetic-device": "synthetic-secret"}')
    manifest = {"version": 1, "files": snapshot_module.files(tmp_path)}
    (tmp_path / "release.json").write_text(json.dumps(manifest))
    assert snapshot_module.verify(tmp_path) == manifest
    secret.write_text("changed")
    with pytest.raises(ValueError, match="changed or is incomplete"):
        snapshot_module.verify(tmp_path)
    secret.unlink()
    with pytest.raises(ValueError):
        snapshot_module.verify(tmp_path)


def test_prepare_keeps_source_files_unchanged(snapshot_module, tmp_path, monkeypatch):
    import shutil
    import subprocess

    root = tmp_path / "workbench"
    root.mkdir()
    (root / "scripts").mkdir()
    (root / "config").mkdir()
    source = Path(__file__).resolve().parents[1] / "scripts/configure.py"
    shutil.copy(source, root / "scripts/configure.py")
    subprocess.run(
        ["python3", str(root / "scripts/configure.py"), "--bind", "192.168.50.10"],
        check=True,
        capture_output=True,
    )
    before = snapshot_module.files(root)
    monkeypatch.setattr(snapshot_module, "ROOT", root)

    def command(arguments, **kwargs):
        if arguments[:2] == ["git", "rev-parse"]:
            return "a" * 40
        if arguments[:2] == ["git", "status"]:
            return ""
        return json.dumps([{"Id": "sha256:" + "b" * 64, "RepoDigests": []}])

    monkeypatch.setattr(snapshot_module.subprocess, "check_output", command)
    release = tmp_path / "releases/one"
    snapshot_module.prepare(release, "synthetic-image")
    assert snapshot_module.files(root) == before
    manifest = snapshot_module.verify(release)
    assert manifest["image"] == "sha256:" + "b" * 64
    assert release.stat().st_mode & 0o777 == 0o700
    assert not (release / "credentials.txt").exists()
    with pytest.raises(ValueError, match="already exists"):
        snapshot_module.prepare(release, "synthetic-image")
