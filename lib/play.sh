# shellcheck shell=bash
# Dependency check shared by OCR engines. Sourced, not executed.

# need <cmd> <install hint> — fail loudly and usefully.
need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "speak: '$1' not found — $2" >&2
  command -v notify-send >/dev/null 2>&1 &&
    notify-send -a "Speak" "Provider unavailable" "$1 not installed. $2" 2>/dev/null
  exit 127
}
