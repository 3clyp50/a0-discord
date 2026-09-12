# Discord Integration Plugin — Setup Guide

## Requirements

- Agent Zero v2026-03-13 or later
- Docker or local Python 3.10+
- Discord account

## Dependencies

Installed automatically by `initialize.py`:
- `aiohttp` — Async HTTP client for Discord REST API calls
- `pyyaml` — YAML configuration parsing
- `discord.py` — Official Discord library (used by the chat bridge Gateway connection)

## Installation

### Option A: Plugin Hub (Recommended)

1. Open Agent Zero WebUI
2. Go to Settings > Plugins
3. Find "Discord Integration" and click **Install**
4. Dependencies install automatically via `hooks.py` → `initialize.py`
5. Restart Agent Zero

### Option B: Install Script

```bash
# Copy plugin to container and run install
docker cp a0-discord/. a0-container:/tmp/discord-plugin/
docker exec a0-container bash /tmp/discord-plugin/install.sh
```

The install script auto-detects the Agent Zero root (`/a0/` or `/git/agent-zero/`), copies files, creates the symlink, installs dependencies, and enables the plugin.

### Option C: Manual Installation

```bash
# Copy files
docker cp a0-discord/. a0-container:/a0/usr/plugins/discord/

# Create symlink for Python imports
docker exec a0-container ln -sf /a0/usr/plugins/discord /a0/plugins/discord

# Install dependencies
docker exec a0-container /opt/venv-a0/bin/python /a0/usr/plugins/discord/initialize.py

# Enable the plugin
docker exec a0-container touch /a0/usr/plugins/discord/.toggle-1

# Restart
docker exec a0-container supervisorctl restart run_ui
```

## Discord Bot Setup

### 1. Create a Discord Application

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** > name it > **Create**

### 2. Create the Bot and Get the Token

1. Go to the **Bot** tab in the left sidebar
2. Click **Reset Token**
3. Copy the **entire** token — this is your bot token

> **Important:** The bot token is a secret. Do not share it publicly. If compromised, regenerate it immediately via the Bot tab > Reset Token.

### 3. Enable Privileged Gateway Intents

Still on the Bot tab, scroll down to **Privileged Gateway Intents** and enable:

- **Message Content Intent** — Required for reading message content
- **Server Members Intent** — Required for the `discord_members` tool

### 4. Configure Installation Settings

1. Go to the **Installation** tab in the left sidebar
2. Under **Installation Contexts**, keep **Guild Install** checked (uncheck User Install if present)
3. Under **Default Install Settings** for Guild Install, add scope: `bot`
4. Add the following bot permissions:

| Permission | Purpose |
|---|---|
| View Channels | List and access server channels |
| Send Messages | Send messages via `discord_send` |
| Read Message History | Read past messages via `discord_read` |
| Add Reactions | Add reactions via `discord_send` |
| Embed Links | Rich embeds in bot messages |
| Manage Messages | Auto-delete `!auth` commands in chat bridge (security) |

### 5. Invite the Bot to Your Server

1. Copy the install link from the Installation tab
2. Open it in a browser
3. Select the server you want to add the bot to
4. Confirm the permissions and authorize

## User Token (Optional)

> **Warning:** Using a user token (also called a "self-bot" token) may violate Discord's Terms of Service. Use at your own risk.

The plugin supports an optional user token for read-only operations. When configured, the user token provides access to servers and channels that the bot account has not been invited to. The plugin enforces read-only usage — write operations (sending messages, reactions) always use the bot token.

### How to Get a User Token

1. Open Discord in a web browser (not the desktop app)
2. Press `F12` to open Developer Tools
3. Go to the **Network** tab
4. Send a message or perform any action in Discord
5. Click on any request to `discord.com/api`
6. In the request headers, find the `Authorization` header — this is your user token

### Configuration

Set the user token via one of these methods:

- **WebUI:** Settings > Discord > User Account > User Token
- **Config file:** Set `user.token` in `config.json`
- **Environment variable:** `DISCORD_USER_TOKEN`

The `user.read_only` flag defaults to `true` in `default_config.yaml` and should not be changed.

## Getting Server and Channel IDs

Discord uses numeric "snowflake" IDs for servers, channels, and users. You need these IDs when using plugin tools.

### Enable Developer Mode

1. Open Discord (desktop or web)
2. Go to **User Settings** (gear icon)
3. Navigate to **Advanced**
4. Toggle **Developer Mode** on

### Copy IDs

With Developer Mode enabled:

| What | How to Get |
|---|---|
| **Server ID** | Right-click the server name > **Copy Server ID** |
| **Channel ID** | Right-click the channel name > **Copy Channel ID** |
| **User ID** | Right-click a username > **Copy User ID** |

You can also extract IDs from a Discord URL:
```
https://discord.com/channels/SERVER_ID/CHANNEL_ID
```

## Credential Mapping Reference

