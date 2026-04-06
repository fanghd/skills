"""Summary generation for conversation turns."""

import re
from datetime import datetime, timezone
from typing import Optional


SUMMARY_PROMPT_TEMPLATE = """\
你是一个专业的对话分析助手。请根据以下对话轮次生成摘要。

### 用户输入
{user_message}

### 助手回复
{assistant_response}

### 请输出以下格式的摘要（严格遵守格式）：

## 摘要内容
[2-3 段精准概括，包含核心意图、关键信息、重要决策]

## 关键决策/行动项
[列出具体决策和后续行动项，如果没有则写"无"]

## 语义指纹
[8-15 个关键词/短语，用于后续语义匹配召回，一行一个]

要求：
1. 摘要要精炼，不超过 200 字
2. 语义指纹要覆盖技术关键词和主题关键词
3. 行动项要具体可执行
"""


class Summarizer:
    """Generates structured summaries from conversation turns."""

    def __init__(self, use_llm: bool = False):
        self.use_llm = use_llm  # When True, requires LLM API integration
        self.max_summary_length = 200

    def generate(self, user_message: str, assistant_response: str) -> dict:
        """
        Generate summary for a conversation turn.

        Returns dict with:
          - summary: str — the 2-3 paragraph summary
          - action_items: list[str] — decisions and action items
          - semantic_fingerprint: list[str] — keywords for recall matching
          - keywords: list[str] — extracted topic keywords
        """
        if self.use_llm:
            return self._generate_llm(user_message, assistant_response)
        return self._generate_fallback(user_message, assistant_response)

    def _generate_llm(self, user_message: str, assistant_response: str) -> dict:
        """Generate summary via LLM API. Stub — integrate your preferred LLM."""
        # Placeholder for LLM integration
        # Example with Anthropic:
        #
        # import anthropic
        # client = anthropic.Anthropic()
        # response = client.messages.create(
        #     model="claude-haiku-4-5-20251001",
        #     max_tokens=500,
        #     prompt=SUMMARY_PROMPT_TEMPLATE.format(
        #         user_message=user_message, assistant_response=assistant_response
        #     ),
        # )
        # return self._parse_llm_response(response.content[0].text)
        raise NotImplementedError(
            "LLM summarization not configured. Set use_llm=True and integrate your LLM provider, "
            "or use the default fallback summarization."
        )

    def _generate_fallback(self, user_message: str, assistant_response: str) -> dict:
        """Rule-based fallback summarization when LLM is unavailable."""
        # Extract first 2 sentences from user input as summary
        user_sentences = re.split(r'[。！？.!?\n]', user_message.strip())
        user_preview = '。'.join(s for s in user_sentences[:3] if s.strip())

        if len(user_preview) > self.max_summary_length:
            user_preview = user_preview[:self.max_summary_length] + "..."

        # Extract keywords from combined text
        combined = f"{user_message} {assistant_response}"
        keywords = self._extract_keywords(combined)

        return {
            "summary": f"[自动摘要] 用户询问/操作：{user_preview}",
            "action_items": ["无"],
            "semantic_fingerprint": keywords,
            "keywords": keywords[:8]
        }

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract meaningful keywords from text (CJK + English)."""
        # For English: extract words (filter common stopwords)
        english_stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "and",
            "but", "or", "nor", "not", "so", "yet", "both", "either",
            "neither", "each", "every", "all", "any", "few", "more",
            "most", "other", "some", "such", "no", "only", "own",
            "same", "than", "too", "very", "just", "because", "it",
            "that", "this", "these", "those", "what", "which", "who",
            "whom", "when", "where", "why", "how", "if", "then"
        }
        # Simple word tokenization for English
        words = re.findall(r'[a-zA-Z]{3,}', text.lower())
        english_keywords = [w for w in words if w not in english_stopwords]

        # For CJK: extract contiguous non-whitespace sequences
        cjk_parts = []
        for segment in re.split(r'\s+', text):
            # Keep meaningful CJK segments (length > 1)
            cjk_text = re.sub(r'[a-zA-Z0-9\s\-\[\]\{\}\(\)<>:"\'.,!?;]', '', segment)
            if len(cjk_text) > 1:
                cjk_parts.append(cjk_text)

        return english_keywords[:8] + cjk_parts[:7]

    @staticmethod
    def _parse_llm_response(text: str) -> dict:
        """Parse LLM-generated summary text into structured dict."""
        summary_match = re.search(
            r'## 摘要内容\s*\n(.*?)(?=## 关键决策)', text, re.DOTALL
        )
        actions_match = re.search(
            r'## 关键决策/行动项\s*\n(.*?)(?=## 语义指纹)', text, re.DOTALL
        )
        fingerprint_match = re.search(
            r'## 语义指纹\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL
        )

        summary = summary_match.group(1).strip() if summary_match else text[:200]
        action_items = []
        if actions_match:
            action_items = [
                line.strip().lstrip('-* ')
                for line in actions_match.group(1).strip().split('\n')
                if line.strip().startswith(('-', '*')) or line.strip() == '无'
            ]
        keywords = []
        if fingerprint_match:
            keywords = [
                line.strip().lstrip('-* ')
                for line in fingerprint_match.group(1).strip().split('\n')
                if line.strip() and not line.strip().startswith('#')
            ]

        return {
            "summary": summary,
            "action_items": action_items or ["无"],
            "semantic_fingerprint": keywords,
            "keywords": keywords[:8]
        }
