# Chat Bridge Configuration Guide

Use Discord as a real-time chat frontend to Agent Zero's LLM. Mention the bot with `@Bot your message` in an allowed server to create a chat, without registering a channel first. Later mentions or Discord replies to the bot in the same channel reuse that chat, even when reply notifications are disabled. Mentioning only `@Bot` starts with a greeting.

The chat appears in Agent Zero's sidebar as `Discord #channel`, with saved messages and replies. New chats use the configured default preset and agent profile. Read-only mode includes the profile instructions and actual model, preset, profile, time, and Discord context. Shell access and publishing still require elevated-mode authentication.

Each request includes the latest 30 channel messages and any replied-to message. The model can make up to eight further read requests, list readable server channels, read messages with source links, and browse active and public archived threads. History pages contain at most 100 messages and 40,000 serialized characters. Pagination cursors indicate partial coverage; the entire server is not loaded into every prompt.

Reads remain within the current allowed server and require both the bot and requesting member to have channel visibility and Read Message History permission. Private threads also require membership unless the member can manage threads. Authentication commands are excluded from model context. Read access never falls back to a user token.

Enable **Auto-start chat bridge** to connect at startup, even with no registered channels. The background job loop also picks up this setting within a minute. Channels registered through `discord_chat` additionally receive replies to messages without a mention; mentioning a bot does not register the channel for this behavior.

Run the mention regression check in the Agent Zero framework environment from `/a0`:

```bash
/opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_mentions
/opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_bridge_reader
```

---

## Multiple bots

In Config, add a bot entry for each Discord application and choose its preset/profile and access rules. Save, then use Open to start it or enable its auto-start setting. Every bot has its own gateway connection, rate limits, authentication sessions, registered channels and channel-to-chat mappings, even when bots share a Discord channel. Existing single-bot chats stay in the `default` namespace. A local label change never changes the stable bot ID.

Pass `bot_id` to any `discord_chat` action to select a bot. Without it, commands use the current Discord chat's bot, or the first enabled configured bot for ordinary Agent Zero chats. Removed bots stop on the next background tick; their saved chats are retained.

The Open dashboard shows saved defaults for **new** chats; existing chats retain their selected model/profile. Stop pauses auto-start for the current Agent Zero process; Start or Restart resumes it.

Runnable isolation check (does not contact Discord):

```bash
/opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_multi_bot
```

## How the Chat Bridge Works

```
Discord User sends message in #llm-chat
    |
    v
Discord Gateway (WebSocket) ---> ChatBridgeBot (discord.py)
    |
    v
on_message() handler checks:
  1. Is the bot mentioned, replied to, or is this a designated chat channel? (skip otherwise)
  2. Is the author a bot? (skip bots)
  3. Are the server and author allowed? (silently ignore if not)
  4. Is this an auth/deauth command? (handle separately)
  5. Is the message empty? (skip empty)
  6. Rate limit check (10 msgs / 60 sec per user)
    |
    v
Show typing indicator in Discord
    |
    v
Route based on session state:
  - Elevated session active -> full Agent Zero agent loop
  - Otherwise -> preset's main chat model with scoped read-only Discord access
    |
    v
Create/retrieve AgentContext for this channel
  - New chats use the bridge's default preset and agent profile
  - Messages and replies are saved to history and the WebUI log
  - Image attachments: saved to temp files and forwarded as file paths
  - Each channel has its own conversation context (independent history)
    |
    v
LLM generates response
    |
    v
Send response back to Discord channel
  - Replies to the original message
  - Splits into 2000-char chunks if needed
```

---

## Security

The chat bridge is designed with a **defense-in-depth** approach. Multiple independent layers work together to control who can interact with the bot and what they can do.

### Privilege Isolation (Architectural)

By default, the chat bridge operates in **read-only mode**: Discord messages use the selected preset's main model and profile instructions. The only executable operation is the dedicated Discord reader; every other tool request is rejected in code. Read-only conversations cannot run commands, access local files, submit issues, or create PRs. Runtime metadata is supplied explicitly so the model can identify its provider/model and explain the bridge's extras without guessing.

### User Allowlist (Access Control)

