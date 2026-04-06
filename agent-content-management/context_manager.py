#!/usr/bin/env python3
"""Context Manager — unified CLI for agent content management.

Usage:
    python context_manager.py --store [--user-input "..." --assistant-output "..." --session-id "..." ]
    python context_manager.py --recall <query> [--session-id "..." --mode auto|summary|transcript]
    python context_manager.py --check [--current-estimated-tokens N]
    python context_manager.py --compress
    python context_manager.py --search <keyword>
    python context_manager.py --list
    python context_manager.py --history
    python context_manager.py --init
"""

import argparse
import json
import os
import sys
from pathlib import Path

from config import Config
from store_engine import StoreEngine
from recall_engine import RecallEngine, RecallMode
from context_monitor import ContextMonitor


def get_default_store_path() -> Path:
    return Path(os.path.expanduser("~/.openclaw/workspace/context-store/"))


def cmd_init(args):
    """Initialize the context store."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path
    for subdir in ["summaries", "transcripts"]:
        (store_path / subdir).mkdir(parents=True, exist_ok=True)

    # Save default config if not exists
    config_path = store_path / "context_config.json"
    if not config_path.exists():
        config.save(config_path)

    # Initialize empty compression log
    (store_path / "compression_log.md").write_text(
        "# 上下文压缩日志\n\n| 时间 | 触发前使用率 | 压缩后使用率 | 归档轮次 | 方式 |\n|------|-------------|-------------|---------|------|\n",
        encoding="utf-8"
    )
    # Initialize active summaries
    (store_path / "active_summaries.md").write_text(
        "# Active Summaries\n\n暂无活跃对话。\n", encoding="utf-8"
    )
    print(f"Context store initialized at: {store_path}")
    print(f"  - summaries/")
    print(f"  - transcripts/")
    print(f"  - index.json")
    print(f"  - compression_log.md")
    print(f"  - active_summaries.md")


def cmd_store(args):
    """Store a conversation turn."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path
    engine = StoreEngine(store_path, config)

    session_id = args.session_id or os.environ.get("CLAUDE_SESSION_ID", "default")
    user_input = args.user_input or ""
    assistant_output = args.assistant_output or ""

    # Try reading from stdin if not provided
    if not user_input and not sys.stdin.isatty():
        try:
            data = json.loads(sys.stdin.read())
            user_input = data.get("user_input", "")
            assistant_output = data.get("assistant_output", "")
            session_id = data.get("session_id", session_id)
        except (json.JSONDecodeError, KeyError):
            pass

    if not user_input or not assistant_output:
        print("Error: --user-input and --assistant-output are required for --store")
        sys.exit(1)

    tool_calls = None
    if args.tool_calls:
        try:
            tool_calls = json.loads(args.tool_calls)
        except json.JSONDecodeError:
            pass

    result = engine.store_turn(user_input, assistant_output, session_id, tool_calls)
    print(f"Stored turn: {result['turn_id']} (session: {session_id})")
    print(f"  Summary:  {result['summary_path']}")
    print(f"  Transcript: {result['transcript_path']}")
    print(f"  Tokens:     {result['tokens']}")


def cmd_recall(args):
    """Recall context for a query."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path
    engine = RecallEngine(store_path, config)

    session_id = args.session_id or os.environ.get("CLAUDE_SESSION_ID", "default")
    mode_str = args.mode or "auto"
    mode_map = {
        "auto": RecallMode.AUTO,
        "summary": RecallMode.SUMMARY,
        "transcript": RecallMode.TRANSCRIPT,
    }
    mode = mode_map.get(mode_str, RecallMode.AUTO)

    result = engine.recall(args.query, session_id, mode)

    output = {"summaries": [], "transcripts": []}
    for s in result.summaries:
        output["summaries"].append({
            "session_id": s["session_id"],
            "turn_id": s["turn_id"],
            "score": round(s["score"], 3),
            "summary": s["summary_content"][:200]
        })
    for t in result.transcripts:
        output["transcripts"].append({
            "session_id": t["session_id"],
            "turn_id": t["turn_id"],
            "score": round(t["score"], 3),
        })

    # Print injectable context
    inject_text = result.inject_text()
    if inject_text:
        print(inject_text)
    else:
        print("[No relevant context found]")


def cmd_check(args):
    """Check current context token usage."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path
    from index import IndexManager

    if args.current_estimated_tokens:
        total = args.current_estimated_tokens
    else:
        total = IndexManager(store_path).get_total_tokens()

    max_context = config.get("compression", "model_max_context", default=200000)
    ratio = total / max_context

    status = ""
    if ratio >= 0.80:
        status = "[COMPRESS] threshold exceeded"
    elif ratio >= 0.70:
        status = "[WARNING] approaching threshold"
    else:
        status = "OK"

    print(f"Context usage: {total:,} / {max_context:,} tokens ({ratio:.0%}) - {status}")


