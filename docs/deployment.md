# Deployment and recovery

Supported targets: Linux amd64, one Asterisk instance, using Docker Compose or
the plain-Docker launcher. Kubernetes is not supplied. All example addresses and
device names are synthetic. Run commands from the repository root. Keep actual
site inputs, release selections, backups and logs outside SCM.

## Runtime contract

- SIP UDP 5060 binds the configured private IPv4 address. RTP uses UDP
  10000–10099; restrict both in the host firewall. Host networking is intentional.
- There is no SIP TLS listener or HTTP management listener in this configuration.
  WireGuard, if used, is terminated by the host/router; LAN SIP/RTP is unencrypted.
  ATA HTTPS provisioning/trust is a separate service and is not configured here.
- `/etc/asterisk` is a read-only native configuration mount. Writable persistent
  state is `/var/lib/asterisk` in `private-asterisk-data`. `/run/asterisk`,
  `/var/spool/asterisk`, `/var/log/asterisk` and `/tmp` use temporary filesystems.
  Voicemail and recordings are not enabled; enable durable storage before adding
  features that require spool/log retention. Console logs are size-limited.
- The foreground Asterisk process runs as UID/GID 10001, receives shutdown signals,
  and has no Linux capabilities. Serving startup needs no Internet access.
- Compose has a stable project name `private-asterisk`, one instance and a fixed
  container name. Do not scale it or run the plain launcher concurrently.
  Restart/recreate interrupts registration and calls briefly; it is not seamless.
- A healthy container confirms the CLI, private SIP transport and PJSIP channel
  are running. Registration and an echo call are the representative operation.

Install Docker Engine and the Compose v2 plugin for Compose deployments. Install
uv and run `uv sync --locked --python 3.12` for host-side validation. If Docker
requires a different login group, use a shell with that group activated.

## Build and select an image

```sh
docker build --platform linux/amd64 -f container/Dockerfile -t local/asterisk:alpine-3.24 .
uv run --locked scripts/test-image.sh local/asterisk:alpine-3.24
```

Image builds remain local; CI does not build, publish or deploy. No third-party
Asterisk image is trusted implicitly. This source build follows the earlier
repository/image assessment: the distribution package lagged security fixes,
while the general-purpose third-party image carried unnecessary sample services
and codecs. The official Alpine base and checksum-pinned upstream Asterisk supply
a small environment-neutral runtime. Version updates need deliberate review.

## Prepare a coherent candidate before stopping the active instance

The inventory tool is a workbench, not the live release directory. Batch device
edits there, then commit the intended public tooling/default configuration. Keep
private inventory and secrets uncommitted. Do not edit inventory/secrets manually
while preparing a snapshot; CLI edits share an exclusive lock with preparation.

```sh
umask 077
mkdir -p releases backups
chmod 700 releases backups
uv run --locked python scripts/snapshot.py prepare releases/candidate-001 \
  --image local/asterisk:alpine-3.24
uv run --locked python scripts/snapshot.py verify releases/candidate-001
IMAGE=$(python3 -c 'import json; print(json.load(open("releases/candidate-001/release.json"))["image"])')
uv run --locked scripts/test-image.sh "$IMAGE" releases/candidate-001
```

Preparation locks and copies inventory/secrets, native config and the renderer,
then renders only in temporary output. It never changes active inputs or contacts
ATAs. It records the local immutable image ID, any registry manifest digests, source
revision, and SHA-256 fingerprints of all release inputs. It refuses dirty public
source unless `--allow-dirty` is explicitly used for development verification.
Snapshots cannot overwrite existing destinations. Their enclosing directory is
0700; secret stores are 0600. Do not publish snapshots or validation diagnostics.

Validation verifies fingerprints and deterministic rendering, uses the exact
selected image, then boots it with the intended configuration in a disconnected
network namespace. A short-lived official Alpine helper assigns the intended
bind address only inside that namespace (NET_ADMIN there, never host networking).
A capability-free Python test client shares that namespace and verifies actual
SIP registration, rejection of incorrect credentials, and RTP echo. No production
contacts, active containers or durable data are touched. Keep `alpine:3.24` and
`python:3.12-slim` available locally; validation may pull these test-only helpers.
A preparation/validation failure must leave the active deployment unchanged.

Offline validation cannot establish actual LAN/VPN routing, firewall rules, ATA
firmware behavior, or call quality. Check these after activation. An empty/all-disabled
inventory intentionally fails the representative-call check.

### Record a private selection

Create an environment file containing the immutable image ID, snapshot path and
manifest fingerprint. The path is absolute, so Compose's base directory cannot
silently select another config folder. Do not edit a published snapshot; prepare
another candidate instead.

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
release = Path('releases/candidate-001').resolve()
manifest = release / 'release.json'
record = json.loads(manifest.read_text())
values = {
    'ASTERISK_IMAGE': record['image'],
    'ASTERISK_CONFIG_DIR': str(release / 'config'),
    'ASTERISK_RELEASE_ID': hashlib.sha256(manifest.read_bytes()).hexdigest(),
    'ASTERISK_DATA_VOLUME': 'private-asterisk-data',
}
selection = Path('releases/candidate.env')
selection.write_text(''.join(f'{key}={json.dumps(value)}\n' for key, value in values.items()))
selection.chmod(0o600)
PY
```

For local builds `sha256:...` is Docker's content-addressed image/config ID, not
an invented registry manifest digest. Keep the local image or save it privately
with `docker image save`. If using a registry later, select a real `repo@sha256:...`
reference and retain its resolved manifest digest as well. Mutable tags alone are
not production release identities.

## Activate and verify (Compose)

Before an update, preserve `releases/active.env` as `releases/previous.env` if it
exists. Keep that previous snapshot, renderer, image, and data backup. For updates
where data compatibility matters, stop the active service and take a consistent
data backup as described below after candidate validation and before activation.

```sh
if [ -f releases/active.env ]; then cp -p releases/active.env releases/previous.env; fi
cp -p releases/candidate.env releases/active.env
docker compose --env-file releases/active.env -p private-asterisk \
  -f deploy/compose/compose.yaml up -d --no-build --force-recreate --wait --wait-timeout 60
