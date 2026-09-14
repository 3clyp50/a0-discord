"""Prompt injection defense for the Discord plugin.

Sanitizes all untrusted external content (messages, usernames, embeds,
filenames) before it reaches the LLM agent context.
"""

import os
import re
import unicodedata

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
MAX_MESSAGE_CONTENT = 4000
MAX_USERNAME = 100
MAX_EMBED_CONTENT = 2000
MAX_FILENAME = 255
MAX_BULK_INPUT_CHARS = 200_000
MAX_MESSAGE_LIMIT = 500  # Cap for summarize/insights limit arg

# ---------------------------------------------------------------------------
# Zero-width and invisible characters to strip
# ---------------------------------------------------------------------------
_INVISIBLE_CHARS = re.compile(
    "["
    "\u200b"  # zero-width space
    "\u200c"  # zero-width non-joiner
    "\u200d"  # zero-width joiner
    "\u200e"  # left-to-right mark
    "\u200f"  # right-to-left mark
    "\u2060"  # word joiner
    "\u2061"  # function application
    "\u2062"  # invisible times
    "\u2063"  # invisible separator
    "\u2064"  # invisible plus
    "\ufeff"  # zero-width no-break space / BOM
    "\u00ad"  # soft hyphen
    "\u034f"  # combining grapheme joiner
    "\u061c"  # arabic letter mark
    "\u115f"  # hangul choseong filler
    "\u1160"  # hangul jungseong filler
    "\u17b4"  # khmer vowel inherent aq
    "\u17b5"  # khmer vowel inherent aa
    "\u180e"  # mongolian vowel separator
    "\u2028"  # line separator
    "\u2029"  # paragraph separator
    "\u202a"  # left-to-right embedding
    "\u202b"  # right-to-left embedding
    "\u202c"  # pop directional formatting
    "\u202d"  # left-to-right override
    "\u202e"  # right-to-left override
    "\u202f"  # narrow no-break space
    "\ufff9"  # interlinear annotation anchor
    "\ufffa"  # interlinear annotation separator
    "\ufffb"  # interlinear annotation terminator
    "]+"
)

# ---------------------------------------------------------------------------
# Injection patterns (compiled once at module load)
# ---------------------------------------------------------------------------
# These catch common LLM prompt injection prefixes.  We match them
# case-insensitively at the start of a line (after optional whitespace).
_INJECTION_PHRASES = [
    # Classic instruction override
    r"ignore all previous instructions",
    r"ignore prior instructions",
    r"ignore above instructions",
    r"ignore the above",
    r"disregard all previous",
    r"disregard prior instructions",
    r"forget all previous",
    r"forget your instructions",
    # Role hijacking
    r"you are now",
    r"you must now",
    r"you will now",
    r"you should now",
    r"from now on",
    r"pretend you are",
    r"act as if",
    r"roleplay as",
    # Instruction injection
    r"new instructions:",
    r"override:",
    r"system:",
    r"SYSTEM:",
    r"reminder:",
    r"important:",
    r"attention:",
    r"actually,? (?:the user|i) (?:want|meant|need)",
    # Model-specific tokens
    r"\[INST\]",
    r"\[/INST\]",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"<<SYS>>",
    r"<</SYS>>",
    r"</s>",
    r"<\|endoftext\|>",
    r"<\|system\|>",
    r"<\|user\|>",
    r"<\|assistant\|>",
    # Chat role markers
    r"Human:",
    r"Assistant:",
    r"### Instruction",
    r"### System",
    r"## System",
    # Meta-manipulation
    r"the (?:previous|above|preceding) instructions (?:are|were)",
    r"do not follow (?:the|your) (?:previous|original)",
]

_INJECTION_RE = re.compile(
    r"^\s*(?:" + "|".join(_INJECTION_PHRASES) + r")",
    re.IGNORECASE | re.MULTILINE,
)

# Delimiter tags we use to wrap content — must be escaped inside user data
_DELIMITER_TAGS = [
    "<discord_user_content>",
    "</discord_user_content>",
    "<discord_embed_content>",
    "</discord_embed_content>",
    "<discord_messages>",
    "</discord_messages>",
]

_DELIMITER_RE = re.compile(
    "|".join(re.escape(tag) for tag in _DELIMITER_TAGS),
    re.IGNORECASE,
)

# Discord snowflake ID pattern (17-20 digit number)
_SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")

# Allowed URL hosts for image downloads (SSRF defense)
_ALLOWED_IMAGE_HOSTS = {
    "cdn.discordapp.com",
    "media.discordapp.net",
    "images-ext-1.discordapp.net",
    "images-ext-2.discordapp.net",
}


# ---------------------------------------------------------------------------
# Text normalization (Unicode defense)
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Normalize Unicode to defeat homoglyph and invisible-char attacks.

    1. NFKC normalization maps look-alike characters and decomposes
       compatibility characters.
    2. Strip zero-width / invisible characters that can split keywords.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_CHARS.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Sanitization functions
