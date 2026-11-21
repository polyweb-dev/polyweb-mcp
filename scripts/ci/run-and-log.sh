#!/usr/bin/env bash
# Run one CI step command: preserve its exit status and raw log, convert CR
# progress for Woodpecker, enforce the fixed CI time limit, and record the
# step's resource use (layer 3 metrics, language agnostic).
#
#   run-and-log.sh <log-file> <command> [args...]
#
# Time limit. No CI job may run longer than 60 minutes. A step gets at most
# CI_STEP_LIMIT_CAP_SECONDS (55 min), which leaves room for the clone and the
# artifact upload. CI_STEP_TIMEOUT_SECONDS may lower the limit, never raise it.
# On a GCP worker the VM deletes itself 60 minutes after boot (30 for the
# mutation profile), so on a reused VM the step also stops 2 minutes before
# that deadline. Either way the step ends with exit status 124 and a
# CI_TIME_LIMIT_EXCEEDED banner instead of disappearing with its VM.
#
# Metrics. The step's cgroup (the step container in CI) gives CPU time,
# throttling, peak memory, OOM kills, disk I/O and pressure stall time. They
# are printed to stderr and written as JSON to
# ${CI_METRICS_DIR:-test_reports/ci-metrics}/<log name>.json. Outside a
# container the cgroup is the caller's whole session; run the command under
# `systemd-run --user --scope` for isolated numbers. CI_JOB_METRICS=0 skips them.
set -euo pipefail
log_file=$1
shift

readonly CI_JOB_LIMIT_MINUTES=60
readonly CI_STEP_LIMIT_CAP_SECONDS=3300
readonly VM_DEADLINE_MARGIN_SECONDS=120

limit_s=$CI_STEP_LIMIT_CAP_SECONDS
limit_reason="the fixed ${CI_JOB_LIMIT_MINUTES}-minute CI job limit (steps get $((CI_STEP_LIMIT_CAP_SECONDS / 60)) minutes)"
if [[ -n "${CI_STEP_TIMEOUT_SECONDS:-}" ]]; then
  if [[ ! "$CI_STEP_TIMEOUT_SECONDS" =~ ^[0-9]+$ || "$CI_STEP_TIMEOUT_SECONDS" -lt 1 ]]; then
    echo "CI_STEP_TIMEOUT_SECONDS must be a positive whole number of seconds" >&2
    exit 2
  fi
  if (( CI_STEP_TIMEOUT_SECONDS > CI_STEP_LIMIT_CAP_SECONDS )); then
    echo "CI_STEP_TIMEOUT_SECONDS=${CI_STEP_TIMEOUT_SECONDS} exceeds the fixed cap; using ${CI_STEP_LIMIT_CAP_SECONDS}" >&2
  else
    limit_s=$CI_STEP_TIMEOUT_SECONDS
    limit_reason="CI_STEP_TIMEOUT_SECONDS=${CI_STEP_TIMEOUT_SECONDS}"
  fi
fi
# Worker names come from scripts/gcp-ci-worker; /proc/uptime is the VM's.
# Woodpecker leaves CI_MACHINE empty (it is filled in before an agent is
# chosen), so in CI ask the GCP metadata server, in plain bash for any image.
gcp_metadata() {
  CI_GCP_METADATA_ADDRESS=${CI_GCP_METADATA_ADDRESS:-} METADATA_PATH=$1 timeout 2 bash -c '
    exec 3<>"/dev/tcp/${CI_GCP_METADATA_ADDRESS:-169.254.169.254/80}" || exit 1
    printf "GET /computeMetadata/v1/instance/%s HTTP/1.0\r\nHost: metadata.google.internal\r\nMetadata-Flavor: Google\r\n\r\n" "$METADATA_PATH" >&3
    tail -n 1 <&3' 2>/dev/null | tr -cd "A-Za-z0-9._/-" || true
}
machine=${CI_MACHINE:-}
machine_type=
if [[ -z "$machine" && -n "${CI:-}" ]]; then
  machine=$(gcp_metadata name)
  if [[ -n "$machine" ]]; then
    machine_type=$(gcp_metadata machine-type)
    machine_type=${machine_type##*/}
  fi
fi
case "$machine" in
  gcp-spot-mutation-*) vm_lifetime_s=1800 ;;
  gcp-spot-* | gcp-worker-*) vm_lifetime_s=3600 ;;
  *) vm_lifetime_s= ;;
