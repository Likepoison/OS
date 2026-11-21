#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$root"
export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-1.100.0}"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$root/target/proj20-units}"
for component in ch3 ch4 ch5 ch6 ch8 kernel-vm kernel-alloc task-manage syscall easy-fs sync; do
    printf '\n=== %s ===\n' "$component"
    cargo test --manifest-path "tg-rcore-tutorial-$component/Cargo.toml" "$@"
done