| What You Need | Source | Plugin Config Field |
|---|---|---|
| Bot Token | Developer Portal > Bot > Reset Token | Settings > **Bot Token** |
| User Token (optional) | Browser DevTools > Network > Authorization header | Settings > **User Token** |
| Server IDs | Right-click server > Copy Server ID | Settings > **Allowed Server IDs** |
| Chat Bridge User Allowlist | Right-click user > Copy User ID | Settings > Chat Bridge > **User Allowlist** |
| Elevated Mode Auth Key | Auto-generated when elevated mode enabled | Settings > Elevated Mode > **Auth Key** |

## Verifying Installation

1. Open Agent Zero WebUI
2. Go to Settings > External Services
3. Confirm "Discord Integration" appears in the plugin list
4. Click the plugin
5. Enter your bot token and click the outer **Save** button
6. Use **Config** to manage bots. Save changes, then use each bot row's Start, Stop, Restart and Test connection icons.
7. Click **"Test Connection"**
8. Expected: green "Connected" badge showing your bot's username

If the test fails, check the [Troubleshooting](#troubleshooting) section below.

## How Authentication Works

### Bot Token

The bot token authenticates via the Discord Gateway API (WebSocket) for the chat bridge and via the REST API (`https://discord.com/api/v10/`) for all tool operations. The token is stored in `config.json` with `0600` permissions inside the plugin directory.

The token can also be set via the `DISCORD_BOT_TOKEN` environment variable, which overrides the config file value.

### User Token (Read-Only)

When configured, the user token is used only for read operations (`discord_read`). It authenticates against the same REST API but as a user account rather than a bot. Write operations are never routed through the user token — the plugin enforces this at the client layer regardless of the `user.read_only` config flag.

### Chat Bridge Authentication

The chat bridge has a separate two-tier authentication system:

1. **User Allowlist** — Only listed Discord user IDs can interact with the bot (empty = allow all server members)
2. **Elevated Mode Auth Key** — Users send `!auth <key>` in a bridge channel to unlock full agent access
   - Key is auto-generated (cryptographic random) or can be set manually
   - `!auth` messages are auto-deleted by the bot (requires Manage Messages permission)
   - Brute-force protection: 5 failed attempts per 5-minute window per user
   - Sessions expire after the configured timeout (default: 1 hour)
   - Users deauthenticate with `!deauth` (also accepts `!dauth`, `!unauth`, `!logout`, `!logoff`)

## Rate Limits

The Discord API enforces these limits:

| Limit | Value |
|---|---|
| Global requests per second | 50 |
| Per-endpoint per second | 5 (varies by endpoint) |
| Messages per channel per 5 seconds | 5 |
| Gateway identifies per day | 1000 |
| Invalid command responses per minute | 200 |

The plugin handles `429 Too Many Requests` responses from Discord by reporting the error. The `discord_client.py` helper includes per-route rate limit tracking that respects `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers returned by Discord.

The chat bridge enforces its own limits:
- **Message rate limit:** 10 messages per 60-second sliding window per user
- **Auth failure rate limit:** 5 failed attempts per 5-minute window per user

## Troubleshooting

| Issue | Solution |
|---|---|
| Plugin not visible | Check `.toggle-1` exists: `ls /a0/usr/plugins/discord/.toggle-1` |
| Plugin not loading | Check symlink: `ls -la /a0/plugins/discord` should point to `/a0/usr/plugins/discord` |
| "No module named 'plugins.discord'" | Create symlink: `ln -sf /a0/usr/plugins/discord /a0/plugins/discord` |
| Import errors | Run `initialize.py` again: `/opt/venv-a0/bin/python /a0/usr/plugins/discord/initialize.py` |
| API returns 404 | Files must be in `/a0/` (not just `/git/agent-zero/`). Re-run the installer or copy manually. |
| "Bot token not configured" | Enter token in plugin settings and click Save, or set `DISCORD_BOT_TOKEN` env var |
| "Discord API error 401" | Token is invalid — regenerate in Developer Portal > Bot > Reset Token |
| "Discord API error 403" | Bot lacks required permissions. Re-invite with correct permissions (View Channels, Send Messages, Read Message History, Add Reactions, Embed Links, Manage Messages) |
| Test shows "API unavailable" | Ensure `run_ui` is running: `supervisorctl status run_ui` |
| Chat bridge not responding | Check User Allowlist (if configured); ensure Message Content Intent is enabled in Developer Portal |
| Bridge "Already connected" error | Only one bridge instance can run per bot token — stop the existing bridge first |
| Bot doesn't see messages | Enable **Message Content Intent** in Developer Portal > Bot > Privileged Gateway Intents |
| Bot can't list members | Enable **Server Members Intent** in Developer Portal > Bot > Privileged Gateway Intents |
| "Infection check terminated" | See Known Behaviors in [QUICKSTART.md](QUICKSTART.md) |
| Config not saving | Use the outer framework Save button, not a custom button inside the plugin UI |
| Changes not taking effect | Clear cache and restart: `find /a0 -path '*/discord*/__pycache__' -exec rm -rf {} +` then `supervisorctl restart run_ui` |
