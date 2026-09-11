"""Read-only Discord access scoped to the requesting member and server."""

import json
import re
from datetime import datetime

import discord

from usr.plugins.discord.helpers.sanitize import (
    sanitize_channel_name, sanitize_content, sanitize_embed, sanitize_filename,
    sanitize_username,
)


class BridgeReader:
    MAX_OUTPUT_CHARS = 40000

    def __init__(self, bot, message):
        self.bot = bot
        self.message = message
        self.guild = message.guild
        self.member = message.author if isinstance(message.author, discord.Member) else None

    async def _visible(self, channel):
        if self.guild is None:
            return channel.id == self.message.channel.id
        if getattr(getattr(channel, "guild", None), "id", None) != self.guild.id:
            return False
        if self.member is None:
            self.member = self.guild.get_member(self.message.author.id) or await self.guild.fetch_member(self.message.author.id)
        bot_member = self.guild.me or await self.guild.fetch_member(self.bot.user.id)
        for member in (self.member, bot_member):
            permissions = channel.permissions_for(member)
            if not permissions.view_channel or not permissions.read_message_history:
                return False
            if isinstance(channel, discord.Thread) and channel.is_private() and not permissions.manage_threads:
                try:
                    await channel.fetch_member(member.id)
                except (discord.Forbidden, discord.NotFound):
                    return False
        return True

    async def _channel(self, channel_id):
        channel_id = int(channel_id or self.message.channel.id)
        channel = self.message.channel if channel_id == self.message.channel.id else (
            self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        )
        if not await self._visible(channel):
            raise ValueError("Channel is not readable by both the bot and requesting user in this server.")
        return channel

    @staticmethod
    def message_record(message):
        # Authentication commands must never enter model context or saved logs.
        command_text = re.sub(r"<@!?\d+>", " ", message.content)
        if re.search(r"(?:^|\s)!auth\b", command_text, re.IGNORECASE):
            return None
        return {
            "id": str(message.id),
            "url": message.jump_url,
            "author": sanitize_username(message.author.display_name),
            "created_at": message.created_at.isoformat(),
            "content": sanitize_content(message.content),
            "embeds": [
                {"title": sanitize_embed(e.title or ""), "description": sanitize_embed(e.description or "")}
                for e in message.embeds
            ],
            "attachments": [
                {"name": sanitize_filename(a.filename), "url": a.url}
                for a in message.attachments
            ],
            "reply_to": str(message.reference.message_id) if message.reference else None,
        }

    @staticmethod
    def channel_record(channel):
        return {
            "id": str(channel.id), "name": sanitize_channel_name(getattr(channel, "name", "Direct messages")),
            "type": str(channel.type), "parent_id": str(getattr(channel, "parent_id", "") or ""),
        }

    async def read(self, args):
        try:
            config = self.bot._get_config()
            servers = [str(s) for s in config.get("servers", [])]
            users = [str(u) for u in config.get("chat_bridge", {}).get("allowed_users", [])]
            if users and str(self.message.author.id) not in users:
                raise ValueError("User is no longer allowed to use the bridge.")
            if servers and (self.guild is None or str(self.guild.id) not in servers):
                raise ValueError("Server is not allowed.")
            if args.get("guild_id") and (self.guild is None or str(args["guild_id"]) != str(self.guild.id)):
                raise ValueError("Reads are limited to the current server.")
            action = args.get("action", "messages")
            limit = max(1, min(int(args.get("limit", 50)), 100))
            if action == "channels":
                channels = []
                for channel in self.guild.channels if self.guild else [self.message.channel]:
                    if not isinstance(channel, discord.CategoryChannel) and await self._visible(channel):
                        channels.append(self.channel_record(channel))
                return {"channels": channels}
            if action == "threads":
                if self.guild is None:
                    raise ValueError("Threads require a server.")
                parent = await self._channel(args["channel_id"]) if args.get("channel_id") else None
                threads = []
                for thread in await self.guild.active_threads():
                    if (parent is None or thread.parent_id == parent.id) and await self._visible(thread):
                        threads.append(self.channel_record(thread))
                cursor = None
                if parent is not None and hasattr(parent, "archived_threads"):
                    before = datetime.fromisoformat(args["before"]) if args.get("before") else None
                    async for thread in parent.archived_threads(limit=limit, before=before):
                        cursor = thread.archive_timestamp.isoformat()
                        if await self._visible(thread):
                            threads.append(self.channel_record(thread))
                return {"threads": threads, "next_before": cursor,
                        "coverage": "Active threads; also one page of public archived threads when channel_id is supplied."}
            if action != "messages":
                raise ValueError("Use messages, channels, or threads. This reader cannot write or execute code.")
            channel = await self._channel(args.get("thread_id") or args.get("channel_id"))
            if not hasattr(channel, "history"):
                raise ValueError("List this channel's threads first, then read a thread ID.")
            if args.get("message_id"):
                record = self.message_record(await channel.fetch_message(int(args["message_id"])))
                return {"messages": [record] if record else [], "next_before": None}
            before = discord.Object(id=int(args["before"])) if args.get("before") else None
            after = discord.Object(id=int(args["after"])) if args.get("after") else None
            records, size, cursor, scanned = [], 0, None, 0
            async for item in channel.history(limit=limit, before=before, after=after, oldest_first=False):
                record = self.message_record(item)
                record_size = len(json.dumps(record)) if record else 0
                if records and size + record_size > self.MAX_OUTPUT_CHARS:
                    break
                cursor, scanned = str(item.id), scanned + 1
                if record:
                    records.append(record)
                    size += record_size
            return {"channel_id": str(channel.id), "messages": records, "order": "newest first",
                    "scanned": scanned, "next_before": cursor,
                    "coverage": "One page only; follow next_before until an empty page for older history."}
        except (discord.DiscordException, ValueError, TypeError) as exc:
            return {"error": str(exc)}