docker compose --env-file releases/active.env -p private-asterisk \
  -f deploy/compose/compose.yaml ps
docker inspect -f '{{.State.Health.Status}} {{.Image}} {{index .Config.Labels "io.bchociej.asterisk.release"}}' private-asterisk
```

Compare the image ID and release label with the selected manifest and its hash.
Then confirm an intended ATA registers, call another extension, and call 6000
for echo. Do not publish contacts or unredacted logs. If activation/readiness or
representative calls fail, stop further changes and roll back the paired selection.
Do not overwrite the previous snapshot or just restart the failed candidate.
The Compose file's explicit paths and project name are required on every call.
Never use `down -v` as an update: it deletes durable data.

Before migrating an older installation, inspect its actual volume name and back
it up. Earlier Compose defaults may have created a project-prefixed volume;
select that name with `ASTERISK_DATA_VOLUME` or restore to a new one. Do not
silently start with an empty volume or run both launcher methods at once.

## Configuration reloads

The normal release path is immutable snapshot + recreate above. Recreating
activates image and native config together and also handles transport changes.
The existing developer workbench can instead use native reload, but must first
prepare and validate a snapshot of the intended edited inputs as above. Retain
the previous native files and secrets before replacing the mounted workbench
outputs, then render and activate:

```sh
python3 scripts/configure.py render
docker exec private-asterisk asterisk -rx 'module reload res_pjsip.so'
docker exec private-asterisk asterisk -rx 'dialplan reload'
docker exec private-asterisk /usr/local/bin/healthcheck
```

Only use this with a container actually mounted to the workbench `config/`.
CLI exit status alone can be misleading; inspect the reload response, endpoint
caller ID/extension mapping, and test a registration/call. If either reload fails,
restore the previous matching inventory, secrets and rendered files and reload
both again; if still unhealthy, recreate the previously validated release.
Reload does not terminate an existing call or erase every cached contact.
Transport/bind changes require recreate/restart, not reload. A Compose recreate
from the selected snapshot remains the production path.

## Backup, recovery and rollback

Keep inventory, secret store, snapshots, selection files, pinned images and
`/var/lib/asterisk` backups together in private, access-controlled backup storage;
use encryption for off-host backups. Backups contain credentials. Temporary spool
and logs are not durable. To make a consistent backup of the default data volume:

```sh
umask 077
mkdir -p backups/data-001
chmod 700 backups/data-001
# Use the currently active selection; candidate validation must already have passed.
docker compose --env-file releases/active.env -p private-asterisk \
  -f deploy/compose/compose.yaml stop asterisk
docker run --rm --mount type=volume,src=private-asterisk-data,dst=/data,readonly \
  --mount "type=bind,src=$(pwd)/backups/data-001,dst=/backup" \
  alpine:3.24 sh -c 'umask 077; tar -czf /backup/asterisk-data.tgz -C /data .'
```

Use the actual selected volume name if it differs. Keep the service stopped
until the intended candidate or previous release is activated. Backup the private
snapshot tree separately, for example `tar -czf backups/releases.tgz releases
inventory secrets` under `umask 077`; never upload it as a CI artifact.

To roll back both the image and configuration selection:

```sh
cp -p releases/previous.env releases/active.env
docker compose --env-file releases/active.env -p private-asterisk \
  -f deploy/compose/compose.yaml up -d --no-build --force-recreate --wait --wait-timeout 60
docker exec private-asterisk /usr/local/bin/healthcheck
```

Verify the previous image/release label, registrations and calls again. Keep every
referenced snapshot and image available. Restore a matching data backup when a
version change requires it. Restore into a **new** volume to preserve the failed
state for investigation:

```sh
docker volume create private-asterisk-restored
docker run --rm --mount type=volume,src=private-asterisk-restored,dst=/data \
  --mount "type=bind,src=$(pwd)/backups/data-001,dst=/backup,readonly" \
  alpine:3.24 tar -xzf /backup/asterisk-data.tgz -C /data
```

Set `ASTERISK_DATA_VOLUME` in the private active selection to that restored volume
and recreate with the same explicit Compose command. Retest readiness/calls.
Do not restore over a running database. Restoring a selection does not rewrite
the editing workbench: before preparing further releases, deliberately restore
the desired inventory and secrets together under `inventory/.lock`, or retain the
newer workbench as an explicitly different pending candidate.

## Plain Docker alternative

After the same snapshot validation, set `ASTERISK_IMAGE` to its recorded image ID
and `ASTERISK_CONFIG_DIR` to its absolute `config/` path, then run
`./scripts/run.sh`. The launcher uses the same default durable volume and fixed
container name. On update, stop/remove that container without deleting the volume,
then launch the selected candidate and verify health/calls. On failure repeat
with the previous paired image/config. It cannot overlap a Compose instance.
Use Compose for the managed update/recovery procedure above; do not mix methods.
