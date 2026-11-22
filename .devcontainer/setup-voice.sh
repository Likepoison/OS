#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
model=vosk-model-small-cn-0.22
cache=.tracetutor/voice
checksum=3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba

python -m pip --disable-pip-version-check install --user --no-warn-script-location vosk==0.3.45
if [[ ! -f "$cache/$model/am/final.mdl" ]]; then
  mkdir -p "$cache"
  staging=$(mktemp -d "$cache/.download.XXXXXX")
  trap 'rm -rf -- "$staging"' EXIT
  archive="$staging/model.zip"
  curl --fail --silent --show-error --connect-timeout 10 --max-time 150 --retry 2 \
    "https://alphacephei.com/vosk/models/$model.zip" --output "$archive"
  printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check -
  python -m zipfile -e "$archive" "$staging"
  mv -T "$staging/$model" "$cache/$model"
fi
printf '%s\n' 'TraceTutor Mandarin speech recognition is ready.'