# ---------------------------------------------------------------------------

def sanitize_content(text: str, max_length: int = MAX_MESSAGE_CONTENT) -> str:
    """Sanitize a Discord message body for safe LLM consumption.

    - Normalizes Unicode (homoglyph / invisible char defense)
    - Neutralises known injection patterns
    - Escapes our own delimiter tags so they can't be spoofed
    - Truncates to *max_length* AFTER sanitization (prevents boundary attacks)
    """
    if not text:
        return ""
    # Normalize BEFORE pattern matching to defeat homoglyphs / zero-width
    text = _normalize_text(text)
    # Escape delimiter tags
    text = _DELIMITER_RE.sub(_escape_tag, text)
    # Block injection patterns
    text = _INJECTION_RE.sub("[blocked: suspected prompt injection]", text)
    # Truncate AFTER sanitization to prevent boundary attacks
    text = text[:max_length]
    return text


def sanitize_username(name: str, max_length: int = MAX_USERNAME) -> str:
    """Sanitize a Discord username / display name."""
    if not name:
        return "Unknown"
    name = _normalize_text(name)
    name = name[:max_length]
    # Collapse to single line
    name = name.replace("\n", " ").replace("\r", " ")
    # Escape delimiter tags
    name = _DELIMITER_RE.sub(_escape_tag, name)
    # Neutralise injection phrases in usernames
    name = _INJECTION_RE.sub("[blocked]", name)
    return name


def sanitize_embed(text: str, max_length: int = MAX_EMBED_CONTENT) -> str:
    """Sanitize Discord embed title or description."""
    if not text:
        return ""
    text = _normalize_text(text)
    text = _DELIMITER_RE.sub(_escape_tag, text)
    text = _INJECTION_RE.sub("[blocked: suspected prompt injection]", text)
    text = text[:max_length]
    return text


def sanitize_filename(name: str, max_length: int = MAX_FILENAME) -> str:
    """Sanitize an attachment filename."""
    if not name:
        return "file"
    name = name[:max_length]
    # Strip path traversal
    name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    # Remove newlines
    name = name.replace("\n", "").replace("\r", "")
    return name


def sanitize_channel_name(name: str, max_length: int = MAX_USERNAME) -> str:
    """Sanitize a channel or thread name from the Discord API."""
    if not name:
        return "unknown"
    name = _normalize_text(name)
    name = name[:max_length]
    name = name.replace("\n", " ").replace("\r", " ")
    name = _DELIMITER_RE.sub(_escape_tag, name)
    name = _INJECTION_RE.sub("[blocked]", name)
    return name


def truncate_bulk(text: str, max_length: int = MAX_BULK_INPUT_CHARS) -> str:
    """Truncate large message batches (for summarize / insights)."""
    if len(text) <= max_length:
        return text
    suffix = "\n[... truncated for safety ...]"
    return text[:max_length - len(suffix)] + suffix


def clamp_limit(limit: int, default: int = 100, maximum: int = MAX_MESSAGE_LIMIT) -> int:
    """Clamp a user-provided message limit to a safe range."""
    if limit < 1:
        return default
    return min(limit, maximum)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_snowflake(value: str, name: str = "ID") -> str:
    """Validate that a string is a valid Discord snowflake ID.

    Returns the validated string or raises ValueError.
    """
    if not value:
        raise ValueError(f"{name} is required.")
    value = value.strip()
    if not _SNOWFLAKE_RE.match(value):
        raise ValueError(f"Invalid {name}: must be a 17-20 digit number.")
    return value


def validate_image_url(url: str) -> bool:
    """Check that a URL is from an allowed Discord CDN host (SSRF defense)."""
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            return False
        if parsed.hostname not in _ALLOWED_IMAGE_HOSTS:
            return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def require_auth(config: dict) -> None:
    """Raise ValueError if neither bot nor user token is configured."""
    bot_token = (config.get("bot", {}).get("token", "") or "").strip()
    user_token = (config.get("user", {}).get("token", "") or "").strip()
    if not bot_token and not user_token:
        raise ValueError(
            "No Discord authentication token configured. "
            "Set DISCORD_BOT_TOKEN or DISCORD_USER_TOKEN, "
            "or configure tokens in the Discord plugin settings."
        )


# ---------------------------------------------------------------------------
# Secure file write helper
# ---------------------------------------------------------------------------

def secure_write_json(path, data, indent: int = 2):
    """Write JSON to a file with restrictive permissions (0o600) and atomic rename."""
    import json
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)
        os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        with open(path, "w") as f:
            json.dump(data, f, indent=indent)
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _escape_tag(match: re.Match) -> str:
    """Replace angle brackets in a matched delimiter tag so it's inert."""
    return match.group(0).replace("<", "&lt;").replace(">", "&gt;")
