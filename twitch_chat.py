"""Анонимное чтение чата Twitch через IRC (без токена и авторизации)."""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import AsyncIterator

log = logging.getLogger(__name__)

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667


@dataclass
class ChatMessage:
    user: str  # логин (lowercase)
    display_name: str  # ник как он отображается в чате
    text: str
    badges: set[str] = field(default_factory=set)  # broadcaster, moderator, vip, subscriber...
    emote_ranges: list[tuple[int, int]] = field(default_factory=list)  # позиции смайлов в text


def _parse_tags(raw: str) -> dict[str, str]:
    tags = {}
    for part in raw.split(";"):
        key, _, value = part.partition("=")
        tags[key] = value
    return tags


def _parse_emotes(value: str) -> list[tuple[int, int]]:
    # формат: "25:0-4,12-16/1902:6-10"
    ranges = []
    if not value:
        return ranges
    for emote in value.split("/"):
        _, _, positions = emote.partition(":")
        for pos in positions.split(","):
            start, _, end = pos.partition("-")
            if start.isdigit() and end.isdigit():
                ranges.append((int(start), int(end)))
    return sorted(ranges)


def parse_privmsg(line: str) -> ChatMessage | None:
    tags: dict[str, str] = {}
    if line.startswith("@"):
        raw_tags, _, line = line[1:].partition(" ")
        tags = _parse_tags(raw_tags)

    # :user!user@user.tmi.twitch.tv PRIVMSG #channel :text
    if not line.startswith(":"):
        return None
    prefix, _, rest = line[1:].partition(" ")
    command, _, rest = rest.partition(" ")
    if command != "PRIVMSG":
        return None
    _, _, text = rest.partition(" :")

    user = prefix.split("!", 1)[0]
    # /me сообщения приходят как \x01ACTION текст\x01
    if text.startswith("\x01ACTION ") and text.endswith("\x01"):
        text = text[8:-1]

    badges = {b.split("/", 1)[0] for b in tags.get("badges", "").split(",") if b}
    return ChatMessage(
        user=user,
        display_name=tags.get("display-name") or user,
        text=text,
        badges=badges,
        emote_ranges=_parse_emotes(tags.get("emotes", "")),
    )


async def read_chat(channel: str) -> AsyncIterator[ChatMessage]:
    """Бесконечно читает чат канала, переподключаясь при обрывах."""
    channel = channel.lower().lstrip("#")
    delay = 1
    while True:
        try:
            reader, writer = await asyncio.open_connection(IRC_HOST, IRC_PORT)
            nick = f"justinfan{random.randint(10000, 99999)}"  # анонимный ник Twitch
            writer.write(
                b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
                + f"NICK {nick}\r\nJOIN #{channel}\r\n".encode()
            )
            await writer.drain()
            log.info("Подключились к чату #%s", channel)
            delay = 1

            while True:
                raw = await reader.readline()
                if not raw:
                    raise ConnectionError("соединение закрыто сервером")
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("PING"):
                    writer.write(line.replace("PING", "PONG", 1).encode() + b"\r\n")
                    await writer.drain()
                    continue
                if " RECONNECT" in line:
                    raise ConnectionError("Twitch попросил переподключиться")
                try:
                    msg = parse_privmsg(line)
                except Exception:
                    log.exception("Не удалось разобрать строку чата: %r", line)
                    continue
                if msg:
                    yield msg
        except (OSError, ConnectionError) as e:
            log.warning("Обрыв соединения (%s), переподключение через %d с", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
