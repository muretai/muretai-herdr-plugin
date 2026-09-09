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

A name is not merely a label. It is spent twice — as `--as <name>` and as the path
segment in `keys/<name>.key` — so `check_name` below is the same rule the node applies
in `agent/paths.py:check_key_name`, and it is applied HERE, at the point a descriptor
is believed, not only at the point a key is looked up.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import unicodedata
from pathlib import Path

FORMAT_KEY = "muretai_local_agent"
FORMAT_VERSION = 1

#: A real descriptor is a few hundred bytes. The cap is applied to the BYTES before
#: parsing, because the parser is the thing being protected.
MAX_BYTES = 4096

#: What we read. `drive` is deliberately absent: this plugin never calls the drive API,
#: so it never has to reason about the loopback rule that guards it.
FIELDS = ("did", "name", "primary", "state_dir", "relay", "speak")

#: `keys/<name>.key` must not land on one of the node's per-agent secondary keys:
#: `agent/paths.py` classifies those by suffix, so an agent named `alice.op` files its
#: identity where alice's OPERATIONAL sidecar lives and the two readers disagree about
#: what that file is. Kept in the same order and spelling as the node's list.
SIDECAR_NAME_SUFFIXES = (".op", ".next", ".rootnext", ".ygg", ".tls", ".iroh")

#: A name is a directory entry and a CLI argument; nothing needs to be longer.
MAX_NAME = 128
#: A DID is a URI. did:key is ~60 characters; the cap is only there so a descriptor
#: cannot hand a kilometre of text to a terminal.
MAX_DID = 512


class UnsafeName(ValueError):
    """A name that must not become `keys/<name>.key` or `--as <name>`."""


def _has_control(text: str) -> bool:
    """C0, DEL and C1. ESC in a name is not a character, it is a terminal command."""
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F or 0x80 <= ord(ch) <= 0x9F
               for ch in text)


def check_name(name: object) -> str:
    """Refuse a name that may not be spent as a path segment. Returns it unchanged.

    This is `agent/paths.py:check_key_name` from the node, restated where the plugin can
    reach it, and it has to be restated rather than imported: the plugin runs on machines
    whose node predates that function, and the mint guard in bin/common.sh is worth
    exactly as much as the weakest reader that feeds it a name.

      1. one path component — `../../outside` or `sub/b` names a key OUTSIDE keys/, and
         the existence check would then pass on a file that is not an identity at all;
      2. no leading dot — `keys/.foo.key` is a key `ls` does not show and backups skip;
      3. not a sidecar shape, folded the way a case-insensitive filesystem folds;
      4. no control characters — the name is printed in a pane and in a notification.
    """
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise UnsafeName(f"invalid agent name: {name!r}")
    if len(name) > MAX_NAME:
        raise UnsafeName(f"agent name longer than {MAX_NAME} characters")
    if _has_control(name):
        raise UnsafeName(f"agent name contains control characters: {name!r}")
    if "\0" in name or "/" in name or "\\" in name or os.sep in name:
        raise UnsafeName(f"agent name may not contain a path separator: {name!r}")
    if Path(name).name != name:
        raise UnsafeName(f"agent name must be a single path component: {name!r}")
    if name.startswith("."):
        raise UnsafeName(f"agent name may not begin with a dot: {name!r}")
    folded = unicodedata.normalize("NFKC", name).casefold()
    if folded.endswith(SIDECAR_NAME_SUFFIXES):
        raise UnsafeName(
            f"agent name may not end in a sidecar key suffix: {name!r} "
            f"(`keys/{name}.key` would be read as another agent's sidecar)")
    return name


def check_did(did: object) -> str:
    """Refuse a DID we would print. Same reasoning as `check_name`, weaker rule.

    A DID is opaque to this plugin — we never resolve it, we only SHOW it — so the test
    is about what it can do to a terminal, not about method syntax.
    """
    if not isinstance(did, str) or not did.startswith("did:"):
        raise UnsafeName(f"not a DID: {did!r}")
    if len(did) > MAX_DID:
        raise UnsafeName(f"DID longer than {MAX_DID} characters")
    if _has_control(did) or any(ch.isspace() for ch in did):
        raise UnsafeName(f"DID contains control or whitespace characters: {did!r}")
    return did


def scrub(text: str, limit: int = 0) -> str:
    """What is safe to print. Control characters become a visible replacement.

    Used for the one thing we print that we did not validate: the PATH of a file we
    refused, which a hostile filename supplies. lib/scrub.py does the same job for the
    node's own output, which carries text a peer typed.
    """
    out = "".join("�" if (ord(c) < 0x20 or ord(c) == 0x7F
                               or 0x80 <= ord(c) <= 0x9F) else c
                  for c in text)
    if limit and len(out) > limit:
        out = out[: limit - 1] + "…"
    return out


