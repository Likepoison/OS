#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
model=vosk-model-small-cn-0.22
cache=.tracetutor/voice
checksum=3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba
speech_model=vits-piper-zh_CN-xiao_ya-medium
speech_checksum=9396a3dffbb95b037acaa18094500f58d0db9a7c4f2689554e2539717cf0db65

mkdir -p "$cache"
python -m pip --disable-pip-version-check install --no-warn-script-location --target "$cache/python" --upgrade \
  vosk==0.3.45 sherpa-onnx==2.0.2 lameenc==1.9.0 imageio-ffmpeg==0.6.0
if [[ ! -f "$cache/$model/am/final.mdl" ]]; then
  staging=$(mktemp -d "$cache/.download.XXXXXX")
  trap 'rm -rf -- "$staging"' EXIT
  archive="$staging/model.zip"
  curl --fail --silent --show-error --connect-timeout 10 --max-time 150 --retry 2 \
    "https://alphacephei.com/vosk/models/$model.zip" --output "$archive"
  printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check -
  python -m zipfile -e "$archive" "$staging"
  mv -T "$staging/$model" "$cache/$model"
  rm -rf -- "$staging"
  trap - EXIT
fi
if [[ ! -f "$cache/$speech_model/zh_CN-xiao_ya-medium.onnx" ]]; then
  staging=$(mktemp -d "$cache/.download.XXXXXX")
  trap 'rm -rf -- "$staging"' EXIT
  archive="$staging/model.tar.bz2"
  curl --fail --silent --show-error --connect-timeout 10 --max-time 180 --retry 1 \
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/$speech_model.tar.bz2" --output "$archive"
  printf '%s  %s\n' "$speech_checksum" "$archive" | sha256sum --check -
  tar -xjf "$archive" -C "$staging"
  mv -T "$staging/$speech_model" "$cache/$speech_model"
fi
printf '%s\n' 'TraceTutor Mandarin recognition and character voice are ready.'
