---
name: agent-content-management
description: Use when managing agent conversation context via file-based storage, recall, and compression. Use when context window approaches 80% capacity, when needing to recall past conversations by keyword, when conversation persistence is required, or when cross-session context retrieval is needed. Works with any agent platform (Claude Code, OpenClaw, etc.).
---

# Agent Content Management

File-based context store with summary+transcript storage, two-tier recall, and 80%-threshold compression. Platform-agnostic — works with any AI agent runtime.

## Architecture

```
Agent Runtime (any)         Storage Layer
┌──────────────────┐        ┌─────────────────────────┐
│  Pre-message     │        │  File System Store        │
│  ┌─────────────┐ │        │                         │
│  │ Recall      │─┼───────▶│  ┌───────────────────┐  │
│  │ Engine      │ │        │  │ summaries/        │  │
│  └─────────────┘ │        │  │ transcripts/      │  │
│                  │        │  │ index.json         │  │
│  Post-response   │        │  │ compression_log.md │  │
│  ┌─────────────┐ │        │  │ active_summaries.md│  │
│  │ Store       │─┼───────▶│  └───────────────────┘  │
│  │ Engine      │ │        └─────────────────────────┘
│  └─────────────┘ │
│  ┌─────────────┐ │
│  │ Context     │ │
│  │ Monitor     │ │
│  └─────────────┘ │
└──────────────────┘
```

## Core Pattern

**Three-phase lifecycle per conversation turn:**

1. **Recall** (user sends message) → Search index, inject summaries or full transcripts
2. **Monitor** (before/after response) → Check token usage, compress if >80%
3. **Store** (turn complete) → Generate summary, save transcript, update index

Two-tier recall:
- **Tier 1 (default):** Summary-only recall via keyword matching
- **Tier 2 (triggered):** Full transcript recall when user references past content or top score < 0.6

## When to Use

- Context window approaches 80% — automatic compression needed
- Recalling past conversations by topic/keyword rather than scrolling
- Long-running sessions where context overflow is a risk
- Cross-session context retrieval needed
- Agent needs persistent memory across restarts

## Quick Reference

| Command | Purpose |
|---------|---------|
| `init` | Initialize context store |
| `store` | Store current turn (summary + transcript) |
| `recall <query>` | Recall context for query (auto mode) |
| `check` | Check current token usage |
| `compress` | Show compression configuration |
| `search <keyword>` | Search index for keyword |
| `list` | List all sessions |
| `history` | Show recent active summaries |

## Implementation

This skill includes these files:

- `context_manager.py` — Main entry point, unified CLI
- `store_engine.py` — Conversation storage (summary + transcript)
- `recall_engine.py` — Two-tier recall engine
- `context_monitor.py` — Token monitoring and compression
- `index.py` — Semantic index management
- `summarizer.py` — Summary generation (LLM placeholder + rule-based fallback)
- `config.py` — Configuration loader
- `context_config.json` — Default configuration

## Platform Integration

### Claude Code

Use `hooks` in `settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [{
      "type": "exec",
      "command": "python agent-content-management/context_manager.py store"
    }],
    "PreResponse": [{
      "type": "exec",
      "command": "python agent-content-management/context_manager.py check"
    }]
  }
}
```

### OpenClaw

Configure in OpenClaw's hook system:

```yaml
hooks:
  on_message: python agent-content-management/context_manager.py recall "{query}"
  on_response: python agent-content-management/context_manager.py store
```

### Manual / Programmatic

```bash
# Initialize
python context_manager.py init --config context_config.json

# Store a turn
python context_manager.py store \
    --user-input "用户输入" \
    --assistant-output "助手回复" \
    --session-id "my-session-id"

# Recall
python context_manager.py recall "查询关键词" \
    --session-id "my-session-id" \
    --mode auto

# API (Python)
from context_manager import ContextManager
cm = ContextManager()
cm.on_conversation_complete("用户消息", "回复内容", "session-id")
result = cm.on_new_message("新问题", "session-id")
```

## Compression Strategy

Agent platforms handle internal context management autonomously. This system handles **external storage and recall management**:

```
Layer 1: Platform's internal compression (automatic, don't interfere)
Layer 2: StoreEngine → removes recalled content from context when archived
Layer 3: RecallEngine → limits active summaries to recent 5 turns
Target: Keep context < 60% after compression (threshold at 80%)
```

## Configuration

Override defaults via `context_config.json`:

```json
{
  "store_path": "~/.agent-context-store/",
  "recall": {
    "summary_threshold": 0.4,
    "transcript_threshold": 0.6,
    "max_summary_returns": 5,
    "max_transcript_returns": 2
  },
  "compression": {
    "warning_threshold": 0.70,
    "compress_threshold": 0.80,
    "target_after_compress": 0.60,
    "model_max_context": 200000
  }
}
```

Session ID resolution (in order):
1. `--session-id` CLI argument
2. `AGENT_SESSION_ID` environment variable
3. `CLAUDE_SESSION_ID` environment variable
4. `OPENCLAW_SESSION_ID` environment variable
5. Falls back to `"default"`