esac
if [[ -n "$vm_lifetime_s" && -r /proc/uptime ]]; then
  uptime_s=$(cut -d. -f1 /proc/uptime)
  vm_left_s=$(( vm_lifetime_s - uptime_s - VM_DEADLINE_MARGIN_SECONDS ))
  if (( vm_left_s < limit_s )); then
    limit_s=$(( vm_left_s > 60 ? vm_left_s : 60 ))
    limit_reason="the worker VM's fixed $((vm_lifetime_s / 60))-minute lifetime (the VM has run $((uptime_s / 60)) minutes)"
  fi
fi

metrics=${CI_JOB_METRICS:-1}
cgroup=
if [[ "$metrics" != 0 && -r /proc/self/cgroup ]]; then
  path=$(awk -F: '$1 == "0" { print $3; exit }' /proc/self/cgroup)
  if [[ -n "$path" && -r "/sys/fs/cgroup${path%/}/cpu.stat" ]]; then
    cgroup="/sys/fs/cgroup${path%/}"
  fi
fi

# key value pairs from a flat cgroup file such as cpu.stat or memory.events.
cg_value() {
  awk -v key="$2" '$1 == key { print $2; found = 1; exit } END { if (!found) print 0 }' \
    "$cgroup/$1" 2>/dev/null || echo 0
}
cg_number() { cat "$cgroup/$1" 2>/dev/null || echo 0; }
# Total stall time from a PSI file ("some ... total=<usec>").
cg_stall() {
  awk '$1 == "some" { split($5, total, "="); print total[2]; found = 1 } END { if (!found) print 0 }' \
    "$cgroup/$1" 2>/dev/null || echo 0
}
cg_io() {
  awk -v field="$1" '{ for (i = 2; i <= NF; i++) { split($i, kv, "="); if (kv[1] == field) sum += kv[2] } } END { printf "%.0f\n", sum }' \
    "$cgroup/io.stat" 2>/dev/null || echo 0
}
snapshot() {
  [[ -n "$cgroup" ]] || return 0
  snap_cpu=$(cg_value cpu.stat usage_usec)
  snap_user=$(cg_value cpu.stat user_usec)
  snap_system=$(cg_value cpu.stat system_usec)
  snap_throttled=$(cg_value cpu.stat throttled_usec)
  snap_read=$(cg_io rbytes)
  snap_write=$(cg_io wbytes)
  snap_cpu_stall=$(cg_stall cpu.pressure)
  snap_memory_stall=$(cg_stall memory.pressure)
  snap_io_stall=$(cg_stall io.pressure)
  snap_oom=$(cg_value memory.events oom_kill)
}

started_ns=$(date +%s%N)
snapshot
before=("${snap_cpu:-0}" "${snap_user:-0}" "${snap_system:-0}" "${snap_throttled:-0}" \
  "${snap_read:-0}" "${snap_write:-0}" "${snap_cpu_stall:-0}" "${snap_memory_stall:-0}" \
  "${snap_io_stall:-0}" "${snap_oom:-0}")

# GNU timeout runs the command in its own process group and signals all of it.
set +e
timeout --kill-after=30 "$limit_s" "$@" 2>&1 | tee "$log_file" | stdbuf -oL tr '\r' '\n'
statuses=("${PIPESTATUS[@]}")
set -e
ended_ns=$(date +%s%N)
wall_ms=$(( (ended_ns - started_ns) / 1000000 ))
status=${statuses[0]}
for pipe_status in "${statuses[@]:1}"; do
  if (( status == 0 && pipe_status != 0 )); then status=$pipe_status; fi
done

timed_out=false
if (( statuses[0] == 124 || (statuses[0] == 137 && wall_ms >= limit_s * 1000) )); then
  timed_out=true
  status=124
  banner=$(cat <<EOF

==========================================================================
CI_TIME_LIMIT_EXCEEDED
This step was stopped after $(( wall_ms / 60000 )) minutes by ${limit_reason}.
No CI job in this repository may run longer than ${CI_JOB_LIMIT_MINUTES} minutes; the limit is
fixed so a stalled run cannot hold a worker VM. It is not a test assertion.
Stalls are often intermittent: rerun the pipeline once. If it stops here
again, look at the last output above for the test or command that hung.
Step command: $*
==========================================================================
EOF
)
  printf '%s\n' "$banner" >&2
  printf '%s\n' "$banner" >> "$log_file"
fi