The User Allowlist controls which Discord users can interact with the chat bridge at all. When configured, unlisted users are **silently ignored** -- the bot sends no response and reveals no information about its existence or capabilities.

| Allowlist State | Behavior |
|-----------------|----------|
| Empty (default) | All server members can interact |
| Populated | Only listed user IDs receive responses |

**Key behaviors:**
- Changes take effect **immediately** -- no bridge restart needed. The config is read on every incoming message.
- Unlisted users receive **no feedback** -- this prevents information leakage.
- User IDs must be Discord snowflake IDs (17-20 digit numbers). Get them via Developer Mode (right-click user > Copy User ID).

Configure in the WebUI (Settings > Chat Bridge > User Allowlist) or in `config.json`:
```json
{
  "chat_bridge": {
    "allowed_users": ["123456789012345678", "987654321098765432"]
  }
}
```

### Elevated Mode (Full Agent Access)

Elevated mode is an **opt-in** feature that allows authenticated Discord users to access the full Agent Zero agent loop, including all tools, code execution, file operations, and system access.

**This is disabled by default.** When enabled, users must authenticate at runtime using `!auth <key>` before gaining elevated access.

#### Security Model

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Discord Server                                 │
│   Only members of your private server can see channels  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Layer 2: User Allowlist                           │  │
│  │   Only listed user IDs get any bot response       │  │
│  │                                                   │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │ Layer 3: Auth Key (2FA)                     │  │  │
│  │  │   Must know the key to elevate              │  │  │
│  │  │                                             │  │  │
│  │  │  ┌───────────────────────────────────────┐  │  │  │
│  │  │  │ Layer 4: Session Timeout              │  │  │  │
│  │  │  │   Elevated access expires             │  │  │  │
│  │  │  └───────────────────────────────────────┘  │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

#### Optimal Configuration

The **recommended setup** for elevated mode:

1. **Dedicated private Discord server** -- Create a server specifically for Agent Zero. Do not enable elevated mode on public or community servers. The server is part of your security perimeter.

2. **Defined User Allowlist** -- Explicitly list every Discord user ID that should have access. This is your primary access control.

3. **Minimal membership** -- Ideally a single user and the bot. This is the strongest configuration because the communication channel is fully controlled. If collaboration is needed, only invite people you deeply trust.

4. **Short session timeouts** -- Use the default 1-hour timeout or shorter. This limits exposure if a session is left active.

5. **Secure key distribution** -- Share the auth key only through secure, out-of-band channels (not through Discord). Regenerate if you suspect compromise.

7. **Manage Messages permission** -- The bot **must** have the `Manage Messages` permission to auto-delete `!auth` commands. Without this, the auth key will remain visible in the channel history. Grant this in Server Settings > Roles > [bot role] > Manage Messages, or re-invite the bot with updated permissions.

6. **Discord security awareness** -- Understand Discord's permission model: channel visibility, role hierarchy, and server verification levels all affect who can observe bot interactions.

#### What Elevated Mode Grants

When a user authenticates with `!auth <key>`, their messages are routed through the **full Agent Zero agent loop** instead of a restricted model call. This gives them access to:

- All Agent Zero tools (code execution, file read/write, web requests, etc.)
- The host filesystem (within the Agent Zero container)
- All installed plugins and their capabilities
- Network access from the container

**Only enable elevated mode if you fully understand these implications.**

#### Authentication Flow

1. User types `!auth <key>` in a bridge channel
2. The `!auth` message is **automatically deleted** to protect the key (requires the bot to have **Manage Messages** permission -- without it, the key remains visible in chat)
3. If the key matches, the user's session is elevated for the configured timeout
4. All messages from this user now route through the full agent loop
5. Session expires after the timeout, or the user types `!deauth`
6. On deauth, conversation history is cleared and the user returns to restricted mode

#### Deauth Commands

The bot recognizes multiple aliases for ending an elevated session:
`!deauth`, `!dauth`, `!unauth`, `!logout`, `!logoff`

This tolerance for common typos ensures users can always exit elevated mode.

### Rate Limiting

A sliding-window rate limiter (10 messages per 60 seconds per user) protects against abuse. This applies in both restricted and elevated modes.

---

## Configuration

The chat bridge has two configuration layers:

