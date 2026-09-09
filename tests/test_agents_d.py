#!/usr/bin/env python3
"""The descriptor reader, against files a hostile or careless machine could contain.

Needs no herdr and no muretai node: it builds its own agents.d in a temporary directory.

    python3 tests/test_agents_d.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import agents_d  # noqa: E402


def descriptor(name: str, did: str, **extra) -> dict:
    d = {"muretai_local_agent": 1, "did": did, "name": name,
         "primary": False, "state_dir": "/somewhere", "speak": ["cli"]}
    d.update(extra)
    return d


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "agents.d"
        self.dir.mkdir()
        # HOME must move too. MURETAI_AGENTS_DIR does not REPLACE the search path: the
        # home and machine-wide roots are always searched as well, so a test that only
        # set the env var would read the real machine and pass or fail by accident.
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp.name
        os.environ["MURETAI_AGENTS_DIR"] = str(self.dir)
        os.environ.pop("MURETAI_AS", None)
        os.environ.pop("MURETAI_STATE_DIR", None)

    def tearDown(self):
        os.environ.pop("MURETAI_AGENTS_DIR", None)
        if self._home is not None:
            os.environ["HOME"] = self._home
        self.tmp.cleanup()

    def write(self, filename: str, payload, mode: int = 0o644) -> Path:
        p = self.dir / filename
        p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        p.chmod(mode)
        return p

    # ---------------------------------------------------------------- the format

    def test_reads_a_descriptor(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        agents, skipped = agents_d.discover()
        self.assertEqual([a["name"] for a in agents], ["alice"])
        self.assertEqual(skipped, [])

    def test_true_is_not_version_one(self):
        # `True == 1` in Python. A bool discriminator must not be believed.
        self.write("a.json", descriptor("alice", "did:key:zAlice",
                                        muretai_local_agent=True))
        agents, _ = agents_d.discover()
        self.assertEqual(agents, [])

    def test_unknown_version_is_ignored(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice",
                                        muretai_local_agent=2))
        self.assertEqual(agents_d.discover()[0], [])

    def test_planted_keys_never_reach_the_caller(self):
        # The descriptor is a pointer, never a payload: a file that names a command
        # must not merely be unused, it must not be visible at all.
        self.write("a.json", descriptor("alice", "did:key:zAlice",
                                        command="/bin/sh", args=["-c", "id"],
                                        env={"PATH": "/tmp/evil"}, cwd="/tmp"))
        agents, _ = agents_d.discover()
        self.assertEqual(len(agents), 1)
        for forbidden in ("command", "args", "env", "cwd"):
            self.assertNotIn(forbidden, agents[0])

    def test_missing_or_malformed_identity_is_refused(self):
        self.write("a.json", descriptor("alice", "not-a-did"))
        self.write("b.json", {"muretai_local_agent": 1, "did": "did:key:zB"})
        self.write("c.json", "{ this is not json")
        agents, skipped = agents_d.discover()
        self.assertEqual(agents, [])
        self.assertTrue(any("not readable JSON" in s for s in skipped))

    # ------------------------------------------------------------- the refusals

    def test_world_writable_file_is_skipped_and_reported(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"), mode=0o666)
        agents, skipped = agents_d.discover()
        self.assertEqual(agents, [])
        self.assertTrue(any("world-writable" in s for s in skipped),
                        "a refusal must be explained, not silent")

    def test_group_writable_is_tolerated(self):
        # umask 002 is the default for regular users on several systems, so our own
        # writers land at 0664 there. Refusing it would refuse a correct install.
        self.write("a.json", descriptor("alice", "did:key:zAlice"), mode=0o664)
        self.assertEqual(len(agents_d.discover()[0]), 1)

    def test_symlink_is_skipped(self):
        real = Path(self.tmp.name) / "real.json"
        real.write_text(json.dumps(descriptor("alice", "did:key:zAlice")))
        (self.dir / "a.json").symlink_to(real)
        agents, skipped = agents_d.discover()
        self.assertEqual(agents, [])
        self.assertTrue(any("symbolic link" in s for s in skipped))

    def test_oversize_file_is_refused_before_parsing(self):
        self.write("a.json", json.dumps(descriptor("alice", "did:key:zAlice",
                                                   pad="x" * 8000)))
        agents, skipped = agents_d.discover()
        self.assertEqual(agents, [])
        self.assertTrue(any("larger than" in s for s in skipped))

    # ------------------------------------------------------------- the choosing

    def test_one_agent_is_the_agent(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        self.assertEqual(agents_d.pick()["name"], "alice")

    def test_primary_wins(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        self.write("b.json", descriptor("bob", "did:key:zBob", primary=True))
        self.assertEqual(agents_d.pick()["name"], "bob")

    def test_several_and_no_primary_refuses_to_guess(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        self.write("b.json", descriptor("bob", "did:key:zBob"))
        with self.assertRaises(agents_d.Ambiguous) as cm:
            agents_d.pick()
        self.assertIn("alice", str(cm.exception))
        self.assertIn("bob", str(cm.exception), "it must name them all")

    def test_two_primaries_is_still_ambiguous(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice", primary=True))
        self.write("b.json", descriptor("bob", "did:key:zBob", primary=True))
        with self.assertRaises(agents_d.Ambiguous):
            agents_d.pick()

    def test_an_unknown_name_is_an_error_not_a_fallback(self):
        # The trap this guards: muretai CREATES an identity when told to act as a name
        # that does not exist. Quietly falling back to some other agent would be worse.
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        with self.assertRaises(agents_d.Ambiguous):
            agents_d.pick("alise")

    def test_env_selects_when_several_exist(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        self.write("b.json", descriptor("bob", "did:key:zBob"))
        os.environ["MURETAI_AS"] = "bob"
        try:
            self.assertEqual(agents_d.pick()["name"], "bob")
        finally:
            os.environ.pop("MURETAI_AS")

    def test_duplicate_did_is_read_once(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        self.write("b.json", descriptor("alice-again", "did:key:zAlice"))
        self.assertEqual(len(agents_d.discover()[0]), 1)

    def test_empty_machine_says_so(self):
        with self.assertRaises(agents_d.Ambiguous) as cm:
            agents_d.pick()
        self.assertIn("no muretai agent", str(cm.exception))

    # ------------------------------------------------------- the name is a path

    def test_a_name_that_is_a_path_is_refused(self):
        # `keys/<name>.key` with a name like this points OUTSIDE keys/, and the mint
        # guard in bin/common.sh is an existence test on exactly that path.
        for bad in ("../../outside", "sub/b", "a\\b", ".hidden", ".", ".."):
            with self.subTest(name=bad):
                self.assertIsNone(agents_d._project(
                    descriptor(bad, "did:key:zAlice")), f"{bad!r} was believed")
                with self.assertRaises(agents_d.UnsafeName):
                    agents_d.check_name(bad)

    def test_a_sidecar_shaped_name_is_refused(self):
        # `alice.op.key` is how the node files alice's OPERATIONAL sidecar, so an agent
        # named `alice.op` is a key two readers disagree about. The second name folds
        # onto `.tls` on a case-insensitive filesystem, which is why the fold is NFKC.
        for bad in ("alice.op", "alice.TLS", "alice.tl\u017f", "bob.iroh"):
            with self.subTest(name=bad):
                with self.assertRaises(agents_d.UnsafeName):
                    agents_d.check_name(bad)

    def test_ordinary_names_still_pass(self):
        # Mixed case and underscores are 18 test identities in the node's own suite;
        # a charset regex here would refuse them and buy nothing against traversal.
        for good in ("alice", "relay_HQ", "async_A", "a.b", "agent-2"):
            with self.subTest(name=good):
                self.assertEqual(agents_d.check_name(good), good)

    def test_control_characters_are_refused_in_name_and_did(self):
        self.assertIsNone(agents_d._project(
            descriptor("alice\nRUN", "did:key:zAlice")))
        self.assertIsNone(agents_d._project(
            descriptor("alice", "did:key:z\x1b[31mRED")))

    def test_pick_refuses_an_unsafe_preferred_name(self):
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        with self.assertRaises(agents_d.Ambiguous):
            agents_d.pick("../../outside")

    def test_primary_must_be_json_true(self):
        # Every non-empty string is truthy, so `"false"` used to WIN pick().
        for value in ("false", "no", 1, "true", [1]):
            with self.subTest(primary=value):
                desc = agents_d._project(
                    descriptor("alice", "did:key:zAlice", primary=value))
                self.assertIs(desc["primary"], False)
        self.assertIs(agents_d._project(
            descriptor("alice", "did:key:zAlice", primary=True))["primary"], True)

    # ------------------------------------------------- the file is not a file

    def test_a_fifo_is_skipped_and_never_opened(self):
        # The bug this pins: open() on a FIFO with no writer BLOCKS, and discover() runs
        # on every pane and on the idle hook. A hung reader is a hung plugin.
        os.mkfifo(self.dir / "block.json")
        agents, skipped = agents_d.discover()
        self.assertEqual(agents, [])
        self.assertTrue(any("FIFO" in s for s in skipped), skipped)

    def test_a_directory_named_json_is_skipped(self):
        (self.dir / "a.json").mkdir()
        agents, skipped = agents_d.discover()
        self.assertEqual(agents, [])
        self.assertTrue(any("directory" in s for s in skipped), skipped)

    # ------------------------------------------------------------- the parents

    def test_world_writable_ancestor_is_refused(self):
        # 0755 on agents.d protects nothing if anyone can rename agents.d away and put
        # their own there. The walk goes to the root.
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        parent = Path(self.tmp.name)
        mode = parent.stat().st_mode
        parent.chmod(0o777)
        try:
            agents, skipped = agents_d.discover()
        finally:
            parent.chmod(mode)
        self.assertEqual(agents, [])
        self.assertTrue(any("writable by everyone" in s for s in skipped), skipped)

    def test_sticky_world_writable_ancestor_is_tolerated(self):
        # /tmp is 1777 on every machine this runs on: everyone may create an entry,
        # only the owner may replace ours. That is the property being asked about.
        self.write("a.json", descriptor("alice", "did:key:zAlice"))
        parent = Path(self.tmp.name)
        mode = parent.stat().st_mode
        parent.chmod(0o1777)
        try:
            agents, _ = agents_d.discover()
        finally:
            parent.chmod(mode)
        self.assertEqual([a["name"] for a in agents], ["alice"])

    # ------------------------------------------------------------ search order

    def test_relative_env_dir_is_ignored(self):
        os.environ["MURETAI_AGENTS_DIR"] = "relative/agents.d"
        try:
            self.assertNotIn(Path("relative/agents.d"), agents_d.search_dirs())
        finally:
            os.environ["MURETAI_AGENTS_DIR"] = str(self.dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
