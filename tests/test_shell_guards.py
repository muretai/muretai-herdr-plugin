#!/usr/bin/env python3
"""The guards that live in bash, against the machine an attacker would arrange.

lib/agents_d.py has its own suite. This one covers the half of the plugin a python test
cannot reach: the mint guard, the plugin config, the message body, and the state file
the idle hook writes with nobody watching. Every case here is a bug that was real —
each was reproduced against this repository before the guard it tests existed.

Needs bash and no muretai node: the node is a directory with an inert operator_cli.py.

    python3 tests/test_shell_guards.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = ROOT / "bin" / "common.sh"


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.node = self.dir / "node"
        self.node.mkdir()
        (self.node / "operator_cli.py").write_text("import sys\n")
        self.state = self.dir / "state"
        (self.state / "keys").mkdir(parents=True)
        (self.state / "keys" / "alice.key").write_text("fixture, not a key")

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, **over) -> dict:
        env = os.environ.copy()
        for k in list(env):
            if k.startswith(("MURETAI_", "HERDR_")):
                env.pop(k)
        env.update({
            "HERDR_PLUGIN_ROOT": str(ROOT),
            "HOME": str(self.home),
            "MURETAI_NODE_DIR": str(self.node),
            "MURETAI_STATE_DIR": str(self.state),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        env.update({k: str(v) for k, v in over.items()})
        return env

    def bash(self, script: str, **over) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", f"source {COMMON}\n{script}\n"],
            env=self.env(**over), capture_output=True, text=True, timeout=60)

    # ------------------------------------------------------------ the name guard

    def test_a_name_that_leaves_keys_is_refused(self):
        # The key file exists — one directory ABOVE keys/. The guard used to say yes,
        # and `--as ../../outside` then reached a node that would mint an identity.
        (self.dir / "outside.key").write_text("fixture")
        self.assertTrue((self.state / "keys" / ".." / ".." / "outside.key").exists())
        r = self.bash("mrt_assert_key '../../outside' && echo ACCEPTED")
        self.assertNotIn("ACCEPTED", r.stdout)
        self.assertIn("refusing", r.stderr.lower())

    def test_a_name_with_a_separator_is_refused(self):
        (self.state / "keys" / "sub").mkdir()
        (self.state / "keys" / "sub" / "b.key").write_text("fixture")
        r = self.bash("mrt_assert_key 'sub/b' && echo ACCEPTED")
        self.assertNotIn("ACCEPTED", r.stdout)

    def test_a_real_name_is_still_accepted(self):
        r = self.bash("mrt_assert_key alice && echo ACCEPTED")
        self.assertIn("ACCEPTED", r.stdout, r.stderr)

    def test_a_missing_key_is_still_refused(self):
        r = self.bash("mrt_assert_key bob && echo ACCEPTED")
        self.assertNotIn("ACCEPTED", r.stdout)
        self.assertIn("no key for", r.stderr)

    # ---------------------------------------------------------------- the config

    def test_a_world_writable_config_is_ignored_and_said_so(self):
        cfg = self.dir / "config-dir"
        cfg.mkdir()
        (cfg / "config").write_text("agent=planted\nnode=/somewhere/else\n")
        (cfg / "config").chmod(0o666)
        r = self.bash("mrt_config agent", HERDR_PLUGIN_CONFIG_DIR=cfg)
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn("ignoring the plugin config", r.stderr)

    def test_a_config_that_is_a_symlink_is_ignored(self):
        real = self.dir / "elsewhere-config"
        real.write_text("agent=planted\n")
        cfg = self.dir / "config-link-dir"
        cfg.mkdir()
        (cfg / "config").symlink_to(real)
        r = self.bash("mrt_config agent", HERDR_PLUGIN_CONFIG_DIR=cfg)
        self.assertEqual(r.stdout.strip(), "")

    def test_a_config_you_own_is_still_read(self):
        cfg = self.dir / "good-config-dir"
        cfg.mkdir()
        (cfg / "config").write_text("agent=alice\n")
        (cfg / "config").chmod(0o600)
        r = self.bash("mrt_config agent", HERDR_PLUGIN_CONFIG_DIR=cfg)
        self.assertEqual(r.stdout.strip(), "alice")

    def test_a_world_writable_node_tree_is_not_run(self):
        self.node.chmod(0o777)
        try:
            r = self.bash("mrt_assert_node && echo RAN")
        finally:
            self.node.chmod(0o755)
        self.assertNotIn("RAN", r.stdout)
        self.assertIn("refusing to run", r.stderr)

    # ------------------------------------------------------------------ the body

    @unittest.skipUnless(shutil.which("ps"), "needs ps")
    def test_the_message_body_is_not_in_the_process_table(self):
        (self.node / "operator_cli.py").write_text("import time; time.sleep(3)\n")
        secret = "BODY" + uuid.uuid4().hex
        proc = subprocess.Popen(
            ["bash", "-c", f"source {COMMON}\nmrt_op_body alice \"$BODY\" dm peer\n"],
            env=self.env(BODY=secret), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        try:
            seen = False
            for _ in range(20):
                time.sleep(0.1)
                ps = subprocess.run(["ps", "-axo", "command="], capture_output=True,
                                    text=True, errors="replace").stdout
                if secret in ps:
                    seen = True
                    break
                if proc.poll() is not None:
                    break
            self.assertFalse(seen, "the message body was visible in `ps`")
        finally:
            proc.kill()
            proc.wait(timeout=5)

    # ------------------------------------------------------------------ the stamp

    def test_a_state_write_does_not_follow_a_symlink(self):
        victim = self.dir / "victim"
        victim.write_text("0\n")
        stamp = self.dir / "stamp"
        stamp.symlink_to(victim)
        r = self.bash(f"mrt_state_write {stamp} 1234 || true")
        self.assertEqual(victim.read_text().strip(), "0",
                         "the write went through the link onto its target")
        self.assertIn("symbolic link", r.stderr)

    def test_the_idle_hook_does_not_clobber_through_its_stamp(self):
        victim = self.dir / "idle-victim"
        victim.write_text("0\n")          # numeric, or the rate limit aborts first
        pstate = self.dir / "plugin-state"
        pstate.mkdir()
        (pstate / "last_check").symlink_to(victim)
        agents = self.dir / "agents.d"
        agents.mkdir()
        (agents / "a.json").write_text(json.dumps(
            {"muretai_local_agent": 1, "did": "did:key:zAlice", "name": "alice"}))
        subprocess.run(
            ["bash", str(ROOT / "bin" / "on_idle.sh")],
            env=self.env(HERDR_PLUGIN_STATE_DIR=pstate, MURETAI_AGENTS_DIR=agents,
                         HERDR_PLUGIN_EVENT_JSON='{"agent_status":"idle"}'),
            capture_output=True, timeout=60)
        self.assertEqual(victim.read_text().strip(), "0")

    # ----------------------------------------------------------------- the label

    def test_a_hostile_sender_label_is_not_glob_expanded(self):
        # `set -- $summary` was pathname expansion on a name a peer chose: a label of
        # `*` listed the pane's working directory into the notification.
        work = self.dir / "cwd"
        work.mkdir()
        (work / "GLOBBED").write_text("")
        r = subprocess.run(
            ["bash", "-c",
             'summary="1 7 *"\nread -r count latest who <<<"$summary"\nprintf %s "$who"'],
            cwd=work, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout, "*")


if __name__ == "__main__":
    unittest.main(verbosity=2)
