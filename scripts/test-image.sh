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
    if [ "${passed:-no}" = yes ]; then rm -rf "$config_dir"; else
        echo "Test files and log retained at $config_dir" >&2
        cat "$config_dir/container.log" >&2
    fi
}
trap cleanup EXIT HUP INT TERM
cp -R config "$config_dir/config"
# Keep any real deployment files outside the test.
rm -f "$config_dir/config/pjsip.conf" "$config_dir/config/extensions.conf"
cp scripts/configure.py "$config_dir/configure.py"
mkdir "$config_dir/scripts"
mv "$config_dir/configure.py" "$config_dir/scripts/configure.py"
# Only this disposable test binds every interface in its isolated namespace.
python3 "$config_dir/scripts/configure.py" --bind 192.168.250.1
sed -i 's/192.168.250.1:5060/0.0.0.0:5060/' "$config_dir/config/pjsip.conf"
chmod 755 "$config_dir"
docker run -d --name "$name" --read-only --cap-drop ALL \
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
docker exec "$name" asterisk -rx 'pjsip show endpoints'
docker exec "$name" asterisk -rx 'dialplan show phones'
for module in chan_iax2 res_http_websocket res_ari; do
    if docker exec "$name" asterisk -rx "module show like $module" | grep -q 'Running'; then
        echo "Unexpected module: $module" >&2; exit 1
    fi
done
ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$name")
docker exec "$name" asterisk -rx 'manager show settings' | grep -Eq 'Manager \(AMI\):[[:space:]]+No'
python3 -m pytest -q -m integration tests/test_sip.py \
    --pbx-host "$ip" --pbx-config "$config_dir/config/pjsip.conf"
passed=yes
echo 'PASS: non-root, read-only startup; private transport; endpoint registration; restricted modules.'
