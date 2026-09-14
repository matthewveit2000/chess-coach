"""Configuration loading.

Precedence, highest first: environment variables, config/config.toml, defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The project root is three levels up from this file:
# <root>/src/chess_coach/config.py
ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = ROOT / "config" / "config.toml"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "config.example.toml"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
DB_PATH = DATA_DIR / "games.db"


@dataclass
class EngineConfig:
    path: str = "data/engine/stockfish.exe"
    depth: int = 16
    multipv: int = 2
    threads: int = 0
    hash_mb: int = 256

    def resolved_path(self) -> Path:
        env = os.environ.get("CHESS_COACH_ENGINE_PATH")
        raw = Path(env) if env else Path(self.path)
        return raw if raw.is_absolute() else (ROOT / raw)

    def resolved_threads(self) -> int:
        if self.threads > 0:
            return self.threads
        return max(1, (os.cpu_count() or 2) - 1)


@dataclass
class AnalysisConfig:
    skip_opening_plies: int = 8
    inaccuracy: float = 0.10
    mistake: float = 0.20
    blunder: float = 0.30
    decided_threshold: float = 0.90


@dataclass
class TrendsConfig:
    min_games_for_opening: int = 4


@dataclass
class Config:
    chesscom_user: str = ""
    lichess_user: str = ""
    engine: EngineConfig = field(default_factory=EngineConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    trends: TrendsConfig = field(default_factory=TrendsConfig)

    def username_for(self, source: str) -> str:
        return {"chesscom": self.chesscom_user, "lichess": self.lichess_user}.get(source, "")


def _load_env_file() -> None:
    """Minimal .env reader. Avoids a dependency for five lines of parsing."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if value and key not in os.environ:
            os.environ[key] = value


def load_config() -> Config:
    _load_env_file()

    raw: dict = {}
    if CONFIG_PATH.exists():
        raw = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    player = raw.get("player", {})
    cfg = Config(
        chesscom_user=player.get("chesscom", "").strip(),
        lichess_user=player.get("lichess", "").strip(),
        engine=EngineConfig(**{**EngineConfig().__dict__, **raw.get("engine", {})}),
        analysis=AnalysisConfig(**{**AnalysisConfig().__dict__, **raw.get("analysis", {})}),
        trends=TrendsConfig(**{**TrendsConfig().__dict__, **raw.get("trends", {})}),
    )

    # Placeholder from the example file counts as "not set".
    if cfg.chesscom_user.upper().startswith("YOUR_"):
        cfg.chesscom_user = ""
    return cfg


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