### 1. Plugin Config (persistent settings)

Stored in `config.json` (via WebUI or API). Controls whether the bot auto-starts.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `chat_bridge.auto_start` | bool | `false` | Start the bot automatically when Agent Zero initializes |
| `chat_bridge.allowed_users` | list | `[]` | Discord user IDs allowed to interact. Empty = all users. |
| `chat_bridge.allow_elevated` | bool | `false` | Enable elevated mode (full agent access via `!auth`) |
| `chat_bridge.auth_key` | string | `""` | Auth key for elevated mode. Auto-generated on first use if empty. |
| `chat_bridge.session_timeout` | int | `3600` | Elevated session timeout in seconds (0 = never expire) |

**Set via WebUI:**
Go to Discord plugin settings page > Chat Bridge section. Configure the User Allowlist and elevated mode settings as needed, then click **Save Discord Settings**.

**Set via config file** (`usr/plugins/discord/config.json`):
```json
{
  "bot": {
    "token": "YOUR_BOT_TOKEN"
  },
  "chat_bridge": {
    "auto_start": true,
    "allowed_users": ["YOUR_DISCORD_USER_ID"],
    "allow_elevated": false,
    "session_timeout": 3600
  }
}
```

**Set via API:**
```bash
curl -X POST http://localhost/api/plugins/discord/discord_config_api \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "set",
    "config": {
      "bot": {"token": "YOUR_BOT_TOKEN"},
      "chat_bridge": {
        "auto_start": true,
        "allowed_users": ["YOUR_DISCORD_USER_ID"],
        "allow_elevated": false
      }
    }
  }'
```

### 2. Channel Assignments (runtime state)

Channels are NOT configured in `config.json`. They are managed at runtime through the `discord_chat` tool and stored in `data/chat_bridge_state.json`.

This separation exists because channels are managed interactively — you add and remove them by talking to the agent, not by editing config files.

**Add a channel (tell Agent Zero):**
> Add Discord channel YOUR_CHANNEL_ID to the chat bridge, label it "llm-chat", server YOUR_SERVER_ID

