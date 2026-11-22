#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
model=sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09
cache=.tracetutor/voice
checksum=7305f7905bfcf77fa0b39388a313f3da35c68d971661a65475b56fb2162c8e63
speech_model=vits-piper-zh_CN-xiao_ya-medium
speech_checksum=9396a3dffbb95b037acaa18094500f58d0db9a7c4f2689554e2539717cf0db65

mkdir -p "$cache"
python -m pip --disable-pip-version-check install --no-warn-script-location --target "$cache/python" --upgrade \
  sherpa-onnx==2.0.2 lameenc==1.9.0 imageio-ffmpeg==0.6.0
if [[ ! -f "$cache/$model/model.int8.onnx" || ! -f "$cache/$model/tokens.txt" ]]; then
  staging=$(mktemp -d "$cache/.download.XXXXXX")
  trap 'rm -rf -- "$staging"' EXIT
  archive="$staging/model.tar.bz2"
  curl --fail --silent --show-error --connect-timeout 10 --max-time 180 --retry 1 \
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$model.tar.bz2" --output "$archive"
  printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check -
  tar -xjf "$archive" -C "$staging" "$model/model.int8.onnx" "$model/tokens.txt"
  mkdir -p "$cache/$model"
  mv -- "$staging/$model/model.int8.onnx" "$staging/$model/tokens.txt" "$cache/$model/"
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
