#!/usr/bin/env python3
"""Read the local muretai agent directory (agents.d) — the published discovery convention.

This is the ONLY part of the plugin that answers "which muretai agent lives on this
machine". It is a reader, never a writer, and it implements the convention published in
muretai's SPECIFICATION rather than inventing one.

The one rule that governs the whole file, quoted from that specification:

    Nothing in this file is a command and you must never execute anything named by it,
    derive an executable path from it, or pass any of its values as environment
    variables to a process.

So this module answers WHICH agent, and nothing else. WHERE the node is comes from the
environment and from convention, in bin/common.sh, and the two are deliberately kept
apart: a world-readable JSON file that could name an interpreter would be a config file
with exec rights.

We project onto the fields we actually use and drop everything else, including `drive`.
An unknown key is not merely unused here, it never reaches the caller.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

FORMAT_KEY = "muretai_local_agent"
FORMAT_VERSION = 1

#: A real descriptor is a few hundred bytes. The cap is applied to the BYTES before
#: parsing, because the parser is the thing being protected.
MAX_BYTES = 4096

#: What we read. `drive` is deliberately absent: this plugin never calls the drive API,
#: so it never has to reason about the loopback rule that guards it.
FIELDS = ("did", "name", "primary", "state_dir", "relay", "speak")


def _refuse_unsafe(p: Path) -> str:
    """Return a reason to skip this path, or "" if it is safe to believe.

    Three checks, on the directory and on the file, exactly as the convention states:
    not a symbolic link, not writable by other, and not owned by a third party. The
    group bit is deliberately tolerated -- `umask 002` is the default for regular users
    on several distributions and in many container images, so our own writers land at
    0664 there and refusing it would refuse a correct install.
    """
    try:
        st = p.lstat()
    except OSError as e:
        return f"cannot stat ({e.__class__.__name__})"
    if stat.S_ISLNK(st.st_mode):
        return "symbolic link"
    if st.st_mode & stat.S_IWOTH:
        return "world-writable"
    if hasattr(os, "geteuid"):
        if st.st_uid not in (os.geteuid(), 0):
            return f"owned by uid {st.st_uid}"
    return ""


def search_dirs() -> list[Path]:
    """The four roots, in the order the convention fixes. No root is ever relative."""
    out: list[Path] = []
    env_dir = os.environ.get("MURETAI_AGENTS_DIR", "").strip()
    state = os.environ.get("MURETAI_STATE_DIR", "").strip()
    if env_dir and Path(env_dir).is_absolute():
        out.append(Path(env_dir))
    elif state and Path(state).is_absolute():
        out.append(Path(state) / "agents.d")
    for cand in (Path.home() / ".muretai" / "agents.d", Path("/etc/muretai/agents.d")):
        if cand not in out:
            out.append(cand)
    return out


def _project(raw: object) -> dict | None:
    """Return the fields we use, or None if this is not a descriptor we understand."""
    if not isinstance(raw, dict):
        return None
    version = raw.get(FORMAT_KEY)
    # `True == 1` in Python, so a bool would otherwise pass this test. The discriminator
    # is an INTEGER; a reader that does not recognise it must ignore the file entirely.
    if isinstance(version, bool) or version != FORMAT_VERSION:
        return None
    did = raw.get("did")
    name = raw.get("name")
    if not isinstance(did, str) or not did.startswith("did:"):
        return None
    if not isinstance(name, str) or not name:
        return None
    desc = {"did": did, "name": name, "primary": bool(raw.get("primary"))}
    for key in ("state_dir", "relay"):
        val = raw.get(key)
        if isinstance(val, str) and val:
            desc[key] = val
    speak = raw.get("speak")
    if isinstance(speak, list):
        desc["speak"] = [s for s in speak if isinstance(s, str)]
    return desc


def discover() -> tuple[list[dict], list[str]]:
    """Every local agent, de-duplicated by DID with the earliest directory winning.

    Returns (agents, skipped) where `skipped` explains every file we refused, so the
    caller can show the owner why a descriptor they can see was not believed. Silence
    about a refusal is how a machine ends up looking empty for a reason nobody can find.
    """
    agents: list[dict] = []
    seen: set[str] = set()
    skipped: list[str] = []
    for d in search_dirs():
        if not d.is_dir():
            continue
        reason = _refuse_unsafe(d)
        if reason:
            skipped.append(f"{d}: {reason}")
            continue
        for f in sorted(d.glob("*.json")):
            reason = _refuse_unsafe(f)
            if reason:
                skipped.append(f"{f}: {reason}")
                continue
            try:
                with f.open("rb") as fh:
                    blob = fh.read(MAX_BYTES + 1)
            except OSError as e:
                skipped.append(f"{f}: unreadable ({e.__class__.__name__})")
                continue
            if len(blob) > MAX_BYTES:
                skipped.append(f"{f}: larger than {MAX_BYTES} bytes")
                continue
            try:
                desc = _project(json.loads(blob.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                skipped.append(f"{f}: not readable JSON")
                continue
            if desc is None:
                continue
            if desc["did"] in seen:
                continue
            seen.add(desc["did"])
            agents.append(desc)
    return agents, skipped


class Ambiguous(Exception):
    """Several agents and no way to choose. Naming them all is the correct answer."""


def pick(preferred: str = "") -> dict:
    """The one agent to act as, or an exception explaining why we will not guess.

    The order is the convention's: an explicit name, exactly one entry, exactly one
    marked primary, then MURETAI_AS. Past that a reader must NOT guess -- it names all
    of them to its owner, because speaking as the wrong identity is worse than stopping.
    """
    agents, _ = discover()
    if not agents:
        raise Ambiguous("no muretai agent found on this machine")
    want = (preferred or os.environ.get("MURETAI_AS", "")).strip()
    if want:
        for a in agents:
            if a["name"] == want:
                return a
        names = ", ".join(a["name"] for a in agents)
        raise Ambiguous(f"no local agent named {want!r} (found: {names})")
    if len(agents) == 1:
        return agents[0]
    primaries = [a for a in agents if a["primary"]]
    if len(primaries) == 1:
        return primaries[0]
    names = ", ".join(a["name"] for a in agents)
    raise Ambiguous(
        f"several local agents and none is primary ({names}); "
        "choose one with MURETAI_AS=<name>"
    )


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "list":
        agents, skipped = discover()
        json.dump({"agents": agents, "skipped": skipped}, sys.stdout)
        sys.stdout.write("\n")
        return 0
    if cmd == "table":
        # One row per local agent, with the one we are acting as marked. Formatting
        # lives here so the shell never has to build columns.
        agents, skipped = discover()
        acting = argv[2] if len(argv) > 2 else ""
        if not agents:
            print("no muretai agent on this machine")
        for a in agents:
            mark = "->" if a["name"] == acting else "  "
            print(f"{mark} {a['name']:<20} {a['did']}")
        for s in skipped:
            print(f"   skipped {s}")
        return 0
    if cmd == "pick":
        try:
            sys.stdout.write(pick(argv[2] if len(argv) > 2 else "")["name"] + "\n")
            return 0
        except Ambiguous as e:
            sys.stderr.write(f"{e}\n")
            return 3
    sys.stderr.write("usage: agents_d.py [list|pick [name]]\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
