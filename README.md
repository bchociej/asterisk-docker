# Private Asterisk on Alpine

Asterisk **22.11.0 LTS** on **Alpine 3.24**, for calls between analog phones on
Grandstream ATAs across two privately routed LANs/WireGuard. One PBX serves both
sites. G.711 µ-law, UDP SIP, RTP 10000–10099, authenticated extensions only.

The image builds checksum-verified upstream source because Alpine stable's
packaged 22.9.0 does not include the later security fixes. The build uses Alpine's
musl compatibility patches; the runtime contains no compiler or downloaded
proprietary codec. Modules are explicitly selected at build and runtime. There
are no upstream sample configs, guest accounts, voicemail, trunks or web services.

## Build and test

Install the Python development dependencies below before running the image test.

```sh
docker build --pull -t local/asterisk:alpine-3.24 .
./scripts/test-image.sh
```

The test uses disposable credentials and an isolated container without publishing
ports. It checks non-root read-only startup, endpoints, authenticated SIP
registration, rejection of incorrect credentials, and a PCMU RTP echo call.
Real handset calls and cross-site audio still need testing on your network.

## Configure

Requires Python 3 on the host. Substitute an actual private IPv4 address **assigned
to the PBX host**, reachable from both sites. Do not use the example unchanged.

```sh
python3 scripts/configure.py --bind 192.168.10.20 --extensions 1001 1002 1003 1004
```

This creates `config/pjsip.conf`, `config/extensions.conf`, and `credentials.txt`.
They are ignored by Git; passwords/configuration are excluded from image builds.
The generator refuses to overwrite existing files. Protect the repository on the
host: PJSIP configuration must be readable by container UID 10001 and contains
passwords. The separate credential summary is mode 0600.

## Run (Linux)

Keep WireGuard on your router or host, outside this container. Both site LANs
must have distinct subnets, working return routes, and WireGuard AllowedIPs that
cover the required routes. With routed private addresses there is no STUN or
public external-media address to configure. Disable SIP ALG if traffic traverses
a router that applies it. Do not add NAT unless your topology requires it.

Before starting, allow UDP **5060** and **10000–10099** only from your ATAs/site
networks in the host/router firewall. SIP binds to the configured private IP;
RTP may bind other interfaces, so firewall restriction is still required.
No Internet port forwarding is needed. WireGuard encrypts the inter-site leg;
SIP/RTP on each local LAN remains unencrypted.

With the Docker Compose plugin installed:

```sh
docker compose up -d
docker compose logs -f
```

If the Compose plugin is unavailable, `./scripts/run.sh` provides the
same essential settings using plain Docker. Both deployment methods use host
networking, UID/GID 10001, a read-only root filesystem/config, no capabilities,
no-new-privileges, temporary runtime directories and persistent PBX data.
Use one deployment method at a time.

## Configure each HT801

- Primary SIP Server: the PBX private IP; transport UDP, port 5060.
- SIP User ID and Authenticate ID: that ATA's extension from `credentials.txt`.
- Authenticate Password: its generated password; SIP registration enabled.
- Preferred codec PCMU; DTMF via RTP/RFC2833; start with 20 ms packets.
- Routed LAN/VPN setup: NAT traversal/STUN off initially.

Dial another configured extension. Dial **6000** for a prompt-free echo test.
The internal dialplan contains only configured extensions and the echo test.
Asterisk anchors media (`direct_media=no`); both ATAs must reach its RTP range.

```sh
docker exec -it private-asterisk asterisk -rv
docker exec private-asterisk asterisk -rx 'pjsip show contacts'
docker exec private-asterisk asterisk -rx 'core reload'
```

For Compose use `docker compose exec asterisk ...` instead. Restart after changing
the transport bind address; reloading alone does not apply transport changes.
There are no sound files; install a reviewed sound package if adding prompts.

## Updates

Rebuild regularly with `--pull --no-cache` to refresh Alpine packages. Asterisk
is pinned: update the version, SHA-256 and image version label together when a
new supported release is selected, then rebuild and run the smoke test. Rebuilding
alone does not update the pinned Asterisk source. Keep previous images for
rollback. Back up configuration and the named data volume; `down -v` deletes data.

This image is deliberately source-built; its Asterisk updates are your
responsibility, rather than coming through `apk upgrade`. The Docker build log
records the source checksum check and the resolved Alpine base image digest.

## Keeping deployment details private

Generated SIP configuration and credentials, environment files, local Compose
overrides, TLS keys, recordings, packet captures, logs and runtime data are
ignored by Git. The Docker build context is an allowlist that excludes generated
SIP configuration and credentials. Keep site-specific files in the ignored paths;
tracked configuration files are public defaults. Never use `git add -f` to add
private deployment files. Before publishing changes, inspect `git diff --cached`
and `git status --ignored`. Gitignore does not remove previously committed data.

## Development checks

Use Python 3.12 or newer, pytest for Python tests, Ruff for Python lint/format,
and Bats plus ShellCheck for shell tests/lint. The shell scripts remain POSIX
`sh`; Bats tests use Bash. On Debian/Ubuntu, install the system tools with:

```sh
sudo apt-get install python3-venv bats shellcheck
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Run the same checks as CI:

```sh
ruff check .
ruff format --check .
python -m pytest -m 'not integration'
shellcheck scripts/*.sh tests/shell/*.bats
bats tests/shell
```

Use `ruff format .` to format Python and `ruff check --fix .` for safe lint fixes.
The Python tests cover credential generation, invalid inputs, and overwrite
protection. Bats covers launcher behavior, health-check failures, and smoke-test
cleanup using mocks, without starting Docker or contacting ATAs.

The SIP/RTP test uses pytest too. `./scripts/test-image.sh` starts a disposable
container from an already-built image and passes its address and credentials to
the integration test. A normal `pytest` run skips it unless both `--pbx-host` and
`--pbx-config` are supplied; use the wrapper to avoid targeting a real PBX.

GitHub Actions runs linting, formatting checks, and local tests on pushes and
pull requests. It does not build an image or run the Docker integration test.
