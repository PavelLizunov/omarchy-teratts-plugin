# shellcheck shell=bash
# Configuration helpers shared by the CLI tools.  All writers go through an
# atomic replace so the QML panel can never observe half-written JSON.

tts_config_file() {
  # Atomic replacement of a symlink path severs dotfile-manager links. Resolve
  # an existing link and replace its target instead; ordinary paths are left
  # untouched. A dangling link is unsafe to guess at and is rejected.
  if [[ -L "$CONFIG" ]]; then
    [[ -e "$CONFIG" && -f "$CONFIG" ]] || return 1
    local target
    target="$(readlink -f -- "$CONFIG")" || return 1
    [[ -n "$target" && -f "$target" ]] || return 1
    printf '%s' "$target"
  else
    [[ ! -e "$CONFIG" || -f "$CONFIG" ]] || return 1
    printf '%s' "$CONFIG"
  fi
}

tts_with_config_lock() { # function [args...]
  local lock_fd rc config_file
  config_file="$(tts_config_file)" || return 1
  [[ -n "$config_file" ]] || return 1
  mkdir -p "$(dirname "$config_file")"
  exec {lock_fd}>>"${config_file}.lock" || return 1
  flock "$lock_fd" || { exec {lock_fd}>&-; return 1; }
  "$@"; rc=$?
  flock -u "$lock_fd"
  exec {lock_fd}>&-
  return "$rc"
}

tts_config_init() {
  tts_with_config_lock tts_config_init_unlocked
}

