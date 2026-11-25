#!/usr/bin/env bash
# Cross-build Pillow for Chaquopy Python 3.13 on Android (SEC-02): the Chaquopy repository stops at Pillow 11.0.0,
# which has the PSD out-of-bounds writes and later advisories.
# usage: build_pillow.sh <abi: arm64-v8a|x86_64>
# Features: JPEG (libjpeg-turbo, static) and zlib (Android's system libz). Bento only reads EXIF and makes JPEG
# thumbnails on desktop; Android thumbnails come from the platform (`media_tools` bridge). Everything else is off,
# and `adapters/media/image_formats.py` limits the parsers Bento ever runs.
# Needs: Android NDK r27b, cmake + ninja, work/buildenv (see build_all.sh).
set -euo pipefail
ABI=$1
PILLOW=13.0.0
JPEG_TURBO=3.2.1
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$HERE/work; OUT=$HERE/dist
NDK=${ANDROID_NDK_HOME:-$HOME/Android/Sdk/ndk/27.1.12297006}
TC=$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin
SYSROOT=$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot
PY_TARGET=3.13.16-0
API=24
case $ABI in
  arm64-v8a) TRIPLE=aarch64-linux-android; SIMD=ON;;
  x86_64) TRIPLE=x86_64-linux-android; SIMD=OFF;;  # x86_64 SIMD needs nasm; the ABI only runs on emulators
  *) echo "unknown ABI $ABI" >&2; exit 2;;
esac
mkdir -p "$WORK/src" "$OUT"

TARGET_DIR=$WORK/target-$ABI  # shared with build_rust_wheel.sh: headers + libpython3.13.so of the embedded Python
if [ ! -f "$TARGET_DIR/jniLibs/$ABI/libpython3.13.so" ]; then
  mkdir -p "$TARGET_DIR"
  curl -sSfL -o "$WORK/target-$ABI.zip" \
    "https://repo1.maven.org/maven2/com/chaquo/python/target/$PY_TARGET/target-$PY_TARGET-$ABI.zip"
  (cd "$TARGET_DIR" && unzip -qo "$WORK/target-$ABI.zip")
fi

# libjpeg-turbo, static and position independent, linked into _imaging.
PREFIX=$WORK/pillow-deps-$ABI
if [ ! -f "$PREFIX/lib/libjpeg.a" ]; then
  [ -d "$WORK/src/libjpeg-turbo-$JPEG_TURBO" ] || {
    curl -sSfL -o "$WORK/src/libjpeg-turbo-$JPEG_TURBO.tar.gz" \
      "https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/$JPEG_TURBO/libjpeg-turbo-$JPEG_TURBO.tar.gz"
    tar xzf "$WORK/src/libjpeg-turbo-$JPEG_TURBO.tar.gz" -C "$WORK/src"
  }
  rm -rf "$WORK/jpeg-build-$ABI"
  cmake -S "$WORK/src/libjpeg-turbo-$JPEG_TURBO" -B "$WORK/jpeg-build-$ABI" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" -DANDROID_ABI="$ABI" -DANDROID_PLATFORM=$API \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DENABLE_SHARED=OFF -DENABLE_STATIC=ON -DWITH_TURBOJPEG=OFF \
    -DWITH_TOOLS=OFF -DWITH_TESTS=OFF -DWITH_SIMD=$SIMD >/dev/null
  cmake --build "$WORK/jpeg-build-$ABI" >/dev/null
  cmake --install "$WORK/jpeg-build-$ABI" >/dev/null
fi
# zlib: the system libz.so of the NDK sysroot (headers + stub), exposed under the same prefix for Pillow's search.
ln -sf "$SYSROOT/usr/include/zlib.h" "$SYSROOT/usr/include/zconf.h" "$PREFIX/include/"
ln -sf "$SYSROOT/usr/lib/$TRIPLE/$API/libz.so" "$PREFIX/lib/libz.so"

[ -d "$WORK/src/pillow-$PILLOW" ] || {
  url=$(curl -s "https://pypi.org/pypi/pillow/$PILLOW/json" | python3 -c "import json,sys;print([u['url'] for u in json.load(sys.stdin)['urls'] if u['packagetype']=='sdist'][0])")
  curl -sSfL -o "$WORK/src/pillow-$PILLOW.tar.gz" "$url"; tar xzf "$WORK/src/pillow-$PILLOW.tar.gz" -C "$WORK/src"
}
"$WORK/buildenv/bin/python" -m pip install -q "setuptools>=77" wheel pybind11

RAW=$WORK/raw-pillow-$ABI; rm -rf "$RAW" "$WORK/src/pillow-$PILLOW/build"; mkdir -p "$RAW"
export CC="$TC/${TRIPLE}${API}-clang" LDSHARED="$TC/${TRIPLE}${API}-clang -shared" AR="$TC/llvm-ar"
# The embedded interpreter's headers come before the build Python's (setuptools appends its own -I).
export CFLAGS="-I$TARGET_DIR/include/python3.13 -I$PREFIX/include -O2 -fPIC"
export LDFLAGS="-L$PREFIX/lib -L$TARGET_DIR/jniLibs/$ABI -lpython3.13 -Wl,--strip-all"
export JPEG_ROOT=$PREFIX ZLIB_ROOT=$PREFIX PKG_CONFIG=/bin/false
export _PYTHON_HOST_PLATFORM=android-$API-${ABI//-/_}  # wheel tag android_24_<abi>
(cd "$WORK/src/pillow-$PILLOW" && "$WORK/buildenv/bin/python" -m pip wheel -q --no-deps --no-build-isolation -w "$RAW" . \
  -C platform-guessing=disable -C zlib=enable -C jpeg=enable -C tiff=disable -C freetype=disable -C raqm=disable \
  -C lcms=disable -C webp=disable -C jpeg2000=disable -C imagequant=disable -C xcb=disable -C avif=disable)
for wheel in "$RAW"/*.whl; do
  # setuptools names extensions with the build Python's EXT_SUFFIX (`*.cpython-313-x86_64-linux-gnu.so`).
  "$WORK/buildenv/bin/python" "$HERE/fix_ext_suffix.py" "$wheel"
  mv "$RAW"/*.whl "$OUT/"
done
