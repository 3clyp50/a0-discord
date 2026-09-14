"""Shared Discord delivery: fenced artifacts, explicit uploads and text fallback."""
import json
import os
import re
import stat
from pathlib import Path

DEFAULT_UPLOAD_LIMIT = 10 * 1024 * 1024
MAX_ATTACHMENTS = 10
EXTENSIONS = {
    "": "md", "md": "md", "markdown": "md",
    "text": "txt", "txt": "txt", "plaintext": "txt",
    "js": "js", "javascript": "js", "jsx": "jsx",
    "ts": "ts", "typescript": "ts", "tsx": "tsx",
    "py": "py", "python": "py", "json": "json",
    "yaml": "yaml", "yml": "yaml", "toml": "toml",
    "html": "html", "css": "css", "xml": "xml", "svg": "svg",
    "sh": "sh", "bash": "sh", "shell": "sh", "zsh": "sh",
    "sql": "sql", "csv": "csv", "c": "c", "cpp": "cpp", "c++": "cpp",
    "cs": "cs", "csharp": "cs", "java": "java", "go": "go",
    "rust": "rs", "rs": "rs", "ruby": "rb", "rb": "rb", "php": "php",
}


def fences(text, include_unclosed=False):
    """Yield (start, end, language, body, marker) for line-based fenced blocks."""
    opening = None
    offset = 0
    for line in text.splitlines(keepends=True):
        if opening is None:
            match = re.fullmatch(r" {0,3}(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?", line)
            if match:
                marker, info = match.groups()
                if marker[0] != "`" or "`" not in info:
                    language = info.strip().split()[0].lower() if info.strip() else ""
                    opening = (offset, offset + len(line), language, marker)
        else:
            start, body_start, language, marker = opening
            if re.fullmatch(r" {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*(?:\r?\n)?", line):
                yield start, offset + len(line), language, text[body_start:offset], marker
                opening = None
        offset += len(line)
    if opening and include_unclosed:
        start, body_start, language, marker = opening
        yield start, len(text), language, text[body_start:], marker


def _text_chunks(text, limit):
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit) + 1 or text.rfind(" ", 0, limit) + 1 or limit
        yield text[:cut]
        text = text[cut:]
    if text:
        yield text


def split_message(text, max_length=2000):
    """Close/reopen code fences on every chunk, including unfinished model output."""
    if max_length < 16:
        raise ValueError("Message limit must leave room for Markdown fences.")
    chunks = []
    cursor = 0
    for start, end, language, body, marker in fences(text, include_unclosed=True):
        chunks.extend(_text_chunks(text[cursor:start], max_length))
        header = marker + language + "\n"
        footer = "\n" + marker
        room = max_length - len(header) - len(footer)
        if room < 1:
            # Escape oversized fence syntax rather than emit an unbalanced block.
            chunks.extend(_text_chunks(text[start:end].replace("`", "\\`").replace("~", "\\~"), max_length))
        else:
            chunks.extend(header + piece + footer for piece in list(_text_chunks(body, room)) or [""])
        cursor = end
    chunks.extend(_text_chunks(text[cursor:], max_length))
    return [chunk for chunk in chunks if chunk.strip()]


def read_attachments(paths, upload_limit=DEFAULT_UPLOAD_LIMIT):
    """Only explicit absolute regular-file paths; never fetch URLs or follow symlinks."""
    if not isinstance(paths, list) or len(paths) > MAX_ATTACHMENTS:
        raise ValueError("attachments must be a list of at most 10 absolute file paths.")
    uploads = []
    for path in paths:
        if not isinstance(path, str) or not os.path.isabs(path) or "\x00" in path:
            raise ValueError("Each attachment must be an absolute local file path, not a URL.")
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(path).name)[:128] or "attachment"
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Only regular files can be attached.")
                if info.st_size > upload_limit:
                    raise ValueError(f"Attachment {filename} exceeds the {upload_limit}-byte upload limit.")
                data = stream.read(upload_limit + 1)
                if len(data) > upload_limit:
                    raise ValueError(f"Attachment {filename} grew beyond the upload limit.")
        except OSError as error:
            raise ValueError(f"Cannot read attachment {filename}; use an accessible regular file, not a symlink.") from error
        uploads.append((filename, data))
    return uploads


def _upload_rejected(error):
    status = getattr(error, "status", None)
    if status in (403, 413):
        return True
    if status != 400:
        return False
    code = getattr(error, "code", None)
    if code is None:
        try:
            code = json.loads(getattr(error, "body", "{}")).get("code")
        except (ValueError, TypeError, AttributeError):
            return False
    return code == 40005


async def deliver_message(send, text, attachments=(), upload_limit=DEFAULT_UPLOAD_LIMIT):
    """send(content, files, first) returns a transport result; files are (name, bytes)."""
    results, failed = [], []
    can_upload = True

    async def emit(content, files=()):
        result = await send(content, files, not results)
        results.append(result)

    async def upload(pending, files):
        chunks = split_message(pending)
        for chunk in chunks[:-1]:
            await emit(chunk)
        caption = chunks[-1] if chunks else ""
        try:
            await emit(caption or None, files)
        except Exception as error:
            if not _upload_rejected(error):
                raise
            return caption, False
        return "", True

    cursor, pending = 0, ""
    for index, (start, end, language, body, _marker) in enumerate(fences(text), 1):
        pending += text[cursor:start]
        data = body.encode("utf-8")
        uploaded = False
        if body and can_upload and len(data) <= upload_limit:
            filename = f"snippet-{index}.{EXTENSIONS.get(language, 'txt')}"
            pending, uploaded = await upload(pending, [(filename, data)])
            can_upload = uploaded
        if not uploaded:
            pending += text[start:end]
        cursor = end
    pending += text[cursor:]
    if attachments:
        if can_upload:
            pending, can_upload = await upload(pending, attachments)
        if not can_upload:
            failed = [name for name, _data in attachments]
            pending += "\n\nAttachments not delivered (uploads unavailable): " + ", ".join(failed)
    for chunk in split_message(pending):
        await emit(chunk)
    return results, failed
