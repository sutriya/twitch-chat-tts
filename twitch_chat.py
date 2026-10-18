"""Анонимное чтение чата Twitch через IRC (без токена и авторизации)."""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import AsyncIterator

log = logging.getLogger(__name__)

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697  # TLS; открытый 6667 провайдеры и роутеры чаще обрывают
USE_TLS = True
CONNECT_TIMEOUT = 15  # с на подключение
PING_INTERVAL = 20  # если столько секунд ничего не пришло, шлём свой PING
PONG_TIMEOUT = 10  # и ждём ответ; нет ответа - переподключаемся


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


async def _readline(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bytes:
    """Читает строку; если сервер молчит, проверяет связь своим PING.

    Без этого «тихо умершее» соединение (роутер, Wi-Fi, сон сети) не даёт ни ошибки,
    ни конца потока, и чтение чата зависает навсегда.
    """
    try:
        return await asyncio.wait_for(reader.readline(), PING_INTERVAL)
    except asyncio.TimeoutError:
        log.debug("Чат молчит %d с, проверяем связь", PING_INTERVAL)
        writer.write(b"PING :keepalive\r\n")
        await writer.drain()
    try:
        return await asyncio.wait_for(reader.readline(), PONG_TIMEOUT)
    except asyncio.TimeoutError:
        raise ConnectionError(f"Twitch не ответил на PING за {PONG_TIMEOUT} с") from None


async def read_chat(channel: str) -> AsyncIterator[ChatMessage]:
    """Бесконечно читает чат канала, переподключаясь при обрывах."""
    channel = channel.lower().lstrip("#")
    delay = 1
    while True:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(IRC_HOST, IRC_PORT, ssl=USE_TLS or None), CONNECT_TIMEOUT
            )
            nick = f"justinfan{random.randint(10000, 99999)}"  # анонимный ник Twitch
            writer.write(
                b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
                + f"NICK {nick}\r\nJOIN #{channel}\r\n".encode()
            )
            await writer.drain()
            log.info("Подключились к чату #%s", channel)
            delay = 1

            while True:
                raw = await _readline(reader, writer)
                if not raw:
                    raise ConnectionError("соединение закрыто сервером")
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("PING"):
                    log.debug("PING от Twitch, отвечаем")
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
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as e:
            # ValueError - слишком длинная строка от сервера (readline)
            log.warning("Обрыв соединения (%s), переподключение через %d с", str(e) or type(e).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
        finally:
            if writer is not None:
                writer.close()
