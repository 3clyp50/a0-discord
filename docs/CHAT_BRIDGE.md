# Discord Chat Bridge

Mention a bot with `@` or reply to one of its messages. The bridge creates a saved Agent Zero chat and reuses it for that bot/channel pair. Bare mentions start with a greeting. No channel registration is necessary for mentions or replies.

New chats use the bot's configured preset and agent profile. Existing chats retain their selected settings. The WebUI shows saved messages and responses; the read-only model receives actual provider/model, preset, profile, current time and Discord requester/channel metadata.

## Administration

Use **Config** for individual bot status, Start/Stop and Restart icons, tokens, labels, access rules, presets and profiles. There is no separate Open dashboard. Saved auto-start settings are picked up by the job loop; Stop pauses auto-start until manual Start or an Agent Zero restart.

For agent-driven operations, load `discord-chat` and read [its bridge reference](../skills/discord-chat/references/bridge.md). Calls use the skill-gated administration workflow through `discord_send`, with the stable `bot_id` inside `parameters`. The old `discord_chat` tool is no longer exposed.

Register a channel only to receive replies to every message. Unregistering removes its bridge mapping, not its saved Agent Zero chat. Bot labels can change without losing their stable IDs. Legacy single-bot mappings remain under `default`.

## Bot instructions

Use **Config > bot > Instructions** for the bot's role, tone and workflows instead of creating a dedicated agent profile. The multiline field accepts Markdown and supplements the selected profile without replacing its capabilities or granting tool access.

Saved instructions are read when building each prompt, including existing chats. They apply to the read-only bridge and the root agent in Discord-linked chats, including full-agent slash requests and their WebUI chat. Other bots, ordinary WebUI chats and subordinate agents do not inherit them. Clearing the field removes the added guidance on the next prompt; it does not erase earlier chat history.

Profile and preset defaults still apply only to new chats. When moving guidance out of a custom profile, update existing chats' profiles separately if needed.

## Read-only operation

The bridge uses a dedicated read-only reader. It does not run the normal agent loop, generic tools, shell commands or skill workflows. A profile's instructions do not grant capabilities outside that reader. The normal Agent Zero tool baseline is separately limited to `discord_read` and `discord_send`.

Each turn includes up to 30 recent channel messages and its replied-to message. The model can make up to 24 remote reads to find evidence. Full history pages contain at most 100 messages and approximately 12,000 serialized characters; they are not the full channel or server. The model receives at most 60,000 characters of tool results per response; full tool results remain in the saved chat log.

Readable channels must be in the current permitted server. Both bot and requester must have View Channel and Read Message History permissions. Private threads additionally require membership unless the member can manage threads. Authentication messages are excluded, and access never falls back to user-account credentials.

## Focused historical search

Use the bridge reader's `search` action for a known topic, author or date rather than paging raw history into the prompt. This action is specific to the bridge, not the ordinary Agent Zero `discord_read` tool.

- `channel_id`: exact channel name, such as `#general`, or an ID. `thread_id` selects one thread. `channel_ids` or `thread_ids` batch up to four already-known targets.
- `query`: all words must match, case-insensitively, across text, embeds (including URLs) or attachment names. Double-quoted phrases require adjacent normalized words. Attachment contents are not searched.
- `query_any`: up to eight alternative query strings. At least one must match; each uses the same word/phrase rules. These alternatives are combined with the other filters using AND.
- `has_pr`: when true, require a GitHub pull-request URL in the message or embed. This does not fetch or verify the PR itself.
- `author_id`: exact user ID, or `me` for the requester.
- `since` / `until`: ISO dates or timestamps. Start inclusive; end exclusive. Missing timezone means UTC.
- `order`: `oldest` for first announcements, or `newest` for recent findings.
- `limit`: up to 20 matching excerpts. `scan_limit`: up to 1,000 messages per call.
- `include_bots`: false by default, preventing bot summaries from masquerading as original announcements.

