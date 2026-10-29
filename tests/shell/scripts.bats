#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$BATS_TEST_DIRNAME/../.."
    export TEST_PROJECT="$BATS_TEST_TMPDIR/project with spaces"
    mkdir -p "$TEST_PROJECT/scripts" "$TEST_PROJECT/config" "$BATS_TEST_TMPDIR/bin"
    cp "$PROJECT_ROOT/scripts/run.sh" "$TEST_PROJECT/scripts/"
    export PATH="$BATS_TEST_TMPDIR/bin:$PATH"
    export DOCKER_LOG="$BATS_TEST_TMPDIR/docker-args"
    cat > "$BATS_TEST_TMPDIR/bin/docker" <<'MOCK'
#!/bin/sh
printf '%s\n' "$@" > "$DOCKER_LOG"
exit "${DOCKER_EXIT:-0}"
MOCK
    cat > "$BATS_TEST_TMPDIR/bin/asterisk" <<'MOCK'
#!/bin/sh
case "$2" in
    'core show uptime') echo 'System uptime: 10 seconds' ;;
    'pjsip show transports') echo "${TRANSPORT_NAME:-private-udp}" ;;
    'module show like chan_pjsip.so') echo "chan_pjsip.so PJSIP Channel Driver 0 ${MODULE_STATE:-Running} core" ;;
esac
exit "${CLI_EXIT:-0}"
MOCK
    chmod +x "$BATS_TEST_TMPDIR/bin/"*
}

@test "launcher refuses missing configuration without calling Docker" {
    run sh "$TEST_PROJECT/scripts/run.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *configure.py* ]]
    [ ! -e "$DOCKER_LOG" ]
}

@test "launcher preserves paths with spaces and container restrictions" {
    printf 'configured\n' > "$TEST_PROJECT/config/pjsip.conf"
    printf 'configured\n' > "$TEST_PROJECT/config/extensions.conf"
    run sh "$TEST_PROJECT/scripts/run.sh"
    [ "$status" -eq 0 ]
    grep -Fx -- '--read-only' "$DOCKER_LOG"
    grep -Fx -- '--cap-drop' "$DOCKER_LOG"
    grep -Fx -- 'ALL' "$DOCKER_LOG"
    grep -Fx -- 'no-new-privileges:true' "$DOCKER_LOG"
    grep -Fx -- "type=bind,src=$TEST_PROJECT/config,dst=/etc/asterisk,readonly" "$DOCKER_LOG"
}

@test "launcher propagates Docker failure" {
    printf 'configured\n' > "$TEST_PROJECT/config/pjsip.conf"
    printf 'configured\n' > "$TEST_PROJECT/config/extensions.conf"
    export DOCKER_EXIT=42
    run sh "$TEST_PROJECT/scripts/run.sh"
    [ "$status" -eq 42 ]
}

@test "health check accepts responsive SIP channel and transport" {
    run sh "$PROJECT_ROOT/scripts/healthcheck.sh"
    [ "$status" -eq 0 ]
}

@test "health check rejects a channel marked Not Running" {
    export MODULE_STATE='Not Running'
    run sh "$PROJECT_ROOT/scripts/healthcheck.sh"
    [ "$status" -ne 0 ]
}

@test "health check rejects a missing private transport" {
    export TRANSPORT_NAME=unrelated-transport
    run sh "$PROJECT_ROOT/scripts/healthcheck.sh"
    [ "$status" -ne 0 ]
}

@test "health check propagates CLI failure even with plausible output" {
    export CLI_EXIT=1
    run sh "$PROJECT_ROOT/scripts/healthcheck.sh"
    [ "$status" -ne 0 ]
}

@test "image test cleans up after Docker startup failure without touching deployment files" {
    cp "$PROJECT_ROOT/scripts/test-image.sh" "$PROJECT_ROOT/scripts/configure.py" "$TEST_PROJECT/scripts/"
    printf 'real deployment credential\n' > "$TEST_PROJECT/config/pjsip.conf"
    printf 'real dialplan\n' > "$TEST_PROJECT/config/extensions.conf"
    cat > "$BATS_TEST_TMPDIR/bin/docker" <<'MOCK'
#!/bin/sh
printf '%s\n' "$1" >> "$DOCKER_LOG"
case "$1" in
    run) exit 23 ;;
    logs) echo 'startup failure' ;;
    rm) exit 0 ;;
esac
MOCK
    run sh "$TEST_PROJECT/scripts/test-image.sh"
    [ "$status" -eq 23 ]
    grep -Fx 'logs' "$DOCKER_LOG"
    grep -Fx 'rm' "$DOCKER_LOG"
    grep -Fx 'real deployment credential' "$TEST_PROJECT/config/pjsip.conf"
    grep -Fx 'real dialplan' "$TEST_PROJECT/config/extensions.conf"
    # Failed integration runs deliberately retain their temporary diagnostics.
    retained=$(printf '%s\n' "$output" | sed -n 's/^Test files and log retained at //p')
    [ -d "$retained" ]
    rm -rf "$retained"
}
