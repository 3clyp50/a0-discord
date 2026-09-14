"""Plugin lifecycle hooks for the Discord Integration plugin.

Called by Agent Zero's plugin system during install, uninstall, and update.
See: helpers/plugins.py -> call_plugin_hook()
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("discord_hooks")


def _get_plugin_dir() -> Path:
    """Return the directory this hooks.py lives in."""
    return Path(__file__).parent.resolve()


def _get_a0_root() -> Path:
    """Detect A0 root directory."""
    if Path("/a0/plugins").is_dir():
        return Path("/a0")
    if Path("/git/agent-zero/plugins").is_dir():
        return Path("/git/agent-zero")
    return Path("/a0")


def _find_python() -> str:
    """Find the appropriate Python interpreter."""
    candidates = ["/opt/venv-a0/bin/python3", sys.executable, "python3"]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "python3"


def _sync_skills():
    import shutil
    source = _get_plugin_dir() / "skills"
    destination = _get_a0_root() / "usr" / "skills"
    # Verification now belongs to core guidance and per-bot instructions.
    retired = destination / "discord-testing"
    if retired.exists():
        shutil.rmtree(retired)
    for skill_dir in source.iterdir():
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            shutil.copytree(skill_dir, destination / skill_dir.name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))


def update(**kwargs):
    """Refresh plugin-owned skill mirrors without rerunning dependency setup."""
    _sync_skills()


def install(**kwargs):
    """Post-install hook: set up data dir, deps, skills, toggle."""
    plugin_dir = _get_plugin_dir()
    a0_root = _get_a0_root()
    plugin_name = "discord"

    logger.info("Running post-install hook...")

    # 1. Enable plugin
    toggle = plugin_dir / ".toggle-1"
    if not toggle.exists():
        toggle.touch()
        logger.info("Created %s", toggle)

    # 2. Create data directory with restrictive permissions
    data_dir = plugin_dir / "data"
    data_dir.mkdir(exist_ok=True)
    os.chmod(str(data_dir), 0o700)

    # 3. Pre-create config.json with restrictive permissions (0o600).
    # The framework's write_file() preserves permissions on existing files,
    # so subsequent saves via the settings UI will keep 0o600.
    config_file = plugin_dir / "config.json"
    if not config_file.exists():
        import json
        fd = os.open(str(config_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({}, f)
        logger.info("Created config.json with 0o600 permissions")

    # 4. Install skills, including their on-demand reference files.
    _sync_skills()

    # 5. Install Python dependencies via initialize.py
    init_script = plugin_dir / "initialize.py"
    if init_script.is_file():
        python = _find_python()
        try:
            subprocess.run(
                [python, str(init_script)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            logger.info("Dependencies installed")
        except subprocess.CalledProcessError as e:
            logger.warning("Dependency install failed: %s", e.stderr[:200])
        except subprocess.TimeoutExpired:
            logger.warning("Dependency install timed out")

    # 6. Mirror to /git/agent-zero if running in /a0 runtime
    if str(a0_root) == "/a0" and Path("/git/agent-zero/usr").is_dir():
        git_plugin = Path("/git/agent-zero/usr/plugins") / plugin_name
        if not git_plugin.exists():
            try:
                import shutil
                shutil.copytree(str(plugin_dir), str(git_plugin))
            except Exception:
                pass

    logger.info("Post-install hook complete")


def save_plugin_config(settings: dict, **kwargs) -> dict:
    """Validate bot settings; agent approvals are managed separately in the Web UI."""
    import re
    from usr.plugins.discord.helpers.discord_client import get_bot_configs, resolve_agent_profile

    bots = get_bot_configs(settings)
    if not isinstance(bots, list):
        raise ValueError("Discord bots must be a list.")
    ids, tokens = set(), set()
    for bot in bots:
        if not isinstance(bot, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(bot.get("id", ""))):
            raise ValueError("Each Discord bot needs a stable ID (letters, digits, underscore or hyphen).")
        if bot["id"] in ids:
            raise ValueError("Discord bot IDs must be unique.")
        ids.add(bot["id"])
        bot["name"] = str(bot.get("name", "") or "").strip() or bot["id"]
        token = str(bot.get("token", "") or "").strip()
        if token and token in tokens:
            raise ValueError("Each Discord bot needs its own token. This token is already configured.")
        if token:
            tokens.add(token)
        bot["token"] = token
        if not isinstance(bot.get("enabled", True), bool):
            raise ValueError("Discord bot enabled must be true or false.")
        bridge = bot.setdefault("chat_bridge", {})
        if not isinstance(bridge, dict):
            raise ValueError("Discord chat bridge settings must be an object.")
        bridge = {key: value for key, value in bridge.items()
                  if key in ("auto_start", "default_preset", "default_agent_profile", "allowed_users", "instructions")}
        bot["chat_bridge"] = bridge
        if not isinstance(bridge.setdefault("instructions", ""), str):
            raise ValueError("Discord instructions must be text.")
        for owner, field in ((bot, "servers"), (bridge, "allowed_users")):
            values = owner.get(field, [])
            if not isinstance(values, list) or any(not str(value).isdigit() for value in values):
                raise ValueError("Discord server and user allowlists must contain numeric IDs.")
            owner[field] = [str(value) for value in values]
        for field in ("auto_start",):
            if not isinstance(bridge.get(field, False), bool):
                raise ValueError(f"Discord {field} must be true or false.")
        bridge["default_agent_profile"] = resolve_agent_profile(
            bridge.get("default_agent_profile", ""), kwargs.get("project_name") or None
        )
    settings["bots"] = bots
    # The list is authoritative; removing its last entry must not revive the old bot.
    settings["bot"] = {"token": ""}
    settings["chat_bridge"] = {}
    return settings


def uninstall(**kwargs):
    """Pre-uninstall hook: clean up skills."""
    a0_root = _get_a0_root()
    plugin_name = "discord"

    logger.info("Running uninstall hook...")

    # Remove skills
    skills_dst = a0_root / "usr" / "skills"
    for skill_name in ['discord-alerts', 'discord-chat', 'discord-communicate', 'discord-persona-mapping', 'discord-research', 'discord-testing']:
        skill_path = skills_dst / skill_name
        if skill_path.is_dir():
            import shutil
            shutil.rmtree(str(skill_path))
            logger.info("Removed skill: %s", skill_name)

    logger.info("Uninstall hook complete")
