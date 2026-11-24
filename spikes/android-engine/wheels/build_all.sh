#!/usr/bin/env bash
# Builds every wheel the spike needs that neither PyPI nor the Chaquopy repository provides for Android cp313:
#   pydantic-core 2.46.4 and cryptg 0.6.1 (Rust/PyO3, both ABIs), pyaes 1.6.1 and hkdf 0.0.3 (pure Python, sdist-only).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); WORK=$HERE/work; mkdir -p "$WORK/src" "$HERE/dist"
rustup target add aarch64-linux-android x86_64-linux-android
[ -x "$WORK/buildenv/bin/python" ] || uv venv -q -p 3.13 "$WORK/buildenv"
uv pip install -q -p "$WORK/buildenv/bin/python" maturin==1.16.0 pip
fetch() {  # name version
  local url; url=$(curl -s "https://pypi.org/pypi/$1/$2/json" | python3 -c "import json,sys;print([u['url'] for u in json.load(sys.stdin)['urls'] if u['packagetype']=='sdist'][0])")
  curl -sSfL -o "$WORK/src/$1-$2.tar.gz" "$url"; tar xzf "$WORK/src/$1-$2.tar.gz" -C "$WORK/src"
}
fetch pydantic-core 2.46.4; fetch cryptg 0.6.1
for abi in arm64-v8a x86_64; do
  "$HERE/build_rust_wheel.sh" "$WORK/src/pydantic_core-2.46.4" "$abi"
  "$HERE/build_rust_wheel.sh" "$WORK/src/cryptg-0.6.1" "$abi"
done
"$WORK/buildenv/bin/python" -m pip wheel -q --no-deps pyaes==1.6.1 hkdf==0.0.3 -w "$HERE/dist"
ls -l "$HERE/dist"
