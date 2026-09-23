# Deploy: imapclient-yandex

Краткая инструкция деплоя на Ubuntu по SSH.

## 1. Подключение

```bash
ssh adlab@SERVER_IP
```

## 2. Установка Git

```bash
sudo apt update
sudo apt install -y git
```

## 3. Клонирование проекта

```bash
cd /opt
sudo git clone https://github.com/instocky/imapclient-yandex.git
sudo chown -R $USER:$USER /opt/imapclient-yandex
cd /opt/imapclient-yandex
```

## 4. Установка uv

Если `uv` ещё не установлен:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
```

Проверка:

```bash
uv --version
```

## 5. Зависимости

```bash
cd /opt/imapclient-yandex
uv sync
```

## 6. Настройка Yandex IMAP

```bash
cp .env.example .env
nano .env
```

Заполнить:

```ini
IMAP_USER=your-address@yandex.ru
IMAP_PASSWORD=app-password-here
```

Использовать пароль приложения Yandex.

## 7. Тестовый запуск

```bash
uv run python main.py
```

Проверить, что письма забираются без ошибок.

## 8. Cron — запуск каждые 30 минут

```bash
crontab -e
```

Добавить (без редиректа в файл — логом теперь владеет само приложение через `logging` + `TimedRotatingFileHandler`):

```cron
*/30 * * * * cd /opt/imapclient-yandex && /home/adlab/.local/bin/uv run python main.py
```

> Важно: не добавляйте `>> cron.log 2>&1`. Приложение само пишет в `cron.log` и ротирует его в полночь. Если оставить shell-редирект, после ротации cron продолжит писать в переименованный старый файл.

Проверить:

```bash
crontab -l
```

## 9. Проверка лога

Активный лог — `cron.log`, формат: `YYYY-MM-DD HH:MM:SS,mmm LEVEL message`.
Ротированные копии за 7 дней — `cron.log.YYYY-MM-DD` (снимаются в полночь).

```bash
tail -f /opt/imapclient-yandex/cron.log
```

Последние строки:

```bash
tail -n 50 /opt/imapclient-yandex/cron.log
```

Список ротированных файлов:

```bash
ls -1 /opt/imapclient-yandex/cron.log*
```

## 10. Просмотр SQLite

```bash
cd /opt/imapclient-yandex
uv run python scripts/inspect_db.py
```

## Структура на сервере

```text
/opt/imapclient-yandex/
├── main.py
├── scripts/
├── pyproject.toml
├── uv.lock
├── .env
├── cron.log
└── data/
    └── mail.db
```

`.env`, `cron.log` и `data/mail.db` не должны попадать в Git.
