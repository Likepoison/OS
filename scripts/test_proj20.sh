#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
case "${1:-all}" in
    all) chapters=(3 4 5 6 8) ;;
    ch3|ch4|ch5|ch6|ch8) chapters=("${1#ch}") ;;
    *) echo "Usage: bash scripts/test_proj20.sh [all|ch3|ch4|ch5|ch6|ch8]" >&2; exit 2 ;;
esac
if (( $# > 1 )); then
    echo "Expected one chapter selector" >&2
    exit 2
fi

export TG_USER_DIR="$root/tg-rcore-tutorial-user"
export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-1.100.0}"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
export TIMEOUT_SEC="${TIMEOUT_SEC:-210}"
for tool in cargo rust-objcopy qemu-system-riscv64 tg-rcore-tutorial-checker; do
    command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
if [[ -n "${PROJ20_LOG_DIR:-}" ]]; then
    mkdir -p -- "$PROJ20_LOG_DIR"
    logs=$(mktemp -d "$(cd -- "$PROJ20_LOG_DIR" && pwd)/run-XXXXXX")
else
    logs=$(mktemp -d "${TMPDIR:-/tmp}/proj20-XXXXXX")
fi
echo "Logs: $logs"
{
    date --iso-8601=seconds
    git -C "$root" rev-parse HEAD
    git -C "$root" status --porcelain
    rustc --version
    qemu-system-riscv64 --version
} >"$logs/environment.log"

for chapter in "${chapters[@]}"; do
    for suite in base exercise; do
        log="$logs/ch$chapter-$suite.log"
        if (cd -- "$root/tg-rcore-tutorial-ch$chapter" && timeout -k 5s 300s bash test.sh "$suite" </dev/null) >"$log" 2>&1 &&
            grep -a 'Test PASSED' "$log" | sed "s/^/ch$chapter $suite: /"; then
            continue
        fi
        echo "ch$chapter $suite failed. Log: $log" >&2
        tail -n 25 "$log" >&2
        exit 1
    done
done