tts_config_init_unlocked() {
  local config_file invalid tmp
  config_file="$(tts_config_file)" || return 1
  [[ -n "$config_file" ]] || return 1

  if [[ -e "$config_file" ]] &&
      { [[ "$(stat -c%s "$config_file" 2>/dev/null || printf 1048577)" -gt 1048576 ]] ||
        ! jq -e 'type == "object"' "$config_file" >/dev/null 2>&1; }; then
    invalid="${config_file}.invalid.$(date +%Y%m%dT%H%M%S).$$"
    mv -T -- "$config_file" "$invalid" || return 1
    chmod 600 "$invalid" || return 1
    printf 'speak: preserved invalid configuration as %s\n' "$invalid" >&2
  fi
  if [[ ! -s "$config_file" ]]; then
    tmp="$(mktemp "${config_file}.XXXXXX")" || return 1
    if ! cat >"$tmp" <<'JSON'
{
  "schemaVersion": 4,
  "provider": "teratts",
  "teratts": { "voice": "ru_f1", "endpoint": "" },
  "rate": 1.0,
  "maxChars": 0,
  "ocr": { "engine": "tesseract", "langs": "eng", "minConfidence": 60 },
  "sanitizer": {
    "urls": "domain",
    "inlineCode": true,
    "announceCodeBlocks": true,
    "stripMarkdown": true,
    "expandUnits": true
  },
  "ui": {
    "lastTab": 0,
    "exportFormat": "mp3",
    "sampleText": "Highlight any text and press the key. This is how it sounds right now."
  }
}
JSON
    then
      rm -f "$tmp"
      return 1
    fi
    if ! chmod 600 "$tmp" || ! mv -T -- "$tmp" "$config_file"; then
      rm -f "$tmp"
      return 1
    fi
  fi

  # Preserve syntactically valid but structurally unsafe input before repairing
  # it. This includes the nested scalar/array shapes that used to make every
  # command, including --stop, fail during migration.
  if ! jq -e '
      type == "object"
      and ([.teratts,.ocr,.sanitizer,.ui]
           | all(. == null or type == "object"))
      and (.ocr == null or (.ocr.tesseract == null or (.ocr.tesseract|type) == "object"))
      and (.ocr == null or (.ocr.easyocr == null or (.ocr.easyocr|type) == "object"))
      and (.ocr == null or (.ocr.openai == null or (.ocr.openai|type) == "object"))
      and (.ocr == null or (.ocr.remote == null or (.ocr.remote|type) == "object"))
      and (.ocr == null or (.ocr.engine|type) != "string"
           or .ocr[.ocr.engine] == null or (.ocr[.ocr.engine]|type) == "object")
    ' "$config_file" >/dev/null 2>&1; then
    invalid="${config_file}.invalid.$(date +%Y%m%dT%H%M%S).$$"
    cp -- "$config_file" "$invalid" || return 1
    chmod 600 "$invalid" || return 1
    printf 'speak: preserved structurally invalid configuration as %s\n' "$invalid" >&2
  fi

  # Additive, type-safe migration. Valid user values win; malformed leaves are
  # normalized individually instead of taking the entire control plane down.
  tmp="$(mktemp "${config_file}.XXXXXX")" || return 1
  if jq '
    .schemaVersion = 4
    | .provider = "teratts"
    | .teratts = (if (.teratts|type) == "object" then .teratts else {} end)
    | .teratts.voice = (if (.teratts.voice|type) == "string" and (.teratts.voice|test("^(ru_(f1|f2|m1|m5)|eng_(f3|f4_whisper|f5|m2_whisper|m3|m4))$")) then .teratts.voice else "ru_f1" end)
    | .teratts.endpoint = (if (.teratts.endpoint|type) == "string" and (.teratts.endpoint|test("^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$|^http://(127[.]0[.]0[.]1|localhost|\\[::1\\])(:[0-9]{1,5})?$")) then .teratts.endpoint else "" end)
    | .ocr = (if (.ocr|type) == "object" then .ocr else {} end)
    | .sanitizer = (if (.sanitizer|type) == "object" then .sanitizer else {} end)
    | .ui = (if (.ui|type) == "object" then .ui else {} end)
    | .ocr.engine = (if (.ocr.engine|type) == "string" and (.ocr.engine|test("^[A-Za-z0-9._-]+$")) then .ocr.engine else "tesseract" end)
    | .ocr.engine as $ocrEngine
    | .ocr[$ocrEngine] = (if (.ocr[$ocrEngine]|type) == "object" then .ocr[$ocrEngine] else {} end)
    | .ocr.langs = (if (.ocr.langs|type) == "string" and (.ocr.langs|test("^[A-Za-z0-9_+.-]+$")) then .ocr.langs else "eng" end)
    | .ocr.tesseract = (if (.ocr.tesseract|type) == "object" then .ocr.tesseract else {} end)
    | .ocr.tesseract.langs = (if (.ocr.tesseract.langs|type) == "string" and (.ocr.tesseract.langs|test("^[A-Za-z0-9_+.-]+$")) then .ocr.tesseract.langs else .ocr.langs end)
    | .ocr.easyocr = (if (.ocr.easyocr|type) == "object" then .ocr.easyocr else {} end)
    | .ocr.easyocr.langs = (if (.ocr.easyocr.langs|type) == "string" and (.ocr.easyocr.langs|test("^[A-Za-z0-9_+.-]+$")) then .ocr.easyocr.langs else "eng" end)
    | .ocr.openai = (if (.ocr.openai|type) == "object" then .ocr.openai else {} end)
    | .ocr.openai.model = (if (.ocr.openai.model|type) == "string" and (.ocr.openai.model|test("^[A-Za-z0-9._-]+$")) then .ocr.openai.model else "gpt-4.1-mini" end)
    | .ocr.remote = (if (.ocr.remote|type) == "object" then .ocr.remote else {} end)
    | .ocr.remote.endpoint = (if (.ocr.remote.endpoint|type) == "string" and
        (.ocr.remote.endpoint == "" or
         (.ocr.remote.endpoint|test("^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$|^http://(127[.]0[.]0[.]1|localhost|\\[::1\\])(:[0-9]{1,5})?$")))
        then .ocr.remote.endpoint else "" end)
    | del(.ocr.remote.model)
    | .sanitizer.urls = (if .sanitizer.urls == "link" then "link" else "domain" end)
    | .sanitizer.inlineCode = (if (.sanitizer.inlineCode|type) == "boolean" then .sanitizer.inlineCode else true end)
    | .sanitizer.announceCodeBlocks = (if (.sanitizer.announceCodeBlocks|type) == "boolean" then .sanitizer.announceCodeBlocks else true end)
    | .sanitizer.stripMarkdown = (if (.sanitizer.stripMarkdown|type) == "boolean" then .sanitizer.stripMarkdown else true end)
    | .sanitizer.expandUnits = (if (.sanitizer.expandUnits|type) == "boolean" then .sanitizer.expandUnits else true end)
    | .ui.sampleText = (if (.ui.sampleText|type) == "string" then .ui.sampleText[0:4096] else "Highlight any text and press the key. This is how it sounds right now." end)
    | .ui.exportFormat = (if (.ui.exportFormat == "mp3" or .ui.exportFormat == "ogg" or .ui.exportFormat == "wav") then .ui.exportFormat else "mp3" end)
    | .rate = (if (.rate|type)=="number" and .rate>=0.25 and .rate<=4 then .rate else 1.0 end)
    | .maxChars = (if (.maxChars|type)=="number" and .maxChars>=0 and .maxChars<=1048576 then (.maxChars|floor) else 0 end)
    | .ocr.minConfidence = (if (.ocr.minConfidence|type)=="number" and .ocr.minConfidence>=0 and .ocr.minConfidence<=100 then (.ocr.minConfidence|floor) else 60 end)
    | .ui.lastTab = (if (.ui.lastTab|type)=="number" and .ui.lastTab>=0 and .ui.lastTab<=5 then (.ui.lastTab|floor) else 0 end)
  ' "$config_file" >"$tmp"; then
    chmod 600 "$tmp" || { rm -f "$tmp"; return 1; }
    if cmp -s -- "$tmp" "$config_file"; then
      rm -f "$tmp"
    else
      mv -T -- "$tmp" "$config_file" || { rm -f "$tmp"; return 1; }
    fi
    chmod 600 "$config_file" || return 1
    return 0
  fi
  rm -f "$tmp"
  return 1
}

