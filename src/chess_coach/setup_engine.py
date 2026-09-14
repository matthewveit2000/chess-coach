"""Download and verify a Stockfish binary into data/engine/.

Stockfish is GPL-3.0 and free. We fetch the official release straight from the
project's GitHub releases rather than a repackaged mirror.

Modern Stockfish (17+) publishes one "universal" binary per platform that picks
the right CPU instruction set at runtime. Older releases published a separate
build per instruction set (avx2, sse41-popcnt, ...), and a binary built for
instructions your CPU lacks crashes instantly rather than failing gracefully.
So the preference list below tries the universal build first, keeps the legacy
names as fallbacks, and -- either way -- actually starts the binary and
completes a UCI handshake before declaring success.
"""

from __future__ import annotations

import io
import platform
import stat
import tarfile
import zipfile
from pathlib import Path

import requests

from .config import DATA_DIR

RELEASES_API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
ENGINE_DIR = DATA_DIR / "engine"

# Most-preferred first, per (system, architecture). Legacy per-CPU names are
# kept so pinning an older Stockfish release still works.
PREFERENCES: dict[tuple[str, str], list[str]] = {
    ("Windows", "x86_64"): [
        "stockfish-windows-x86-64-universal.zip",
        "stockfish-windows-x86-64-avx2.zip",
        "stockfish-windows-x86-64-sse41-popcnt.zip",
        "stockfish-windows-x86-64.zip",
    ],
    ("Windows", "arm64"): ["stockfish-windows-arm64-universal.zip"],
    ("Linux", "x86_64"): [
        "stockfish-linux-x86-64-universal.tar.gz",
        "stockfish-ubuntu-x86-64-avx2.tar",
        "stockfish-ubuntu-x86-64-sse41-popcnt.tar",
    ],
    ("Linux", "arm64"): ["stockfish-linux-arm64-universal.tar.gz"],
    ("Darwin", "x86_64"): ["stockfish-macos-universal.tar.gz"],
    ("Darwin", "arm64"): ["stockfish-macos-universal.tar.gz"],
}


class EngineInstallError(RuntimeError):
    pass


def _architecture() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine


def _preference_list() -> list[str]:
    key = (platform.system(), _architecture())
    prefs = PREFERENCES.get(key)
    if not prefs:
        raise EngineInstallError(
            f"No automatic download for {key[0]}/{key[1]}. Install Stockfish "
            "yourself and set engine.path in config/config.toml."
        )
    return prefs


def _assets() -> tuple[str, dict[str, dict]]:
    resp = requests.get(
        RELEASES_API, timeout=30, headers={"Accept": "application/vnd.github+json"}
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("tag_name", "unknown"), {a["name"]: a for a in data.get("assets", [])}


def _verify(exe: Path) -> bool:
    """Start the binary and complete a UCI handshake. Proves it actually runs."""
    import chess.engine

    try:
        engine = chess.engine.SimpleEngine.popen_uci(str(exe))
        engine.quit()
        return True
    except Exception:
        return False


def _extract_zip(content: bytes, dest: Path) -> Path:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        exes = [n for n in zf.namelist() if n.lower().endswith(".exe")]
        if not exes:
            raise EngineInstallError("No .exe found inside the Stockfish archive.")
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / "stockfish.exe"
        out.write_bytes(zf.read(exes[0]))
        return out


def _extract_tar(content: bytes, dest: Path) -> Path:
    # mode "r" auto-detects gzip/bzip2/xz, so .tar and .tar.gz both work.
    with tarfile.open(fileobj=io.BytesIO(content), mode="r") as tf:
        files = [m for m in tf.getmembers() if m.isfile()]
        if not files:
            raise EngineInstallError("Stockfish archive contained no files.")
        # The engine binary is by far the largest member; the rest is docs.
        binary = max(files, key=lambda m: m.size)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / "stockfish"
        handle = tf.extractfile(binary)
        if handle is None:
            raise EngineInstallError("Could not read the Stockfish binary from the archive.")
        out.write_bytes(handle.read())
        out.chmod(out.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return out


def install(log=print) -> Path:
    tag, by_name = _assets()
    log(f"Latest Stockfish release: {tag}")

    tried: list[str] = []
    for wanted in _preference_list():
        asset = by_name.get(wanted)
        if not asset:
            continue
        tried.append(wanted)
        size_mb = asset.get("size", 0) / 1_048_576
        log(f"Downloading {wanted} ({size_mb:.0f} MB) ...")
        content = requests.get(asset["browser_download_url"], timeout=600).content

        extract = _extract_zip if wanted.endswith(".zip") else _extract_tar
        exe = extract(content, ENGINE_DIR)
        log(f"Extracted to {exe}")

        log("Verifying the binary runs on this CPU ...")
        if _verify(exe):
            log("UCI handshake OK.")
            return exe
        log(f"{wanted} will not run here. Trying a more conservative build.")

    available = ", ".join(sorted(by_name)) or "none"
    raise EngineInstallError(
        f"Could not get a working Stockfish build.\n"
        f"  Tried: {tried or 'no matching asset names'}\n"
        f"  Release {tag} offers: {available}\n"
        "Download one manually from https://stockfishchess.org/download/ and set "
        "engine.path in config/config.toml."
    )
