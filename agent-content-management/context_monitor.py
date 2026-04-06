"""Context Monitor — token estimation and compression at 80% threshold."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import Config
from index import IndexManager


@dataclass
class CompressResult:
    action: str  # "none", "warn", "compressed"
    ratio: float
    compressed_context: Optional[list] = None
    archived_turns: int = 0
    compression_ratio: float = 0.0
    log_entry: str = ""


# Thresholds
WARNING_THRESHOLD = 0.70
COMPRESS_THRESHOLD = 0.80
TARGET_AFTER_COMPRESS = 0.60
RECENT_TURNS_TO_KEEP = 4


class ContextMonitor:
    """Monitors context usage and triggers compression at 80%."""

    def __init__(self, store_path: Path, config: Optional[Config] = None):
        self.config = config or Config()
        self.store_path = store_path
        self.index = IndexManager(store_path)
        self.compression_log_path = store_path / "compression_log.md"

        comp_cfg = self.config.get("compression") or {}
        self.warning_threshold = comp_cfg.get("warning_threshold", WARNING_THRESHOLD)
        self.compress_threshold = comp_cfg.get("compress_threshold", COMPRESS_THRESHOLD)
        self.target_after_compress = comp_cfg.get("target_after_compress", TARGET_AFTER_COMPRESS)
        self.recent_turns_to_keep = comp_cfg.get("recent_turns_to_keep", RECENT_TURNS_TO_KEEP)
        self.max_context = comp_cfg.get("model_max_context", 200000)

    def estimate_tokens(self, conversation: list[dict]) -> int:
        """
        Estimate token count for the conversation.
        Counts characters: ~4 chars per token for mixed CJK/English.
        """
        total = 0
        for msg in conversation:
            content = msg.get("content", "")
            total += len(content)
            if "tool_calls" in msg:
                total += len(str(msg["tool_calls"]))
        return max(1, total // 4)

    def check_and_compress(self, conversation: list[dict]) -> CompressResult:
        """
        Check current context usage. Returns CompressResult:
        - action="none"  : under threshold, no action needed
        - action="warn"  : approaching threshold (70%+)
        - action="compressed" : compressed to bring back under target
        """
        token_estimate = self.estimate_tokens(conversation)
        ratio = token_estimate / self.max_context

        if ratio >= self.compress_threshold:
            return self._compress(conversation, ratio)
        elif ratio >= self.warning_threshold:
            return CompressResult(
                action="warn",
                ratio=ratio,
                log_entry=f"[WARN] Context at {ratio:.0%} — approaching compression threshold"
            )
        return CompressResult(action="none", ratio=ratio)

    def _compress(self, conversation: list[dict],
                  before_ratio: float) -> CompressResult:
        """
        Compress the conversation context.

        Strategy:
        1. Keep system messages
        2. Keep the most recent N turns intact
        3. Replace older turns with a compression summary
        4. Update compression log
        """
        # Separate system messages from the rest
        system_msgs = [m for m in conversation if m.get("role") == "system"]
        non_system = [m for m in conversation if m.get("role") != "system"]

        # Keep most recent turns
        turn_msg_count = len(non_system)  # user + assistant pairs
        recent_count = self.recent_turns_to_keep * 2  # user + assistant for N turns
        older = non_system[:-recent_count] if turn_msg_count > recent_count else []
        recent = non_system[-recent_count:] if turn_msg_count > recent_count else non_system

        if older:
            # Generate compression summary for older turns
            turn_pairs = len(older) // 2
            summary = self._generate_compression_summary(older, turn_pairs)
            summary_msg = {
                "role": "system",
                "content": (
                    f"[上下文压缩摘要 - 包含 {turn_pairs} 轮已归档对话的浓缩信息]\n\n"
                    f"{summary}\n\n"
                    f"以上对话的完整原文存储在外部文件中，可通过 recall 功能召回。"
                )
            }
            compressed = system_msgs[:1] + [summary_msg] + recent
        else:
            compressed = system_msgs + recent

        after_tokens = self.estimate_tokens(compressed)
        after_ratio = after_tokens / self.max_context
        archived_turns = len(older) // 2 if older else 0

        log_entry = self._log_compression(
            before_ratio, after_ratio, archived_turns
        )

        return CompressResult(
            action="compressed",
            ratio=after_ratio,
            compressed_context=compressed,
            archived_turns=archived_turns,
            compression_ratio=1 - (len(compressed) / len(conversation)),
            log_entry=log_entry
        )

    def _generate_compression_summary(self, older_messages: list, turn_count: int) -> str:
        """Generate a dense summary of older conversation turns."""
        user_messages = [m["content"] for m in older_messages if m.get("role") == "user"]
        lines = [f"已压缩 {turn_count} 轮对话的摘要："]
        for i, content in enumerate(user_messages[:5]):  # Summarize up to 5 user messages
            preview = content[:50].strip()
            if len(content) > 50:
                preview += "..."
            lines.append(f"  {i+1}. {preview}")
        if len(user_messages) > 5:
            lines.append(f"  ... 以及 {len(user_messages) - 5} 轮更早的对话")
        return "\n".join(lines)

    def _log_compression(self, before: float, after: float,
                         archived_turns: int) -> str:
        """Append compression entry to log file."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        entry = (
            f"| {now} | {before:.0%} | {after:.0%} | {archived_turns} | 分级压缩 |"
        )

        header = "# 上下文压缩日志\n\n| 时间 | 触发前使用率 | 压缩后使用率 | 归档轮次 | 方式 |\n|------|-------------|-------------|---------|------|\n"
        existing = ""
        if self.compression_log_path.exists():
            existing = self.compression_log_path.read_text(encoding="utf-8")
            # Remove header if it exists to avoid duplicates
            existing = re.sub(r'^# 上下文压缩日志\n\n.*?\|------\|.*?\|.*?\|\n?', '', existing, flags=re.MULTILINE)

        content = header + entry + "\n" + existing.strip() + "\n"
        self.compression_log_path.write_text(content, encoding="utf-8")
        return entry
