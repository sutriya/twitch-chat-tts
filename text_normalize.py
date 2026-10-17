"""Подготовка текста для Silero: он понимает только кириллицу, без цифр и латиницы."""

import re

from num2words import num2words

NUMBER_RE = re.compile(r"\d+")
LATIN_WORD_RE = re.compile(r"[A-Za-z]+")

# сначала длинные сочетания, потом одиночные буквы
_DIGRAPHS = [
    ("shch", "щ"), ("sch", "ш"), ("tch", "ч"),
    ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ph", "ф"),
    ("th", "т"), ("ck", "к"), ("qu", "кв"), ("ee", "и"), ("oo", "у"),
    ("ya", "я"), ("yu", "ю"), ("yo", "ё"), ("ye", "е"),
]
_LETTERS = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
    "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
    "y": "и", "z": "з",
}


def transliterate_word(word: str) -> str:
    word = word.lower()
    out = []
    i = 0
    while i < len(word):
        for latin, cyr in _DIGRAPHS:
            if word.startswith(latin, i):
                out.append(cyr)
                i += len(latin)
                break
        else:
            ch = word[i]
            nxt = word[i + 1] if i + 1 < len(word) else ""
            if ch == "c" and nxt and nxt in "eiy":
                out.append("с")  # city -> сити
            elif ch == "y" and (i == 0 or word[i - 1] in "aeiou" or (nxt and nxt in "aeiou")):
                out.append("й")  # play -> плай
            else:
                out.append(_LETTERS.get(ch, ch))
            i += 1
    return "".join(out)


def latin_to_cyrillic(text: str) -> str:
    return LATIN_WORD_RE.sub(lambda m: transliterate_word(m.group()), text)


def numbers_to_words(text: str, max_digits: int = 12) -> str:
    def repl(m: re.Match) -> str:
        digits = m.group()
        if len(digits) > max_digits:
            # слишком длинное число читаем по цифрам
            return " ".join(num2words(int(d), lang="ru") for d in digits)
        return num2words(int(digits), lang="ru")

    return NUMBER_RE.sub(lambda m: f" {repl(m)} ", text)


def for_cyrillic_tts(text: str) -> str:
    text = numbers_to_words(text)
    text = latin_to_cyrillic(text)
    return re.sub(r"\s+", " ", text).strip()
