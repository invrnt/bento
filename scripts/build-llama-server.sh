#!/usr/bin/env bash
# Builds llama-server (smart search embedding runtime, decision D4) from the pinned llama.cpp source for
# this machine. Bento never downloads executables at runtime: this binary ships inside the installers,
# the CLI bundle and the Docker image. Windows: scripts/build-llama-server.ps1. Procedure for a bump:
# docs/dev/smart-search.md.
#
#   scripts/build-llama-server.sh [--out DIR] [--source-tarball FILE] [--cache DIR] [--jobs N] [--force]
#   scripts/build-llama-server.sh --print-target      prints <platform>-<arch> (Node names) and exits
#   scripts/build-llama-server.sh --print-licenses    prints the bundled third-party components and exits
#
# Output (predictable per OS/arch): dist/llama-server/<platform>-<arch>/
#   llama-server                    the server, linked with an $ORIGIN / @loader_path rpath
#   lib*.so | lib*.dylib            libllama, libggml*, libmtmd and the CPU backend variants (GGML_BACKEND_DL)
#   licenses/                       llama.cpp and vendored component licenses, THIRD-PARTY.txt
#   bento-llama-server.json         pin, source digest, CMake flags, target
#   SHA256SUMS                      every file above (relative paths)
#
# The source tarball is verified against LLAMA_CPP_SOURCE_SHA256 before anything is extracted.
set -euo pipefail

LLAMA_CPP_TAG="b12777"
LLAMA_CPP_BUILD_NUMBER="12777"
LLAMA_CPP_COMMIT="caea914e9"
LLAMA_CPP_SOURCE_URL="https://github.com/ggml-org/llama.cpp/archive/refs/tags/${LLAMA_CPP_TAG}.tar.gz"
LLAMA_CPP_SOURCE_SHA256="d7f875b82ebda0b88ac5229d3deff3e53239a08030ce5aa6f7ce358fc219cd8c"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT=""
TARBALL=""
CACHE="${BENTO_LLAMA_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/bento/llama.cpp}"
JOBS=""
FORCE=0
ACTION="build"

die() { echo "build-llama-server: $*" >&2; exit 1; }
say() { echo "build-llama-server: $*" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="${2:?--out needs a directory}"; shift 2 ;;
    --source-tarball) TARBALL="${2:?--source-tarball needs a file}"; shift 2 ;;
    --cache) CACHE="${2:?--cache needs a directory}"; shift 2 ;;
    --jobs) JOBS="${2:?--jobs needs a number}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --print-target) ACTION="target"; shift ;;
    --print-licenses) ACTION="licenses"; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

# Node's platform/arch names, so Electron (process.platform-process.arch) finds the same folder.
host_target() {
  local os machine
  os="$(uname -s)"
  machine="$(uname -m)"
  case "$os" in
    Linux) os="linux" ;;
    Darwin) os="darwin" ;;
    MINGW*|MSYS*|CYGWIN*) die "use scripts/build-llama-server.ps1 on Windows" ;;
    *) die "unsupported OS: $os" ;;
  esac
  case "$machine" in
    x86_64|amd64) machine="x64" ;;
    aarch64|arm64) machine="arm64" ;;
    *) die "unsupported architecture: $machine" ;;
  esac
  echo "${os}-${machine}"
}

# Components compiled into llama-server at this tag: `component | license | text`. The third-party notices
# and apps/desktop/scripts/generate-sbom.mjs read this list; keep the `|` format.
print_licenses() {
  cat <<'EOF'
llama.cpp (ggml-org) | MIT | licenses/LICENSE-llama.cpp
cpp-httplib (yhirose) | MIT | licenses/LICENSE-cpp-httplib
nlohmann/json (Niels Lohmann) | MIT | licenses/LICENSE-nlohmann-json
xxHash (Yann Collet) | BSD-2-Clause | licenses/LICENSE-xxhash
rotate-bits (William Casarin) | MIT | licenses/LICENSE-rotate-bits
sha256 (Igor Pavlov) and sha1 (Steve Reid) | public domain | licenses/LICENSE-sha256
miniaudio (David Reid) | public domain or MIT-0 | in miniaudio.h
stb_image (Sean Barrett) | public domain or MIT | in stb_image.h
subprocess.h (sheredom) | Unlicense | in subprocess.h
EOF
}

