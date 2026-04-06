---
name: agent-content-management
description: Use when managing agent conversation context via file-based storage, recall, and compression. Use when context window approaches 80% capacity, when needing to recall past conversations by keyword, when conversation persistence is required, or when coordinating with Claude Code's built-in context compression.
---

# Agent Content Management

File-based context store with summary+transcript storage, two-tier recall, and 80%-threshold compression that complements Claude Code's internal context management.

## Architecture

```
PreUserMessage Hook          PostToolUse Hook
       │                           │
       ▼                           ▼
┌──────────────┐           ┌──────────────┐
│ RecallEngine │           │ StoreEngine  │
│  摘要召回     │           │ 摘要+原文存储  │
│  (必要时原文)│           │              │
└──────────────┘           └──────────────┘
       ▲                           ▲
       │                           │
       └──────── ContextManager ───┘
                       │
                       ▼
               ┌──────────────┐
               │ContextMonitor│
               │  80%压缩阈值  │
               └──────────────┘
```

## Core Pattern

**Three-phase lifecycle per conversation turn:**

1. **Recall** (user sends message) → Search index, inject summaries or full transcripts
2. **Monitor** (before response) → Check token usage, compress if >80%
3. **Store** (turn complete) → Generate summary, save transcript, update index

Two-tier recall:
- **Tier 1 (default):** Summary-only recall via keyword matching
- **Tier 2 (triggered):** Full transcript recall when user references past content or top score < 0.6

## When to Use

- Context window approaches 80% — automatic compression needed
- Recalling past conversations by topic/keyword rather than scrolling
- Long-running sessions where context overflow is a risk
- Building skills that need access to conversation history across sessions

## Quick Reference

| Command | Purpose |
|---------|---------|
| `--store` | Store current turn (summary + transcript) |
| `--recall <query>` | Recall context for query (auto mode) |
| `--recall --mode summary <query>` | Summary-only recall |
| `--recall --mode transcript <query>` | Full transcript recall |
| `--check` | Check current token usage |
| `--compress` | Force context compression |
| `--search <keyword>` | Search index for keyword |
| `--list` | List all sessions |
| `--history` | Show recent active summaries |

## Implementation

This skill includes these files:

- `context_manager.py` — Main entry point, unified CLI
- `store_engine.py` — Conversation storage (summary + transcript)
- `recall_engine.py` — Two-tier recall engine
- `context_monitor.py` — Token monitoring and compression
- `index.py` — Semantic index management
- `summarizer.py` — LLM-based summary generation
- `config.py` — Configuration loader
- `context_config.json` — Default configuration

See `IMPLEMENTATION.md` for the full implementation plan with file-by-file code and task breakdown.

## Claude Code Integration

Configure in `settings.json` hooks:

```json
{
  "hooks": {
    "PostToolUse": [{
      "type": "exec",
      "command": "python context_manager.py --store"
    }],
    "PreResponse": [{
      "type": "exec",
      "command": "python context_manager.py --check"
    }]
  }
}
```

Recall is called automatically by ContextManager during message processing — no separate hook needed.

## Compression Strategy (Coordinated with Claude Code)

Claude Code handles internal message compression autonomously. This system handles **external storage and recall management**:

```
Layer 1: Claude Code internal compression (automatic, don't interfere)
Layer 2: Our StoreEngine → removes recalled content from context when archived
Layer 3: Our RecallEngine → limits active summaries to recent 5 turns
Target: Keep context < 60% after compression (threshold at 80%)
```
