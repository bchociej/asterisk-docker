#!/usr/bin/env python3
"""Generate private SIP accounts without putting passwords in the image or Git."""

import argparse
import ipaddress
import os
import secrets
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--bind",
    type=ipaddress.IPv4Address,
    required=True,
    help="Private IPv4 address on the PBX host (not 0.0.0.0)",
)
parser.add_argument(
    "--extensions",
    nargs="+",
    default=["1001", "1002"],
    help="Unique four-digit extension numbers",
)
args = parser.parse_args()
address = args.bind
if (
    address.is_unspecified
    or address.is_multicast
    or address.is_loopback
    or not address.is_private
):
    parser.error("--bind must be a reachable private unicast IPv4 address")
if len(set(args.extensions)) != len(args.extensions) or any(
    len(x) != 4 or not x.isascii() or not x.isdigit() or x == "6000"
    for x in args.extensions
):
    parser.error("Use unique four-digit extensions; 6000 is reserved for the echo test")
root = Path(__file__).resolve().parent.parent
paths = [
    root / "config/pjsip.conf",
    root / "config/extensions.conf",
    root / "credentials.txt",
]
if any(p.exists() for p in paths):
    parser.error(
        "Generated files already exist; back them up and remove them before regenerating credentials"
    )
accounts = {x: secrets.token_hex(24) for x in args.extensions}
pjsip = f"""[global]
type = global
endpoint_identifier_order = username

[private-udp]
type = transport
protocol = udp
bind = {address}:5060

[phone](!)
type = endpoint
transport = private-udp
context = phones
disallow = all
allow = ulaw
dtmf_mode = rfc4733
direct_media = no
force_rport = yes
rewrite_contact = yes
rtp_symmetric = yes
allow_subscribe = no
"""
for extension, password in accounts.items():
    pjsip += f"""
[{extension}](phone)
auth = auth-{extension}
aors = {extension}
callerid = Phone {extension} <{extension}>

[auth-{extension}]
type = auth
auth_type = userpass
username = {extension}
password = {password}

[{extension}]
type = aor
max_contacts = 1
remove_existing = yes
qualify_frequency = 30
"""
dialplan = "[general]\nstatic = yes\nwriteprotect = yes\n\n[phones]\n"
for extension in accounts:
    dialplan += (
        f"exten => {extension},1,Dial(PJSIP/{extension},30)\n same => n,Hangup()\n"
    )
dialplan += "\n; Prompt-free echo test: speak and listen for your voice.\nexten => 6000,1,Answer()\n same => n,Echo()\n same => n,Hangup()\n"
credentials = f"Primary SIP server: {address}\nSIP transport: UDP, port 5060\nCodec: PCMU; DTMF: RFC2833\n\n"
credentials += "".join(
    f"Extension / SIP user / Authenticate ID: {x}\nPassword: {p}\n\n"
    for x, p in accounts.items()
)
# Config must be readable by the container's service UID. Keep the credential
# summary private to the host user; control access to this entire repository.
for path, content, mode in zip(
    paths, [pjsip, dialplan, credentials], [0o644, 0o644, 0o600]
):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as f:
        f.write(content)
print("Created config/pjsip.conf, config/extensions.conf and credentials.txt")
print("Passwords are in credentials.txt; they have not been printed.")