tts_config_set() { # jq path, JSON-or-string value
  tts_with_config_lock tts_config_set_unlocked "$@"
}

tts_config_set_unlocked() { # jq path, JSON-or-string value
  local path="$1" value="$2" tmp engine="" config_file
  config_file="$(tts_config_file)" || return 1
  [[ -n "$config_file" ]] || return 1
  if [[ "$path" =~ ^\.ocr\.([A-Za-z0-9._-]+)\.langs$ ]]; then
    engine="${BASH_REMATCH[1]}"
  fi
  case "$path" in
    .provider|.rate|.maxChars|.teratts.voice|.teratts.endpoint|\
    .ocr.engine|.ocr.langs|.ocr.tesseract.langs|.ocr.easyocr.langs|.ocr.openai.model|.ocr.remote.endpoint|.ocr.minConfidence|\
    .sanitizer.urls|.sanitizer.inlineCode|.sanitizer.announceCodeBlocks|\
    .sanitizer.stripMarkdown|.sanitizer.expandUnits|.ui.lastTab|.ui.sampleText|.ui.exportFormat) ;;
    *) [[ -n "$engine" ]] || return 2 ;;
  esac
  case "$path" in
    .provider) [[ "$value" == teratts ]] || return 3 ;;
    .teratts.voice) [[ "$value" =~ ^(ru_(f1|f2|m1|m5)|eng_(f3|f4_whisper|f5|m2_whisper|m3|m4))$ ]] || return 3 ;;
    .teratts.endpoint)
      [[ "$value" =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ || "$value" =~ ^http://(127[.]0[.]0[.]1|localhost|\[::1\])(:[0-9]{1,5})?$ ]] || return 3 ;;
    .ocr.remote.endpoint)
      [[ -z "$value" || "$value" =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ || "$value" =~ ^http://(127[.]0[.]0[.]1|localhost|\[::1\])(:[0-9]{1,5})?$ ]] || return 3 ;;
    .rate)
      [[ "$value" =~ ^(0?[.][0-9]+|[1-3]([.][0-9]+)?|4([.]0+)?)$ ]] || return 3
      awk -v value="$value" 'BEGIN { exit !(value >= 0.25 && value <= 4.0) }' || return 3 ;;
    .maxChars)
      [[ "$value" =~ ^[0-9]+$ && ${#value} -le 7 ]] || return 3
      awk -v value="$value" 'BEGIN { exit !(value <= 1048576) }' || return 3 ;;
    .ocr.minConfidence)
      [[ "$value" =~ ^[0-9]+$ ]] &&
        awk -v value="$value" 'BEGIN { exit !(value <= 100) }' || return 3 ;;
    .ocr.engine) [[ "$value" =~ ^[A-Za-z0-9._-]+$ ]] || return 3 ;;
    .ocr.openai.model) [[ "$value" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || return 3 ;;
    .ocr.langs|*.langs) [[ "$value" =~ ^[A-Za-z0-9_+.-]+$ ]] || return 3 ;;
    .sanitizer.urls) [[ "$value" == domain || "$value" == link ]] || return 3 ;;
    .sanitizer.inlineCode|.sanitizer.announceCodeBlocks|.sanitizer.stripMarkdown|.sanitizer.expandUnits)
      [[ "$value" == true || "$value" == false ]] || return 3 ;;
    .ui.lastTab) [[ "$value" =~ ^[0-5]$ ]] || return 3 ;;
    .ui.sampleText) [[ ${#value} -le 4096 ]] || return 3 ;;
    .ui.exportFormat) [[ "$value" == mp3 || "$value" == ogg || "$value" == wav ]] || return 3 ;;
  esac
  tmp="$(mktemp "${config_file}.XXXXXX")" || return 1
  if [[ -n "$engine" ]]; then
    jq --arg engine "$engine" --arg value "$value" \
      '.ocr[$engine] = (if (.ocr[$engine]|type) == "object" then .ocr[$engine] else {} end)
       | .ocr[$engine].langs = $value' "$config_file" >"$tmp"
  elif [[ "$path" == .rate || "$path" == .maxChars || "$path" == .ocr.minConfidence ||
          "$path" == .ui.lastTab || "$path" == .sanitizer.inlineCode ||
          "$path" == .sanitizer.announceCodeBlocks || "$path" == .sanitizer.stripMarkdown ||
          "$path" == .sanitizer.expandUnits ]]; then
    jq --argjson value "$value" "$path = \$value" "$config_file" >"$tmp"
  else
    jq --arg value "$value" "$path = \$value" "$config_file" >"$tmp"
  fi
  [[ -s "$tmp" ]] || { rm -f "$tmp"; return 1; }
  chmod 600 "$tmp" || { rm -f "$tmp"; return 1; }
  if cmp -s -- "$tmp" "$config_file"; then
    rm -f "$tmp"
  else
    mv -T -- "$tmp" "$config_file" || { rm -f "$tmp"; return 1; }
  fi
}
