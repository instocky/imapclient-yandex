"""Plain-text extraction check — run: uv run python scripts/check_text.py

Cases taken from what this mailbox actually sends: quoted-printable, html-only,
a PDF attachment riding along, a body cut off mid-part (we only ever get a
prefix), and the bare body *section* the server hands over with no top-level
headers.
"""

import email.policy
import re
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from main import plain_text

CRLF = bytes([13, 10])


def build(html: bool = False, attachment: bool = False) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "тест"
    msg.set_content("Привет, это текст.")
    if html:
        msg.add_alternative("<p>Привет, это <b>html</b>.</p>", subtype="html")
    if attachment:
        msg.add_attachment(b"%PDF-1.4 " + b"x" * 5000, maintype="application", subtype="pdf")
    return msg.as_bytes(policy=email.policy.SMTP)  # CRLF, like the server


def demo() -> None:
    text = plain_text(build())
    assert "Привет, это текст." in text, text
    assert "Subject" not in text and "%PDF" not in text, text

    both = plain_text(build(html=True, attachment=True))
    assert "Привет, это текст." in both, both
    assert "<p>" not in both and "%PDF" not in both, both

    # html-only: no text/plain part at all -> tags stripped
    html_only = b"Content-Type: text/html; charset=utf-8" + CRLF + CRLF + b"<p>Hi <b>there</b></p>"
    assert plain_text(html_only) == "Hi  there", repr(plain_text(html_only))

    # truncated body: the closing boundary is missing (our 64 KB prefix)
    truncated = build(attachment=True)[:1200]
    assert "Привет, это текст." in plain_text(truncated), plain_text(truncated)

    # what the server actually sends: a body section, no top-level headers
    section = build(html=True, attachment=True)
    section = section[re.search(rb"(?m)^--", section).start() :]
    assert plain_text(section) == "Привет, это текст.", repr(plain_text(section))

    # same section, with the "This is a multi-part message" preamble in front
    preamble = b"This is a multi-part message in MIME format." + CRLF + section
    assert plain_text(preamble) == "Привет, это текст.", repr(plain_text(preamble))

    # boundary with dots and dashes, the style bizmail sends
    dotted = CRLF.join(
        [
            b"--_===25065962====be1.volganet.ru===_",
            b'Content-Type: text/plain; charset="utf-8"',
            b"",
            "Привет,".encode(),
            b"--_===25065962====be1.volganet.ru===_",
            b'Content-Disposition: attachment; filename="scan.pdf"',
            b"",
            b"%PDF-1.4 xxxx",
            b"--_===25065962====be1.volganet.ru===_--",
            b"",
        ]
    )
    assert plain_text(dotted) == "Привет,", repr(plain_text(dotted))

    # a `--` divider in an ordinary text mail is not a MIME boundary
    dashed = "Привет".encode() + CRLF * 2 + b"-" * 30 + CRLF + "Подпись".encode()
    assert plain_text(dashed) == dashed.decode(), repr(plain_text(dashed))

    # plain single-part body, as sent for non-multipart mail
    assert plain_text("Просто текст.".encode()) == "Просто текст."

    # empty body
    assert plain_text(b"") == ""

    print("[OK] plain text")


if __name__ == "__main__":
    demo()
