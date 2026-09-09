#!/usr/bin/env python3
"""Make text a stranger wrote safe to print in a pane. A filter, and nothing else.

Everything the node prints back to us — a sender label, a message body, a peer's chosen
display name — was typed by somebody else. A pane is a terminal, so an ESC in that text
is not a character: it is an instruction to move the cursor, clear the screen or repaint
the row above in another colour. That is display spoofing, not code execution, and it is
worth exactly one filter rather than a rule per pane.

    ... | python3 lib/scrub.py        # stdin -> stdout, streaming, never fails

What survives: printable text of every language, newlines, tabs. What does not: C0, DEL,
C1, and the carriage return that would let a peer overwrite the line the plugin printed.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import sys

#: A visible mark, so that a stripped byte reads as "something was here" rather than as
#: text the peer did not send.
MARK = "�"

KEEP = ("\n", "\t")


def scrub(text: str) -> str:
    return "".join(
        ch if ch in KEEP or not (ord(ch) < 0x20 or ord(ch) == 0x7F
                                 or 0x80 <= ord(ch) <= 0x9F)
        else MARK
        for ch in text
    )


def clean_field(text: str, limit: int = 60) -> str:
    """One line, safe to interpolate into a notification or a heading.

    Stricter than `scrub`: a field is a fragment, so a newline in it would break the
    line it lands in, and length is capped because a notification body is not a place
    to render a kilobyte a peer chose.
    """
    out = " ".join(scrub(text).replace(MARK, " ").split())
    if len(out) > limit:
        out = out[: limit - 1] + "…"
    return out or "someone"


def main() -> int:
    for line in sys.stdin.buffer:
        sys.stdout.write(scrub(line.decode("utf-8", "replace")))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