Dates jump directly to Discord history cursors. Filtering runs inside the plugin; only matching excerpts enter model context, capped at approximately 8,000 characters. Batched searches scan no more than 250 messages and return at most four shortened matches per target. Retrieve a promising result using `messages`, the same channel ID and its exact `message_id` to inspect full wording.

Results include `scanned`, `complete`, and `next_before` or `next_after`. Resume partial results with that cursor and identical filters. An empty partial scan is not proof of absence; a found post is not necessarily the first across other channels or threads. Searches do not recursively include threads. Completed reads are retained as compact per-requester checkpoints, including evidence IDs and child cursors. Duplicate searches return their checkpoint rather than another Discord call.

Matched and exactly retrieved messages have a 15-minute cache, limited to 20 records and 12,000 serialized characters, scoped to the bot/chat/requester. Exact-message reads still check current server, user and channel permissions before using it. Cache hits do not consume a remote-read slot; `refresh: true` bypasses the cache when current edits or deletions matter. This is evidence reuse, not an archival index. Checkpoints may outlive cached records and must not be treated as fresh verification.

### Server-wide sweeps

Use `action: search` with `scope: server`, without individual channel targets. The bridge discovers readable message channels itself, including service channels, and reads up to four concurrently using discord.py's existing rate-limit handling. No extra tool is added.

Each call covers at most 64 channel pages and 1,000 scanned messages in total (`scan_limit` can lower this). Each channel page scans at most 250 messages and returns at most four matches. `limit` caps total matches at 20, also the server default. Match output is bounded; dense channels and larger servers require continuation.

```json
{"tool_name":"discord_read","tool_args":{"action":"search","scope":"server","query_any":["browser cache","evaluate null","large files"],"since":"2026-09-09","until":"2026-09-13","limit":12}}
```

Results contain flat matches with channel IDs, shared filters, checked channel IDs, compact coverage and individual errors. Pass `next_cursor` back as `cursor` with identical filters to resume unfinished channel pages and later channels. The upper date bound is frozen on the first call when omitted. Coverage counts are per call, not cumulative; retain earlier errors and checkpoints when reporting total coverage. `complete` cannot erase an earlier failed channel.

Threads, forum posts and archives remain a separate search scope. A completed channel sweep is never proof of complete thread coverage. An author-only sweep also cannot rule out related discussion by other members: use topic alternatives or PR-link searches across authors, then inspect matching messages and their surrounding discussion.

The model can include a short `progress` string in a subsequent `discord_read` call after finding a lead. The bridge sends at most one such update per response, with mentions disabled, then continues gathering evidence. Read-only replies can export their own fenced text as attachments, but cannot read or upload existing files.

The reader can list visible channels, active threads, and public archived threads for a parent. Thread listings accept a name query and date range, return no more than 30 records, and archive pagination uses archive timestamps, not creation IDs.

## File delivery

Complete line-based fenced blocks in replies become attachments, even when short. The language selects the extension: `js`/`javascript` becomes `.js`, `md`/`markdown` becomes `.md`, and `text` becomes `.txt`. Common programming/data languages are supported; unlabelled blocks default to `.md`, unknown labels to `.txt`. Each file contains the block body without its outer fences. Longer outer fences preserve nested Markdown examples. Surrounding prose stays in chat.

The same delivery path handles regular replies, slash-command output and `discord_send` content. It does not parse inline backticks, fetch URLs, interpret filenames in fence labels, or upload paths mentioned in prose. Unfinished fences stay inline. Generated files are built in memory and do not grant read-only sessions filesystem access.

Approved agents can use `discord_send` with an explicit `attachments` list of absolute local file paths for documents, images and other requested artifacts. At most 10 regular files of 10 MiB each are accepted by this tool. Symlinks, devices, directories, URLs and oversized files are rejected before sending. Normal bot credentials, server restrictions, tool policy and bridge access approvals still apply.

Gateway replies respect the server or interaction's upload limit. The REST tool uses a conservative 10 MiB limit. If uploads are denied or too large, generated text falls back to length-bounded messages with closed/reopened fences. Explicit files are never converted or silently discarded: failed uploads are reported in Discord and to the agent. Network/server errors are not retried as text because delivery may already have occurred. Output mentions are suppressed, and native `/a0` output remains private.

