#!/bin/sh
set -eu
# Preserve CLI/timeout failures as well as checking the response contents.
uptime=$(timeout 3 asterisk -rx 'core show uptime')
printf '%s\n' "$uptime" | grep -q 'System uptime:'
transports=$(timeout 3 asterisk -rx 'pjsip show transports')
printf '%s\n' "$transports" | grep -q 'private-udp'
modules=$(timeout 3 asterisk -rx 'module show like chan_pjsip.so')
printf '%s\n' "$modules" | awk '/^chan_pjsip[.]so[[:space:]]/ && /Running/ && !/Not Running/ { found=1 } END { exit !found }'
