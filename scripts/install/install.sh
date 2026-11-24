#!/bin/sh
# Installs the standalone `bento` CLI for the current user (Linux, macOS).
#
#   curl -fsSL https://raw.githubusercontent.com/invrnt/bento/main/scripts/install/install.sh | sh
#
# Environment:
#   BENTO_CLI_VERSION   version to install (e.g. 0.1.0); default: the newest `cli-v*` release
#   BENTO_CLI_BASE_URL  where the release assets live; default:
#                       https://github.com/invrnt/bento/releases/download/cli-v<version>
#                       (a custom base must serve the archives, SHA256SUMS and, without
#                       BENTO_CLI_VERSION, a VERSION file)
#   BENTO_INSTALL_DIR   default: ${XDG_DATA_HOME:-$HOME/.local/share}/bento-cli
#   BENTO_BIN_DIR       default: $HOME/.local/bin
#
# Nothing runs with sudo. The archive's SHA-256 is verified before anything is installed.
set -eu

REPOSITORY="invrnt/bento"

say() { printf '%s\n' "$*"; }
fail() { printf 'bento install: %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"; }

fetch() {
  # fetch URL DESTINATION
  if command -v curl >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -fsSL --retry 3 -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$2" "$1"
  else
    fail "curl or wget is required"
  fi
}

allow_insecure_base() {
  # A custom base may be a local http:// mirror (tests); curl's --proto would refuse it.
  case "$1" in
    http://127.0.0.1*|http://localhost*|file://*) return 0 ;;
    *) return 1 ;;
  esac
}

fetch_from_base() {
  if allow_insecure_base "$BASE_URL" && command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$2" "$1"
  else
    fetch "$1" "$2"
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$1" | awk '{print $NF}'
  else
    fail "sha256sum, shasum or openssl is required to verify the download"
  fi
}

detect_os() {
  case "$(uname -s)" in
    Linux) printf 'linux' ;;
    Darwin) printf 'macos' ;;
    *) fail "unsupported system $(uname -s); on Windows use scripts/install/install.ps1" ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64) printf 'x64' ;;
    aarch64|arm64) printf 'arm64' ;;
    *) fail "unsupported processor $(uname -m) (supported: x86_64, arm64)" ;;
  esac
}

latest_version() {
  api_file="$WORK/releases.json"
  fetch "https://api.github.com/repos/$REPOSITORY/releases?per_page=50" "$api_file" \
    || fail "could not list releases; set BENTO_CLI_VERSION"
  version="$(grep -o '"tag_name": *"cli-v[^"]*"' "$api_file" | head -n 1 | sed 's/.*"cli-v\([^"]*\)"/\1/')"
  [ -n "$version" ] || fail "no CLI release found; set BENTO_CLI_VERSION"
  printf '%s' "$version"
}

need uname
need tar
need awk
need sed
need grep
need mktemp

OS="$(detect_os)"
ARCH="$(detect_arch)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/bento-install.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM

VERSION="${BENTO_CLI_VERSION:-}"
BASE_URL="${BENTO_CLI_BASE_URL:-}"
if [ -n "$BASE_URL" ]; then
  BASE_URL="${BASE_URL%/}"
  if [ -z "$VERSION" ]; then
    fetch_from_base "$BASE_URL/VERSION" "$WORK/VERSION" || fail "could not read $BASE_URL/VERSION; set BENTO_CLI_VERSION"
    VERSION="$(tr -d ' \r\n' < "$WORK/VERSION")"
  fi
else
  [ -n "$VERSION" ] || VERSION="$(latest_version)"
  BASE_URL="https://github.com/$REPOSITORY/releases/download/cli-v$VERSION"
fi
VERSION="${VERSION#v}"
case "$VERSION" in
  ''|*[!0-9A-Za-z.+-]*) fail "invalid version '$VERSION'" ;;
esac

ASSET="bento-cli-$VERSION-$OS-$ARCH.tar.gz"
say "Downloading Bento CLI $VERSION ($OS-$ARCH)..."
fetch_from_base "$BASE_URL/$ASSET" "$WORK/$ASSET" || fail "download failed: $BASE_URL/$ASSET"
fetch_from_base "$BASE_URL/SHA256SUMS" "$WORK/SHA256SUMS" || fail "checksum list download failed: $BASE_URL/SHA256SUMS"

EXPECTED="$(awk -v name="$ASSET" '$2 == name || $2 == "*" name { print $1; exit }' "$WORK/SHA256SUMS")"
[ -n "$EXPECTED" ] || fail "$ASSET is not listed in SHA256SUMS"
ACTUAL="$(sha256_of "$WORK/$ASSET")"
[ "$EXPECTED" = "$ACTUAL" ] || fail "checksum mismatch for $ASSET; nothing was installed"

mkdir -p "$WORK/extract"
tar -xzf "$WORK/$ASSET" -C "$WORK/extract"
[ -x "$WORK/extract/bento/bento" ] || fail "unexpected archive layout (bento/bento missing)"

INSTALL_DIR="${BENTO_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/bento-cli}"
BIN_DIR="${BENTO_BIN_DIR:-$HOME/.local/bin}"
APP_DIR="$INSTALL_DIR/app"
mkdir -p "$INSTALL_DIR" "$BIN_DIR"
chmod 700 "$INSTALL_DIR" 2>/dev/null || true

# Swap the whole app directory so a running daemon keeps its files until it restarts.
rm -rf "$INSTALL_DIR/app.new" "$INSTALL_DIR/app.old"
mv "$WORK/extract/bento" "$INSTALL_DIR/app.new"
if [ -d "$APP_DIR" ]; then mv "$APP_DIR" "$INSTALL_DIR/app.old"; fi
mv "$INSTALL_DIR/app.new" "$APP_DIR"
rm -rf "$INSTALL_DIR/app.old"
ln -sf "$APP_DIR/bento" "$BIN_DIR/bento"

say "Bento CLI $VERSION installed: $BIN_DIR/bento"
case ":${PATH:-}:" in
  *":$BIN_DIR:"*) ;;
  *) say "Add $BIN_DIR to your PATH, for example:  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.profile" ;;
esac
say ""
say "Next step:  bento setup"
