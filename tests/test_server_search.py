"""Offline: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_server_search."""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from usr.plugins.discord.helpers.bridge_reader import BridgeReader
from usr.plugins.discord.helpers.discord_bot import ChatBridgeBot


async def main():
    author = SimpleNamespace(id=456, display_name="Reporter", bot=False)
    other = SimpleNamespace(id=555, display_name="Reviewer", bot=False)
    guild = SimpleNamespace(id=789, me=SimpleNamespace(id=123), channels=[], get_member=lambda _: author)
    active = peak = 0
    day = datetime(2026, 9, 9, tzinfo=timezone.utc)

    class Channel:
        type = discord.ChannelType.text

        def __init__(self, number, visible=True):
            self.id, self.name, self.guild = number, f"channel-{number}", guild
            self.visible, self.items, self.calls = visible, [], 0
            self.fetch_message = AsyncMock(side_effect=lambda number: next(item for item in self.items if item.id == number))

        def permissions_for(self, _):
            return SimpleNamespace(view_channel=self.visible, read_message_history=self.visible)

        async def history(self, **kwargs):
            nonlocal active, peak
            self.calls += 1
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0)
                before, after = kwargs.get("before"), kwargs.get("after")
                items = sorted(self.items, key=lambda item: item.id, reverse=not kwargs.get("oldest_first"))
                items = [item for item in items if (before is None or item.id < before.id) and (after is None or item.id > after.id)]
                for item in items[:kwargs["limit"]]:
                    yield item
            finally:
                active -= 1

        def add(self, text, who=author, embeds=None):
            stamp = day + timedelta(minutes=len(self.items))
            number = discord.utils.time_snowflake(stamp) + self.id
            item = SimpleNamespace(id=number, content=text, author=who, created_at=stamp,
                                   jump_url=f"https://discord.com/channels/789/{self.id}/{number}",
                                   embeds=embeds or [], attachments=[], reference=None)
            self.items.append(item)
            return item

    channels = [Channel(number) for number in range(101, 152)]
    hidden = Channel(200, False)
    hidden.add("browser cache SECRET")
    guild.channels = channels + [hidden]
    config = {"servers": [789], "chat_bridge": {"allowed_users": [456]}}
    bot = SimpleNamespace(user=guild.me, _get_config=lambda: config,
                          get_channel=lambda number: next((channel for channel in guild.channels if channel.id == number), None))
    request = SimpleNamespace(guild=guild, channel=channels[0], author=author)
    reader = BridgeReader(bot, request)
    report = channels[0].add("browser cache problem")
    pr = channels[8].add("Fix: https://github.com/agent0ai/agent-zero/pull/1894", other)
    channels[8].add("<@123> !auth never-expose")
    channels[-1].add("evaluate returns null", other)
    base = {"action": "search", "scope": "server", "since": "2026-09-09", "until": "2026-09-13"}
    result = await reader.read({**base, "query_any": ["browser cache", "evaluate null"]})
    assert result["complete"] and len(result["checked_channel_ids"]) == 51
    assert len(result["matches"]) == 2 and result["scanned"] == 4
    assert 1 < peak <= 4 and active == 0
    assert hidden.calls == 0 and "SECRET" not in json.dumps(result)
    assert len(json.dumps(result)) < 4000, "Empty channels should not repeat filter/coverage payloads"
    assert "Not searched" in result["coverage"]["threads"]
    found = await reader.read({**base, "has_pr": True})
    assert [item["id"] for item in found["matches"]] == [str(pr.id)]

    exact = {"action": "messages", "channel_id": str(channels[8].id), "message_id": str(pr.id)}
    cached = await reader.read(exact)
    assert cached["cached"] and cached["messages"][0]["content"] == pr.content
    channels[8].fetch_message.assert_not_awaited()
    restored = BridgeReader(bot, request, reader.evidence)
    assert (await restored.read(exact))["cached"]
    channels[8].visible = False
    assert "error" in await restored.read(exact), "Cache must not bypass revoked visibility"
    channels[8].visible = True
    await reader.read({**exact, "refresh": True})
    channels[8].fetch_message.assert_awaited_once_with(pr.id)
    stale = [{**entry, "read_at": time.time() - 901} for entry in reader.evidence]
    assert not BridgeReader(bot, request, stale).evidence

    channels[1].add("embed-only link", other, [SimpleNamespace(title="Fix", description="", url="https://github.com/o/r/pull/2")])
    embedded = await reader.read({**base, "has_pr": True})
    assert len(embedded["matches"]) == 2
    quoted = await reader.read({"action": "search", "channel_id": "101", "query": '"browser cache"'})
    assert quoted["matches"][0]["id"] == str(report.id)
    assert "error" in await reader.read({**base, "query_any": "browser"})
    assert "error" in await reader.read({**base, "has_pr": "true"})

    for channel in channels:
        channel.items.clear()
    for index in range(9):
        channels[0].add(f"browser cache report {index}")
    query = {**base, "query": "browser", "scan_limit": 8, "limit": 2, "order": "oldest"}
    ids, cursor, rounds = [], None, 0
    while True:
        page = await reader.read({**query, **({"cursor": cursor} if cursor else {})})
        assert "error" not in page, page
        assert page["scanned"] <= 8 and len(page["matches"]) <= 2
        ids.extend(item["id"] for item in page["matches"])
        cursor = page["next_cursor"]
        rounds += 1
        assert rounds < 15, "Continuation must advance through partial and empty channels"
        if not cursor:
            assert page["complete"]
            break
        if rounds == 1:
            assert "error" in await reader.read({**query, "query": "different", "cursor": cursor})
    assert len(ids) == len(set(ids)) == 9

    # More than one server window, even when all channels are empty.
    guild.channels = [Channel(number) for number in range(1000, 1070)]
    first = await reader.read(base)
    second = await reader.read({**base, "cursor": first["next_cursor"]})
    assert len(first["checked_channel_ids"]) == 64 and len(second["checked_channel_ids"]) == 6
    assert second["complete"]
    guild.channels[0].history = AsyncMock(side_effect=ValueError("temporarily unavailable"))
    # Raise while constructing the history iterator, like a revoked/unavailable target.
    def unavailable(**_):
        raise ValueError("temporarily unavailable")
    guild.channels[0].history = unavailable
    failed = await reader.read(base)
    assert failed["errors"][0]["channel_id"] == "1000" and not failed["complete"]

    key = ChatBridgeBot._read_request_key
    assert key({"message_id": 123}) == key({"action": "messages", "message_id": "123", "progress": "Working"})
    checkpoint = ChatBridgeBot._read_checkpoint(query, first)
    assert checkpoint["next_cursor"] == first["next_cursor"]
    evidence = ChatBridgeBot._read_checkpoint(exact, cached)
    assert evidence["message_id"] == str(pr.id) and evidence["evidence"][0]["id"] == str(pr.id)
    config["chat_bridge"]["allowed_users"] = [999]
    assert "error" in await reader.read(base)
    assert "error" in await reader.read(exact)
    print("PASS: bounded concurrent server sweeps, compact coverage, resumable cursors, OR/phrase/PR filters, evidence cache and permissions")


if __name__ == "__main__":
    asyncio.run(main())