if [[ "$metrics" != 0 ]]; then
  # `times` must run in this shell (a subshell has no children); its second
  # line is the CPU time of every waited-for descendant, as "XmY.YYYs".
  times_file=$(mktemp 2>/dev/null) || times_file=
  if [[ -n "$times_file" ]]; then times > "$times_file"; fi
  # Everything else runs in a subshell: a metrics problem (an odd cgroup
  # value, a full disk) is reported but never changes the step's exit status.
  (
  snapshot
  cpus=$(nproc 2>/dev/null || echo 0)
  cpu_max=none
  memory_max=none
  memory_peak=0
  if [[ -n "$cgroup" ]]; then
    cpu_max=$(cg_number cpu.max | tr ' ' '/')
    memory_max=$(cg_number memory.max)
    memory_peak=$(cg_number memory.peak)
  fi
  shell_times=()
  if [[ -n "$times_file" ]]; then
    read -r -a shell_times < <(awk 'NR == 2 { for (i = 1; i <= 2; i++) { split($i, t, "m"); sub("s", "", t[2]); printf "%.3f ", t[1] * 60 + t[2] } }' "$times_file") || true
  fi
  cpu_ms=$(( (${snap_cpu:-0} - before[0]) / 1000 ))
  utilisation="n/a"
  if [[ -n "$cgroup" ]] && (( wall_ms > 0 && cpus > 0 )); then
    utilisation=$(awk -v c="$cpu_ms" -v w="$wall_ms" -v n="$cpus" 'BEGIN { printf "%.1f%%", 100 * c / (w * n) }')
  fi
  metrics_dir=${CI_METRICS_DIR:-test_reports/ci-metrics}
  name=$(basename -- "$log_file")
  name=${name%.log}
  if mkdir -p "$metrics_dir" 2>/dev/null; then
    cat > "$metrics_dir/$name.json" <<EOF
{
  "schema": "polyweb.ci-step-metrics/1",
  "step": "$name",
  "machine": "$machine",
  "machine_type": "$machine_type",
  "test_metrics": "${POLYWEB_TEST_METRICS:-0}",
  "exit_status": $status,
  "timed_out": $timed_out,
  "limit_seconds": $limit_s,
  "wall_ms": $wall_ms,
  "cpus": $cpus,
  "cgroup": "${cgroup:-}",
  "cpu_ms": $cpu_ms,
  "cpu_user_ms": $(( (${snap_user:-0} - before[1]) / 1000 )),
  "cpu_system_ms": $(( (${snap_system:-0} - before[2]) / 1000 )),
  "cpu_throttled_ms": $(( (${snap_throttled:-0} - before[3]) / 1000 )),
  "cpu_max": "$cpu_max",
  "memory_peak_bytes": $memory_peak,
  "memory_max": "$memory_max",
  "oom_kills": $(( ${snap_oom:-0} - before[9] )),
  "io_read_bytes": $(( ${snap_read:-0} - before[4] )),
  "io_write_bytes": $(( ${snap_write:-0} - before[5] )),
  "cpu_stall_ms": $(( (${snap_cpu_stall:-0} - before[6]) / 1000 )),
  "memory_stall_ms": $(( (${snap_memory_stall:-0} - before[7]) / 1000 )),
  "io_stall_ms": $(( (${snap_io_stall:-0} - before[8]) / 1000 )),
  "children_cpu_user": "${shell_times[0]:-}",
  "children_cpu_system": "${shell_times[1]:-}"
}
EOF
  fi
  {
    echo "--- step metrics ($name) ---"
    echo "wall $(( wall_ms / 1000 )).$(( wall_ms % 1000 / 100 ))s, limit ${limit_s}s, exit ${status}${machine:+, machine $machine}${machine_type:+ ($machine_type)}"
    if [[ -n "$cgroup" ]]; then
      echo "cpu $(( cpu_ms / 1000 ))s on ${cpus} cpus (${utilisation} average use), throttled $(( (${snap_throttled:-0} - before[3]) / 1000 ))ms"
      echo "memory peak $(( memory_peak / 1048576 )) MiB (max ${memory_max}), oom kills $(( ${snap_oom:-0} - before[9] ))"
      echo "disk read $(( (${snap_read:-0} - before[4]) / 1048576 )) MiB, write $(( (${snap_write:-0} - before[5]) / 1048576 )) MiB"
      echo "stall cpu $(( (${snap_cpu_stall:-0} - before[6]) / 1000 ))ms, memory $(( (${snap_memory_stall:-0} - before[7]) / 1000 ))ms, io $(( (${snap_io_stall:-0} - before[8]) / 1000 ))ms"
    else
      echo "no readable cgroup v2; child cpu user ${shell_times[0]:-?}s system ${shell_times[1]:-?}s"
    fi
  } >&2
  ) || echo "step metrics could not be recorded; the step's exit status is unchanged" >&2
  if [[ -n "$times_file" ]]; then rm -f "$times_file"; fi
fi
exit "$status"
