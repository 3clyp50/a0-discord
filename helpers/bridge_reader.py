"""Read-only Discord access scoped to the requesting member and server."""

import json
import re
from datetime import datetime, timezone

import discord

from usr.plugins.discord.helpers.sanitize import (
    sanitize_channel_name, sanitize_content, sanitize_embed, sanitize_filename,
    sanitize_username,
)


class BridgeReader:
    MAX_OUTPUT_CHARS = 12000
    MAX_SEARCH_MESSAGES = 1000
    MAX_SEARCH_OUTPUT_CHARS = 8000
    MAX_THREADS_RETURNED = 30
    MAX_BATCH_SEARCH_TARGETS = 4

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
        if channel_id and not str(channel_id).isdigit():
            name = str(channel_id).lstrip("#").casefold()
            matches = []
            for channel in self.guild.channels if self.guild else []:
                if channel.name.casefold() == name and await self._visible(channel):
                    matches.append(channel)
            if len(matches) != 1:
                raise ValueError("Channel name is unavailable or ambiguous. List channels and use an exact ID.")
            return matches[0]
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
            "author_id": str(message.author.id),
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

    @staticmethod
    def _history_bounds(args):
        """Intersect pagination cursors with an inclusive start/exclusive end."""
        before = int(args["before"]) if args.get("before") else None
        after = int(args["after"]) if args.get("after") else None
        dates = {}
        for key in ("since", "until"):
            if not args.get(key):
                continue
            stamp = datetime.fromisoformat(str(args[key]).replace("Z", "+00:00"))
            stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
            boundary = discord.utils.time_snowflake(stamp)
            if boundary < 0:
                raise ValueError("Discord history dates must be on or after 2015-01-01.")
            dates[key] = stamp.isoformat()
            if key == "since":
                after = max(after, boundary - 1) if after is not None else boundary - 1
            else:
                before = min(before, boundary) if before is not None else boundary
        if "since" in dates and "until" in dates and dates["since"] >= dates["until"]:
            raise ValueError("since must be earlier than until (exclusive).")
        return (discord.Object(id=before) if before is not None else None,
                discord.Object(id=after) if after is not None else None, dates)

    async def _search(self, args):
        target_key = "thread_ids" if args.get("thread_ids") is not None else "channel_ids"
        targets = args.get(target_key)
        if targets is not None:
            if not isinstance(targets, list) or not 1 <= len(targets) <= self.MAX_BATCH_SEARCH_TARGETS:
                raise ValueError(f"{target_key} must contain 1-{self.MAX_BATCH_SEARCH_TARGETS} channel or thread IDs.")
            if any(not isinstance(target, (str, int)) or not str(target) for target in targets):
                raise ValueError(f"{target_key} must contain channel or thread IDs.")
            base = {key: value for key, value in args.items() if key not in ("channel_ids", "thread_ids", "channel_id", "thread_id")}
            results = []
            for target in dict.fromkeys(map(str, targets)):
                child = {
                    **base,
                    "limit": min(max(1, int(base.get("limit", 10))), 4),
                    "scan_limit": min(max(1, int(base.get("scan_limit", self.MAX_SEARCH_MESSAGES))), 250),
                    "thread_id" if target_key == "thread_ids" else "channel_id": target,
                }
                result = await self._search(child)
                for match in result.get("matches", []):
                    if len(match.get("excerpt", "")) > 360:
                        match["excerpt"] = match["excerpt"][:360]
                        match["excerpt_truncated"] = True
                results.append(result)
            return {
                "searches": results,
                "coverage": "One bounded search per supplied target. Each target scanned at most 250 messages and returns at most four compact matches."
            }
        query = str(args.get("query", "") or "").strip()
        if len(query) > 200:
            raise ValueError("Search query must be at most 200 characters.")
        terms = re.findall(r"[^\W_]+", query.casefold())
        if query and not terms:
            raise ValueError("Search query must contain a word or number.")
        author_id = str(args.get("author_id", "") or "")
        if author_id.casefold() == "me":
            author_id = str(self.message.author.id)
        if author_id and not author_id.isdecimal():
            raise ValueError("author_id must be a Discord user ID or 'me'.")
        if not (terms or author_id or args.get("since") or args.get("until")):
            raise ValueError("Search requires query, author_id, since or until.")
        order = args.get("order", "newest")
        if order not in ("oldest", "newest"):
            raise ValueError("Search order must be oldest or newest.")
        include_bots = args.get("include_bots", False)
        if not isinstance(include_bots, bool):
            raise ValueError("include_bots must be true or false.")
        limit = max(1, min(int(args.get("limit", 10)), 20))
        scan_limit = max(1, min(int(args.get("scan_limit", self.MAX_SEARCH_MESSAGES)), self.MAX_SEARCH_MESSAGES))
        before, after, dates = self._history_bounds(args)
        channel = await self._channel(args.get("thread_id") or args.get("channel_id"))
        if not hasattr(channel, "history"):
            raise ValueError("List this channel's threads first, then search a thread ID.")
        matches, scanned, size, cursor, complete = [], 0, 0, None, True
        # Filter inside the bridge; nonmatching messages never reach the model.
        async for item in channel.history(limit=scan_limit + 1, before=before, after=after, oldest_first=order == "oldest"):
            if scanned >= scan_limit or len(matches) >= limit:
                complete = False
                break
            record = None
            if ((not author_id or str(item.author.id) == author_id)
                    and (include_bots or not getattr(item.author, "bot", False))):
                record = self.message_record(item)
            hit = None
            if record:
                text = "\n".join([record["content"]]
                                 + [e["title"] + " " + e["description"] for e in record["embeds"]]
                                 + [a["name"] for a in record["attachments"]])
                searchable = " ".join(re.findall(r"[^\W_]+", text.casefold()))
                if all(term in searchable for term in terms):
                    start = max(0, text.casefold().find(terms[0]) - 120) if terms else 0
                    excerpt = text[start:start + 600]
                    hit = {key: record[key] for key in ("id", "url", "author", "author_id", "created_at")}
                    hit.update(excerpt=excerpt, excerpt_truncated=start > 0 or len(text) > start + 600)
            hit_size = len(json.dumps(hit, ensure_ascii=False)) if hit else 0
            if size + hit_size > self.MAX_SEARCH_OUTPUT_CHARS - 1024:
                complete = False
                break
            scanned += 1
            cursor = str(item.id)
            if hit:
                matches.append(hit)
                size += hit_size
        return {
            "channel_id": str(channel.id), "query": query, "author_id": author_id or None,
            **dates, "order": order, "include_bots": include_bots,
            "matches": matches, "scanned": scanned, "complete": complete,
            "next_before": cursor if not complete and order == "newest" else None,
            "next_after": cursor if not complete and order == "oldest" else None,
            "coverage": "Only this channel/thread and date range; filters match message text, embeds and attachment names, not attachment contents. "
                        + ("Range exhausted." if complete else "Partial scan; resume with the returned cursor and identical filters."),
        }

    async def read(self, args):
        try:
            config = self.bot._get_config()
            if not config.get("bot", {}).get("enabled", True):
                raise ValueError("This bot is disabled or its configuration is unavailable.")
            servers = [str(s) for s in config.get("servers", [])]
            users = [str(u) for u in config.get("chat_bridge", {}).get("allowed_users", [])]
            if users and str(self.message.author.id) not in users:
                raise ValueError("User is no longer allowed to use the bridge.")
            if servers and (self.guild is None or str(self.guild.id) not in servers):
                raise ValueError("Server is not allowed.")
            if args.get("guild_id") and (self.guild is None or str(args["guild_id"]) != str(self.guild.id)):
                raise ValueError("Reads are limited to the current server.")
            action = args.get("action", "messages")
            if action == "search":
                return await self._search(args)
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
                query = str(args.get("query", "") or "").strip()
                if len(query) > 200:
                    raise ValueError("Thread query must be at most 200 characters.")
                terms = re.findall(r"[^\W_]+", query.casefold())
                _, _, dates = self._history_bounds({key: value for key, value in args.items() if key not in ("before", "after")})
                since = datetime.fromisoformat(dates["since"]) if dates.get("since") else None
                until = datetime.fromisoformat(dates["until"]) if dates.get("until") else None
                parent = await self._channel(args["channel_id"]) if args.get("channel_id") else None
                threads = []
                def matches(thread):
                    if terms and not all(term in str(thread.name).casefold() for term in terms):
                        return False
                    stamp = getattr(thread, "created_at", None) or getattr(thread, "archive_timestamp", None)
                    if stamp:
                        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
                        if (since and stamp < since) or (until and stamp >= until):
                            return False
                    return True
                for thread in await self.guild.active_threads():
                    if (parent is None or thread.parent_id == parent.id) and matches(thread) and await self._visible(thread):
                        threads.append(self.channel_record(thread))
                        if len(threads) >= self.MAX_THREADS_RETURNED:
                            break
                cursor = None
                if len(threads) < self.MAX_THREADS_RETURNED and parent is not None and hasattr(parent, "archived_threads"):
                    before = datetime.fromisoformat(str(args["before"]).replace("Z", "+00:00")) if args.get("before") else None
                    async for thread in parent.archived_threads(limit=limit, before=before):
                        cursor = thread.archive_timestamp.isoformat()
                        if matches(thread) and await self._visible(thread):
                            threads.append(self.channel_record(thread))
                            if len(threads) >= self.MAX_THREADS_RETURNED:
                                break
                return {"threads": threads, "next_before": cursor, "query": query, **dates,
                        "coverage": "Filtered active threads; also one page of public archived threads when channel_id is supplied. Results are capped at 30."}
            if action != "messages":
                raise ValueError("Use search, messages, channels, or threads. This reader cannot write or execute code.")
            channel = await self._channel(args.get("thread_id") or args.get("channel_id"))
            if not hasattr(channel, "history"):
                raise ValueError("List this channel's threads first, then read a thread ID.")
            if args.get("message_id"):
                record = self.message_record(await channel.fetch_message(int(args["message_id"])))
                return {"messages": [record] if record else [], "next_before": None}
            before, after, _ = self._history_bounds(args)
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
        except (discord.DiscordException, ValueError, TypeError, OverflowError) as exc:
            return {"error": str(exc)}
