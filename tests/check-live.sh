#!/usr/bin/env bash
# Check this plugin against YOUR herdr and YOUR muretai node.
#
# WHY THIS SHIPS HERE. A checker that lives in another repository is a promise pointing
# at nothing: if that repository is private, or simply absent, every claim this README
# makes becomes unreproducible by the people the README is for. So it is here, it needs
# no account and no dependency you do not already have, and it exits non-zero, so it can
# gate.
#
#   bash tests/check-live.sh
#
# It is read-only apart from linking the plugin, which it does only with --link and
# unlinks again. It never sends a message, never mints an invite, and never writes a key.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERDR="${HERDR_BIN_PATH:-herdr}"
PLUGIN_ID="muretai.network"
passed=0
declare -a failed=()

ok()   { printf 'ok: %s\n' "$1"; passed=$((passed + 1)); }
bad()  { printf 'FAIL: %s  (%s)\n' "$1" "${2:-}"; failed+=("$1"); }
note() { printf -- '--: %s\n' "$1"; }

case "${1:-}" in
    -h|--help) printf 'usage: bash tests/check-live.sh [--link]\n'; exit 2 ;;
    --link) DO_LINK=1 ;;
    "") DO_LINK=0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
esac

json() { "${PY:-python3}" -c "$@"; }

# ------------------------------------------------------------------------ herdr
if ! command -v "$HERDR" >/dev/null 2>&1; then
    bad "herdr is installed" "not on PATH; set HERDR_BIN_PATH"
else
    ok "herdr is installed"
    ver="$("$HERDR" --version 2>/dev/null | awk '{print $2}')"
    want="$(sed -n 's/^min_herdr_version *= *"\(.*\)"/\1/p' "$ROOT/herdr-plugin.toml")"
    if [ -n "$ver" ] && [ "$(printf '%s\n%s\n' "$want" "$ver" | sort -V | head -1)" = "$want" ]; then
        ok "herdr $ver satisfies min_herdr_version $want"
    else
        bad "herdr satisfies min_herdr_version $want" "found '${ver:-unknown}'"
    fi
    if "$HERDR" agent list >/dev/null 2>&1; then ok "a herdr server is running"
    else bad "a herdr server is running" "start one with: herdr"; fi
fi

# ----------------------------------------------------------------------- plugin
[ "${DO_LINK:-0}" = "1" ] && "$HERDR" plugin link "$ROOT" >/dev/null 2>&1

listing="$("$HERDR" plugin list --json 2>/dev/null)"
mine="$(printf '%s' "$listing" | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(1)
for p in d.get('result',{}).get('plugins',[]):
    if p.get('plugin_id')=='$PLUGIN_ID':
        print(json.dumps(p)); break
" 2>/dev/null)"

if [ -z "$mine" ]; then
    bad "the plugin is registered" "link it: herdr plugin link $ROOT"
else
    ok "the plugin is registered"
    printf '%s' "$mine" | python3 -c "
