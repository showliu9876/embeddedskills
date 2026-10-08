#!/usr/bin/env bash
# Run a command in a shared, visible Herdr pane so the user can watch it, and hand its stdout,
# stderr and exit code back to the caller unchanged. Falls back to running the command directly
# when not inside Herdr, when disabled, or for users listed in HERDR_EXEC_DISABLED_USERS.
#
# Usage:
#   herdr_exec.sh [--label NAME] [--timeout-ms N] -- <command> [args...]
#   herdr_exec.sh --get-pane NAME     print an idle pane labelled NAME (reused or created) and exit
#
# Before splitting a new pane, an idle pane (foreground process is only a shell) carrying one of the
# labels this script manages (embedded-skills, uart-console) in the same workspace is reused.
# Panes without such a label (the user's own shells, agents) are never touched, and no pane is closed.
#
# Environment:
#   HERDR_EXEC_DISABLE=1          always run directly
#   HERDR_EXEC_DISABLED_USERS     space-separated users that always run directly (default: none).
#                                 Commands in a Herdr pane are NOT confined by Claude Code's sandbox,
#                                 so list every account whose sandbox must not be bypassed
#   HERDR_EXEC_TIMEOUT_MS         default wait for completion (default: 600000)
#   HERDR_EXEC_IDLE_WAIT_MS       how long to wait for the shared pane to become idle (default: 3000)
#   HERDR_EXEC_PANE_LABEL         label of the shared pane (default: "embedded-skills")
#   HERDR_EXEC_STATE_DIR          state directory (default: $XDG_RUNTIME_DIR/herdr-exec or /tmp/herdr-exec-$UID)
#
# Exit status: the command's own status; 124 on timeout (the command keeps running in the pane);
# 2 on usage errors.

set -uo pipefail

LABEL="cmd"
TIMEOUT_MS="${HERDR_EXEC_TIMEOUT_MS:-600000}"
IDLE_WAIT_MS="${HERDR_EXEC_IDLE_WAIT_MS:-3000}"
PANE_LABEL="${HERDR_EXEC_PANE_LABEL:-embedded-skills}"
DISABLED_USERS="${HERDR_EXEC_DISABLED_USERS:-}"
MANAGED_LABELS=" embedded-skills uart-console ${PANE_LABEL} "   # only panes with these labels are reused
GET_PANE=0
SHELL_NAMES=" bash zsh sh dash fish "
POLL_S=0.1
WIDE_PANE_COLS=160     # split right when the caller pane is at least this wide, otherwise down
PASS_ENV=(PATH PYTHONPATH VIRTUAL_ENV CONDA_PREFIX JLINK_BIN JLINK_SN)

usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
log() { echo "[herdr-exec] $*" >&2; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --label) LABEL="${2:-}"; shift 2 ;;
      --timeout-ms) TIMEOUT_MS="${2:-}"; shift 2 ;;
      --get-pane) GET_PANE=1; PANE_LABEL="${2:-}"; MANAGED_LABELS+="${PANE_LABEL} "; shift $(( $# > 1 ? 2 : 1 )) ;;
      --) shift; break ;;
      -h|--help) usage ;;
      *) break ;;
    esac
  done
  if (( GET_PANE )); then
    [[ -n "${PANE_LABEL}" ]] || { log "missing pane label"; usage; }
    return 0
  fi
  [[ $# -gt 0 ]] || { log "missing command"; usage; }
  [[ "${TIMEOUT_MS}" =~ ^[0-9]+$ ]] || { log "invalid --timeout-ms '${TIMEOUT_MS}'"; usage; }
  CMD=("$@")
}

use_herdr() {
  [[ "${HERDR_EXEC_DISABLE:-0}" != 1 ]] || return 1
  [[ "${HERDR_ENV:-}" == 1 && -n "${HERDR_PANE_ID:-}" ]] || return 1
  command -v herdr >/dev/null 2>&1 && command -v jq >/dev/null 2>&1 || return 1
  [[ " ${DISABLED_USERS} " != *" $(id -un) "* ]]
}

pane_exists() { herdr pane get "$1" >/dev/null 2>&1; }

pane_is_idle() {
  local names name
  names="$(herdr pane process-info --pane "$1" 2>/dev/null \
    | jq -r '.result.process_info.foreground_processes[]?.name' 2>/dev/null)" || return 1
  [[ -n "${names}" ]] || return 1
  while read -r name; do
    [[ "${SHELL_NAMES}" == *" ${name} "* ]] || return 1
  done <<< "${names}"
}

wait_idle() {
  local pane="$1" waited=0
  until pane_is_idle "${pane}"; do
    (( waited >= IDLE_WAIT_MS )) && return 1
    sleep "${POLL_S}"; waited=$(( waited + 100 ))
  done
}

create_pane() {
  local width dir pane
  width="$(herdr pane layout --pane "${HERDR_PANE_ID}" 2>/dev/null | jq -r --arg p "${HERDR_PANE_ID}" \
    '[.result.layout.panes[] | select(.pane_id == $p) | .rect.width][0] // (.result.layout.panes[0].rect.width // 0)')"
  dir=down; (( ${width:-0} >= WIDE_PANE_COLS )) && dir=right
  pane="$(herdr pane split --pane "${HERDR_PANE_ID}" --direction "${dir}" --cwd "${PWD}" --no-focus \
    | jq -r '.result.pane.pane_id // empty')" || return 1
  [[ -n "${pane}" ]] || return 1
  herdr pane rename "${pane}" "${PANE_LABEL}" >/dev/null 2>&1 || true
  IDLE_WAIT_MS=$(( IDLE_WAIT_MS > 5000 ? IDLE_WAIT_MS : 5000 )) wait_idle "${pane}" || true
  echo "${pane}"
}

# Print an idle pane in this workspace that carries one of MANAGED_LABELS (never the caller's pane).
# ponytail: one `pane get` per pane (the list has no labels); fine for the handful of panes in a workspace.
find_idle_pane() {
  local ws_args=() p label
  [[ -n "${HERDR_WORKSPACE_ID:-}" ]] && ws_args=(--workspace "${HERDR_WORKSPACE_ID}")
  for p in $(herdr pane list "${ws_args[@]}" 2>/dev/null | jq -r '.result.panes[]?.pane_id' 2>/dev/null); do
    [[ "${p}" == "${HERDR_PANE_ID}" ]] && continue
    label="$(herdr pane get "${p}" 2>/dev/null | jq -r '.result.pane.label // empty' 2>/dev/null)"
    [[ -n "${label}" && "${MANAGED_LABELS}" == *" ${label} "* ]] || continue
    pane_is_idle "${p}" && { echo "${p}"; return 0; }
  done
  return 1
}

# Reuse an idle managed pane (relabelled to PANE_LABEL), otherwise split a new one.
idle_or_new_pane() {
  local pane
  if pane="$(find_idle_pane)"; then
    herdr pane rename "${pane}" "${PANE_LABEL}" >/dev/null 2>&1 || true
    echo "${pane}"; return 0
  fi
  create_pane
}

shared_pane() {
  local pane_file="$1" pane=""
  [[ -f "${pane_file}" ]] && pane="$(<"${pane_file}")"
  if [[ -n "${pane}" ]] && pane_exists "${pane}" && wait_idle "${pane}"; then
    echo "${pane}"; return 0
  fi
  pane="$(idle_or_new_pane)" || return 1
  echo "${pane}" > "${pane_file}"
  echo "${pane}"
}

state_dir() { echo "${HERDR_EXEC_STATE_DIR:-${XDG_RUNTIME_DIR:-/tmp}/herdr-exec-$(id -u)}"; }
pane_file() { echo "$1/${HERDR_WORKSPACE_ID//[^A-Za-z0-9_-]/_}.pane"; }

# --get-pane: hand an idle pane to the caller (e.g. for the UART console). If it was the shared
# embedded-skills pane, forget it so later runs do not wait on whatever the caller starts in it.
get_pane() {
  local dir pane
  use_herdr || { log "not inside Herdr (or disabled for this user)"; exit 1; }
  dir="$(state_dir)"; mkdir -p -m 700 "${dir}" || exit 1
  exec 9> "${dir}/lock"
  command -v flock >/dev/null 2>&1 && flock -w $(( TIMEOUT_MS / 1000 + 1 )) 9
  pane="$(idle_or_new_pane)" || { log "could not get a Herdr pane"; exit 1; }
  [[ -f "$(pane_file "${dir}")" && "$(<"$(pane_file "${dir}")")" == "${pane}" ]] && rm -f "$(pane_file "${dir}")"
  echo "${pane}"
  exit 0
}

write_runner() {
  local run_dir="$1" var
  {
    echo "#!/usr/bin/env bash"
    printf 'cd %q || exit 1\n' "${PWD}"
    for var in "${PASS_ENV[@]}"; do
      [[ -n "${!var:-}" ]] && printf 'export %s=%q\n' "${var}" "${!var}"
    done
    echo "export PYTHONUNBUFFERED=1"
    # Nested herdr_exec.sh calls (e.g. workflow -> jlink) run inline and mirror to this pane's tty
    echo 'export HERDR_EXEC_TTY="$(tty 2>/dev/null || echo /dev/null)"'
    printf 'printf "\\n\\033[1;36m> [%%s] %%s\\033[0m\\n" %q %q\n' "${LABEL}" "${CMD[*]}"
    printf 'tail -q -n +1 -F %q %q 2>/dev/null & tail_pid=$!\n' "${run_dir}/out" "${run_dir}/err"
    printf 'start=$SECONDS\n'
    printf '%q ' "${CMD[@]}"; printf '> %q 2> %q\n' "${run_dir}/out" "${run_dir}/err"
    echo 'rc=$?'
    echo 'sleep 0.3; kill "$tail_pid" 2>/dev/null'
    printf 'printf "\\033[1;36m= [%%s] exit=%%s (%%ss)\\033[0m\\n" %q "$rc" "$((SECONDS - start))"\n' "${LABEL}"
    printf 'echo "$rc" > %q && mv %q %q\n' "${run_dir}/rc.tmp" "${run_dir}/rc.tmp" "${run_dir}/rc"
  } > "${run_dir}/runner.sh"
  : > "${run_dir}/out"; : > "${run_dir}/err"
}

wait_done() {
  local run_dir="$1" waited=0
  until [[ -f "${run_dir}/rc" ]]; do
    (( waited >= TIMEOUT_MS )) && return 1
    sleep "${POLL_S}"; waited=$(( waited + 100 ))
  done
}

# Sets FALLBACK=1 (and returns) when the command was NOT started in a pane, so the caller can
# run it directly; any other return value is the command's own exit status.
run_in_pane() {
  local state_dir pane_file pane run_dir rc
  FALLBACK=1
  state_dir="$(state_dir)"
  mkdir -p -m 700 "${state_dir}" || return 1
  pane_file="$(pane_file "${state_dir}")"

  exec 9> "${state_dir}/lock"
  command -v flock >/dev/null 2>&1 && flock -w $(( TIMEOUT_MS / 1000 + 1 )) 9

  pane="$(shared_pane "${pane_file}")" || { log "could not get a Herdr pane, running directly"; return 1; }
  run_dir="$(mktemp -d "${state_dir}/run.XXXXXX")" || return 1
  write_runner "${run_dir}"
  if ! herdr pane run "${pane}" "bash $(printf %q "${run_dir}/runner.sh")" >/dev/null; then
    log "herdr pane run failed, running directly"; return 1
  fi
  FALLBACK=0
  log "running in Herdr pane ${pane}: ${CMD[*]}"

  if ! wait_done "${run_dir}"; then
    cat "${run_dir}/out"; cat "${run_dir}/err" >&2
    log "timeout after ${TIMEOUT_MS} ms; the command is still running in Herdr pane ${pane}"
    return 124
  fi
  rc="$(<"${run_dir}/rc")"
  cat "${run_dir}/out"; cat "${run_dir}/err" >&2
  rm -rf "${run_dir}"
  return "${rc}"
}

# Already inside a herdr_exec pane: taking the lock or the shared pane again would deadlock with the
# outer call, so run inline and mirror the output to the pane's terminal so the user still sees it.
run_nested() {
  local tty="${HERDR_EXEC_TTY}" rc
  [[ -w "${tty}" ]] || exec "${CMD[@]}"
  printf '\n\033[1;35m  > [%s] %s\033[0m\n' "${LABEL}" "${CMD[*]}" >> "${tty}"
  "${CMD[@]}" > >(tee -a "${tty}") 2> >(tee -a "${tty}" >&2)
  rc=$?
  wait
  printf '\033[1;35m  = [%s] exit=%s\033[0m\n' "${LABEL}" "${rc}" >> "${tty}"
  exit "${rc}"
}

main() {
  parse_args "$@"
  (( GET_PANE )) && get_pane
  [[ -n "${HERDR_EXEC_TTY:-}" ]] && run_nested
  if use_herdr; then
    run_in_pane; local rc=$?
    (( FALLBACK )) || exit "${rc}"
  fi
  exec "${CMD[@]}"
}

main "$@"
