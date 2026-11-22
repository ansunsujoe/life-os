"""Process-level configuration (paths, ports).

User-editable behaviour (weights, thresholds, privacy switches) lives in the
`user_settings` table instead — see `lifeos.services.settings`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    home: Path
    db_path: Path
    host: str
    port: int
    background_sync: bool

    @property
    def imports_dir(self) -> Path:
        return self.home / "imports"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    def ensure_dirs(self) -> None:
        for d in (
            self.home,
            self.db_path.parent,
            self.imports_dir / "robinhood",
            self.imports_dir / "apple_health",
            self.imports_dir / "summaries",
            self.exports_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    home = Path(os.environ.get("LIFEOS_HOME", Path.home() / "LifeOS")).expanduser()
    db_path = Path(os.environ.get("LIFEOS_DB", home / "data" / "lifeos.db")).expanduser()
    return AppConfig(
        home=home,
        db_path=db_path,
        # Localhost only by default (spec §11.5). Never default to 0.0.0.0.
        host=os.environ.get("LIFEOS_HOST", "127.0.0.1"),
        port=int(os.environ.get("LIFEOS_PORT", "8765")),
        background_sync=os.environ.get("LIFEOS_BACKGROUND_SYNC", "1") == "1",
    )


config = load_config()
