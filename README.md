# imapclient-yandex

Spike: мониторинг Yandex Mail через IMAP. Проверяет `INBOX`, забирает новые
письма и сохраняет их в локальную SQLite, чтобы повторные запуски не дублировали
уже обработанное.

## Что делает

- Подключается к `imap.yandex.ru:993` по SSL.
- Авторизуется по логину/паролю из `.env`.
- Открывает `INBOX`, ищет письма, которых ещё нет в базе (дедуп по IMAP uid).
- Сохраняет `From`, `Subject`, `Date` и текст письма в `data/mail.db`.
- Выводит новые письма в консоль.

Это **Spike, не production** — простой `main.py`, без тестов, логгера,
отправки писем и сложной архитектуры.

## Установка

Требуется [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

Создайте `.env` на основе примера:

```bash
cp .env.example .env
```

В `.env` укажите данные ящика. Используйте **пароль приложения**, а не пароль
от аккаунта: `https://id.yandex.ru/security/app-passwords`

```ini
IMAP_USER=your-address@yandex.ru
IMAP_PASSWORD=app-password-here
```

## Запуск

Один проход (забрать новые письма и выйти):

```bash
uv run python main.py
```

Планируемый запуск ~раз в 30 минут — через cron / планировщик ОС:

```cron
*/30 * * * * cd /path/to/0922_imapclient-yandex && uv run python main.py
```

## Просмотр сохранённых писем

```bash
uv run python scripts/inspect_db.py
```

## Структура

| Путь                    | Назначение                                          |
| ----------------------- | --------------------------------------------------- |
| `main.py`               | Подключение, выборка новых писем, сохранение, вывод |
| `scripts/inspect_db.py` | Просмотр содержимого `data/mail.db`                 |
| `.env` / `.env.example` | Учётные данные IMAP (не коммитится)                 |
| `data/mail.db`          | SQLite с сохранёнными письмами (не коммитится)      |
