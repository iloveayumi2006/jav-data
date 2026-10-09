"""Portable filesystem configuration; no credentials belong in this file."""

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


def application_root():
    return (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    library_dir: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / "jav-data.sqlite3"

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Settings":
        path = (
            config_path
            or Path(os.getenv("JAV_DATA_CONFIG", str(application_root() / "config.toml")))
        ).resolve()
        config = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        storage = config.get("storage", {})

        def directory(key: str, default: str) -> Path:
            value = os.getenv(f"JAV_DATA_{key.upper()}", storage.get(key, default))
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty path")
            candidate = Path(value).expanduser()
            return (candidate if candidate.is_absolute() else path.parent / candidate).resolve()

        return cls(directory("data_dir", "data"), directory("library_dir", "library"))

    def prepare(self) -> None:
        for path in (self.data_dir, self.library_dir):
            path.mkdir(parents=True, exist_ok=True)
