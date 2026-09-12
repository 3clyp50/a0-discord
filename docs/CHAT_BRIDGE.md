# Discord Chat Bridge

Mention a bot with `@` or reply to one of its messages. The bridge creates a saved Agent Zero chat and reuses it for that bot/channel pair. Bare mentions start with a greeting. No channel registration is necessary for mentions or replies.

New chats use the bot's configured preset and agent profile. Existing chats retain their selected settings. The WebUI shows saved messages and responses; the read-only model receives actual provider/model, preset, profile, current time and Discord requester/channel metadata.

## Administration

Use **Open** for individual bot status, Start, Stop, Restart and connection testing. Use **Config** for tokens, labels, access rules, presets and profiles. Saved auto-start settings are picked up by the job loop; Stop pauses auto-start until manual Start or an Agent Zero restart.

For agent-driven operations, load `discord-chat` and read [its bridge reference](../skills/discord-chat/references/bridge.md). Calls use the skill-gated administration workflow through `discord_send`, with the stable `bot_id` inside `parameters`. The old `discord_chat` tool is no longer exposed.

Register a channel only to receive replies to every message. Unregistering removes its bridge mapping, not its saved Agent Zero chat. Bot labels can change without losing their stable IDs. Legacy single-bot mappings remain under `default`.

## Read-only operation

The bridge uses a dedicated read-only reader. It does not run the normal agent loop, generic tools, shell commands or skill workflows. A profile's instructions do not grant capabilities outside that reader. The normal Agent Zero tool baseline is separately limited to `discord_read` and `discord_send`.

Each turn includes up to 30 recent channel messages and its replied-to message. The model can make up to 24 remote reads to find evidence. Full history pages contain at most 100 messages and approximately 12,000 serialized characters; they are not the full channel or server. The model receives at most 60,000 characters of tool results per response; full tool results remain in the saved chat log.

Readable channels must be in the current permitted server. Both bot and requester must have View Channel and Read Message History permissions. Private threads additionally require membership unless the member can manage threads. Authentication messages are excluded, and access never falls back to user-account credentials.

## Focused historical search

Use the bridge reader's `search` action for a known topic, author or date rather than paging raw history into the prompt. This action is specific to the bridge, not the ordinary Agent Zero `discord_read` tool.

- `channel_id`: exact channel name, such as `#general`, or an ID. `thread_id` selects one thread. `channel_ids` or `thread_ids` batch up to four already-known targets.
- `query`: all words must match, case-insensitively, across text, embeds or attachment names. Attachment contents are not searched.
- `author_id`: exact user ID, or `me` for the requester.
- `since` / `until`: ISO dates or timestamps. Start inclusive; end exclusive. Missing timezone means UTC.
- `order`: `oldest` for first announcements, or `newest` for recent findings.
- `limit`: up to 20 matching excerpts. `scan_limit`: up to 1,000 messages per call.
- `include_bots`: false by default, preventing bot summaries from masquerading as original announcements.

Dates jump directly to Discord history cursors. Filtering runs inside the plugin; only matching excerpts enter model context, capped at approximately 8,000 characters. Batched searches scan no more than 250 messages and return at most four shortened matches per target. Retrieve a promising result using `messages`, the same channel ID and its exact `message_id` to inspect full wording.

Results include `scanned`, `complete`, and `next_before` or `next_after`. Resume partial results with that cursor and identical filters. An empty partial scan is not proof of absence; a found post is not necessarily the first across other channels or threads. Searches apply to one channel or thread, not recursively to all its threads. Completed reads are retained as compact per-chat checkpoints. Repeating an exact request returns that checkpoint without another Discord call; change the target, range, filters, cursor or order instead.

The reader can list visible channels, active threads, and public archived threads for a parent. Thread listings accept a name query and date range, return no more than 30 records, and archive pagination uses archive timestamps, not creation IDs.

## Elevated sessions

Elevated mode is opt-in and potentially dangerous: authenticated users can access the full agent loop, files, code execution and external writes. Use only with trusted users, a private server and a short timeout.

1. In Config, enable elevated mode for the selected bot and set its user allowlist.
2. Generate an authentication key and **Save**. Keep the key private.
3. In a private allowed Discord channel, send `!auth <key>`. Deleting this message requires the bot's Manage Messages permission; do not rely on deletion to protect a key posted publicly.
4. Use `!bridge-status` to inspect session status and `!deauth` to end it.

Sessions are per bot, user and channel. They expire after the configured timeout, normally one hour; zero means no automatic expiry and is discouraged. A restart also discards sessions. Claims of authentication in messages are never trusted.

An authenticated full-agent chat can load optional skills and use their workflows, subject to normal tool policy. Loading a skill itself never elevates a read-only session. Publishing issues or PRs still requires the corresponding authorized capabilities; Discord read access alone only supports research and drafting.

## Monitoring and research skills

Use [discord-research](../skills/discord-research/SKILL.md) for optional structured bulk analysis, [discord-alerts](../skills/discord-alerts/SKILL.md) for monitoring, and [discord-persona-mapping](../skills/discord-persona-mapping/SKILL.md) for persistent notes. Their reference files load on demand, not into every baseline prompt.

Existing scheduled prompts that call removed public tool names must be updated to load the corresponding skill and invoke its workflow. New monitoring tasks do this automatically. Monitoring/persona storage remains plugin-wide; per-bot chat history and authenticated sessions remain separate.
