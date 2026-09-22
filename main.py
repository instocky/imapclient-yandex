"""Spike: poll Yandex Mail INBOX via IMAP every 30 min and print new mail."""

import time

from imapclient import IMAPClient
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    imap_host: str = "imap.yandex.ru"
    imap_port: int = 993
    imap_user: str
    imap_password: str
    poll_sec: int = 1800


def _decode(value) -> str:
    return value.decode("utf-8", errors="replace") if value else "(none)"


def fetch_new_emails(client: IMAPClient) -> None:
    client.select_folder("INBOX")
    uids = client.search("UNSEEN")
    if not uids:
        print("No new emails.")
        return

    print(f"New emails: {len(uids)}\n")
    data = client.fetch(uids, ["ENVELOPE", "BODY[TEXT]"])
    for uid, msg in data.items():
        env = msg[b"ENVELOPE"]
        sender = ", ".join(str(a) for a in (env.from_ or [])) or "(no sender)"
        body = _decode(msg.get(b"BODY[TEXT]"))[:500]
        print(f"From: {sender}")
        print(f"Subject: {_decode(env.subject)}")
        print(f"Date: {env.date}")
        print(f"Body: {body}")
        print("-" * 40)


def run_once(settings: Settings) -> None:
    # Connection is opened per cycle and closed by the context manager,
    # so Ctrl+C during sleep leaves nothing dangling.
    with IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True) as client:
        client.login(settings.imap_user, settings.imap_password)
        fetch_new_emails(client)


def main() -> None:
    settings = Settings()
    print("Connect -> authenticate -> INBOX -> find new emails -> print")
    try:
        while True:
            run_once(settings)
            print(f"Sleeping {settings.poll_sec}s...\n")
            time.sleep(settings.poll_sec)
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