Replace `YOUR_CHANNEL_ID` and `YOUR_SERVER_ID` with your actual Discord IDs (see [Getting Discord IDs](#step-1-identify-your-channel) below).

**Or call the tool directly:**
```json
{
  "tool": "discord_chat",
  "args": {
    "action": "add_channel",
    "channel_id": "YOUR_CHANNEL_ID",
    "guild_id": "YOUR_SERVER_ID",
    "label": "llm-chat"
  }
}
```

**The state file** (`data/chat_bridge_state.json`) looks like:
```json
{
  "channels": {
    "YOUR_CHANNEL_ID": {
      "guild_id": "YOUR_SERVER_ID",
      "label": "llm-chat",
      "added_at": "2026-03-05T14:30:00Z"
    }
  },
  "contexts": {
    "YOUR_CHANNEL_ID": "a1b2c3d4-uuid-of-agent-context"
  }
}
```

You can also edit this file directly if needed, but the tool is the recommended approach.

---

## Prerequisites

### 1. Bot Token
A Discord bot token is required. The chat bridge uses the Gateway (WebSocket) connection via `discord.py`, which only works with bot tokens (not user tokens).

Set it via any of:
- Config file: `config.json` -> `bot.token` (most reliable)
- Environment variable: `DISCORD_BOT_TOKEN=...`
- WebUI: Discord plugin settings > Bot Account > Bot Token

### 2. Gateway Intents
In the [Discord Developer Portal](https://discord.com/developers/applications), your bot application must have these Privileged Gateway Intents enabled:

| Intent | Required | Why |
|--------|----------|-----|
| **Message Content** | Yes | Read message text from users |
| **Server Members** | Recommended | Resolve display names |

Without Message Content intent, the bot will connect but `message.content` will be empty for all messages.

### 3. Bot Permissions
The bot needs these permissions in the channel(s) you designate:

| Permission | Why |
|------------|-----|
| View Channel | See the channel |
| Read Message History | Access messages |
| Send Messages | Reply with LLM responses |
| Manage Messages | Auto-delete `!auth` commands to protect the key (required for elevated mode) |

### 4. Bot Invited to Server
The bot must be a member of the server containing the channel. Use the OAuth2 URL Generator in the Developer Portal to create an invite link.

---

## Step-by-Step Setup

### Quick Setup (3 commands)

```
You: List channels in Discord server YOUR_SERVER_ID
Agent: [shows channels with IDs]

You: Add channel YOUR_CHANNEL_ID to the Discord chat bridge, call it "llm-chat"
Agent: Channel YOUR_CHANNEL_ID added to chat bridge (#llm-chat).

You: Start the Discord chat bridge
Agent: Chat bridge started as MyBot#1234. Listening in 1 channel(s).
```

Done. Go to `#llm-chat` in Discord and start chatting.

### Detailed Setup

#### Step 1: Identify Your Channel

If you don't know the channel ID:

**Option A — Ask Agent Zero:**
> Show me channels in Discord server YOUR_SERVER_ID

**Option B — Discord Developer Mode:**
Enable Developer Mode (User Settings > Advanced > Developer Mode), then right-click the channel > Copy Channel ID.

**Option C — From URL:**
```
https://discord.com/channels/SERVER_ID/CHANNEL_ID
```

#### Step 2: Register the Channel

Tell Agent Zero:
> Add Discord channel CHANNEL_ID to the chat bridge, label it "llm-chat"

The label is optional but makes status output more readable.

You can register multiple channels:
> Add channel CHANNEL_ID_1 to the chat bridge as "general-ai"
> Add channel CHANNEL_ID_2 to the chat bridge as "dev-help"

Each channel gets its own independent conversation context.

#### Step 3: Start the Bot

> Start the Discord chat bridge

The bot connects via WebSocket and begins listening. You'll see:
```
Chat bridge started as MyBot#1234.
Listening in 2 channel(s).
```

#### Step 4: Verify

> Show Discord chat bridge status

```
Chat bridge is connected as MyBot#1234
  User ID: <bot_user_id>
  Guilds: 1
  Chat channels: 2
    - #general-ai (ID: <channel_id_1>)
    - #dev-help (ID: <channel_id_2>)
```

#### Step 5: Enable Auto-Start (Optional)

So the bridge starts automatically after an Agent Zero restart:

> Enable auto-start for the Discord chat bridge

Or set it in config:
```json
{
  "chat_bridge": {
    "auto_start": true
  }
}
```

Auto-start activates when these conditions are met:
1. A bot token is configured
2. `chat_bridge.auto_start` is `true`
3. The Discord plugin is enabled; no registered channels are required

---

## Managing the Chat Bridge

### Check Status
```
You: What's the Discord chat bridge status?
```

### Stop the Bot
```
You: Stop the Discord chat bridge
```

### Add a Channel
```
You: Add channel YOUR_CHANNEL_ID to the chat bridge as "research"
```

### Remove a Channel
```
You: Remove channel YOUR_CHANNEL_ID from the chat bridge
```

### List Channels
```
You: List Discord chat bridge channels
```

### Reset a Conversation
To start fresh in a channel (clear conversation history), remove its context from `data/chat_bridge_state.json`:

```json
{
  "channels": { ... },
  "contexts": {
    "YOUR_CHANNEL_ID": "DELETE_THIS_ENTRY"
  }
}
```

The next message in that channel will create a new conversation context.

---

## Behavior Details

### Message Routing
- Mentions, replies to the bot, and messages in registered channels are processed
- Bot messages are ignored (prevents loops)
- Users not on the allowlist are silently ignored (when allowlist is configured)
- Empty messages are ignored
- Read-only user messages include their Discord display name for context
- If the user has an active elevated session, messages route through the full agent loop
- Otherwise, messages route through the preset's main model with scoped read-only Discord access

### Image Handling
When a user sends an image attachment in a chat bridge channel:
1. The image is downloaded from Discord's CDN
2. Saved to a temporary file on disk
3. The file path is passed to `UserMessage(attachments=[...])` for the LLM
4. The LLM can analyze/describe the image if it supports vision

### Response Splitting
Discord has a 2000-character message limit. Long LLM responses are automatically split:
1. Try to split at the last newline before 2000 chars
2. If no newline, split at the last space
3. If no space, hard-split at 2000 chars
4. The first chunk replies to the original message; subsequent chunks are standalone

### Conversation Contexts
- Each channel has its own Agent Zero `AgentContext`
- Context IDs persist in `data/chat_bridge_state.json`
- If Agent Zero's in-memory context expires (e.g., after restart), a new one is created automatically
- Multiple users in the same channel share the same context (the LLM sees all messages)

### Typing Indicator
The bot shows Discord's typing indicator (`... is typing`) while the LLM processes the response. This gives users visual feedback that the bot received their message.

### Concurrent Messages
If multiple messages arrive while one is being processed, they queue up and are handled sequentially (one at a time per channel, due to the typing indicator lock).

---

## Architecture

### Files

| File | Purpose |
|------|---------|
| `helpers/discord_bot.py` | `ChatBridgeBot` class (discord.py Client), lifecycle management, channel state persistence |
| `tools/discord_chat.py` | `DiscordChat` Tool — management actions (start/stop/add/remove/list/status) |
| `extensions/python/agent_init/_10_discord_chat.py` | Auto-start extension hook |
| `data/chat_bridge_state.json` | Persisted channel assignments and context IDs |

### Key Classes and Functions

**`ChatBridgeBot(discord.Client)`** -- The bot itself:
- `on_ready()` -- Logs when connected (uses discord.py's built-in ready state)
- `on_message()` -- Routes messages from designated channels to Agent Zero
- `_get_agent_response()` -- In-process routing via `initialize_agent()` + `AgentContext.communicate()`
- `_get_agent_response_http()` -- HTTP fallback via `POST /api/api_message`
- `_send_response()` -- Sends (potentially split) responses back to Discord
- `wait_until_ready_timeout()` -- Waits for Gateway connection with timeout (uses discord.py's built-in `wait_until_ready()`)

**Module-level functions:**
- `start_chat_bridge(token)` — Start the singleton bot as a background task
- `stop_chat_bridge()` — Gracefully shut down the bot
- `get_bot_status()` — Returns running/status/user/guilds info
- `add_chat_channel(channel_id, guild_id, label)` — Register a channel
- `remove_chat_channel(channel_id)` — Unregister a channel
- `get_chat_channels()` — List registered channels
- `get_context_id(channel_id)` / `set_context_id(channel_id, context_id)` — Context persistence

### Singleton Pattern
Only one bot instance runs at a time. `start_chat_bridge()` checks if a bot is already running and returns the existing instance if so. This prevents duplicate Gateway connections.

---

## Troubleshooting

### Bot connects but doesn't respond to messages

1. **User not on allowlist** — If `chat_bridge.allowed_users` is configured, only listed user IDs get responses. Check the allowlist in WebUI Settings or `config.json`.
2. **No trigger** — Mention the bot or reply to one of its messages. Register a channel with `discord_chat add_channel` only if every message should receive a reply.
3. **Missing Message Content intent** — Enable it in Developer Portal > Bot > Privileged Gateway Intents.
4. **Bot doesn't have channel access** — Ensure the bot role has View Channel + Read Message History + Send Messages in the target channel.

### "Bot failed to connect within timeout"

- Invalid bot token -- verify with: `curl -H "Authorization: Bot YOUR_TOKEN" https://discord.com/api/v10/users/@me`
- Network issue -- check that the Agent Zero container can reach `gateway.discord.gg`
- Discord outage -- check [Discord Status](https://discordstatus.com)

### Bot responds to itself / loops

This shouldn't happen — `on_message()` skips all bot messages (`message.author.bot`). If you see loops, check if another bot is relaying messages.

### Responses are cut off

Discord's 2000-char limit applies. The bot splits long messages automatically, but check that it has Send Messages permission (needed for each chunk).

### Context doesn't persist after restart

The channel-to-context mapping is saved in `data/chat_bridge_state.json`. However, the Agent Zero context itself is in-memory. After a full Agent Zero restart, the context UUID may point to a context that no longer exists, and a new one will be created. This means conversation history resets on restart.

### Multiple users in same channel — who's talking?

Each message is prefixed with `[Discord - DisplayName]:` so the LLM knows who said what. All users in a channel share the same conversation context.
