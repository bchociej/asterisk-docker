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
        ("6001",),
        ("6002",),
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


def read_state(project):
    import json

    return (
        json.loads((project / "inventory/devices.json").read_text()),
        json.loads((project / "secrets/phones.json").read_text()),
    )


def succeed(project, *arguments):
    result = configure(project, *arguments)
    assert result.returncode == 0, result.stderr
    return result


def test_phone_lifecycle_preserves_existing_passwords(project):
    succeed(project, "init", "--bind", "192.168.50.10")
    succeed(project, "add", "kitchen", "--extension", "1001", "--name", "Kitchen")
    original_inventory, original = read_state(project)
    succeed(project, "add", "office", "--extension", "1002")
    succeed(project, "update", "kitchen", "--extension", "2001", "--name", "Upstairs")
    succeed(project, "render")
    inventory, passwords = read_state(project)
    assert passwords["kitchen"] == original["kitchen"]
    assert (
        inventory["devices"]["kitchen"]["sip_username"]
        == original_inventory["devices"]["kitchen"]["sip_username"]
    )
    config = (project / "config/pjsip.conf").read_text()
    dialplan = (project / "config/extensions.conf").read_text()
    assert "username = phone-kitchen" in config
    assert "callerid = Upstairs <2001>" in config
    assert "exten => 2001,1,Dial(PJSIP/phone-kitchen,30)" in dialplan
    assert "exten => 1001," not in dialplan
    before = {p.name: p.read_bytes() for p in (project / "config").iterdir()}
    succeed(project, "render")
    assert before == {p.name: p.read_bytes() for p in (project / "config").iterdir()}
    assert passwords == read_state(project)[1]
    output = succeed(project, "list").stdout
    assert all(password not in output for password in passwords.values())
    assert all(
        password not in (project / "inventory/devices.json").read_text()
        for password in passwords.values()
    )
    for path in ("inventory/devices.json", "secrets/phones.json", "credentials.txt"):
        assert (project / path).stat().st_mode & 0o777 == 0o600
    for path in ("inventory", "secrets"):
        assert (project / path).stat().st_mode & 0o777 == 0o700


def test_disable_reenable_and_explicit_rotation(project):
    succeed(project, "init", "--bind", "192.168.50.10")
    for device, extension in (("kitchen", "1001"), ("office", "1002")):
        succeed(project, "add", device, "--extension", extension)
    original = read_state(project)[1]
    succeed(project, "update", "kitchen", "--no-enabled")
    succeed(project, "render")
    assert "phone-kitchen" not in (project / "config/pjsip.conf").read_text()
    assert "exten => 1001," not in (project / "config/extensions.conf").read_text()
    assert read_state(project)[1] == original
    succeed(project, "update", "kitchen", "--enabled")
    succeed(project, "rotate-password", "office")
    passwords = read_state(project)[1]
    assert passwords["kitchen"] == original["kitchen"]
    assert passwords["office"] != original["office"]
    succeed(project, "bind", "192.168.50.11")
    succeed(project, "render")
    assert "bind = 192.168.50.11:5060" in (project / "config/pjsip.conf").read_text()
    assert read_state(project)[1] == passwords


@pytest.mark.parametrize(
    "command",
    [
        ("add", "kitchen", "--extension", "1003"),
        ("add", "office", "--extension", "1001"),
        ("update", "absent", "--extension", "1002"),
        ("add", "../escape", "--extension", "1002"),
        ("update", "kitchen", "--name", "bad\npassword=injected"),
        ("update", "kitchen", "--extension", "6000"),
    ],
)
def test_invalid_inventory_edits_are_non_destructive(project, command):
    succeed(project, "init", "--bind", "192.168.50.10")
    succeed(project, "add", "kitchen", "--extension", "1001")
    before = read_state(project)
    assert configure(project, *command).returncode != 0
    assert read_state(project) == before


@pytest.mark.parametrize(
    "damage", ["missing-store", "missing-password", "invalid-json"]
)
def test_render_never_recreates_missing_or_corrupt_secrets(project, damage):
    import json

    succeed(project, "init", "--bind", "192.168.50.10")
    succeed(project, "add", "kitchen", "--extension", "1001")
    succeed(project, "render")
    previous = (project / "config/pjsip.conf").read_bytes()
    store = project / "secrets/phones.json"
    if damage == "missing-store":
        store.unlink()
    elif damage == "missing-password":
        store.write_text(json.dumps({}))
    else:
        store.write_text('{"kitchen": "do-not-print-this-secret"')
    result = configure(project, "render")
    assert result.returncode != 0
    assert "do-not-print-this-secret" not in result.stdout + result.stderr
    assert (project / "config/pjsip.conf").read_bytes() == previous
    assert not store.exists() if damage == "missing-store" else store.read_text() != ""


def test_import_legacy_preserves_passwords_and_numeric_sip_identity(project):
    succeed(project, "--bind", "192.168.50.10", "--extensions", "1001", "1002")
    old_config = (project / "config/pjsip.conf").read_bytes()
    old_passwords = read_state(project)[1]
    # Simulate files left by the previous generator, which had no source stores.
    (project / "inventory/devices.json").unlink()
    (project / "secrets/phones.json").unlink()
    succeed(project, "import-legacy")
    assert read_state(project)[1] == old_passwords
    assert (project / "config/pjsip.conf").read_bytes() == old_config
    succeed(project, "update", "1001", "--extension", "2001")
    succeed(project, "render")
    assert "username = 1001" in (project / "config/pjsip.conf").read_text()
    assert (
        "exten => 2001,1,Dial(PJSIP/1001,30)"
        in (project / "config/extensions.conf").read_text()
    )
    assert read_state(project)[1] == old_passwords
    assert configure(project, "import-legacy").returncode != 0


def test_concurrent_adds_do_not_drop_devices_or_passwords(project):
    succeed(project, "init", "--bind", "192.168.50.10")
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(project / "scripts/configure.py"),
                "add",
                device,
                "--extension",
                extension,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for device, extension in (("kitchen", "1001"), ("office", "1002"))
    ]
    for process in processes:
        _, error = process.communicate(timeout=10)
        assert process.returncode == 0, error
    inventory, passwords = read_state(project)
    assert set(inventory["devices"]) == set(passwords) == {"kitchen", "office"}


def test_codec_change_preserves_credentials(project):
    assert configure(project, "init", "--bind", "192.168.50.10").returncode == 0
    assert configure(project, "add", "studio", "--extension", "1001").returncode == 0
    before = (project / "secrets/phones.json").read_bytes()
    assert configure(project, "update", "studio", "--codec", "g722").returncode == 0
    assert configure(project, "render").returncode == 0
    config = (project / "config/pjsip.conf").read_text()
    assert "[phone-studio](phone)\ndisallow = all\nallow = g722\n" in config
    assert (project / "secrets/phones.json").read_bytes() == before
    assert configure(project, "update", "studio", "--codec", "invalid").returncode != 0
