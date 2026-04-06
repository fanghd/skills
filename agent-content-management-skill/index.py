"""Semantic index management for context store."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class IndexManager:
    """Manages the semantic index for stored conversations."""

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.index_path = store_path / "index.json"
        self._data = self._load()

    def _load(self) -> dict:
        """Load index from file, create empty if not exists."""
        if self.index_path.exists():
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "version": "1.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "conversations": {}
        }

    def save(self) -> None:
        """Persist index to disk."""
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def ensure_session(self, session_id: str) -> dict:
        """Ensure a session entry exists, create if needed."""
        if session_id not in self._data["conversations"]:
            self._data["conversations"][session_id] = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "turns": [],
                "total_tokens": 0,
                "last_activity": datetime.now(timezone.utc).isoformat()
            }
        return self._data["conversations"][session_id]

    def add_turn(self, session_id: str, turn_data: dict) -> None:
        """Add a new turn entry to the index."""
        session = self.ensure_session(session_id)
        session["turns"].append(turn_data)
        session["total_tokens"] += turn_data.get("tokens", 0)
        session["last_activity"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def update_turn(self, session_id: str, turn_id: str, updates: dict) -> bool:
        """Update an existing turn entry. Returns True if found."""
        session = self.ensure_session(session_id)
        for turn in session["turns"]:
            if turn["turn_id"] == turn_id:
                turn.update(updates)
                self.save()
                return True
        return False

    def search(self, keywords: list[str], session_id: Optional[str] = None,
               limit: int = 10) -> list[dict]:
        """Search turns by keyword overlap across all sessions."""
        results = []
        keyword_set = set(k.lower() for k in keywords)

        for sid, conv in self._data["conversations"].items():
            if session_id and sid != session_id:
                continue
            for turn in conv["turns"]:
                turn_keywords = set(k.lower() for k in turn.get("keywords", []))
                fingerprint = set(turn.get("semantic_fingerprint", "").lower().split())
                all_tokens = turn_keywords | fingerprint
                if not all_tokens:
                    continue
                overlap = len(keyword_set & all_tokens)
                if overlap > 0:
                    results.append({
                        "session_id": sid,
                        **turn,
                        "score": overlap / max(len(keyword_set), 1)
                    })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def get_recent_turns(self, session_id: str, n: int = 5) -> list[dict]:
        """Get the most recent N turns from a session."""
        session = self._data["conversations"].get(session_id)
        if not session:
            return []
        return session["turns"][-n:]

    def get_total_tokens(self) -> int:
        """Sum of all tokens across all sessions."""
        total = 0
        for conv in self._data["conversations"].values():
            total += conv.get("total_tokens", 0)
        return total

    def list_sessions(self) -> list[dict]:
        """List all sessions with metadata."""
        result = []
        for sid, conv in self._data["conversations"].items():
            result.append({
                "session_id": sid,
                "created_at": conv["created_at"],
                "last_activity": conv["last_activity"],
                "total_turns": len(conv["turns"]),
                "total_tokens": conv.get("total_tokens", 0)
            })
        return sorted(result, key=lambda s: s["last_activity"], reverse=True)

    def cleanup_old_entries(self, max_age_days: int = 90) -> int:
        """Remove turns older than max_age_days. Returns count removed."""
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
        removed = 0
        for sid, conv in self._data["conversations"].items():
            before = len(conv["turns"])
            conv["turns"] = [
                t for t in conv["turns"]
                if datetime.fromisoformat(t["timestamp"]).timestamp() > cutoff
            ]
            removed += before - len(conv["turns"])
        if removed > 0:
            self.save()
        return removed
