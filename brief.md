# Brief: Yandex Mail Monitor — Spike

## Goal

Проверить техническую гипотезу: **можно ли через Yandex Mail IMAP периодически проверять почтовый ящик и получать новые письма для дальнейшей обработки.** 

## Что проверить

Собрать минимальный рабочий Spike, который:

1. Подключается к Yandex Mail через **IMAP**.
2. Использует `imapclient`.
3. Авторизуется в почтовом ящике.
4. Открывает `INBOX`.
5. Находит новые/непрочитанные письма.
6. Получает `From`, `Subject`, `Date` и текст письма.
7. Выводит найденные письма в консоль.
8. Корректно завершается.
9. Позволяет запускать проверку повторно через 30 минут.

## Target

Yandex Mail:

```text
imap.yandex.ru:993
SSL
```

Проверка:

```text
INBOX
→ UNSEEN
→ получить письма
→ print
```

## Что НЕ делать

Это **Spike, не production implementation**.

Не нужны:

* PRD;
* ADR;
* сложная архитектура;
* SQLite;
* Celery;
* async;
* IMAP IDLE;
* multi-mailbox;
* полноценные tests;
* repositories/services;
* logging infrastructure;
* configuration framework;
* отправка писем.

## Можно использовать

* один `main.py`;
* `.env`;
* `uv`;
* `imapclient`;
* временные решения;
* простой `print()`.

## Expected result

После запуска:

```bash
uv run python main.py
```

должно быть:

```text
Connect → authenticate → INBOX → find new emails → print
```

Например:

```text
New emails: 2

From: test@example.com
Subject: Test message
Date: ...
Body: ...
```

## Constraints

* Python.
* `uv`.
* `imapclient`.
* Yandex Mail IMAP.
* Проверка примерно **раз в 30 минут**.
* Не усложнять архитектуру.

## Done when

Spike считается успешным, если можно авторизоваться в Yandex Mail, открыть `INBOX`, обнаружить новое письмо и **вывести его данные в консоль**.

Следующий этап после успешного Spike — определить механизм хранения уже обработанных писем и запуск каждые 30 минут.
