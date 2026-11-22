#!/usr/bin/env bash
set -euo pipefail

image=tracetutor-sandbox
scratch=$(mktemp -d)
# The fixture directory is mounted read-only, so it can contain only test inputs.
trap 'find "$scratch" -depth -delete' EXIT
container="tracetutor-probe-$$"
trap 'docker rm -f "$container" >/dev/null 2>&1 || true; find "$scratch" -depth -delete' EXIT

docker version --format 'Docker {{.Server.Version}}'
docker info --format 'cgroup={{.CgroupVersion}} driver={{.CgroupDriver}}'
docker build -t "$image" .
docker run --rm --network none --user 65534:65534 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev,exec,size=32m \
  --cpus 1 --memory 128m --memory-swap 128m --pids-limit 16 \
  -i "$image" sh -ec '
    test "$(id -u)" = 65534
    test ! -w /etc
    test "$(cat /sys/fs/cgroup/cpu.max)" = "100000 100000"
    test "$(cat /sys/fs/cgroup/memory.max)" = 134217728
    test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
    test "$(cat /sys/fs/cgroup/pids.max)" = 16
    gcc --version | head -1
    strace --version | head -1
    gcc -std=c11 -Wall -Wextra -Werror -O2 -x c - -o /tmp/probe
    output=$(strace -f -ttt -T -e trace=process,write -o /tmp/trace /tmp/probe)
    test "$output" = child-ok
    cat /tmp/trace
    awk '"'"'/ (clone|fork|vfork)\(/ {parent=$1} /write\(1, "child-ok/ {child=$1} END {exit !(parent && child && parent!=child)}'"'"' /tmp/trace
    /tmp/probe pids
    base64 /tmp/probe
  ' < tests/sandbox_probe.c > "$scratch/compile.out"

sed -n '1,/^pids: /p' "$scratch/compile.out"
sed '1,/^pids: /d' "$scratch/compile.out" | base64 -d > "$scratch/probe"
chmod 755 "$scratch" "$scratch/probe"

limits=(--network none --user 65534:65534 --read-only --cap-drop ALL
  --security-opt no-new-privileges --cpus 1 --memory 32m --memory-swap 32m
  --pids-limit 16 --mount "type=bind,src=$scratch/probe,dst=/probe,readonly")
# Read the same kernel counter as the grader while the cgroup still exists.
docker run --rm "${limits[@]}" "$image" sh -ec '
    oom_count() {
        awk '"'"'$1 == "oom_kill" {print $2; found=1} END {exit !found}'"'"' /sys/fs/cgroup/memory.events
    }
    test "$(cat /sys/fs/cgroup/memory.max)" = 33554432
    before=$(oom_count)
    rc=0
    /probe memory || rc=$?
    after=$(oom_count)
    echo "memory probe: exit=$rc, oom_kill=$before -> $after"
    test "$rc" -eq 137
    test "$after" -gt "$before"
'

docker run -d --name "$container" "${limits[@]}" "$image" /probe hang >/dev/null
timeout 5s bash -c 'until docker logs "$1" | grep -qx detached; do sleep .1; done' _ "$container"
mapfile -t pids < <(docker top "$container" -eo pid | tail -n +2)
test "${#pids[@]}" -eq 2
rc=0
timeout 1s docker wait "$container" >/dev/null || rc=$?
test "$rc" -eq 124
docker rm -f "$container" >/dev/null
if docker inspect "$container" >/dev/null 2>&1; then exit 1; fi
for pid in "${pids[@]}"; do
    # A killed orphan may briefly remain a zombie while the host reaps it.
    if test -r "/proc/$pid/stat"; then
        state=$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)
        test -z "$state" || test "$state" = Z
    fi
done
echo "timeout: container removed with detached child"
