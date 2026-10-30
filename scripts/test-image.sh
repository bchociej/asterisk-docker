#!/bin/sh
# Isolated smoke test. Does not publish ports or touch deployment credentials.
set -eu
cd "$(dirname "$0")/.."
image=${1:-local/asterisk:alpine-3.24}
name="asterisk-smoke-$$"
config_dir=$(mktemp -d)
cleanup() {
    docker logs "$name" > "$config_dir/container.log" 2>&1 || true
    docker rm -f -v "$name" >/dev/null 2>&1 || true
    docker rm -f "$name-net" >/dev/null 2>&1 || true
    if [ "${passed:-no}" = yes ]; then rm -rf "$config_dir"; else
        echo "Test files and log retained at $config_dir" >&2
        if [ -z "${snapshot:-}" ]; then cat "$config_dir/container.log" >&2; fi
    fi
}
trap cleanup EXIT HUP INT TERM
snapshot=${2:-}
network=bridge
client_image=${ASTERISK_TEST_CLIENT_IMAGE:-python:3.12-slim}
mkdir "$config_dir/scripts"
if [ -n "$snapshot" ]; then
    python3 scripts/snapshot.py verify "$snapshot"
    # Require the exact image selected when this snapshot was prepared.
    expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["image"])' "$snapshot/release.json")
    actual=$(docker image inspect -f '{{.Id}}' "$image")
    [ "$actual" = "$expected" ]
    cp -R "$snapshot/config" "$config_dir/config"
    cp -R "$snapshot/inventory" "$config_dir/inventory"
    cp -R "$snapshot/secrets" "$config_dir/secrets"
    cp "$snapshot/scripts/configure.py" "$config_dir/scripts/configure.py"
    python3 "$config_dir/scripts/configure.py" render >/dev/null
    cmp -s "$config_dir/config/pjsip.conf" "$snapshot/config/pjsip.conf"
    cmp -s "$config_dir/config/extensions.conf" "$snapshot/config/extensions.conf"
    bind_ip=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bind"])' "$snapshot/inventory/devices.json")
    # Give the exact intended bind address to a disposable, disconnected network
    # namespace. Never bind candidate configuration on the real host network.
    docker run -d --name "$name-net" --network none --cap-drop ALL \
        --cap-add NET_ADMIN alpine:3.24 sleep 600 >/dev/null
    docker exec "$name-net" ip address add "$bind_ip/32" dev lo
    network="container:$name-net"
else
    # Copy only public defaults; local dialplans/audio never enter generic tests.
    mkdir "$config_dir/config"
    for file in acl ari asterisk ccss cdr cel features http indications logger manager modules pjproject rtp stasis udptl; do
        cp "config/$file.conf" "$config_dir/config/"
    done
    cp scripts/configure.py "$config_dir/scripts/configure.py"
    python3 "$config_dir/scripts/configure.py" init --bind 192.168.250.1
    python3 "$config_dir/scripts/configure.py" add test-a --extension 1001
    python3 "$config_dir/scripts/configure.py" add test-b --extension 1002
    python3 "$config_dir/scripts/configure.py" render
fi
if [ -z "$snapshot" ]; then
    sed -i 's/^bind = .*:5060$/bind = 0.0.0.0:5060/' "$config_dir/config/pjsip.conf"
fi
docker run -d --name "$name" --network "$network" --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --mount "type=bind,src=$config_dir/config,dst=/etc/asterisk,readonly" \
    --tmpfs /run/asterisk:uid=10001,gid=10001,mode=0750 \
    --mount type=volume,dst=/var/lib/asterisk \
    --tmpfs /var/log/asterisk:uid=10001,gid=10001,mode=0750 \
    --tmpfs /var/spool/asterisk:uid=10001,gid=10001,mode=0750 \
    --tmpfs /tmp "$image" >/dev/null
ready=no
for _attempt in $(seq 1 30); do
    if docker exec "$name" /usr/local/bin/healthcheck; then ready=yes; break; fi
    [ "$(docker inspect -f '{{.State.Running}}' "$name")" = true ] || break
    sleep 1
done
[ "$ready" = yes ]
[ "$(docker exec "$name" id -u)" = 10001 ]
if [ -z "$snapshot" ]; then
    docker exec "$name" asterisk -rx 'pjsip show endpoints'
fi
if [ -z "$snapshot" ]; then
    docker exec "$name" asterisk -rx 'dialplan show phones'
fi
for module in chan_iax2 res_http_websocket res_ari; do
    if docker exec "$name" asterisk -rx "module show like $module" | grep -q 'Running'; then
        echo "Unexpected module: $module" >&2; exit 1
    fi
done
docker exec "$name" asterisk -rx 'manager show settings' | grep -Eq 'Manager \(AMI\):[[:space:]]+No'
if [ -n "$snapshot" ]; then
    dependencies=$(python3 -c 'from pathlib import Path; import pytest; print(Path(pytest.__file__).resolve().parent.parent)')
    docker run --rm --network "$network" --read-only --cap-drop ALL \
        --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" \
        --tmpfs /tmp --env PYTHONPATH=/deps --env PYTHONDONTWRITEBYTECODE=1 \
        --env "ASTERISK_TEST_EXTENSION=${ASTERISK_TEST_EXTENSION:-6000}" \
        --mount "type=bind,src=$dependencies,dst=/deps,readonly" \
        --mount "type=bind,src=$(pwd),dst=/repo,readonly" \
        --mount "type=bind,src=$config_dir/config/pjsip.conf,dst=/pjsip.conf,readonly" \
        --workdir /repo "$client_image" python -m pytest -q -p no:cacheprovider \
        -m integration tests/test_sip.py --pbx-host "$bind_ip" --pbx-config /pjsip.conf \
        --tb=no --show-capture=no
else
    ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$name")
    python3 -m pytest -q -m integration tests/test_sip.py \
        --pbx-host "$ip" --pbx-config "$config_dir/config/pjsip.conf" --tb=no --show-capture=no
fi
if [ -z "$snapshot" ]; then
# Re-render a changed extension, then authenticate again with the same secrets.
cp "$config_dir/secrets/phones.json" "$config_dir/secrets-before.json"
python3 "$config_dir/scripts/configure.py" update test-a --extension 2001
python3 "$config_dir/scripts/configure.py" render
cmp "$config_dir/secrets-before.json" "$config_dir/secrets/phones.json"
docker exec "$name" asterisk -rx 'module reload res_pjsip.so'
docker exec "$name" asterisk -rx 'dialplan reload'
docker exec "$name" asterisk -rx 'pjsip show endpoint phone-test-a' | grep -E 'callerid[[:space:]]+:[[:space:]]+.*<2001>'
docker exec "$name" asterisk -rx 'dialplan show 2001@phones' | grep -F 'Dial(PJSIP/phone-test-a,30)'
python3 -m pytest -q -m integration tests/test_sip.py \
    --pbx-host "$ip" --pbx-config "$config_dir/config/pjsip.conf" --tb=no --show-capture=no
else
    python3 scripts/snapshot.py verify "$snapshot"
fi
passed=yes
echo 'PASS: non-root, read-only startup; private transport; endpoint registration; restricted modules.'
