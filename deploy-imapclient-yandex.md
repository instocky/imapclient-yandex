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

## 7. Проверка учётных данных

```bash
cd /opt/imapclient-yandex
uv run python scripts/check_accounts.py
```

Для каждого аккаунта: логин + `STATUS` по `INBOX`, письма не читаются, в базу
ничего не пишется. Код возврата `1`, если хоть один аккаунт не прошёл — удобно
для проверки из скрипта:

```bash
uv run python scripts/check_accounts.py && echo "все аккаунты живы"
```

Ошибка `AUTHENTICATIONFAILED` = пароль приложения отозван или IMAP выключен в
настройках ящика.

## 8. Тестовый запуск

Только под тем же `flock`, что и крон (см. раздел 10):

```bash
cd /opt/imapclient-yandex
flock /tmp/imapclient-yandex.lock uv run python main.py
```

## 9. Cron — запуск каждые 30 минут

```bash
crontab -e
```

Добавить (без редиректа в файл — логом теперь владеет само приложение через `logging` + `TimedRotatingFileHandler`):

```cron
*/30 * * * * cd /opt/imapclient-yandex && flock -n /tmp/imapclient-yandex.lock /home/adlab/.local/bin/uv run python main.py
```

> `flock` защищает от пересечения запусков: пока идёт текущий, следующий
> пропускается (новые письма подхватит следующий запуск по курсору `UID`).

> Важно: не добавляйте `>> cron.log 2>&1`. Приложение само пишет в `cron.log` и ротирует его в полночь. Если оставить shell-редирект, после ротации cron продолжит писать в переименованный старый файл.

Проверить:

```bash
crontab -l
```

## 10. Ручной запуск по SSH, не ломая крон

Ключевое: **блокировка живёт в крон-строке, а не в коде.** Голый
`uv run python main.py` по SSH её не берёт. Два процесса на одном ящике читают
один курсор, и часть писем может быть пропущена навсегда — поэтому ручной запуск
всегда через тот же `flock`.

Сначала — свободна ли блокировка (пусто значит «никто не работает»):

```bash
flock -n /tmp/imapclient-yandex.lock -c 'echo свободно' || echo "идёт прогон"
pgrep -af "python main.py"
```

Прогнать вручную, дождавшись очереди (`flock` без `-n` блокируется):

```bash
cd /opt/imapclient-yandex
flock /tmp/imapclient-yandex.lock uv run python main.py
```

Или не ждать, а сразу выйти, если крон уже работает:

```bash
flock -n /tmp/imapclient-yandex.lock uv run python main.py || echo "прогон уже идёт, пропущено"
```

Что безопасно делать, пока крон живёт:

| Действие | Можно? |
| --- | --- |
| `tail -f cron.log`, `sqlite3`-запросы к базе | Да, только чтение |
| `git pull` | Да. Уже запущенный процесс держит код в памяти, новый подхватит следующий прогон |
| `uv sync` | **Нет**, пока идёт прогон: пересоздание `.venv` ломает ленивый импорт. Если иначе никак — берите `flock` |
| `python main.py` без `flock` | **Нет** |
| `DELETE FROM data` / удаление `mail.db` | Нет, это потеря данных (см. ниже) |

## 11. Проверка лога

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

## 12. Просмотр SQLite

```bash
cd /opt/imapclient-yandex
uv run python scripts/inspect_db.py
```

`inspect_db.py` выводит всё, что есть, — через месяц это простыня. Точечные
запросы:

```bash
sqlite3 data/mail.db "SELECT account, count(*), max(uid) FROM emails GROUP BY account"
sqlite3 data/mail.db "SELECT datetime(received_at), subject FROM emails ORDER BY id DESC LIMIT 10"
sqlite3 data/mail.db "SELECT key, value FROM state"   # курсоры по аккаунтам
```

## 13. Обновление (update)

После изменений в репозитории — как накатить на сервер:

```bash
ssh adlab@SERVER_IP
cd /opt/imapclient-yandex
git pull
# только если менялись pyproject.toml / uv.lock — и только когда никто не работает:
flock /tmp/imapclient-yandex.lock uv sync
# если менялась cron-строка (flock, путь к uv) — пересоздайте задание:
crontab -e
```

> Каждый прогон cron вызывает `uv run python main.py` заново, поэтому перезапуск
> сервиса не нужен — изменения подхватятся следующим запуском (в течение 30 мин).
> `uv sync` стоит делать под `flock` или при свободной блокировке: он пересоздаёт
> `.venv` под ногами запущенного процесса.

Проверить, что всё ок:

```bash
tail -n 50 /opt/imapclient-yandex/cron.log
uv run python scripts/check_cursor.py && uv run python scripts/check_text.py
```

### Что проверять после pull
- **Менялся `main.py`** → если лог пишется самим приложением (через `logging`), shell-редирект `>> cron.log 2>&1` в crontab **должен быть убран** (иначе после ротации cron пишет в переименованный старый файл).
- **Менялся `.env.example`** → сверьте с вашим `.env` (не коммитится). `ACCOUNTS` обязан быть в одну строку.
- **Менялся формат `state`** → старый `mail.db` может не подойти; состояние безопасно сбросить, письма при этом останутся, а повторная первичная загрузка их не перезапишет (сработает `UNIQUE(account, uid)`).
- **Менялся `scripts/`** → перепроверьте `uv run python scripts/check_accounts.py`.

### Сброс состояния

Курсоры лежат в таблице `state` (по две строки на аккаунт). Сброс = повторить
первичную загрузку (только вчерашние письма):

```bash
flock -n /tmp/imapclient-yandex.lock uv run python -c "
import sqlite3
c = sqlite3.connect('data/mail.db')
c.execute(\"DELETE FROM state WHERE key LIKE '%anospokkb%'\")
c.commit()"
```

Сам `mail.db` не трогайте: это единственное хранилище писем, и никакого
`VACUUM`-а в проде делать не надо — он переписывает файл целиком, и делать его
можно только когда никто не работает.

## Структура на сервере

```text
/opt/imapclient-yandex/
├── main.py
├── scripts/
│   ├── check_accounts.py   # логин во все аккаунты
│   ├── check_cursor.py     # логика курсора (офлайн)
│   ├── check_text.py       # разбор MIME (офлайн)
│   └── inspect_db.py       # дамп писем
├── pyproject.toml
├── uv.lock
├── .env
├── cron.log
└── data/
    └── mail.db             # таблицы emails и state
```

`.env`, `cron.log` и `data/mail.db` не должны попадать в Git.
