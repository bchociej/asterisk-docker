# Private Asterisk on Alpine

Asterisk **22.11.0 LTS** on **Alpine 3.24**, for calls between analog phones on
Grandstream ATAs on private networks, including routed VPN deployments. G.711 µ-law, UDP SIP, RTP 10000–10099, authenticated extensions only.

The image builds checksum-verified upstream source because Alpine stable's
packaged 22.9.0 does not include the later security fixes. The build uses Alpine's
musl compatibility patches; the runtime contains no compiler or downloaded
proprietary codec. Modules are explicitly selected at build and runtime. There
are no upstream sample configs, guest accounts, voicemail, trunks or web services.

## Build and test

Install the Python development dependencies below before running the image test.

```sh
docker build --pull --platform linux/amd64 -f container/Dockerfile -t local/asterisk:alpine-3.24 .
uv run --locked scripts/test-image.sh
```

The test uses disposable credentials and an isolated container without publishing
ports. It checks non-root read-only startup, endpoints, authenticated SIP
registration, rejection of incorrect credentials, and a PCMU RTP echo call.
Real handset calls and cross-site audio still need testing on your network.

## Configure and manage phones

Requires Python 3.12 or newer on the host. Use a private IPv4 address assigned
**to the PBX host**, reachable from both sites; replace the example address.

```sh
python3 scripts/configure.py init --bind 192.168.10.20
python3 scripts/configure.py add kitchen --extension 1001 --name Kitchen
python3 scripts/configure.py add office --extension 1002 --name Office
python3 scripts/configure.py render
```

The sources of truth are two private, Git-ignored files:

- `inventory/devices.json`: bind address, stable device IDs, display names,
  extension mappings, enabled state, and SIP usernames. No passwords.
- `secrets/phones.json`: device ID to SIP password. New passwords are generated
  only for new devices or an explicit `rotate-password` command.

Both files are mode 0600 in mode 0700 directories. Back up **both** together in
private storage. If secrets are missing or corrupt, commands fail instead of
inventing replacement passwords. Commands lock the inventory to prevent concurrent
updates from losing changes. Writes use atomic file replacement.

`render` combines these stores into `config/pjsip.conf`,
`config/extensions.conf`, and a private `credentials.txt` provisioning summary.
It can be repeated without changing passwords. These outputs are generated;
edit the inventory through the CLI (or JSON) instead of editing outputs, because
rendering replaces them. Runtime config is mode 0644 so container UID 10001 can
read it: restrict access to the repository on the host. No source stores or
credentials are included in the image or tracked by Git.

```sh
python3 scripts/configure.py list
python3 scripts/configure.py update kitchen --extension 2001 --name Upstairs
python3 scripts/configure.py add den --extension 1003
python3 scripts/configure.py update office --no-enabled
python3 scripts/configure.py update office --enabled
python3 scripts/configure.py bind 192.168.10.21
python3 scripts/configure.py render
```

Device `kitchen` has SIP username `phone-kitchen`. Its username/password stay
unchanged when its extension, display name, enabled state, or PBX address changes.
Each device has one unique four-digit extension; 6000 is reserved for echo testing.
Disabled devices retain their extension reservation and password but are omitted
from generated accounts and dialplan. Disabling is applied on PBX reload; it does
not terminate an already active call.

Edits change the source stores only: batch edits, then render and apply them:

```sh
docker exec private-asterisk asterisk -rx 'module reload res_pjsip.so'
docker exec private-asterisk asterisk -rx 'dialplan reload'
```

Restart the container after changing its SIP bind address. The tool does not
contact Docker, automatically reload Asterisk, or provision any ATA.

To intentionally change one device's password:

```sh
python3 scripts/configure.py rotate-password kitchen
python3 scripts/configure.py render
```

Apply the reload and update that ATA from `credentials.txt`. Other devices keep
their passwords. Output on the terminal never prints passwords.

### Adopting configuration from the old generator

For untouched numeric accounts created by the previous tool, first back up the
existing private files, then run:

```sh
python3 scripts/configure.py import-legacy
```

