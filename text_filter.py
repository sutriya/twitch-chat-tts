"""Фильтрация и чистка сообщений перед озвучкой."""

import re

from twitch_chat import ChatMessage

URL_RE = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:com|ru|tv|net|org|gg|io|me)\S*)", re.I)
REPEAT_RE = re.compile(r"(.)\1{3,}")  # "аааааа" -> "ааа"
SPACES_RE = re.compile(r"\s+")

ROLE_ORDER = ["everyone", "subscriber", "vip", "moderator", "broadcaster"]


def _user_level(badges: set[str]) -> int:
    level = 0
    for badge in badges:
        if badge == "founder":
            badge = "subscriber"
        if badge in ROLE_ORDER:
            level = max(level, ROLE_ORDER.index(badge))
    return level


def strip_emotes(text: str, ranges: list[tuple[int, int]]) -> str:
    for start, end in reversed(ranges):
        text = text[:start] + text[end + 1 :]
    return text


class MessageFilter:
    def __init__(self, cfg: dict):
        self.ignore_users = {u.lower() for u in cfg.get("ignore_users", [])}
        self.ignore_prefixes = tuple(cfg.get("ignore_prefixes", ["!"]))
        self.banned_words = [w.lower() for w in cfg.get("banned_words", [])]
        self.replacements = cfg.get("replacements", {})
        self.min_role = ROLE_ORDER.index(cfg.get("min_role", "everyone"))
        self.max_length = cfg.get("max_length", 200)
        self.skip_emotes = cfg.get("skip_emotes", True)
        self.link_word = cfg.get("link_word", "ссылка")
        self.read_names = cfg.get("read_names", True)
        self.name_template = cfg.get("name_template", "{name} пишет: {text}")
        self.only_with_prefix = cfg.get("only_with_prefix", "")

    def process(self, msg: ChatMessage) -> str | None:
        """Возвращает текст для озвучки или None, если сообщение надо пропустить."""
        if msg.user in self.ignore_users:
            return None
        if _user_level(msg.badges) < self.min_role:
            return None

        if msg.text.lstrip().startswith(self.ignore_prefixes) and not self.only_with_prefix:
            return None

        text = msg.text
        if self.skip_emotes and msg.emote_ranges:
            text = strip_emotes(text, msg.emote_ranges)
        text = text.strip()

        if self.only_with_prefix:
            if not text.startswith(self.only_with_prefix):
                return None
            text = text[len(self.only_with_prefix) :].strip()

        lowered = text.lower()
        if any(w in lowered for w in self.banned_words):
            return None

        text = URL_RE.sub(f" {self.link_word} ", text)
        text = REPEAT_RE.sub(r"\1\1\1", text)
        for src, dst in self.replacements.items():
            text = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, text, flags=re.I)
        # @ник -> ник
        text = SPACES_RE.sub(" ", text.replace("@", "")).strip()

        # нечего читать: пусто или одни знаки препинания
        if not any(ch.isalnum() for ch in text):
            return None

        if len(text) > self.max_length:
            text = text[: self.max_length].rsplit(" ", 1)[0] + "..."

        if self.read_names:
            text = self.name_template.format(name=msg.display_name, text=text)
        return text
