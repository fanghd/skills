# Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build a file-based context store for agent conversations with two-tier recall and 80%-threshold compression.

**Architecture:** Three engines (Store, Recall, Monitor) + Index Manager + Summarizer, orchestrated via ContextManager CLI. Integrates with Claude Code hooks for automatic lifecycle management.

**Tech Stack:** Python 3.10+, file-based storage (Markdown + JSON), no external dependencies beyond stdlib + optional LLM API.

---

## Files Overview

| File | Responsibility | Status |
|------|---------------|--------|
| `SKILL.md` | Skill reference guide | Ready |
| `context_manager.py` | Unified CLI entry point | Ready |
| `store_engine.py` | Turn storage (summary + transcript) | Ready |
| `recall_engine.py` | Two-tier recall engine | Ready |
| `context_monitor.py` | Token monitoring + compression | Ready |
| `index.py` | Semantic index management | Ready |
| `summarizer.py` | Summary generation (LLM + fallback) | Ready |
| `config.py` | Configuration loader | Ready |
| `context_config.json` | Default configuration | Ready |

All implementation files are **already written** above — this file documents the testing and integration steps.

---

## Task 1: Smoke Test — Initialize and Store

**Files:** `context_manager.py`, `store_engine.py`, `config.py`, `index.py`

- [ ] Initialize the context store

```bash
cd agent-content-management-skill
python context_manager.py init --config context_config.json
```

Expected output:
```
Context store initialized at: /path/to/context-store/
  - summaries/
  - transcripts/
  - index.json
  - compression_log.md
  - active_summaries.md
```

Verify created files:
```bash
ls ~/.openclaw/workspace/context-store/
# Should show: summaries/ transcripts/ index.json compression_log.md active_summaries.md
```

- [ ] Store a test conversation turn

```bash
python context_manager.py store \
    --user-input "帮我设计一个数据库架构" \
    --assistant-output "我建议采用微服务架构，使用 PostgreSQL 作为主数据库..." \
    --session-id "test-session-001" \
    --config context_config.json
```

Expected output:
```
Stored turn: turn_001 (session: test-session-001)
  Summary:  summaries/20260406_HHMMSS.md
  Transcript: transcripts/20260406_HHMMSS.md
  Tokens:     ~45
```

- [ ] Store a second turn in the same session

```bash
python context_manager.py store \
    --user-input "这个方案的性能如何？需要考虑哪些优化点？" \
    --assistant-output "主要优化点包括：索引优化、分库分表、查询缓存、读写分离..." \
    --session-id "test-session-001" \
    --config context_config.json
```

- [ ] Verify index.json was updated

```bash
cat ~/.openclaw/workspace/context-store/index.json
```

Should show 2 turns under `test-session-001` with keywords and fingerprints.

---

## Task 2: Recall Engine Tests

**Files:** `recall_engine.py`

- [ ] Test summary recall with relevant query

```bash
python context_manager.py recall "数据库架构设计方案" --session-id test-session-001 --config context_config.json
```

Expected: Returns turn_001 and turn_002 summaries with scores > 0.4

- [ ] Test transcript recall (explicit trigger)

```bash
python context_manager.py recall "之前说的数据库设计方案是什么来着？" --session-id test-session-001 --mode transcript --config context_config.json
```

Expected: Returns full transcript for turn_001 (trigger word "之前" + "设计")

- [ ] Test no-match scenario

```bash
python context_manager.py recall "今天的天气怎么样" --session-id test-session-001 --config context_config.json
```

Expected: "[No relevant context found]"

---

## Task 3: Compression Tests

**Files:** `context_monitor.py`

- [ ] Check compression configuration

```bash
python context_manager.py compress --config context_config.json
```

Expected output:
```
Compression configured:
  Warning threshold:   70%
  Compress threshold:  80%
  Target after:        60%
  Recent turns to keep: 4
  Max context:         200,000
```

- [ ] Check current token usage

```bash
python context_manager.py check --current-estimated-tokens 165000 --config context_config.json
```

Expected:
```
Context usage: 165,000 / 200,000 tokens (82%) — ⚠ COMPRESS — threshold exceeded
```

- [ ] Verify low usage case

```bash
python context_manager.py check --current-estimated-tokens 40000 --config context_config.json
```

Expected:
```
Context usage: 40,000 / 200,000 tokens (20%) — OK
```

---

## Task 4: Search and History

**Files:** `index.py`

- [ ] Search by keyword

```bash
python context_manager.py search "数据库" --config context_config.json
```

Expected: Lists matching turns with scores.

- [ ] List sessions

```bash
python context_manager.py list --config context_config.json
```

Expected: Shows `test-session-001` with 2 turns.

- [ ] View active summaries

```bash
python context_manager.py history --config context_config.json
```

Expected: Shows the active_summaries.md content.

---

## Task 5: Claude Code Integration

**Files:** `settings.json`(Claude Code workspace)

- [ ] Configure hooks in your Claude Code workspace `settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "type": "exec",
        "command": "python ~/.openclaw/workspace/skills/agent-content-management-skill/context_manager.py store --user-input '{PROMPT}' --assistant-output '{LAST_MODEL_RESPONSE}' --session-id '{SESSION_ID}'"
      }
    ],
    "PreResponse": [
      {
        "type": "exec",
        "command": "python ~/.openclaw/workspace/skills/agent-content-management-skill/context_manager.py check"
      }
    ]
  }
}
```

Note: Replace hook variable placeholders with actual Claude Code hook variables. Consult `claude code settings` documentation for the available context variables.

---

## Task 6: Long-Term Usage

- [ ] Store at least 10 conversation turns to simulate realistic usage
- [ ] Verify active_summaries.md shows only the most recent 10
- [ ] Verify index.json contains all entries
- [ ] Run clean up (remove entries > 90 days old)

```python
from index import IndexManager
from pathlib import Path
index = IndexManager(Path("~/.openclaw/workspace/context-store/").expanduser())
removed = index.cleanup_old_entries(max_age_days=1)  # Use 1 day to test
print(f"Removed {removed} old entries")
```

---

## Commit

```bash
git add agent-content-management-skill/
git commit -m "feat: agent content management skill — file-based context store with recall and compression"
```
