# What was measured, and when

Everything this plugin assumes about herdr was checked against a real installation
rather than read from the documentation. Each line is dated, because each is a
version-pinned assumption and herdr moves fast.

**Measured 2026-09-08 against herdr 0.9.0, socket protocol 22, on macOS.**
The herdr website advertised 0.8.2 that day, so `min_herdr_version` comes from the
binary, not from the docs.

## Answers the documentation does not give

| Question | What the installation said |
|---|---|
| Do plugin event hooks accept `pane.agent_status_changed`? The docs only ever show `worktree.created`. | **Yes.** `herdr plugin link` returned and `herdr plugin list --json` reported `"warnings": null`. An unrecognised event name would have been collected there as a non-fatal warning, so an empty warning list is the proof. |
| What values may an action's `contexts` take? The docs only show `workspace`. | Five: `global`, `workspace`, `tab`, `pane`, `selection`. All seven actions registered with the values declared here. |
| What does an action actually receive? | `workspace_id`, `workspace_label`, `workspace_cwd`, `tab_id`, `tab_label`, `focused_pane_id`, `focused_pane_cwd`, `focused_pane_agent`, `focused_pane_status`, `selected_text`, `invocation_source`, `correlation_id`, `clicked_url`, `link_handler_id`. Fields are omitted when they do not apply, so `focused_pane_agent` is simply absent when no agent is running in the focused pane. |
| Where does an action's output go? | To the plugin command log, not to the screen. Nobody is watching that log. This is why every action here opens a pane and the pane does the work. |
| Is a popup a pane? | No. It does not appear in `herdr pane list`, has no pane id, and does not take part in the pane or agent APIs. It is a session-modal, and it closes when its command exits — which is why the panes here wait for a keypress before returning. |
| Do custom sidebar labels appear on their own? | No. Sidebar rows are configured (`sidebar.rows_by_agent`), so a label a plugin reports is invisible until the row layout names it. That is why this plugin paints nothing in the sidebar and puts everything in panes instead. |
| Which socket does the CLI use? | The documentation says `~/.config/herdr/herdr.sock`; the file present after install is `herdr-client.sock`. Nothing here opens a socket — `HERDR_BIN_PATH` is the contract, and it is also the only one that works on Windows named pipes. |

## The muretai side

| Question | What the installation said |
|---|---|
| Is there a `muretai` command on PATH? | **No**, after a standard install. The only guaranteed form is `python3 <node>/operator_cli.py`, preferring `<node>/.venv/bin/python` when it exists. |
| What happens if the agent name is wrong? | `operator_cli.py --as <typo>` does not fail. It creates a new identity with an empty inbox and reports it as yours. Hence the key-file guard in `bin/common.sh`, which runs before every command. |
| Does reading the inbox disturb turn-mode delivery? | **No, and this was measured.** Before: cursor 264. After a full `inbox --json` that drained 1,094 messages: cursor 264, file mtime unchanged. This is the reason `bin/on_idle.sh` reads the inbox instead of running `turn-check`, which would have advanced that cursor and marked mail as delivered to a log nobody reads. |
| Does `invite create` fail loudly? | No. It exits 0 and prints the failure. So the invite pane offers the free `invite list` first and only mints after you say yes. |

## A bug the checker caught, on the day it was written

The first version of `tests/check-live.sh` proved that an unknown agent name is refused
by setting `MURETAI_AS` to a name that does not exist and expecting a refusal. It got
one, and the check was wrong anyway: the plugin config file outranks that variable, so
the probe never reached the guard — it resolved the configured agent and refused nothing.
A check that cannot fail is worse than no check. It now runs against an empty config
directory, and a second check exercises the key-file guard directly.

## Live round trip, 2026-09-08

A message went from this Mac through the plugin's own code path to `node-agent`, a muretai
node on a Fly machine in nrt, and a reply came back. The Fly box runs `--relay-only` with no
inbound HTTP, and herdr cannot add it as a machine without extra plumbing because herdr's
remote attach uses ordinary OpenSSH while a Fly machine answers through Fly's own proxy. So
the conversation happened over a path herdr has no way to represent.

The idle hook then noticed the reply and reported one new message. That is the whole loop.

Two things it taught:

- **`herdr notification show` returned `"reason": "disabled", "shown": false`** with no TUI
  client attached. The hook's notification is best-effort and swallows this, so with nothing
  attached the arrival is recorded in the plugin log and nowhere else. Whether it shows with
  a client attached is UNVERIFIED; `[ui.toast]` in herdr's `config.toml` is the lever.
- **A DID prefix is not accepted by `dm`** even though its own error text offers one. The
  full `did:key:...` worked. The send pane should say so rather than let a person discover it.

## Where a skill finds this plugin, 2026-09-09

**Measured against herdr 0.9.0 on macOS.** `~/.config/herdr/plugins.json` is a list of
installed plugins and each entry carries `plugin_root` — an absolute path to the checkout
herdr runs. That is how `skills/muretai-herdr/SKILL.md` tells an in-pane agent to reach
`bin/common.sh` rather than assembling `operator_cli.py` calls of its own. There is no
environment variable for it outside a plugin command: `HERDR_PLUGIN_ROOT` is set for the
processes herdr spawns from the manifest, and a skill is not one of them.

## The security pass, 2026-09-09

An audit of `06ea062` ran probes against this repository rather than reading it, and the
findings are fixed in 0.1.1. What they had in common is worth keeping in one place: every
one of them was a guard that existed and was **narrower than the thing it guarded**.

- The mint guard tested that `keys/<name>.key` exists, and `../../outside` is a name that
  makes that path point outside `keys/` entirely. The rule was in the node
  (`agent/paths.py:check_key_name`) and not here. It is now asked for, not copied —
  `lib/agents_d.py check-name`, with a structural `case` in bash for the machine where
  python3 is missing.
- The descriptor reader checked permissions on the file and its directory, but not on the
  directories ABOVE it, and not that the file was a file. A 0777 parent made a 0755
  `agents.d` meaningless, and a FIFO named `block.json` hung every pane and the idle hook
  until it was removed.
- `bool("false")` is `True`, so a descriptor could declare itself primary by saying it was
  not. The version key had already taught this lesson once — `True == 1` in Python — and
  the second instance was three lines below the comment explaining the first.
- The idle hook's stamp was written with `>`, which follows a symlink and writes to its
  target. Write access to the plugin's state directory was write access to any file the
  plugin's user could write.
- The message body was an argv element, and `ps -axo command=` shows argv to every user
  on macOS.
- `set -- $summary` is word splitting AND pathname expansion, on a display name a peer
  chose.

Two things the audit reported as findings were checked and are not: hostile `last_check`
contents cannot reach a shell through `$(( ))` (`set -u` aborts first), and `open.sh`
keeps selected text as a single `--env` argument. Both are re-measured in the suites.

## Still unverified

- Ctrl+click actually firing the link handler. The pattern and the action are registered
  and the environment variables are real; the click itself needs a person at a keyboard.
- Linux. Everything above was measured on macOS; CI now runs the two offline suites there.
- Whether herdr blocks its UI while an event hook is slow. The FIFO case is fixed at the
  reader, so this is no longer reachable from `agents.d`, but the question stands.
