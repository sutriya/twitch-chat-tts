# Озвучка чата Twitch

Читает чат канала Twitch и озвучивает сообщения в реальном времени офлайн-синтезатором
[Piper](https://github.com/OHF-Voice/piper1-gpl) (открытый, бесплатный, работает на CPU, без интернета).
Чат читается анонимно — токен и вход в аккаунт не нужны.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m piper.download_voices --download-dir voices ru_RU-irina-medium ru_RU-denis-medium
```

## Запуск

1. Впишите свой канал в `config.toml` → `[twitch] channel = "..."`.
2. Проверьте голос: `python main.py --say "Привет, чат!"`
3. Запустите: `python main.py` (или `python main.py --channel имя_канала`).

Во время работы в консоли: `s` — пропустить, `c` — очистить очередь, `p` — пауза, `q` — выход (+ Enter).

## Звук в OBS

По умолчанию звук идёт в устройство Windows по умолчанию. Чтобы озвучка шла отдельной дорожкой,
поставьте [VB-Audio Virtual Cable](https://vb-audio.com/Cable/), посмотрите номер устройства через
`python main.py --list-devices` и укажите его в `[audio] output_device`. В OBS добавьте
«Захват входного аудиопотока» → `CABLE Output`.

## Настройки

Всё в `config.toml`: голоса и скорость, свой голос для каждого зрителя, кого озвучивать
(все / сабы / VIP / модеры), режим «только по команде» (`only_with_prefix = "!tts"`),
игнор ботов, запрещённые слова, замены сокращений, длина сообщения и размер очереди.

## Файлы

- `main.py` — запуск, очередь озвучки, управление с консоли
- `twitch_chat.py` — анонимное подключение к IRC-чату Twitch
- `text_filter.py` — фильтры и чистка текста (смайлы, ссылки, «ааааа», замены)
- `tts_engine.py` — синтез Piper и воспроизведение
