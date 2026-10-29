# Standards adoption

Status: **adopted with the documented SHOULD departures below**. README records each
version spec and exact resolution. All three resolve to standards source commit
`894bf013623224066a3a99ed1d9f14c2b1bd7c67`, which was verified against remote
`main` before this assessment. This is also the front-matter revision read.

BAS-001 `^5.0.0` resolves to 5.0.0, requiring BAS-002 `^3.0.0`, resolved to 3.0.0.
CAS-001 `^4.0.0` resolves to 4.0.0 and requires BAS-001 `^5.0.0`. The transitive
selection is conflict-free. The abandoned legacy plan created no adoption
records; this is an initial SemVer adoption, not a reinterpretation of integer
versions. Consult the owner before changing resolutions or remediating outside
an approved scope, even if a future version matches a recorded range.

## Scope and established workflow

This repository ships one native Asterisk container and host-side configuration
helpers, using Linux amd64, Docker and Compose. CAS-001 applies. Kubernetes,
web services, runtime database backends, startup rendering and multi-replica
operation are not supported targets. The renderer runs explicitly before release
activation; CAS-001's optional startup-rendering pattern is not being adopted.

Public GitHub hosting, GitHub Actions and the established GitHub noreply commit
identity are retained. The owner approved assessment, implementation, validation,
commits and pushing on the existing `main` workflow. No new worktree, branching,
PR review rule, publication pipeline, history rewrite, actual deployment or ATA
provisioning is introduced. CI remains lint/format/unit/shell checks only.

## Implementation and deliberate choices

- Python development dependencies use `pyproject.toml`, `uv.lock` and locked CI
  synchronization. Ruff, pytest, Bats and ShellCheck remain the established tools.
  Host runtime helpers use only the Python standard library. The image contains
  neither Python tooling nor a compiler.
- The Dockerfile is under `container/`; Compose is under `deploy/compose/`, with
  stable project/container/volume naming and explicit root build/config paths.
  Commands always identify the Compose file/project. File inputs are read-only;
  Asterisk is the non-root foreground process and receives shutdown signals.
- The build context allows only explicitly listed public default configs,
  Dockerfile, health check and upstream compatibility patches. Private inventory,
  secret stores, generated config, snapshots, tooling caches and local overrides
  are excluded. Gitignore protects private artifacts before creation.
- Private snapshots lock source inputs, render into temporary output, pin a local
  content-addressed image ID, and fingerprint the coherent input set. Preflight
  boots the intended image/config in a disconnected namespace with the intended
  bind address, tests registration/authentication/RTP and leaves active data alone.
- Deployment notes cover ports, writable/durable paths, TLS responsibility,
  maintenance outage, validation and failure handling, image/input selection,
  readiness/representative operations, backups and paired rollback.

### Documented SHOULD departures

CAS-001's suggested layout is followed for the Dockerfile and orchestration, but
native default configuration remains in root `config/`, rather than under
`container/`, because the host renderer, native mount interface, tests and image
share this existing interface. Scripts remain in `scripts/`: there is no custom
application daemon needing an `app/` tree. Relocating these further would add
path churn and duplicate interfaces without separating a new component.

Private snapshots are directories inside ignored `releases/`; they are immutable
by convention plus fingerprint verification, rather than enforced by a filesystem
snapshot service. This is suitable for a single operator-controlled instance;
changes are rejected at validation and operators must not edit selected snapshots.
No controller, service database, Kubernetes or packaging framework is added.

## Verification and limitations

Verified during adoption on October 29, 2026:

- `uv sync --locked --python 3.12`, Ruff lint/format and 31 Python unit tests passed.
- ShellCheck and all 8 Bats tests passed.
- Linux amd64 build from `container/Dockerfile` passed.
- Synthetic registration, password rejection, PCMU RTP echo, extension remapping
  and native PJSIP/dialplan reload checks passed against that image.
- Private snapshot preparation and fingerprint checks passed. Exact intended
  image/native configuration validation passed in a disconnected namespace,
  including SIP authentication/RTP. Source and snapshot files were not mutated.
- Compose parsing verified root-relative build context, read-only config mount,
  stable project/volume settings, and one instance.
- Source files, staged changes, public history, author metadata, ignore rules,
  and local documentation links were reviewed. No real credentials, site input
  snapshots, owned-device identifiers, personal paths or private chat links were
  found in publishable material. CI verification is reported in the change record. No production
installation or real ATA configuration is changed as part of adoption.

Checks establish behavior for synthetic fixtures and isolated SIP/RTP traffic;
they do not establish LAN/VPN routing, host firewall correctness, handset audio
quality or external TLS trust. Compose parsing and path resolution are checked,
but actual Compose activation/rollback is documented and deliberately not run on
an operational deployment. Operational readiness and representative calls must
still be checked after each real activation.

The image's Asterisk tarball is checksum-pinned, and Python dependencies are
locked. Alpine packages, helper image tags, runner patch versions and host shell
tool packages may receive updates; this is not a claim of bit-for-bit rebuilds.
Production selection uses the exact image recorded in the private release, not
a mutable tag. Local image/config IDs and registry manifest digests are explicitly
distinguished. Retain the image locally or save it for rollback.

Source/history review is required alongside automated checks. Synthetic target
hardware, example IP addresses and public upstream attribution are intentional;
no real device inventory or deployment records belong in SCM or public logs.
The initial README described a generic multi-network target; it did not include
actual site names, addresses or real device identifiers. Adoption generalizes that
wording and does not rewrite published history. Automated scans are not a claim
of exhaustive secret detection. There are no known MUST exceptions.
