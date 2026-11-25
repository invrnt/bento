"""SHA256SUMS and its detached OpenSSH signature (`ssh-keygen -Y sign`, namespace `bento-release`).

Why ssh-keygen rather than minisign or GPG: it ships with OpenSSH on Linux, macOS and Windows 10+, so
neither the owner nor a user verifying a download installs anything; it works with keys held by
ssh-agent or a hardware token (pass the `.pub` path and the private half never touches disk); and the
same Ed25519 key can sign the git tags (`gpg.format=ssh`) because the namespace keeps the two
signature domains apart. The trust anchor is `scripts/release/allowed_signers`, committed to the
repository, never a file shipped next to the signature.

Private keys are never generated, read or printed here: only their path is passed to ssh-keygen.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

NAMESPACE = "bento-release"
PRINCIPAL = "bento-release"
SUMS = "SHA256SUMS"
SIGNATURE = "SHA256SUMS.sig"
# Never listed in SHA256SUMS: the list itself, its signature and stray platform files.
EXCLUDED = {SUMS, SIGNATURE, ".DS_Store", "Thumbs.db"}


class SigningError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_files(directory: Path) -> list[Path]:
    """Release assets are a flat directory: subdirectories, links and empty files are refused."""
    files = []
    seen: dict[str, str] = {}
    for entry in sorted(directory.iterdir()):
        if entry.name in EXCLUDED:
            continue
        if entry.is_symlink() or not entry.is_file():
            raise SigningError(f"release assets must be regular files: {entry}")
        if entry.stat().st_size == 0:
            raise SigningError(f"release asset is empty: {entry}")
        key = entry.name.lower()
        if key in seen:
            raise SigningError(f"asset names collide case-insensitively: {seen[key]} and {entry.name}")
        seen[key] = entry.name
        files.append(entry)
    if not files:
        raise SigningError(f"no release assets in {directory}")
    return files


def write_sums(directory: Path) -> Path:
    lines = [f"{sha256(path)}  {path.name}\n" for path in asset_files(directory)]
    output = directory / SUMS
    output.write_text("".join(lines), encoding="utf-8")
    stale = directory / SIGNATURE
    if stale.exists():
        stale.unlink()
    return output


def parse_sums(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        digest, separator, name = line.partition("  ")
        name = name.removeprefix("*")
        if not separator or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or not name or "/" in name:
            raise SigningError(f"{SUMS} line {number} is not `<sha256>  <file>`")
        if name in entries:
            raise SigningError(f"{SUMS} lists {name} twice")
        entries[name] = digest
    return entries


def check_sums(directory: Path) -> list[str]:
    """Compares SHA256SUMS with the directory; returns the problems (empty means every file matches)."""
    sums = directory / SUMS
    if not sums.is_file():
        return [f"{SUMS} is missing"]
    entries = parse_sums(sums.read_text(encoding="utf-8"))
    problems = []
    present = {path.name: path for path in asset_files(directory)}
    for name, digest in entries.items():
        if name not in present:
            problems.append(f"{name} is listed but missing")
        elif sha256(present[name]) != digest:
            problems.append(f"{name} does not match its SHA-256")
    problems += [f"{name} is not listed in {SUMS}" for name in sorted(set(present) - set(entries))]
    return problems


def _ssh_keygen() -> str:
    tool = shutil.which("ssh-keygen")
    if not tool:
        raise SigningError("ssh-keygen (OpenSSH 8.1 or later) is required to sign or verify SHA256SUMS")
    return tool


def sign(directory: Path, key: Path) -> Path:
    """Signs SHA256SUMS with `key` (a private key file, or a `.pub` whose private half is in ssh-agent)."""
    if not key.is_file():
        raise SigningError(f"signing key not found: {key}")
    sums = directory / SUMS
    signature = directory / SIGNATURE
    if signature.exists():
        signature.unlink()
    # ssh-keygen may prompt for the key passphrase on the terminal; nothing it prints contains key material.
    result = subprocess.run([_ssh_keygen(), "-Y", "sign", "-f", str(key), "-n", NAMESPACE, str(sums)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not signature.is_file():
        raise SigningError(f"ssh-keygen -Y sign failed (exit {result.returncode}): {(result.stderr.strip().splitlines() or [''])[-1]}")
    signature.chmod(0o644)
    return signature


def public_key_of(key: Path) -> str:
    """The public key line for a key path (reads a `.pub` directly, otherwise asks ssh-keygen -y)."""
    if key.suffix == ".pub":
        return key.read_text(encoding="utf-8").strip()
    pub = key.with_name(key.name + ".pub")
    if pub.is_file():
        return pub.read_text(encoding="utf-8").strip()
    result = subprocess.run([_ssh_keygen(), "-y", "-f", str(key)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise SigningError("could not derive the public key (ssh-keygen -y failed)")
    return result.stdout.strip()


def allowed_signers_entries(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def allowed_signers_line(public_key: str) -> str:
    fields = public_key.split()
    if len(fields) < 2:
        raise SigningError("not an OpenSSH public key")
    return f'{PRINCIPAL} namespaces="{NAMESPACE}" {fields[0]} {fields[1]}'


def verify(directory: Path, allowed_signers: Path) -> str:
    """Verifies SHA256SUMS.sig against an allowed_signers file; returns ssh-keygen's success line."""
    sums, signature = directory / SUMS, directory / SIGNATURE
    if not signature.is_file():
        raise SigningError(f"{SIGNATURE} is missing (the release is unsigned)")
    if not allowed_signers_entries(allowed_signers):
        raise SigningError(f"{allowed_signers} lists no release key yet")
    with sums.open("rb") as stdin:
        result = subprocess.run(
            [_ssh_keygen(), "-Y", "verify", "-f", str(allowed_signers), "-I", PRINCIPAL, "-n", NAMESPACE, "-s", str(signature)],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    if result.returncode != 0:
        raise SigningError(f"signature does not verify: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()
