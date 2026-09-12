"""Read-only Discord access scoped to the requesting member and server."""

import asyncio
import hashlib
import json
import re
import shlex
import time
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
    MAX_SERVER_CHANNELS = 64
    MAX_EVIDENCE_RECORDS = 20
    MAX_EVIDENCE_CHARS = 12000
    EVIDENCE_TTL = 900

    def __init__(self, bot, message, evidence=None):
        self.bot = bot
        self.message = message
        self.guild = message.guild
        self.member = message.author if isinstance(message.author, discord.Member) else None
        self.evidence = [entry for entry in (evidence or [])
                         if time.time() - entry.get("read_at", 0) < self.EVIDENCE_TTL][-self.MAX_EVIDENCE_RECORDS:]

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
                {"title": sanitize_embed(e.title or ""), "description": sanitize_embed(e.description or ""),
                 "url": sanitize_embed(getattr(e, "url", None) or "")}
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

    def _remember(self, channel_id, record):
        if not record:
            return
        entry = {"channel_id": str(channel_id), "record": record, "read_at": time.time()}
        size = len(json.dumps(entry, ensure_ascii=False))
        if size > self.MAX_EVIDENCE_CHARS:
            return
        self.evidence = [old for old in self.evidence
                         if (old["channel_id"], old["record"]["id"]) != (str(channel_id), record["id"])]
        self.evidence.append(entry)
        total = sum(len(json.dumps(old, ensure_ascii=False)) for old in self.evidence)
        while total > self.MAX_EVIDENCE_CHARS or len(self.evidence) > self.MAX_EVIDENCE_RECORDS:
            total -= len(json.dumps(self.evidence.pop(0), ensure_ascii=False))

    @staticmethod
    def _query_terms(query):
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("Each search query must be a string of at most 200 characters.")
        terms = [" ".join(re.findall(r"[^\W_]+", word.casefold())) for word in shlex.split(query)]
        terms = [term for term in terms if term]
        if query.strip() and not terms:
            raise ValueError("Search query must contain a word or number.")
        return terms

    def _search_filters(self, args):
        query = args.get("query") or ""
        self._query_terms(query)
        alternatives = args.get("query_any", [])
        if not isinstance(alternatives, list) or len(alternatives) > 8:
            raise ValueError("query_any must be a list of at most eight alternative queries.")
        if any(not self._query_terms(value) for value in alternatives):
            raise ValueError("query_any entries cannot be empty.")
        author_id = str(args.get("author_id", "") or "")
        if author_id.casefold() == "me":
            author_id = str(self.message.author.id)
        if author_id and not author_id.isdecimal():
            raise ValueError("author_id must be a Discord user ID or 'me'.")
        order = args.get("order", "newest")
        if order not in ("oldest", "newest"):
            raise ValueError("Search order must be oldest or newest.")
        for key in ("include_bots", "has_pr"):
            if not isinstance(args.get(key, False), bool):
                raise ValueError(f"{key} must be true or false.")
        if not (query.strip() or alternatives or author_id or args.get("has_pr") or args.get("since") or args.get("until")):
            raise ValueError("Search requires a query, author, PR-link filter or date range.")
        _, _, dates = self._history_bounds(args)
        return {"query": query.strip(), "query_any": alternatives, "author_id": author_id or None,
                "order": order, "include_bots": args.get("include_bots", False),
                "has_pr": args.get("has_pr", False), **dates}

    async def _search_server(self, args, filters):
        if self.guild is None:
            raise ValueError("Server search requires a server.")
        if any(args.get(key) is not None for key in ("channel_id", "thread_id", "channel_ids", "thread_ids", "before", "after")):
            raise ValueError("Server search uses cursor, not individual channel targets or message cursors.")
        cursor = args.get("cursor") or {}
        if not isinstance(cursor, dict):
            raise ValueError("cursor must be the next_cursor object returned by server search.")
        # Freeze the upper date bound so continuation does not drift with new messages.
        filters = self._search_filters({**filters, "until": filters.get("until") or cursor.get("until") or datetime.now(timezone.utc).isoformat()})
        fingerprint = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()[:16]
        if cursor and cursor.get("filters") != fingerprint:
            raise ValueError("Resume server search with identical filters and the returned cursor.")
        after_channel = str(cursor.get("after_channel", "0"))
        pending = cursor.get("pending", [])
        if not after_channel.isdecimal() or not isinstance(pending, list) or len(pending) > self.MAX_SERVER_CHANNELS:
            raise ValueError("Invalid server cursor.")
        for target in pending:
            if (not isinstance(target, dict) or set(target) - {"channel_id", "before", "after"}
                    or not str(target.get("channel_id", "")).isdecimal()
                    or any(not str(target[key]).isdecimal() for key in ("before", "after") if key in target)):
                raise ValueError("Invalid channel continuation in server cursor.")
        channels = []
        for channel in sorted(self.guild.channels, key=lambda item: item.id):
            if hasattr(channel, "history") and await self._visible(channel):
                channels.append(channel)
        if not pending:
            selected = [channel for channel in channels if channel.id > int(after_channel)][:self.MAX_SERVER_CHANNELS]
            pending = [{"channel_id": str(channel.id)} for channel in selected]
            if selected:
                after_channel = str(selected[-1].id)
        queue, partial, checked, matches, errors = list(pending), [], [], [], []
        scanned, size = 0, 0
        limit = max(1, min(int(args.get("limit", 20)), 20))
        scan_limit = max(1, min(int(args.get("scan_limit", self.MAX_SEARCH_MESSAGES)), self.MAX_SEARCH_MESSAGES))
        # ponytail: breadth-first pages cover at most 64 channels per call; next_cursor continues larger servers.
        while queue:
            count = min(self.MAX_BATCH_SEARCH_TARGETS, len(queue), limit - len(matches),
                        scan_limit - scanned, (self.MAX_SEARCH_OUTPUT_CHARS - 2048 - size) // 1024)
            if count <= 0:
                break
            batch, queue = queue[:count], queue[count:]
            per_target = {"limit": min(4, (limit - len(matches)) // count),
                          "scan_limit": min(250, (scan_limit - scanned) // count)}
            output_limit = (self.MAX_SEARCH_OUTPUT_CHARS - 2048 - size) // count

            async def search_target(target):
                try:
                    return await self._search({**filters, **per_target, **target}, excerpt_limit=240, output_limit=output_limit)
                except (discord.DiscordException, ValueError, TypeError, OverflowError) as exc:
                    return {"channel_id": str(target["channel_id"]), "error": str(exc)}

            for target, result in zip(batch, await asyncio.gather(*(search_target(target) for target in batch))):
                channel_id = result["channel_id"]
                checked.append(channel_id)
                if "error" in result:
                    errors.append(result)
                    continue
                scanned += result["scanned"]
                for hit in result["matches"]:
                    hit = {**hit, "channel_id": channel_id}
                    matches.append(hit)
                    size += len(json.dumps(hit, ensure_ascii=False))
                if not result["complete"]:
                    next_target = dict(target)
                    for key in ("before", "after"):
                        if result.get("next_" + key):
                            next_target[key] = result["next_" + key]
                    partial.append(next_target)
        remaining = queue + partial
        more_channels = any(channel.id > int(after_channel) for channel in channels)
        next_cursor = ({"after_channel": after_channel, "pending": remaining,
                        "until": filters["until"], "filters": fingerprint} if remaining or more_channels else None)
        return {"scope": "server", "filters": filters, "matches": matches, "scanned": scanned,
                "checked_channel_ids": checked, "next_cursor": next_cursor, "errors": errors,
                "complete": next_cursor is None and not errors,
                "coverage": {"readable_channels": len(channels), "checked_this_call": len(checked),
                             "exhausted_this_call": len(checked) - len(partial) - len(errors),
                             "threads": "Not searched; enumerate and search thread IDs separately.",
                             "note": "Combine coverage across continuations; failed channels remain unchecked. No service-channel exclusions."}}

    async def _search(self, args, *, excerpt_limit=600, output_limit=None):
        filters = self._search_filters(args)
        if args.get("scope") == "server":
            return await self._search_server(args, filters)
        if args.get("scope", "channel") != "channel":
            raise ValueError("scope must be channel or server.")
        target_key = "thread_ids" if args.get("thread_ids") is not None else "channel_ids"
        targets = args.get(target_key)
        if targets is not None:
            if not isinstance(targets, list) or not 1 <= len(targets) <= self.MAX_BATCH_SEARCH_TARGETS:
                raise ValueError(f"{target_key} must contain 1-{self.MAX_BATCH_SEARCH_TARGETS} channel or thread IDs.")
            if any(not isinstance(target, (str, int)) or not str(target) for target in targets):
                raise ValueError(f"{target_key} must contain channel or thread IDs.")
            base = {key: value for key, value in args.items() if key not in ("channel_ids", "thread_ids", "channel_id", "thread_id")}
            async def search_target(target):
                child = {
                    **base,
                    "limit": min(max(1, int(base.get("limit", 10))), 4),
                    "scan_limit": min(max(1, int(base.get("scan_limit", self.MAX_SEARCH_MESSAGES))), 250),
                    "thread_id" if target_key == "thread_ids" else "channel_id": target,
                }
                result = await self.read(child)
                for match in result.get("matches", []):
                    if len(match.get("excerpt", "")) > 360:
                        match["excerpt"] = match["excerpt"][:360]
                        match["excerpt_truncated"] = True
                return {key: value for key, value in result.items()
                        if key in ("channel_id", "matches", "scanned", "complete", "next_before", "next_after", "error")}
            results = await asyncio.gather(*(search_target(target) for target in dict.fromkeys(map(str, targets))))
            return {
                "filters": filters, "searches": results,
                "coverage": "Per-target pages, at most 250 scanned and four matches each; threads not included implicitly."
            }
        terms = self._query_terms(filters["query"])
        alternatives = [self._query_terms(query) for query in filters["query_any"]]
        author_id, order, include_bots = filters["author_id"], filters["order"], filters["include_bots"]
        limit = max(1, min(int(args.get("limit", 10)), 20))
        scan_limit = max(1, min(int(args.get("scan_limit", self.MAX_SEARCH_MESSAGES)), self.MAX_SEARCH_MESSAGES))
        before, after, _ = self._history_bounds(args)
        output_limit = min(output_limit if output_limit is not None else self.MAX_SEARCH_OUTPUT_CHARS - 1024,
                           self.MAX_SEARCH_OUTPUT_CHARS - 1024)
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
                                 + [e["title"] + " " + e["description"] + " " + e.get("url", "") for e in record["embeds"]]
                                 + [a["name"] for a in record["attachments"]])
                searchable = " ".join(re.findall(r"[^\W_]+", text.casefold()))
                matched_group = next((group for group in alternatives if all(term in searchable for term in group)), None)
                pr_link = re.search(r"https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+/pull/\d+\b", text, re.IGNORECASE)
                if (all(term in searchable for term in terms) and (not alternatives or matched_group)
                        and (not filters["has_pr"] or pr_link)):
                    anchors = terms or matched_group or []
                    start = max(0, text.casefold().find(anchors[0]) - 120) if anchors else max(0, pr_link.start() - 120) if pr_link else 0
                    excerpt = text[start:start + excerpt_limit]
                    hit = {key: record[key] for key in ("id", "url", "author", "author_id", "created_at")}
                    hit.update(excerpt=excerpt, excerpt_truncated=start > 0 or len(text) > start + excerpt_limit)
            hit_size = len(json.dumps(hit, ensure_ascii=False)) if hit else 0
            if size + hit_size > output_limit:
                complete = False
                break
            scanned += 1
            cursor = str(item.id)
            if hit:
                matches.append(hit)
                size += hit_size
                self._remember(channel.id, record)
        return {
            "channel_id": str(channel.id), **filters,
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
                if not isinstance(args.get("refresh", False), bool):
                    raise ValueError("refresh must be true or false.")
                if not args.get("refresh"):
                    cached = next((entry for entry in reversed(self.evidence)
                                   if entry["channel_id"] == str(channel.id)
                                   and entry["record"]["id"] == str(args["message_id"])
                                   and time.time() - entry["read_at"] < self.EVIDENCE_TTL), None)
                    if cached:
                        return {"channel_id": str(channel.id), "messages": [cached["record"]],
                                "next_before": None, "cached": True, "read_at": cached["read_at"]}
                record = self.message_record(await channel.fetch_message(int(args["message_id"])))
                self._remember(channel.id, record)
                return {"channel_id": str(channel.id), "messages": [record] if record else [], "next_before": None}
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
