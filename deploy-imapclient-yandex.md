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
# Список аккаунтов — JSON-массив в одну строку (dotenv не умеет многострочные
# значения, многострочный JSON молча падает на парсинге).
ACCOUNTS=[{"user":"first@yandex.ru","password":"app-password-1"},{"user":"second@yandex.ru","password":"app-password-2"}]
```

Использовать пароль приложения Yandex.

Первый запуск по каждому новому аккаунту подтягивает только вчерашние письма
(`SINCE`) и запоминает курсор `UID`; архив не импортируется. Состояние лежит в
таблице `state`, сбросить его — значит повторить первую загрузку:

```bash
uv run python -c "import sqlite3;sqlite3.connect('data/mail.db').execute('DELETE FROM state')"
```

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
*/30 * * * * cd /opt/imapclient-yandex && flock -n /tmp/imapclient-yandex.lock /home/adlab/.local/bin/uv run python main.py
```

> `flock` защищает от пересечения запусков: пока идёт текущий, следующий
> пропускается (новые письма подхватит следующий запуск по курсору `UID`).
> Ручные запуски `uv run python main.py` блокировку не используют — не запускайте
> их параллельно с кроном.

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

## 11. Обновление (update)

После изменений в репозитории — как накатить на сервер:

```bash
ssh adlab@SERVER_IP
cd /opt/imapclient-yandex
git pull
# только если менялись pyproject.toml / uv.lock:
uv sync
# если менялась cron-строка (напр. редирект в лог) — пересоздайте задание:
crontab -e
```

> Каждый прогон cron вызывает `uv run python main.py` заново, поэтому перезапуск сервиса не нужен — изменения подхватятся следующим запуском (в течение 30 мин).

Проверить, что всё ок:

```bash
tail -n 50 /opt/imapclient-yandex/cron.log
```

### Что проверять после pull
- **Менялся `main.py`** → если лог пишется самим приложением (через `logging`), shell-редирект `>> cron.log 2>&1` в crontab **должен быть убран** (иначе после ротации cron пишет в переименованный старый файл).
- **Менялся `.env.example`** → сверьте с вашим `.env` (не коммитится).
- **Менялся `scripts/`** → перепроверьте `uv run python scripts/inspect_db.py`.

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
