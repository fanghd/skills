"""Store Engine — saves summaries and transcripts after each turn."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import Config
from index import IndexManager
from summarizer import Summarizer


class StoreEngine:
    """Handles post-turn storage of summaries and transcripts."""

    def __init__(self, store_path: Path, config: Optional[Config] = None):
        self.config = config or Config()
        self.store_path = store_path
        self._init_store()
        self.index = IndexManager(store_path)
        self.summarizer = Summarizer(
            use_llm=False  # Default to fallback (rule-based) until LLM API is integrated
        )

    def _init_store(self) -> None:
        """Create store directory structure if missing."""
        (self.store_path / "summaries").mkdir(parents=True, exist_ok=True)
        (self.store_path / "transcripts").mkdir(parents=True, exist_ok=True)

    def store_turn(self, user_input: str, assistant_output: str,
                   session_id: str, tool_calls: Optional[list] = None) -> dict:
        """
        Store a completed conversation turn: generate summary, save
        transcript, update index, and refresh active summaries.

        Returns the stored turn metadata.
        """
        now = datetime.now(timezone.utc)
        timestamp_file = now.strftime("%Y%m%d_%H%M%S")
        timestamp_iso = now.isoformat()
        turn_id = self._next_turn_id(session_id)

        # Step 1: Generate summary
        summary_data = self.summarizer.generate(user_input, assistant_output)

        # Step 2: Write summary file
        summary_path = self.store_path / "summaries" / f"{timestamp_file}.md"
        summary_content = self._format_summary(
            session_id, turn_id, timestamp_iso, summary_data
        )
        summary_path.write_text(summary_content, encoding="utf-8")

        # Step 3: Write transcript file
        transcript_path = self.store_path / "transcripts" / f"{timestamp_file}.md"
        transcript_content = self._format_transcript(
            session_id, turn_id, timestamp_iso, user_input, assistant_output, tool_calls
        )
        transcript_path.write_text(transcript_content, encoding="utf-8")

        # Step 4: Update index
        turn_entry = {
            "turn_id": turn_id,
            "timestamp": timestamp_iso,
            "summary_path": f"summaries/{timestamp_file}.md",
            "transcript_path": f"transcripts/{timestamp_file}.md",
            "tokens": self._estimate_tokens(user_input, assistant_output),
            "keywords": summary_data["keywords"],
            "topics": [],
            "semantic_fingerprint": " ".join(summary_data["semantic_fingerprint"]),
            "compressed": False,
            "compression_summary_path": None
        }
        self.index.add_turn(session_id, turn_entry)

        # Step 5: Refresh active summaries
        self._update_active_summaries(session_id)

        return turn_entry

    def _next_turn_id(self, session_id: str) -> str:
        session = self.index.ensure_session(session_id)
        turn_num = len(session["turns"]) + 1
        return f"turn_{turn_num:03d}"

    @staticmethod
    def _format_summary(session_id: str, turn_id: str, timestamp: str,
                        data: dict) -> str:
        lines = [
            f"# 对话摘要 - {timestamp}",
            "",
            "## 元信息",
            f"- **会话 ID:** `{session_id}`",
            f"- **轮次 ID:** `{turn_id}`",
            f"- **时间戳:** `{timestamp}`",
            f"- **原文路径:** `transcripts/`",
            f"- **关键词:** {data['keywords']}",
            f"- **语义指纹:** {' '.join(data['semantic_fingerprint'])}",
            "",
            "## 摘要内容",
            data["summary"],
            "",
            "## 关键决策/行动项",
        ]
        for item in data["action_items"]:
            lines.append(f"- {item}")
        lines.extend([
            "",
            "## 语义指纹",
        ])
        for tag in data["semantic_fingerprint"]:
            lines.append(f"- {tag}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_transcript(session_id: str, turn_id: str, timestamp: str,
                           user_input: str, assistant_output: str,
                           tool_calls: Optional[list]) -> str:
        lines = [
            f"# 对话原文 - {timestamp}",
            "",
            "## 元信息",
            f"- **会话 ID:** `{session_id}`",
            f"- **轮次 ID:** `{turn_id}`",
            f"- **时间戳:** `{timestamp}`",
            "",
            "## 用户输入",
            user_input,
            "",
        ]
        if tool_calls:
            lines.append("## 附件/工具调用")
            lines.append("```json")
            import json
            lines.append(json.dumps(tool_calls, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
        lines.extend([
            "## 助手回复",
            assistant_output,
            "",
        ])
        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(*text: str) -> int:
        """Rough token count: ~4 chars per token for mixed CJK/English."""
        total = sum(len(t) for t in text)
        return max(1, total // 4)

    def _update_active_summaries(self, session_id: str) -> None:
        """Refresh active_summaries.md with the most recent turns."""
        active_path = self.store_path / "active_summaries.md"
        all_turns = []
        for conv in self.index._data["conversations"].values():
            for turn in conv["turns"]:
                all_turns.append(turn)
        all_turns.sort(key=lambda t: t["timestamp"], reverse=True)
        recent = all_turns[:10]

        lines = [
            "# Active Summaries",
            f"\n> Last updated: {datetime.now(timezone.utc).isoformat()}",
            f"\n> Showing most recent {len(recent)} turns\n",
        ]
        for turn in recent:
            summary_file = self.store_path / turn["summary_path"]
            if summary_file.exists():
                content = summary_file.read_text(encoding="utf-8")
                # Extract just the summary heading and first section
                content_lines = content.split("\n")
                header_end = next(
                    (i for i, line in enumerate(content_lines)
                     if line.startswith("## 摘要内容")),
                    len(content_lines)
                )
                lines.extend(content_lines[:header_end + 2])
                lines.append("---\n")

        active_path.write_text("\n".join(lines), encoding="utf-8")
