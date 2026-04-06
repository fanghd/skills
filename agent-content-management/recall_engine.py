"""Recall Engine — two-tier context recall (summary → transcript)."""

import math
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from config import Config
from index import IndexManager


class RecallMode(Enum):
    AUTO = "auto"
    SUMMARY = "summary"
    TRANSCRIPT = "transcript"


@dataclass
class RecallResult:
    summaries: list[dict] = field(default_factory=list)
    transcripts: list[dict] = field(default_factory=list)

    def inject_text(self) -> str:
        """Generate text to inject into the conversation context."""
        parts = []
        if self.summaries:
            parts.append("[召回的历史对话摘要]")
            for item in self.summaries:
                parts.append(
                    f"### {item['turn_id']} ({item['session_id']}) — 匹配度 {item['score']:.2f}"
                )
                parts.append(item["summary_content"])
                parts.append("")

        if self.transcripts:
            parts.append("[召回的历史对话原文]")
            for item in self.transcripts:
                parts.append(
                    f"### {item['turn_id']} ({item['session_id']}) — 匹配度 {item['score']:.2f}"
                )
                parts.append(item["transcript_content"])
                parts.append("")

        return "\n".join(parts) if parts else ""


TRANSCRIPT_TRIGGERS = [
    "之前", "刚才", "之前说的", "前面提到", "你刚才说", "你之前说",
    "上次说", "我们之前", "上面", "之前那个", "之前的",
    "具体内容", "完整", "原文", "代码", "文件内容",
    "那个是什么", "具体是什么", "详细内容", "详细说",
    "全文", "完整对话", "原始记录",
]


