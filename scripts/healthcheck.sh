#!/bin/sh
set -eu
# CLI success alone does not guarantee the requested command exists.
timeout 3 asterisk -rx 'core show uptime' | grep -q 'System uptime:'
timeout 3 asterisk -rx 'pjsip show transports' | grep -q 'private-udp'
timeout 3 asterisk -rx 'module show like chan_pjsip.so' | awk '/^chan_pjsip[.]so[[:space:]]/ && /Running/ && !/Not Running/ { found=1 } END { exit !found }'
