# Discord Plugin for Agent Zero

Read and communicate in Discord with a small default tool surface. Connect multiple bots to saved Agent Zero conversations, with per-bot presets, agent profiles and access rules.

## Two baseline tools

| Tool | Purpose |
| --- | --- |
| `discord_read` | Messages, channels, threads, live member lists and individual member details. |
| `discord_send` | Authorized messages/reactions and explicitly loaded, write-capable skill workflows. |

Member reads do not modify the persona registry. The five former standalone tools are preserved as private workflow implementations under `helpers/workflows/`, not advertised tool definitions. Text prompts and native function discovery see only the two public tool files and their two prompt files.

## On-demand skills

| Skill | Load when needed | Reference files |
| --- | --- | --- |
| `discord-research` | Structured bulk summaries or insight extraction; ordinary short summaries need no extra model call. | `references/summarize.md`, `references/insights.md` |
| `discord-alerts` | Watch channels, check new alerts, or explicitly schedule recurring monitoring. | `references/monitoring.md` |
| `discord-chat` | Administer bot connections and register automatic-reply channels. | `references/bridge.md` |
| `discord-persona-mapping` | Synchronize or maintain persistent member notes and registry records. | `references/personas.md` |
| `discord-communicate` | Compose authorized messages, replies and reactions. | `references/messaging.md` |

Load the skill with `skills_tool`, then open only the reference needed for the request:

```json
{"tool_name":"skills_tool","tool_args":{"action":"load","skill_name":"discord-research"}}
```

```json
{"tool_name":"skills_tool","tool_args":{"action":"read_file","skill_name":"discord-research","file_path":"references/summarize.md"}}
```

The reference documents calls through `discord_send` with `action: workflow`, `workflow`, `operation`, and a `parameters` object. Workflow names and operations are allowlisted; arbitrary Python imports or tool names are not accepted. The matching skill must be loaded in the current chat. Both the write tool's policy and explicit legacy backend policy blocks remain enforced.

Bulk research saving is opt-in (`save_to_memory: true`); monitoring still updates cursors, stores alerts and may load images. These side effects are why optional workflows use the write-capable entry, rather than hiding writes inside `discord_read`. Loading a skill is not permission to publish or create scheduled tasks.

The current chat's bot is used for research, monitoring and personas; ordinary Agent Zero chats use the first enabled configured bot. Administration supports an explicit stable `bot_id`. Monitoring and persona state remain plugin-wide.

## Install and configure

Install this repository with Agent Zero's plugin installer. The standalone plugin belongs under `usr/plugins/discord`. Lifecycle hooks prepare dependencies and mirror the bundled skills, including nested reference files, into `usr/skills/`. Updates refresh these skill files without rerunning dependency setup.

For each Discord bot:

1. Create a separate application and bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable Message Content Intent; enable Server Members Intent if member-list operations are needed.
3. Invite the bot with View Channels, Read Message History and Send Messages. Add Add Reactions for reactions and Manage Messages for deleting authentication commands.
4. Open plugin **Config**, add an entry, and enter its token. Choose a label, preset, agent profile, server/user allowlists and auto-start behavior.
5. Save, then reopen **Config**. Each bot row has Start, Stop and Restart icons, live status and tooltips. New or edited bots must be saved before starting or restarting; Stop remains available for running bots.

Names are local labels; renaming an entry does not change its stable ID or saved chats. The plugin connects applications, not creates Discord applications. Gateway bot configuration belongs in global plugin settings; profile/project-scoped settings affect agent tools, not extra gateway instances.

`DISCORD_BOT_TOKEN` overrides the entry with ID `default`; `DISCORD_USER_TOKEN` is an optional read-only account override. User-token use may violate Discord's terms; prefer bot accounts. Never put tokens in prompts, skill files, commits or Discord messages.

Legacy single-bot configuration migrates on Config Save. An explicit empty `bots` list does not revive the old configuration. Removing a bot retains saved chats. Stop pauses auto-start until manual Start or an Agent Zero process restart.

## Discord chat bridge

Mention a bot or reply to its message to create or continue a saved chat. Register a channel only for replies to every message. Bots in the same channel have independent chats, authentication sessions and rate limits.

The read-only bridge has its own dedicated `discord_read` interface, not the two general Agent Zero tools. It includes recent channel context, real runtime model/profile metadata, and permission-scoped server/thread reading. It supports keyword/author/date search that scans inside the plugin and returns compact matches, plus exact-message retrieval. Its eight-read budget is unchanged.

See [Chat Bridge Guide](docs/CHAT_BRIDGE.md) for dates, coverage, authentication and limits. The focused `search` action belongs to the bridge reader; do not invent that action for the normal Agent Zero `discord_read` tool.

## Security

- External message text, usernames, embeds, images and attachments are untrusted data, not instructions or authorization.
- Read-only bridge access requires both bot and requesting member to see the channel and read its history, within configured server/user allowlists. Private threads additionally require membership unless the member can manage threads. The bridge never falls back to a user token.
- The normal agent tools and skill workflows run with the trusted Agent Zero operator's privileges and configured accounts. They are not a replacement for the stricter Discord member-scoped reader.
- Elevated Discord access is off by default. Enabling it allows authenticated users full Agent Zero capabilities, including local files, code execution and external writes. Use a private server, an explicit trusted-user allowlist and short session timeouts.
- Runtime `!auth <key>` authentication is required after operator opt-in. Protect the key; deleting an authentication message requires Manage Messages. Never send it in a public channel. `!deauth` ends the session. Loading a skill does not establish authentication.
- Tool-policy blocks are retained for the former names (`plugin:discord:discord_poll`, etc.). Allowing `discord_send` alone does not override a blocked workflow backend.
- Credentials and runtime files under `config.json` and `data/` are not distribution assets. Do not overwrite them during deployment.

## Upgrade from seven tools

Use live member operations through `discord_read` (`members` / `member`). Load the appropriate skill for the other capabilities; old `discord_chat`, `discord_members`, `discord_poll`, `discord_summarize` and `discord_insights` calls are no longer public tool calls.

New monitoring tasks load `discord-alerts` and invoke the documented workflow. Existing custom or scheduled prompts that directly call the old tool names must be updated; the plugin does not silently rewrite operator-authored tasks. Existing state and saved chats are retained.

Config is the only plugin page. Bot rows use Agent Zero's fields, icon buttons, shared Advanced accordions and notifications. Status refreshes while the modal is open and stops when it closes. Scoped settings cannot operate global bridge controls.

## Runnable checks

From `/a0`, use the framework interpreter:

```bash
/opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_skill_workflows
/opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_bridge_search
/opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_bridge_reader
/opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_multi_bot
```

These are offline checks; they do not establish live Discord or model-provider behavior.