TARGET="$(host_target)"
case "$ACTION" in
  target) echo "$TARGET"; exit 0 ;;
  licenses) print_licenses; exit 0 ;;
esac

OUT="${OUT:-$ROOT/dist/llama-server/$TARGET}"
JOBS="${JOBS:-$( (command -v nproc >/dev/null && nproc) || sysctl -n hw.logicalcpu 2>/dev/null || echo 2)}"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else die "sha256sum or shasum is required"
  fi
}

# CMake flags per target (program doc §Distribution). OpenMP stays off so no libgomp/vcomp must ship;
# OpenSSL, the web UI and llama-connect are off because Bento runs the server --offline on loopback.
CMAKE_ARGS=(
  -DCMAKE_BUILD_TYPE=Release
  -DBUILD_SHARED_LIBS=ON
  -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON
  -DCMAKE_PLATFORM_NO_VERSIONED_SONAME=ON
  -DLLAMA_BUILD_NUMBER="$LLAMA_CPP_BUILD_NUMBER"
  -DLLAMA_BUILD_COMMIT="$LLAMA_CPP_COMMIT"
  -DLLAMA_BUILD_TESTS=OFF
  -DLLAMA_BUILD_EXAMPLES=OFF
  -DLLAMA_BUILD_TOOLS=ON
  -DLLAMA_BUILD_SERVER=ON
  -DLLAMA_BUILD_UI=OFF
  -DLLAMA_USE_PREBUILT_UI=OFF
  -DLLAMA_CONNECT=OFF
  -DLLAMA_OPENSSL=OFF
  -DGGML_OPENMP=OFF
  -DGGML_NATIVE=OFF
)
case "$TARGET" in
  linux-x64|linux-arm64)
    CMAKE_ARGS+=(-DCMAKE_INSTALL_RPATH='$ORIGIN' -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON)
    ;;
  darwin-arm64)
    CMAKE_ARGS+=(-DCMAKE_INSTALL_RPATH='@loader_path' -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON -DGGML_ACCELERATE=ON -DCMAKE_OSX_DEPLOYMENT_TARGET=13.3)
    ;;
  darwin-x64)
    # Matches the official macOS x64 release (no Metal); GGML_NATIVE=OFF keeps it off the runner's ISA.
    CMAKE_ARGS+=(-DCMAKE_INSTALL_RPATH='@loader_path' -DGGML_METAL=OFF -DCMAKE_OSX_DEPLOYMENT_TARGET=13.3)
    ;;
  *) die "no build recipe for $TARGET" ;;
esac
if [ -n "${BENTO_LLAMA_EXTRA_CMAKE_ARGS:-}" ]; then
  # shellcheck disable=SC2206 # intentional word splitting of extra flags
  CMAKE_ARGS+=(${BENTO_LLAMA_EXTRA_CMAKE_ARGS})
fi

FINGERPRINT="$(printf '%s\n' "$LLAMA_CPP_TAG" "$LLAMA_CPP_SOURCE_SHA256" "$TARGET" "${CMAKE_ARGS[@]}" | \
  { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi; } | awk '{print $1}')"

up_to_date() {
  [ -f "$OUT/bento-llama-server.json" ] && [ -x "$OUT/llama-server" ] && [ -f "$OUT/SHA256SUMS" ] || return 1
  grep -q "\"fingerprint\": \"$FINGERPRINT\"" "$OUT/bento-llama-server.json" || return 1
  (cd "$OUT" && while read -r digest name; do
    [ -f "$name" ] && [ "$(sha256_of "$name")" = "$digest" ] || exit 1
  done < SHA256SUMS) || return 1
}

if [ "$FORCE" -eq 0 ] && up_to_date; then
  say "$OUT is up to date (llama.cpp $LLAMA_CPP_TAG, $TARGET)"
  echo "$OUT"
  exit 0
fi

command -v cmake >/dev/null 2>&1 || die "cmake is required (3.21 or later)"

# ---------------------------------------------------------------------------------------- source

