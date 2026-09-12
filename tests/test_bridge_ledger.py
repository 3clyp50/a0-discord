"""Offline check: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_bridge_ledger."""
import json

from usr.plugins.discord.helpers.discord_bot import ChatBridgeBot


def main():
    bot = object.__new__(ChatBridgeBot)
    request = {"action": "search", "channel_id": "#general", "query": "OpenCode", "since": "2026-06-18", "until": "2026-06-19", "order": "oldest"}
    assert ChatBridgeBot._read_request_key(request) == ChatBridgeBot._read_request_key(dict(reversed(list(request.items()))))
    summary = ChatBridgeBot._read_checkpoint(request, {
        "matches": [{"id": "1"}], "scanned": 415, "complete": True, "coverage": "Range exhausted.",
    })
    assert summary["matches"] == 1 and summary["scanned"] == 415
    bot.MAX_READ_LEDGER_PROMPT_ENTRIES = 2
    text = bot._format_read_ledger([{"key": str(i), "summary": {"target": str(i)}} for i in range(3)])
    assert '"target": "0"' not in text and '"target": "2"' in text
    result = {"coverage": "x", "matches": [{"excerpt": "x" * 1000} for _ in range(20)]}
    compact = json.loads(bot._bounded_tool_result(result, 300))
    assert compact["truncated_for_model"] and len(compact.get("matches", [])) <= 3
    assert "budget reached" in ChatBridgeBot._bounded_tool_result(result, 0)
    print("PASS: persistent checkpoints, duplicate keys and bounded tool context")


if __name__ == "__main__":
    main()
