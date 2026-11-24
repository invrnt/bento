#!/bin/sh
# Packages a built CLI onedir as a Debian/Ubuntu .deb.
#
#   scripts/install/build_deb.sh BUNDLE_DIR VERSION OUTPUT_DIR [ARCH]
#
# BUNDLE_DIR is the PyInstaller onedir (`<output>/bento` from apps/api/scripts/build_cli.py).
# ARCH is the Debian architecture (amd64, arm64); default: `dpkg --print-architecture`.
# Produces OUTPUT_DIR/bento-cli_<version>_<arch>.deb installing to /opt/bento-cli with a
# /usr/bin/bento symlink. The binary is frozen (Python and libraries bundled), so the package
# declares no dependencies beyond the base system.
set -eu

fail() { printf 'build_deb: %s\n' "$*" >&2; exit 1; }

[ "$#" -ge 3 ] || fail "usage: build_deb.sh BUNDLE_DIR VERSION OUTPUT_DIR [ARCH]"
BUNDLE="$1"
VERSION="${2#v}"
OUTPUT="$3"
ARCH="${4:-}"
command -v dpkg-deb >/dev/null 2>&1 || fail "dpkg-deb is required"
[ -x "$BUNDLE/bento" ] || fail "$BUNDLE/bento is not an executable CLI bundle"
case "$VERSION" in
  [0-9]*) ;;
  *) fail "invalid Debian version '$VERSION' (must start with a digit)" ;;
esac
case "$VERSION" in
  *[!0-9A-Za-z.+~-]*) fail "invalid Debian version '$VERSION'" ;;
esac
if [ -z "$ARCH" ]; then
  command -v dpkg >/dev/null 2>&1 || fail "pass ARCH (amd64 or arm64)"
  ARCH="$(dpkg --print-architecture)"
fi
case "$ARCH" in
  amd64|arm64) ;;
  *) fail "unsupported architecture '$ARCH'" ;;
esac

umask 022
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/bento-deb.XXXXXX")"
trap 'rm -rf "$ROOT"' EXIT INT TERM
chmod 0755 "$ROOT"

mkdir -p "$ROOT/DEBIAN" "$ROOT/opt" "$ROOT/usr/bin" "$ROOT/usr/share/doc/bento-cli"
cp -R "$BUNDLE" "$ROOT/opt/bento-cli"
# A build-config.json next to the executable is public build configuration (world-readable on purpose).
find "$ROOT/opt/bento-cli" -type d -exec chmod 0755 {} +
find "$ROOT/opt/bento-cli" -type f -exec chmod go-w,a+r {} +
chmod 0755 "$ROOT/opt/bento-cli/bento"
ln -s /opt/bento-cli/bento "$ROOT/usr/bin/bento"

SIZE_KB="$(du -sk "$ROOT/opt" | awk '{print $1}')"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: bento-cli
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Installed-Size: $SIZE_KB
Maintainer: Bento contributors <noreply@bento.invalid>
Homepage: https://github.com/invrnt/bento
Description: Bento command-line client
 Command-line client and headless daemon for Bento, the private library
 that keeps your files end-to-end encrypted in your own Telegram account.
 Designed for AI agents, servers and power users. Run "bento setup" to start.
EOF
cat > "$ROOT/usr/share/doc/bento-cli/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: bento
Source: https://github.com/invrnt/bento
EOF

mkdir -p "$OUTPUT"
TARGET="$OUTPUT/bento-cli_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "$TARGET" >/dev/null
printf 'build_deb: wrote %s\n' "$TARGET"