mkdir -p "$CACHE"
if [ -z "$TARBALL" ]; then
  TARBALL="$CACHE/llama.cpp-$LLAMA_CPP_TAG.tar.gz"
  if [ ! -f "$TARBALL" ] || [ "$(sha256_of "$TARBALL")" != "$LLAMA_CPP_SOURCE_SHA256" ]; then
    say "downloading $LLAMA_CPP_SOURCE_URL"
    rm -f "$TARBALL.part"
    if command -v curl >/dev/null 2>&1; then
      curl -fL --retry 3 --proto '=https' --tlsv1.2 -o "$TARBALL.part" "$LLAMA_CPP_SOURCE_URL"
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O "$TARBALL.part" "$LLAMA_CPP_SOURCE_URL"
    else
      die "curl or wget is required to download the llama.cpp source (or pass --source-tarball)"
    fi
    mv "$TARBALL.part" "$TARBALL"
  fi
fi
[ -f "$TARBALL" ] || die "source tarball not found: $TARBALL"
ACTUAL="$(sha256_of "$TARBALL")"
if [ "$ACTUAL" != "$LLAMA_CPP_SOURCE_SHA256" ]; then
  case "$TARBALL" in "$CACHE"/*) rm -f "$TARBALL" ;; esac
  die "source digest mismatch for $TARBALL: expected $LLAMA_CPP_SOURCE_SHA256, got $ACTUAL"
fi
say "source verified: sha256 $ACTUAL"

WORK="$CACHE/$LLAMA_CPP_TAG-$TARGET"
SRC="$WORK/src"
BUILD="$WORK/build"
rm -rf "$SRC"
mkdir -p "$SRC" "$BUILD"
tar -xzf "$TARBALL" -C "$SRC" --strip-components=1
[ -f "$SRC/CMakeLists.txt" ] || die "unexpected source layout in $TARBALL"

# ---------------------------------------------------------------------------------------- build

say "configuring llama.cpp $LLAMA_CPP_TAG for $TARGET"
cmake -S "$SRC" -B "$BUILD" "${CMAKE_ARGS[@]}"
cmake --build "$BUILD" --config Release --target llama-server -j "$JOBS"
BIN="$BUILD/bin"
[ -x "$BIN/llama-server" ] || die "the build did not produce $BIN/llama-server"

# ---------------------------------------------------------------------------------------- stage

rm -rf "$OUT"
mkdir -p "$OUT/licenses"
cp -L "$BIN/llama-server" "$OUT/llama-server"
find "$BIN" -maxdepth 1 \( -type f -o -type l \) \( -name '*.so' -o -name '*.so.*' -o -name '*.dylib' \) -print0 |
  while IFS= read -r -d '' library; do cp -L "$library" "$OUT/$(basename "$library")"; done
chmod 0755 "$OUT/llama-server"

copy_license() {
  if [ -f "$SRC/$1" ]; then cp "$SRC/$1" "$OUT/licenses/$2"; else say "warning: license file $1 not found at $LLAMA_CPP_TAG"; fi
}
copy_license LICENSE LICENSE-llama.cpp
copy_license vendor/cpp-httplib/LICENSE LICENSE-cpp-httplib
copy_license licenses/LICENSE-jsonhpp LICENSE-nlohmann-json
copy_license vendor/hash/xxhash/LICENSE LICENSE-xxhash
copy_license vendor/hash/rotate-bits/LICENSE.md LICENSE-rotate-bits
copy_license vendor/hash/sha256/LICENSE LICENSE-sha256
print_licenses > "$OUT/licenses/THIRD-PARTY.txt"

json_args=""
for argument in "${CMAKE_ARGS[@]}"; do
  json_args="${json_args:+$json_args, }\"${argument//\"/\\\"}\""
done
cat > "$OUT/bento-llama-server.json" <<EOF
{
  "schema_version": 1,
  "name": "llama-server",
  "tag": "$LLAMA_CPP_TAG",
  "build_number": $LLAMA_CPP_BUILD_NUMBER,
  "commit": "$LLAMA_CPP_COMMIT",
  "source_url": "$LLAMA_CPP_SOURCE_URL",
  "source_sha256": "$LLAMA_CPP_SOURCE_SHA256",
  "license": "MIT",
  "target": "$TARGET",
  "executable": "llama-server",
  "cmake_args": [$json_args],
  "fingerprint": "$FINGERPRINT"
}
EOF

(cd "$OUT" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort | while IFS= read -r name; do
  printf '%s  %s\n' "$(sha256_of "$name")" "$name"
done > SHA256SUMS)

"$OUT/llama-server" --version >/dev/null 2>&1 || die "$OUT/llama-server --version failed"
say "built llama-server $LLAMA_CPP_TAG for $TARGET:"
print_licenses >&2
echo "$OUT"