def cmd_compress(args):
    """Force or report compression status."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path
    monitor = ContextMonitor(store_path, config)
    print(f"Compression configured:")
    print(f"  Warning threshold:   {monitor.warning_threshold:.0%}")
    print(f"  Compress threshold:  {monitor.compress_threshold:.0%}")
    print(f"  Target after:        {monitor.target_after_compress:.0%}")
    print(f"  Recent turns to keep: {monitor.recent_turns_to_keep}")
    print(f"  Max context:         {monitor.max_context:,}")


def cmd_search(args):
    """Search index for keyword."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path
    engine = RecallEngine(store_path, config)

    results = engine.index.search([args.keyword])
    if not results:
        print(f"No results for '{args.keyword}'")
        return

    print(f"Search results for '{args.keyword}' ({len(results)} found):")
    for r in results:
        print(f"  [{r['score']:.2f}] {r['session_id']}/{r['turn_id']} "
              f"(keywords: {', '.join(r.get('keywords', []))})")


def cmd_list(args):
    """List all sessions."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path
    from index import IndexManager
    sessions = IndexManager(store_path).list_sessions()
    if not sessions:
        print("No sessions found.")
        return

    print(f"Sessions ({len(sessions)}):")
    for s in sessions:
        print(f"  {s['session_id']}")
        print(f"    Created:     {s['created_at']}")
        print(f"    Last active: {s['last_activity']}")
        print(f"    Turns:       {s['total_turns']}")
        print(f"    Tokens:      {s['total_tokens']:,}")
        print()


def cmd_history(args):
    """Show recent active summaries."""
    config = Config(args.config) if args.config else Config()
    store_path = config.store_path

    active_path = store_path / "active_summaries.md"
    if active_path.exists():
        print(active_path.read_text(encoding="utf-8"))
    else:
        print("No active summaries found. Has a conversation turn been stored yet?")


def main():
    parser = argparse.ArgumentParser(
        description="Agent Content Management — context store, recall, and compression"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Shared --config via parent parser
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--config", default=None, help="Path to context_config.json")

    def add_subparser(name, help_text):
        p = subparsers.add_parser(name, help=help_text, parents=[config_parser])
        return p

    # --init
    add_subparser("init", "Initialize context store")

    # --store
    store_p = add_subparser("store", "Store a conversation turn")
    store_p.add_argument("--user-input", default="", help="User message content")
    store_p.add_argument("--assistant-output", default="", help="Assistant response content")
    store_p.add_argument("--session-id", default=None, help="Session identifier")
    store_p.add_argument("--tool-calls", default=None, help="JSON string of tool calls")

    # --recall
    recall_p = add_subparser("recall", "Recall context for a query")
    recall_p.add_argument("query", help="Search query for context recall")
    recall_p.add_argument("--session-id", default=None, help="Session identifier")
    recall_p.add_argument("--mode", choices=["auto", "summary", "transcript"],
                          default="auto", help="Recall mode")

    # --check
    check_p = add_subparser("check", "Check context token usage")
    check_p.add_argument("--current-estimated-tokens", type=int, default=None,
                         help="Current estimated token count")

    # --compress
    add_subparser("compress", "Show compression configuration")

    # --search
    search_p = add_subparser("search", "Search index by keyword")
    search_p.add_argument("keyword", help="Keyword to search")

    # --list
    add_subparser("list", "List all sessions")

    # --history
    add_subparser("history", "Show recent active summaries")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    def get_config():
        return Config(args.config) if args.config else Config()

    commands = {
        "init": cmd_init,
        "store": cmd_store,
        "recall": cmd_recall,
        "check": cmd_check,
        "compress": cmd_compress,
        "search": cmd_search,
        "list": cmd_list,
        "history": cmd_history,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
