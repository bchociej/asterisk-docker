#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
config_dir=${ASTERISK_CONFIG_DIR:-$(pwd)/config}
image=${ASTERISK_IMAGE:-local/asterisk:alpine-3.24}
if [ ! -s "$config_dir/pjsip.conf" ] || [ ! -s "$config_dir/extensions.conf" ]; then
    echo 'Run scripts/configure.py with the PBX private IP first.' >&2
    exit 1
fi
exec docker run -d --name private-asterisk --network host \
    --restart unless-stopped --stop-timeout 30 \
    --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    --mount "type=bind,src=$config_dir,dst=/etc/asterisk,readonly" \
    --mount type=volume,src=private-asterisk-data,dst=/var/lib/asterisk \
    --tmpfs /run/asterisk:uid=10001,gid=10001,mode=0750 \
    --tmpfs /var/spool/asterisk:uid=10001,gid=10001,mode=0750 \
    --tmpfs /var/log/asterisk:uid=10001,gid=10001,mode=0750 \
    --tmpfs /tmp:mode=1777 \
    --log-opt max-size=10m --log-opt max-file=3 \
    "$image"
