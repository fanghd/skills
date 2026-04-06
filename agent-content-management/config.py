"""Configuration loader for context management."""

import json
import os
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG = {
    "store_path": "~/.openclaw/workspace/context-store/",
    "summarization": {
        "max_summary_length": 200,
        "model": "claude-haiku-4-5-20251001",
        "prompt_template": "default"
    },
    "recall": {
        "summary_threshold": 0.4,
        "transcript_threshold": 0.6,
        "max_summary_returns": 5,
        "max_transcript_returns": 2,
        "time_decay_factor": 0.5,
        "same_session_bonus": 0.15,
        "auto_mode": True
    },
    "compression": {
        "warning_threshold": 0.70,
        "compress_threshold": 0.80,
        "target_after_compress": 0.60,
        "recent_turns_to_keep": 4,
        "model_max_context": 200000
    },
    "index": {
        "max_index_age_days": 30,
        "auto_cleanup_transcripts_days": 90
    }
}


class Config:
    """Configuration for the context management system."""

    def __init__(self, config_path: Optional[str] = None):
        self._data = dict(DEFAULT_CONFIG)
        if config_path and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            self._merge(self._data, overrides)
        self._resolve_paths()

    @staticmethod
    def _merge(base: dict, override: dict) -> None:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Config._merge(base[key], value)
            else:
                base[key] = value

    def _resolve_paths(self) -> None:
        self.store_path = Path(self._data["store_path"]).expanduser().resolve()

    def get(self, *keys: str, default=None):
        """Get nested config value by key path."""
        current = self._data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    @property
    def data(self) -> dict:
        return dict(self._data)

    def save(self, path: Optional[str] = None) -> None:
        """Save current config to file."""
        save_path = path or (self.store_path / "context_config.json")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
