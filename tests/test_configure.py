import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    source = Path(__file__).resolve().parents[1] / "scripts/configure.py"
    shutil.copy(source, tmp_path / "scripts/configure.py")
    return tmp_path


def configure(project, *arguments):
    return subprocess.run(
        [sys.executable, str(project / "scripts/configure.py"), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_generate_accounts_without_disclosing_passwords(project):
    result = configure(
        project, "--bind", "192.168.50.10", "--extensions", "1001", "1002", "1003"
    )
    assert result.returncode == 0, result.stderr
    config = (project / "config/pjsip.conf").read_text()
    credentials = (project / "credentials.txt").read_text()
    passwords = re.findall(r"^password = (\w+)$", config, re.MULTILINE)
    assert len(set(passwords)) == 3
    assert all(len(password) == 48 for password in passwords)
    assert all(password in credentials for password in passwords)
    assert all(password not in result.stdout + result.stderr for password in passwords)
    assert (project / "credentials.txt").stat().st_mode & 0o777 == 0o600
    dialplan = (project / "config/extensions.conf").read_text()
    for extension in ("1001", "1002", "1003"):
        assert f"Dial(PJSIP/{extension},30)" in dialplan
    assert "exten => 6000,1,Answer()" in dialplan


@pytest.mark.parametrize(
    "address", ["0.0.0.0", "127.0.0.1", "224.0.0.1", "8.8.8.8", "::1", "invalid"]
)
def test_reject_invalid_bind_without_writing_files(project, address):
    result = configure(project, "--bind", address)
    assert result.returncode != 0
    assert not list((project / "config").iterdir())
    assert not (project / "credentials.txt").exists()


@pytest.mark.parametrize(
    "extensions",
    [
        ("1001", "1001"),
        ("6000",),
        ("123",),
        ("abcd",),
        ("１２３４",),
        ("1001\npassword=x",),
    ],
)
def test_reject_invalid_extensions(project, extensions):
    result = configure(project, "--bind", "192.168.50.10", "--extensions", *extensions)
    assert result.returncode != 0
    assert not list((project / "config").iterdir())


@pytest.mark.parametrize(
    "filename", ["config/pjsip.conf", "config/extensions.conf", "credentials.txt"]
)
def test_never_overwrite_existing_deployment(project, filename):
    path = project / filename
    path.write_text("existing private configuration\n")
    result = configure(project, "--bind", "192.168.50.10")
    assert result.returncode != 0
    assert path.read_text() == "existing private configuration\n"
    assert "already exist" in result.stderr
