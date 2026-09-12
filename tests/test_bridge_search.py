"""Offline check: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_bridge_search."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import discord

from usr.plugins.discord.helpers.bridge_reader import BridgeReader


async def main():
    author = SimpleNamespace(id=456, display_name="Reporter", bot=False)
    other = SimpleNamespace(id=555, display_name="Other", bot=False)
    bot_author = SimpleNamespace(id=123, display_name="Bot", bot=True)
    guild = SimpleNamespace(id=789, me=bot_author, channels=[], get_member=Mock(return_value=author))
    day = datetime(2026, 6, 18, tzinfo=timezone.utc)
    items = []

    def message(stamp, text, who=author):
        number = discord.utils.time_snowflake(stamp) + 42
        return SimpleNamespace(id=number, content=text, author=who, created_at=stamp,
                               jump_url=f"https://discord.com/channels/789/101/{number}",
                               embeds=[], attachments=[], reference=None)

    class Channel:
        id, name, type = 101, "general", discord.ChannelType.text

        def __init__(self, visible=True):
            self.guild, self.visible, self.calls = guild, visible, []

        def permissions_for(self, member):
            return SimpleNamespace(view_channel=self.visible, read_message_history=self.visible)

        async def history(self, **kwargs):
            self.calls.append(kwargs)
            before, after = kwargs.get("before"), kwargs.get("after")
            selected = sorted(items, key=lambda m: m.id, reverse=not kwargs.get("oldest_first", False))
            selected = [m for m in selected if (before is None or m.id < before.id) and (after is None or m.id > after.id)]
            for item in selected[:kwargs["limit"]]:
                yield item

    channel, hidden = Channel(), Channel(False)
    hidden.id, hidden.name = 202, "private"
    guild.channels = [channel, hidden]
    config = {"servers": [789], "chat_bridge": {"allowed_users": [456]}}
    bot = SimpleNamespace(user=bot_author, _get_config=lambda: config,
                          get_channel=lambda n: {101: channel, 202: hidden}.get(n))
    request = SimpleNamespace(guild=guild, channel=channel, author=author)
    reader = BridgeReader(bot, request)
    target = message(day + timedelta(hours=12), "Released OpenCode Go: https://example.com/a0_opencode_go")
    items.extend(message(day + timedelta(seconds=i), "unrelated chatter " + "x" * 1000) for i in range(850))
    items.extend([
        message(day - timedelta(days=1), "OpenCode Go outside the day"),
        message(day + timedelta(days=1), "OpenCode Go at the exclusive end"),
        message(day + timedelta(hours=1), "OpenCode Go from another author", other),
        message(day + timedelta(hours=2), "OpenCode Go repeated by bot", bot_author),
        message(day + timedelta(hours=3), "<@123>!auth OpenCode Go never-expose"),
        target,
    ])
    query = {"action": "search", "channel_id": "#general", "query": "OpenCode Go",
             "author_id": "me", "since": "2026-06-18", "until": "2026-06-19", "order": "oldest"}
    result = await reader.read(query)
    assert result["complete"] and result["scanned"] == 854
    assert [m["id"] for m in result["matches"]] == [str(target.id)]
    assert result["matches"][0]["created_at"] == target.created_at.isoformat()
    assert "unrelated chatter" not in json.dumps(result) and "never-expose" not in json.dumps(result)
    assert len(json.dumps(result)) < 2000, "Nonmatching history must stay outside model context"
    assert len(channel.calls) == 1 and channel.calls[0]["oldest_first"]
    assert channel.calls[0]["before"].id == discord.utils.time_snowflake(day + timedelta(days=1))

    second_channel = Channel()
    second_channel.id, second_channel.name = 303, "releases"
    guild.channels.append(second_channel)
    bot.get_channel = lambda n: {101: channel, 202: hidden, 303: second_channel}.get(n)
    batched = await reader.read({**query, "channel_ids": ["101", "303"], "scan_limit": 1000})
    assert len(batched["searches"]) == 2
    assert all(result["scanned"] <= 250 and len(result["matches"]) <= 4 for result in batched["searches"])

    items[:] = [message(day + timedelta(minutes=i), "OpenCode Go " + str(i)) for i in range(5)]
    first = await reader.read({**query, "scan_limit": 2})
    assert not first["complete"] and len(first["matches"]) == 2
    rest = await reader.read({**query, "after": first["next_after"]})
    assert rest["complete"] and len(rest["matches"]) == 3
    assert not {m["id"] for m in first["matches"]} & {m["id"] for m in rest["matches"]}
    newest = await reader.read({**query, "order": "newest", "limit": 1})
    older = await reader.read({**query, "order": "newest", "before": newest["next_before"]})
    assert len(newest["matches"]) == 1 and len(older["matches"]) == 4
    partial = await reader.read({**query, "query": "missing", "scan_limit": 1})
    assert not partial["complete"] and not partial["matches"] and partial["next_after"]
    assert "error" in await reader.read({**query, "until": "2026-06-17"})
    assert "error" in await reader.read({**query, "author_id": "Reporter"})
    assert "error" in await reader.read({**query, "channel_id": "#private"})
    assert not hidden.calls
    assert "error" in await reader.read({**query, "guild_id": "999"})
    before, after, _ = reader._history_bounds({"since": "2026-06-18T02:00:00+02:00", "until": "2026-06-19"})
    assert after.id == discord.utils.time_snowflake(day) - 1
    assert before.id == discord.utils.time_snowflake(day + timedelta(days=1))

    items[:] = [message(day, "OpenCode Go " + "details " * 150)]
    clipped = await reader.read(query)
    assert clipped["matches"][0]["excerpt_truncated"] and len(clipped["matches"][0]["excerpt"]) == 600
    config["chat_bridge"]["allowed_users"] = [555]
    assert "error" in await reader.read(query)
    print("PASS: date jumps, author/keyword filtering, bounded excerpts, resumable scans and permissions")


if __name__ == "__main__":
    asyncio.run(main())