class RecallEngine:
    """Two-tier recall: summary by default, transcript when triggered."""

    def __init__(self, store_path: Path, config: Optional[Config] = None):
        self.config = config or Config()
        self.store_path = store_path
        self.index = IndexManager(store_path)

        recall_cfg = self.config.get("recall") or {}
        self.summary_threshold = recall_cfg.get("summary_threshold", 0.4)
        self.transcript_threshold = recall_cfg.get("transcript_threshold", 0.6)
        self.max_summary_returns = recall_cfg.get("max_summary_returns", 5)
        self.max_transcript_returns = recall_cfg.get("max_transcript_returns", 2)
        self.time_decay_factor = recall_cfg.get("time_decay_factor", 0.5)
        self.same_session_bonus = recall_cfg.get("same_session_bonus", 0.15)

    def recall(self, user_input: str, session_id: str = "default",
               mode: RecallMode = RecallMode.AUTO) -> RecallResult:
        """
        Recall relevant context for the given user input.

        Returns RecallResult with summaries (always) and transcripts
        (only when mode=TRANSCRIPT or auto-triggered).
        """
        user_tokens = self._tokenize(user_input)

        # Tier 1: summary-level recall
        candidates = self._summary_recall(user_tokens, session_id)

        # Should we escalate to full transcripts?
        need_transcripts = (
            mode == RecallMode.TRANSCRIPT
            or self._should_recall_transcript(user_input, candidates)
        )

        if need_transcripts:
            transcript_candidates = self._transcript_recall(candidates)
            return RecallResult(summaries=candidates, transcripts=transcript_candidates)

        return RecallResult(summaries=candidates, transcripts=[])

    def _summary_recall(self, user_tokens: set, session_id: str) -> list[dict]:
        """Search index for matching summaries."""
        results = []
        for sid, conv in self.index._data["conversations"].items():
            for turn in conv["turns"]:
                score = self._compute_relevance(
                    user_tokens, turn, session_id
                )
                if score > self.summary_threshold:
                    summary_content = self._load_summary(turn)
                    if summary_content:
                        results.append({
                            "session_id": sid,
                            "turn_id": turn["turn_id"],
                            "score": score,
                            "timestamp": turn["timestamp"],
                            "summary_content": summary_content,
                        })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:self.max_summary_returns]

    def _transcript_recall(self, candidates: list[dict]) -> list[dict]:
        """Load full transcripts for high-scoring candidates."""
        results = []
        for candidate in candidates:
            if candidate["score"] < self.transcript_threshold:
                continue
            if len(results) >= self.max_transcript_returns:
                break

            turn = self._find_turn(candidate["session_id"], candidate["turn_id"])
            if not turn:
                continue

            transcript_path = self.store_path / turn["transcript_path"]
            if transcript_path.exists():
                content = transcript_path.read_text(encoding="utf-8")
                results.append({
                    **candidate,
                    "transcript_content": content,
                })

        return results

    def _compute_relevance(self, user_tokens: set, turn: dict,
                           session_id: str) -> float:
        """
        Compute relevance score (0–1) from:
        - Jaccard keyword overlap: 40%
        - Time decay: 30%
        - TF-IDF cosine similarity: 30%
        - Same-session bonus: +0.15
        """
        doc_tokens = set(turn.get("keywords", []))
        fingerprint = set(turn.get("semantic_fingerprint", "").split())
        all_doc = doc_tokens | fingerprint

        jaccard = (
            len(user_tokens & all_doc) / len(user_tokens | all_doc)
            if (user_tokens | all_doc)
            else 0
        )

        hours_ago = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(turn["timestamp"])
        ).total_seconds() / 3600
        time_decay = math.exp(-self.time_decay_factor * hours_ago)

        # Simple term overlap as proxy for cosine
        if user_tokens:
            tfidf_proxy = len(user_tokens & all_doc) / len(user_tokens)
        else:
            tfidf_proxy = 0

        score = 0.4 * jaccard + 0.3 * time_decay + 0.3 * tfidf_proxy

        same_session = turn.get("session_id", session_id) == session_id
        if same_session:
            score += self.same_session_bonus

        return min(score, 1.0)

    def _should_recall_transcript(self, user_input: str,
                                   candidates: list[dict]) -> bool:
        """Decide whether to escalate from summary to transcript recall."""
        # Trigger word detection
        if any(t in user_input for t in TRANSCRIPT_TRIGGERS):
            return True

        # Low confidence on summary recall
        if candidates:
            top_score = max(c["score"] for c in candidates)
            if top_score < self.transcript_threshold:
                return True

        # Explicit user request
        explicit_words = ["全文", "完整对话", "原始记录", "全部"]
        if any(w in user_input for w in explicit_words):
            return True

        return False

    def _load_summary(self, turn: dict) -> Optional[str]:
        """Load summary content for a turn."""
        summary_path = self.store_path / turn["summary_path"]
        if not summary_path.exists():
            return None
        content = summary_path.read_text(encoding="utf-8")
        # Extract just the summary section
        match = re.search(
            r'## 摘要内容\s*\n(.*?)(?=##|$)', content, re.DOTALL
        )
        return match.group(1).strip() if match else content[:500]

    def _find_turn(self, session_id: str, turn_id: str) -> Optional[dict]:
        """Find a specific turn in the index."""
        conv = self.index._data["conversations"].get(session_id)
        if not conv:
            return None
        for turn in conv["turns"]:
            if turn["turn_id"] == turn_id:
                return turn
        return None

    @staticmethod
    def _tokenize(text: str) -> set:
        """Simple tokenization: CJK characters + English words (lowercased)."""
        tokens = set()
        # English words (3+ chars)
        tokens.update(w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text))
        # CJK: treat each contiguous CJK block as a token, or split into bigrams
        cjk_matches = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]+', text)
        for match in cjk_matches:
            if len(match) <= 2:
                tokens.add(match)
            else:
                tokens.add(match)
                for i in range(len(match) - 1):
                    tokens.add(match[i:i+2])
        # Numbers/identifiers
        tokens.update(re.findall(r'[a-zA-Z_]\w*', text))
        tokens.discard("")
        return tokens