This creates inventory/secrets while preserving SIP usernames and passwords and
leaves runtime files unchanged. Existing device IDs are their old numeric SIP
usernames, so `update 1001 --extension 2001` changes the extension while keeping SIP
username `1001`. Run `render` and reload when ready. Import refuses to overwrite
existing source stores. Custom hand-written configurations require manual migration.
The original `--bind ... --extensions ...` bootstrap syntax remains available for
compatibility; it still refuses to overwrite deployment files.

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
docker compose -p private-asterisk -f deploy/compose/compose.yaml up -d
docker compose -p private-asterisk -f deploy/compose/compose.yaml logs -f
```

If the Compose plugin is unavailable, `./scripts/run.sh` provides the
same essential settings using plain Docker. Both deployment methods use host
networking, UID/GID 10001, a read-only root filesystem/config, no capabilities,
no-new-privileges, temporary runtime directories and persistent PBX data.
Use one deployment method at a time.

## Configure each HT801

- Primary SIP Server: the PBX private IP; transport UDP, port 5060.
- SIP User ID and Authenticate ID: that device's SIP username from `credentials.txt`
  (for example `phone-kitchen`), which is independent of its dialed extension.
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

For Compose use `docker compose -p private-asterisk -f deploy/compose/compose.yaml exec asterisk ...` instead. Restart after changing
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
sudo apt-get install bats shellcheck
# Install uv using its official installation instructions.
uv sync --locked --python 3.12
```

Run the same checks as CI:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m pytest -m 'not integration'
shellcheck scripts/*.sh tests/shell/*.bats
bats tests/shell
```

Use `uv run --locked ruff format .` to format Python and
`uv run --locked ruff check --fix .` for safe lint fixes. Development dependencies
are locked in `uv.lock`; update them deliberately with uv and commit the lockfile.
The host-side runtime helpers still need only Python's standard library.
The Python tests cover account lifecycle, stable credentials and SIP identities,
legacy migration, missing secrets, invalid inputs, and overwrite protection. Bats covers launcher behavior, health-check failures, and smoke-test
cleanup using mocks, without starting Docker or contacting ATAs. Snapshot tests
check integrity, immutability and that source inputs are left unchanged.

The SIP/RTP test uses pytest too. `uv run --locked scripts/test-image.sh` starts a disposable
container from an already-built image and passes its address and credentials to
the integration test. A normal `pytest` run skips it unless both `--pbx-host` and
`--pbx-config` are supplied; use the wrapper to avoid targeting a real PBX.

GitHub Actions runs linting, formatting checks, and local tests on pushes and
pull requests. It does not build an image or run the Docker integration test.

## Production deployment and recovery

The quick-start commands above are for development. For coherent immutable input
snapshots, pinned image selection, offline preflight, activation, verification,
backups and paired rollback, follow [deployment instructions](docs/deployment.md).
No production deployment, Kubernetes support or image publication is implied.
Install uv using the [official instructions](https://docs.astral.sh/uv/getting-started/installation/).

## Applied standards

Standards source: [bchociej/dev-standards](https://github.com/bchociej/dev-standards).

| Standard | Version spec | Resolved version | Source ref and path | Status |
| --- | --- | --- | --- | --- |
| BAS-001 | ^5.0.0 | 5.0.0 | [`894bf01:bas-001-repository-and-development-fundamentals.md`](https://github.com/bchociej/dev-standards/blob/894bf013623224066a3a99ed1d9f14c2b1bd7c67/bas-001-repository-and-development-fundamentals.md) | Adopted; see notes |
| BAS-002 | ^3.0.0 | 3.0.0 | [`894bf01:bas-002-recording-standards-adoption.md`](https://github.com/bchociej/dev-standards/blob/894bf013623224066a3a99ed1d9f14c2b1bd7c67/bas-002-recording-standards-adoption.md) | Adopted; see notes |
| CAS-001 | ^4.0.0 | 4.0.0 | [`894bf01:cas-001-container-application-repositories.md`](https://github.com/bchociej/dev-standards/blob/894bf013623224066a3a99ed1d9f14c2b1bd7c67/cas-001-container-application-repositories.md) | Adopted; see notes |

See [adoption notes](docs/standards.md) for the assessment, documented departures,
verification and limitations. Matching future versions are candidates for review,
not permission for automatic upgrades.