def _kind(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "a FIFO"
    if stat.S_ISSOCK(mode):
        return "a socket"
    if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
        return "a device"
    if stat.S_ISDIR(mode):
        return "a directory"
    return "not a regular file"


def _refuse_unsafe(p: Path, want: str = "file") -> str:
    """Return a reason to skip this path, or "" if it is safe to believe.

    The checks the convention states — not a symbolic link, not writable by other, not
    owned by a third party — plus the one it assumes: it must be the KIND of thing we
    came for. A FIFO named `block.json` is not a slow descriptor, it is a descriptor
    that never arrives, and `discover()` runs on every pane and on the idle hook.

    The group bit is deliberately tolerated -- `umask 002` is the default for regular
    users on several distributions and in many container images, so our own writers land
    at 0664 there and refusing it would refuse a correct install. That tolerance is a
    SHARED-HOST assumption, and it is written down in the README.
    """
    try:
        st = p.lstat()
    except OSError as e:
        return f"cannot stat ({e.__class__.__name__})"
    if stat.S_ISLNK(st.st_mode):
        return "symbolic link"
    if want == "dir" and not stat.S_ISDIR(st.st_mode):
        return f"not a directory ({_kind(st.st_mode)})"
    if want == "file" and not stat.S_ISREG(st.st_mode):
        return _kind(st.st_mode)
    if st.st_mode & stat.S_IWOTH:
        return "world-writable"
    if hasattr(os, "geteuid"):
        if st.st_uid not in (os.geteuid(), 0):
            return f"owned by uid {st.st_uid}"
    return ""


def _refuse_unsafe_ancestors(p: Path) -> str:
    """Return a reason to distrust everything UNDER p, or "".

    A 0755 agents.d inside a 0777 parent is not protected by its own mode: anyone who
    can write the parent can rename it away and put their own there, and then they are
    the primary identity this machine speaks as. So the walk goes to the root.

    It walks the RESOLVED path, which is what makes a symlinked component safe to allow:
    `realpath` of any prefix is itself a prefix of the resolved chain, so the directory
    that holds a link is checked even though the link is gone by then. (On macOS /var is
    a symlink to /private/var; refusing links here would refuse every temporary
    directory on the platform.)

    The sticky bit is honoured: a 1777 /tmp lets everyone create entries but lets only
    the owner replace ours, which is exactly the property this check is asking about.
    """
    try:
        real = Path(os.path.realpath(p))
    except OSError as e:
        return f"cannot resolve ({e.__class__.__name__})"
    for anc in real.parents:
        try:
            st = anc.lstat()
        except OSError as e:
            return f"{anc}: cannot stat ({e.__class__.__name__})"
        if st.st_mode & stat.S_IWOTH and not st.st_mode & stat.S_ISVTX:
            return f"{anc} is writable by everyone (and not sticky)"
        if hasattr(os, "geteuid") and st.st_uid not in (os.geteuid(), 0):
            return f"{anc} is owned by uid {st.st_uid}"
    return ""


def _read_capped(p: Path) -> tuple[bytes | None, str]:
    """The descriptor's bytes, or (None, reason).

    O_NOFOLLOW and the second, post-open check close the window between `lstat` and
    `open`: the lstat above says what the name pointed at a moment ago, `fstat` on the
    descriptor says what we are actually holding. O_NONBLOCK means that even a FIFO
    that slipped past both returns instead of parking the pane forever.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(p, flags)
    except OSError as e:
        return None, f"unreadable ({e.__class__.__name__})"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, _kind(st.st_mode)
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_BYTES:
            try:
                chunk = os.read(fd, MAX_BYTES + 1 - size)
            except OSError as e:
                return None, f"unreadable ({e.__class__.__name__})"
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks), ""
    finally:
        os.close(fd)


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
    try:
        did = check_did(raw.get("did"))
        name = check_name(raw.get("name"))
    except UnsafeName:
        return None
    # `is True`, not `bool(...)`: every non-empty string is truthy, so `"false"` would
    # otherwise MAKE this the primary identity — the one that wins pick() silently when
    # a machine has several. The version key above already learned this lesson once.
    desc = {"did": did, "name": name, "primary": raw.get("primary") is True}
    for key in ("state_dir", "relay"):
        val = raw.get(key)
        if isinstance(val, str) and val and not _has_control(val):
            desc[key] = val
    speak = raw.get("speak")
    if isinstance(speak, list):
        desc["speak"] = [s for s in speak if isinstance(s, str) and not _has_control(s)]
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
        reason = _refuse_unsafe(d, want="dir") or _refuse_unsafe_ancestors(d)
        if reason:
            skipped.append(f"{scrub(str(d))}: {reason}")
            continue
        for f in sorted(d.glob("*.json")):
            reason = _refuse_unsafe(f)
            if reason:
                skipped.append(f"{scrub(str(f))}: {reason}")
                continue
            blob, reason = _read_capped(f)
            if blob is None:
                skipped.append(f"{scrub(str(f))}: {reason}")
                continue
            if len(blob) > MAX_BYTES:
                skipped.append(f"{scrub(str(f))}: larger than {MAX_BYTES} bytes")
                continue
            try:
                desc = _project(json.loads(blob.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                skipped.append(f"{scrub(str(f))}: not readable JSON")
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
        # A name that arrives from the config or the environment gets the same test a
        # name inside a descriptor gets; it is spent on the same two things.
        try:
            check_name(want)
        except UnsafeName as e:
            raise Ambiguous(str(e)) from None
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
            print(f"   skipped {scrub(s, limit=200)}")
        return 0
    if cmd == "pick":
        try:
            sys.stdout.write(pick(argv[2] if len(argv) > 2 else "")["name"] + "\n")
            return 0
        except Ambiguous as e:
            sys.stderr.write(f"{e}\n")
            return 3
    if cmd == "check-name":
        # The shell's mint guard asks here rather than carrying a second copy of the
        # rule: two copies is how the node ended up with four of them.
        try:
            check_name(argv[2] if len(argv) > 2 else "")
            return 0
        except UnsafeName as e:
            sys.stderr.write(f"{e}\n")
            return 4
    sys.stderr.write("usage: agents_d.py [list|table|pick [name]|check-name <name>]\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
