from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--pbx-host", help="Disposable Asterisk test endpoint IPv4 address"
    )
    parser.addoption(
        "--pbx-config", help="Generated PJSIP config for that test endpoint"
    )


@pytest.fixture
def pbx(request):
    host = request.config.getoption("--pbx-host")
    config = request.config.getoption("--pbx-config")
    if not host and not config:
        pytest.skip("Run scripts/test-image.sh to test a disposable Asterisk instance")
    if not host or not config:
        pytest.fail("Supply both --pbx-host and --pbx-config")
    path = Path(config)
    if not path.is_file():
        pytest.fail("The supplied PJSIP configuration does not exist")
    return host, path