## Agent access approvals

Read-only is the default. Full agent access includes tools, code execution, files and external writes, subject to normal tool policy. Only the trusted Web UI operator can grant it; Discord messages and command output cannot approve access.

1. Contact the bot in the intended server channel: mention it, reply to it, or use native `/a0`. This records an unapproved user/channel request, not an authorization.
2. Open Discord **Config** under **Global / All profiles**, expand the bot, and find **Agent access**.
3. Check the user, channel and server IDs. Select 1 hour (default), 8 hours, 24 hours, or **Until revoked**, then confirm **Approve** on that row.
4. Use `!bridge-status` in Discord to see the current mode and expiry. **Revoke** in Config blocks new requests immediately; stop an already running task separately in its chat.

Approvals are scoped to an exact bot, server, user and channel. Threads require their own approval. All approvals persist across restarts. **Until revoked** has no automatic expiry; timed approvals expire normally. Both modes must still pass current bot-enabled, user-allowlist and server-allowlist checks. Approval actions apply immediately; bot-setting drafts must be saved first. Revoke remains available with unsaved settings or a stopped bot.

The approval API accepts `duration: 0` for Until revoked. State stores an explicit `expires_at: null` for permanent access; missing or zero expiry means no approval. Permanent approvals are not evicted as expired requests. Selecting the duration alone never grants access: confirm the exact row's Approve action.

No shared key, login/logout command, global elevation toggle or compatibility alias exists. Keys from older settings are not converted into approvals. Historical credential-message redaction remains a data-protection measure, not an authentication flow.

Both regular messages and slash commands use the same approval gate. Unapproved slash commands cannot execute scripts, inspect the command catalog or change chat state. Native `/a0` responses remain private; normal bot replies are visible to their channel, so approve only users you trust with the full agent and the channel's audience.

Pending identities and approvals are stored with the existing per-bot chat state. The list is bounded to 100 entries per bot; old inactive entries can be replaced when the list is full. No message text or credentials are stored in an access request.

## Agent Zero slash commands

Use Discord's native `/a0` command and enter a command such as `goal status` in its **command** field. Autocomplete uses the active chat's command catalog. Native responses are visible only to the requester. The bot registers this entry when it starts; restart the bridge after updating its code. If registration fails, check the Agent Zero logs and the application's command permissions and gateway interaction configuration.

Slash text also works: `@bot /commands`, or `/commands` in a registered channel. Replying to a bot message works too. Executable commands require the same per-bot, per-user, per-channel approval described above. `/stop` reaches an active task without waiting for its reply.

- `/commands [page]` lists available commands, including enabled plugin commands and project overrides. Custom commands use the shared Agent Zero resolver once.
- `/new`, `/sessions [page]`, and `/chat <ID>` manage saved chats belonging to this bot and channel. Other channels and bots cannot be selected.
- `/goal`, `/queue`, `/profile`, `/project`, `/models`, and `/browser` use the shared backend operations.
- `/permissions` lists canonical tool IDs and accepts `allow`, `block`, or `default`; `/plugins` lists instance-wide toggles. Follow the displayed syntax to change settings.
- `/compact` requests confirmation using the current chat ID. `/copy` sends a transcript file. `/attach` explains image attachments.

Commands that open WebUI-only settings provide a WebUI handoff. Host computer permissions remain controlled through A0 Launcher or A0 CLI. Command output suppresses Discord mentions.

## Monitoring and research skills

Use [discord-research](../skills/discord-research/SKILL.md) for optional structured bulk analysis, [discord-alerts](../skills/discord-alerts/SKILL.md) for monitoring, and [discord-persona-mapping](../skills/discord-persona-mapping/SKILL.md) for persistent notes. Their reference files load on demand, not into every baseline prompt.

Existing scheduled prompts that call removed public tool names must be updated to load the corresponding skill and invoke its workflow. New monitoring tasks do this automatically. Monitoring/persona storage remains plugin-wide; per-bot chat history and access approvals remain separate.
