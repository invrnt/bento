#!/usr/bin/env bash
# Cross-build a PyO3/maturin sdist for Chaquopy Python 3.13 on Android.
# usage: build_rust_wheel.sh <srcdir> <abi: arm64-v8a|x86_64>
# Needs: rustup targets aarch64-linux-android/x86_64-linux-android, Android NDK, work/buildenv (see build_all.sh).
set -euo pipefail
SRC=$1; ABI=$2
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$HERE/work; OUT=$HERE/dist
NDK=${ANDROID_NDK_HOME:-$HOME/Android/Sdk/ndk/27.1.12297006}
TC=$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin
PY_TARGET=3.13.16-0
case $ABI in
  arm64-v8a) TRIPLE=aarch64-linux-android; ENVT=AARCH64_LINUX_ANDROID;;
  x86_64) TRIPLE=x86_64-linux-android; ENVT=X86_64_LINUX_ANDROID;;
  *) echo "unknown ABI $ABI" >&2; exit 2;;
esac
# libpython3.13.so of the exact Chaquopy target the app embeds (PyO3 links it on Android).
TARGET_DIR=$WORK/target-$ABI
if [ ! -f "$TARGET_DIR/jniLibs/$ABI/libpython3.13.so" ]; then
  mkdir -p "$TARGET_DIR"
  curl -sSfL -o "$WORK/target-$ABI.zip" \
    "https://repo1.maven.org/maven2/com/chaquo/python/target/$PY_TARGET/target-$PY_TARGET-$ABI.zip"
  (cd "$TARGET_DIR" && unzip -qo "$WORK/target-$ABI.zip")
fi
CFG=$WORK/pyo3-$ABI.cfg
cat > "$CFG" <<CFGEOF
implementation=CPython
version=3.13
shared=true
abi3=false
lib_name=python3.13
lib_dir=$TARGET_DIR/jniLibs/$ABI
pointer_width=64
build_flags=
suppress_build_script_link_lines=false
CFGEOF
export PYO3_CONFIG_FILE=$CFG
export CARGO_TARGET_${ENVT}_LINKER=$TC/${TRIPLE}24-clang
export CC_${TRIPLE//-/_}=$TC/${TRIPLE}24-clang
export AR_${TRIPLE//-/_}=$TC/llvm-ar
export CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS:-4}
export CARGO_TARGET_DIR=$WORK/cargo-target
RAW=$WORK/raw-$ABI; rm -rf "$RAW"; mkdir -p "$RAW" "$OUT"
(cd "$SRC" && "$WORK/buildenv/bin/maturin" build --release --strip --target "$TRIPLE" --out "$RAW" --compatibility linux --skip-auditwheel)
for wheel in "$RAW"/*.whl; do
  # maturin names the extension `*.cpython-313-<arch>-android-android.so`; CPython on Android expects
  # `*.cpython-313-<triple>.so` (EXT_SUFFIX), so rename it and rewrite RECORD.
  "$WORK/buildenv/bin/python" "$HERE/fix_ext_suffix.py" "$wheel"
  mv "$wheel" "$OUT/"
done
