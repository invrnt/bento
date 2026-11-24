# Android Python wheels

Chaquopy 17 installs `--only-binary`: every native package needs a prebuilt Android wheel for cp313.
`requirements-android.txt` is generated from the `android` extra of `apps/api` (`uv export --extra android --no-dev
--no-emit-project`, markers evaluated for Android, plus the overrides in `generate_requirements.py`); `core/engine`
passes it to Chaquopy pip with `--find-links dist/` (git-ignored). Regenerate after changing the extra or `uv.lock`:
`uv run --project ../api --extra dev python python-wheels/generate_requirements.py` (`--check` is part of
`./gradlew check` as `:core:engine:checkPythonRequirements`).

| Package | Source |
|---|---|
| `pydantic-core` 2.46.4, `cryptg` 0.6.1 | built here: `build_rust_wheel.sh` (maturin + NDK r27b, PyO3 config file against the exact Chaquopy `libpython3.13.so`, `fix_ext_suffix.py` renames the extension to the interpreter's `EXT_SUFFIX` and fixes cryptg's `0.1.0` metadata) |
| `pyaes` 1.6.1, `hkdf` 0.0.3 | built here: pure wheels from sdist-only PyPI releases (`hkdf` is no longer required: spake2 0.9 uses cryptography's HKDF) |
| `cryptography` 42.0.8, `cffi`, `pillow`, `greenlet` | Chaquopy package repository |
| `markupsafe` 3.0.4 | PyPI official `android_24_*` wheels |
| everything else | PyPI `py3-none-any` |

Rebuild: `./build_all.sh` (needs `uv`, `rustup`, `ANDROID_NDK_HOME` or `~/Android/Sdk/ndk/27.1.12297006`).
CI runs the same script (`.github/workflows/android.yml`, cached by the hash of these files).
History and measurements: `docs/dev/android-spike.md` § Wheels.
