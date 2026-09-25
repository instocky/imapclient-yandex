"""Cursor logic check — run: uv run python scripts/check_cursor.py

Offline: a fake IMAPClient drives sync_account through the cases that would
silently lose mail if the cursor were wrong.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main


class FakeClient:
    def __init__(self, uidvalidity: int, uidnext: int, uids: list[int]) -> None:
        self.uidvalidity, self.uidnext, self.uids = uidvalidity, uidnext, uids

    def select_folder(self, folder):
        pass

    def folder_status(self, folder, what):
        return {b"UIDVALIDITY": self.uidvalidity, b"UIDNEXT": self.uidnext}

    def search(self, criteria):
        if "SINCE" in criteria:
            return list(self.uids)
        start = int(str(criteria[0]).split(":")[0])
        hit = [u for u in self.uids if u >= start]
        # Servers answer `UID n:*` with the mailbox's highest uid when n is past
        # it (Yandex does) — mimic that, sync_account has to filter it out.
        return hit or ([max(self.uids)] if self.uids else [])

    def fetch(self, uids, parts):
        return {
            uid: {
                b"ENVELOPE": SimpleNamespace(
                    message_id=f"<{uid}@t>", from_=[], subject=f"s{uid}", date="d"
                ),
                b"BODY[TEXT]": b"body",
            }
            for uid in uids
        }


def demo() -> None:
    tmp = Path(tempfile.mkdtemp()) / "check.db"
    main.DB_PATH = tmp
    conn = main._init_db()
    account = "a@t"
    count = lambda: conn.execute(
        "SELECT count(*) FROM emails WHERE account = ?", (account,)
    ).fetchone()[0]
    cursor = lambda: main._state(conn, f"last_uid:{account}")

    # 1. first run: seeds SINCE mail, cursor pinned at UIDNEXT-1 (not max(found))
    main.sync_account(FakeClient(100, 20, [10, 11, 12]), account, conn)
    assert count() == 3, count()
    assert cursor() == "19", cursor()  # 19, not 12 — the whole point

    # 2. no new mail: server echoes the highest uid, nothing stored, cursor unmoved
    main.sync_account(FakeClient(100, 20, [10, 11, 12]), account, conn)
    assert count() == 3, count()
    assert cursor() == "19", cursor()

    # 3. new mail above the cursor: picked up, cursor advances
    main.sync_account(FakeClient(100, 26, [10, 11, 12, 25]), account, conn)
    assert count() == 4, count()
    assert cursor() == "25", cursor()

    # 4. mailbox recreated (UIDVALIDITY changed): cursor reset, not reused
    main.sync_account(FakeClient(200, 3, [1, 2]), account, conn)
    assert cursor() == "2", cursor()
    assert count() == 6, count()  # old rows kept, new account of the mailbox seeded

    print("[OK] cursor logic")


if __name__ == "__main__":
    demo()
