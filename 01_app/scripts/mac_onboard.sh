#!/bin/bash
# Bootstrap only project-local uv/Python; no Homebrew, sudo or shell-profile edits.
set -eu
DISCLOSURE_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$DISCLOSURE_ROOT"
if [ "$(uname -s)" != Darwin ]; then echo '此入口仅支持 macOS。'; exit 2; fi
if ! /usr/bin/sw_vers -productVersion | awk -F. '{exit !($1>13 || ($1==13 && $2>=5))}'; then
  echo '本运行包要求 macOS 13.5 或更新版本。'; exit 2
fi
case "$(uname -m)" in
  arm64) DISCLOSURE_PLATFORM=macos-arm64 ;;
  x86_64) DISCLOSURE_PLATFORM=macos-x64 ;;
  *) echo '当前 Mac 架构不受支持。'; exit 2 ;;
esac
DISCLOSURE_LOCK="$DISCLOSURE_ROOT/runtime/portable-runtime.lock.tsv"
DISCLOSURE_URL="$(awk -F '\t' -v k="uv-$DISCLOSURE_PLATFORM" '$1==k{print $3}' "$DISCLOSURE_LOCK")"
DISCLOSURE_SHA="$(awk -F '\t' -v k="uv-$DISCLOSURE_PLATFORM" '$1==k{print $4}' "$DISCLOSURE_LOCK")"
if [ -z "$DISCLOSURE_URL" ] || [ "${#DISCLOSURE_SHA}" != 64 ]; then echo 'uv 版本锁不完整。'; exit 2; fi
DISCLOSURE_BASE="$DISCLOSURE_ROOT/runtime/portable/$DISCLOSURE_PLATFORM"
DISCLOSURE_UV="$DISCLOSURE_BASE/uv/uv"
mkdir -p "$DISCLOSURE_BASE/downloads"
if [ ! -x "$DISCLOSURE_UV" ]; then
  DISCLOSURE_ARCHIVE="$DISCLOSURE_BASE/downloads/${DISCLOSURE_URL##*/}"
  if [ ! -f "$DISCLOSURE_ARCHIVE" ]; then
    DISCLOSURE_PART="$(mktemp "$DISCLOSURE_BASE/downloads/uv-download.XXXXXX")"
    curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --output "$DISCLOSURE_PART" "$DISCLOSURE_URL"
    if [ "$(shasum -a 256 "$DISCLOSURE_PART" | cut -d ' ' -f 1)" != "$DISCLOSURE_SHA" ]; then echo 'uv 下载校验失败，未执行。'; exit 2; fi
    mv "$DISCLOSURE_PART" "$DISCLOSURE_ARCHIVE"
  fi
  if [ "$(shasum -a 256 "$DISCLOSURE_ARCHIVE" | cut -d ' ' -f 1)" != "$DISCLOSURE_SHA" ]; then echo 'uv 原件校验失败，已保留文件。'; exit 2; fi
  DISCLOSURE_STAGE="$(mktemp -d "$DISCLOSURE_BASE/uv-stage.XXXXXX")"
  tar -xzf "$DISCLOSURE_ARCHIVE" -C "$DISCLOSURE_STAGE" --strip-components=1
  if [ -e "$DISCLOSURE_BASE/uv" ]; then echo 'uv 目录不完整，请保留现场并联系维护者。'; exit 2; fi
  mv "$DISCLOSURE_STAGE" "$DISCLOSURE_BASE/uv"
fi
if [ "$(basename "$DISCLOSURE_ROOT")" = 01_app ]; then
  DISCLOSURE_LOCAL="$(dirname "$DISCLOSURE_ROOT")/03_local"
else
  DISCLOSURE_LOCAL="$DISCLOSURE_ROOT"
fi
export UV_CACHE_DIR="$DISCLOSURE_LOCAL/cache/portable/$DISCLOSURE_PLATFORM/uv-cache"
export UV_PYTHON_INSTALL_DIR="$DISCLOSURE_BASE/python"
export UV_PYTHON_INSTALL_BIN=0
export UV_NO_MODIFY_PATH=1
"$DISCLOSURE_UV" --no-config python install 3.13.12
DISCLOSURE_PYTHON="$("$DISCLOSURE_UV" --no-config python find --managed-python --system 3.13.12)"
exec "$DISCLOSURE_PYTHON" -X utf8 "$DISCLOSURE_ROOT/scripts/portable_runtime.py" --uv "$DISCLOSURE_UV" "$@"