import json,sys
p=json.load(sys.stdin)
w=p.get('warnings')
print('WARN' if w else 'CLEAN', json.dumps(w))
" | { read -r verdict rest
          if [ "$verdict" = "CLEAN" ]; then
              # The load-bearing one. herdr collects an unrecognised event name as a
              # non-fatal warning, so an empty warning list is the proof that our
              # pane.agent_status_changed hook is a real subscription and not a no-op.
              ok "herdr accepted the manifest with no warnings"
          else
              bad "herdr accepted the manifest with no warnings" "$rest"
          fi; }

    # Structure comes out of the JSON, not out of grep: json.dumps spaces its
    # separators, and a checker that quietly matches nothing is worse than no checker.
    while IFS='|' read -r verdict label detail; do
        [ "$verdict" = "ok" ] && ok "$label" || bad "$label" "$detail"
    done < <(printf '%s' "$mine" | python3 -c "
import json, sys
p = json.load(sys.stdin)
have = {a.get('id') for a in p.get('actions', [])}
for want in ('status', 'inbox', 'send', 'invite', 'join', 'wire', 'doctor'):
    print(('ok' if want in have else 'no') + f\"|action '{want}' is registered|absent from plugin list\")
events = {e.get('on') for e in p.get('events', [])}
print(('ok' if 'pane.agent_status_changed' in events else 'no')
      + '|the idle event hook is registered|no such event in plugin list')
links = {l.get('id') for l in p.get('link_handlers', [])}
print(('ok' if 'invite-link' in links else 'no')
      + '|the invite link handler is registered|no link handler in plugin list')
panes = {q.get('id') for q in p.get('panes', [])}
missing = sorted(have - panes)
print(('ok' if not missing else 'no')
      + f\"|every action has a pane to open|no pane for: {', '.join(missing)}\")
")
fi

# ---------------------------------------------------------------------- muretai
# A person running this by hand has no HERDR_PLUGIN_CONFIG_DIR in their environment --
# herdr only sets it for a command it launches. Ask herdr for it, so the checker reads
# the same `agent=` the plugin will read.
if [ -z "${HERDR_PLUGIN_CONFIG_DIR:-}" ] && command -v "$HERDR" >/dev/null 2>&1; then
    cfg="$("$HERDR" plugin config-dir "$PLUGIN_ID" 2>/dev/null | tr -d '\r')"
    [ -d "${cfg:-}" ] && export HERDR_PLUGIN_CONFIG_DIR="$cfg"
fi

NODE="${MURETAI_NODE_DIR:-$HOME/muretai-node}"
if [ -f "$NODE/operator_cli.py" ]; then
    ok "a muretai node is present at $NODE"
    PY="$NODE/.venv/bin/python"; [ -x "$PY" ] || PY=python3
    if name="$(HERDR_PLUGIN_ROOT="$ROOT" bash -c 'source "'"$ROOT"'/bin/common.sh"; mrt_agent' 2>&1)"; then
        ok "an agent is chosen: $name"
        if [ -f "${MURETAI_STATE_DIR:-$NODE}/keys/${name}.key" ]; then
            ok "the key for '$name' is already on this machine"
        else
            bad "the key for '$name' is already on this machine" "no key file"
        fi
    else
        note "no agent chosen yet: ${name}"
    fi

    # The guard that matters most, exercised rather than asserted: a name that does
    # not exist must be refused, because muretai would otherwise CREATE that identity.
    # The config file outranks MURETAI_AS by design, so the probe runs against an empty
    # config dir -- otherwise it would silently test the configured agent instead, and
    # report a pass for a guard it never reached.
    probe="$(mktemp -d)"
    if HERDR_PLUGIN_ROOT="$ROOT" HERDR_PLUGIN_CONFIG_DIR="$probe" MURETAI_AS="no-such-agent-$$" \
        bash -c 'source "'"$ROOT"'/bin/common.sh"; mrt_agent' >/dev/null 2>&1; then
        bad "an unknown agent name is refused" "accepted; a typo would mint a new identity"
    else
        ok "an unknown agent name is refused"
    fi
    # And the second, independent guard: even if a name got through, no command runs
    # without its key file already on disk.
    if HERDR_PLUGIN_ROOT="$ROOT" \
        bash -c 'source "'"$ROOT"'/bin/common.sh"; mrt_assert_key "no-such-agent-'"$$"'"' \
        >/dev/null 2>&1; then
        bad "a missing key file stops the command" "it did not"
    else
        ok "a missing key file stops the command"
    fi
    rmdir "$probe" 2>/dev/null || true
    if [ -f "$NODE/keys/no-such-agent-$$.key" ]; then
        bad "nothing was minted while checking" "a key file appeared"
    else
        ok "nothing was minted while checking"
    fi
else
    note "no muretai node at $NODE (install: curl -fsSL https://muretai.com/install | MURETAI_AGREE_TOS=1 bash)"
fi

# ---------------------------------------------------- the promises in the README
grep -rq "agent prompt\|agent.prompt" "$ROOT/bin" "$ROOT/lib" 2>/dev/null \
    && bad "nothing here types into a pane" "a script calls agent prompt" \
    || ok "nothing here types into a pane"

grep -q "^\[\[build\]\]" "$ROOT/herdr-plugin.toml" \
    && bad "there is no build step" "the manifest declares [[build]]" \
    || ok "there is no build step"

if python3 "$ROOT/tests/test_agents_d.py" >/dev/null 2>&1; then
    ok "the descriptor reader tests pass"
else
    bad "the descriptor reader tests pass" "run: python3 tests/test_agents_d.py"
fi

[ "${DO_LINK:-0}" = "1" ] && "$HERDR" plugin unlink "$PLUGIN_ID" >/dev/null 2>&1

printf '%*s\n' 60 '' | tr ' ' -
if [ "${#failed[@]}" -eq 0 ]; then
    printf 'CONFORMANT: %s passed, 0 failed\n' "$passed"
    exit 0
fi
printf 'NOT CONFORMANT: %s passed, %s failed\n' "$passed" "${#failed[@]}"
printf '  failed: %s\n' "$(IFS='; '; echo "${failed[*]}")"
exit 1
