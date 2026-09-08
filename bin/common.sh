#!/usr/bin/env bash
# Shared resolution for every action in this plugin. Sourced, never executed.
#
# It answers two questions that must stay apart:
#   WHICH agent  -- from the agents.d descriptors (lib/agents_d.py), which are pointers
#                   and carry no command, path or environment to run.
#   WHERE muretai -- from the environment and convention, never from a descriptor.
#
# It also holds the five guards that a caller must not be trusted to remember.

set -euo pipefail

PLUGIN_ROOT="${HERDR_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# GUARD 3: identify ourselves on every command we spawn. Without this the owner's
# `doctor` reports that something on this machine drives the node anonymously.
export MURETAI_CLIENT="muretai-herdr-plugin"

mrt_die() { printf '%s\n' "$*" >&2; exit 1; }

mrt_rule() { printf '%*s\n' 60 '' | tr ' ' -; }

# ---------------------------------------------------------------- plugin config
# A two-key file the owner may write. Parsed, never sourced: a config file that is
# executed is a config file with exec rights.
#   agent=<name>
#   node=/path/to/muretai-node
mrt_config() {
    local key="$1" dir="${HERDR_PLUGIN_CONFIG_DIR:-}" file
    [ -n "$dir" ] || return 0
    file="$dir/config"
    [ -f "$file" ] || return 0
    sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$file" | head -1 | tr -d '\r'
}

# ------------------------------------------------------------------- where it is
mrt_node() {
    local n
    n="$(mrt_config node)"
    [ -n "$n" ] || n="${MURETAI_NODE_DIR:-$HOME/muretai-node}"
    printf '%s\n' "${n/#\~/$HOME}"
}

# The node's own venv carries the fast crypto backend the relay path wants; plain
# python3 works but is the fallback, not the preference.
mrt_python() {
    local node; node="$(mrt_node)"
    if [ -x "$node/.venv/bin/python" ]; then printf '%s\n' "$node/.venv/bin/python"
    else printf 'python3\n'; fi
}

# The state tree holds keys/. It follows MURETAI_STATE_DIR when the owner set one,
# and otherwise is the node tree, which is what a standard install gives.
mrt_state() {
    if [ -n "${MURETAI_STATE_DIR:-}" ]; then printf '%s\n' "$MURETAI_STATE_DIR"
    else mrt_node; fi
}

mrt_have_muretai() { [ -f "$(mrt_node)/operator_cli.py" ]; }

mrt_install_hint() {
    cat <<'HINT'
No muretai node found on this machine.

Install one (the terms are at https://muretai.com/terms; that variable records
YOUR consent, not your agent's):

    curl -fsSL https://muretai.com/install | MURETAI_AGREE_TOS=1 bash

If your node lives somewhere else, point this plugin at it:

    echo "node=/path/to/muretai-node" >> "$(herdr plugin config-dir muretai.network)/config"
HINT
}

# ------------------------------------------------------------------- which agent
mrt_agent() {
    local want out rc
    want="$(mrt_config agent)"
    [ -n "$want" ] || want="${MURETAI_AS:-}"
    # One call, both streams kept: the reader's refusal message IS the explanation the
    # owner needs, so it must not be thrown away to re-derive a worse one.
    out="$("$(mrt_python)" "$PLUGIN_ROOT/lib/agents_d.py" pick "$want" 2>&1)" && rc=0 || rc=$?
    if [ "$rc" -ne 0 ]; then
        mrt_die "muretai: ${out}

Pick one for this plugin:
    echo \"agent=<name>\" >> \"\$(herdr plugin config-dir muretai.network)/config\""
    fi
    printf '%s\n' "$out"
}

# GUARD 1, the most important line in this repo. `operator_cli.py --as <typo>` does not
# fail: it MINTS a brand-new identity with an empty inbox and reports it as yours. So no
# command runs until its key file is already there.
mrt_assert_key() {
    local name="$1" key
    key="$(mrt_state)/keys/${name}.key"
    [ -f "$key" ] || mrt_die "muretai: no key for '${name}' at ${key}
Refusing to run: naming an agent that does not exist would CREATE a new identity."
}

# ---------------------------------------------------------------------- invoking
# GUARD 2: --as is a top-level flag and must come BEFORE the verb. Every call goes
# through here so that ordering is decided once.
mrt_op() {
    local name="$1"; shift
    mrt_have_muretai || { mrt_install_hint; exit 1; }
    mrt_assert_key "$name"
    "$(mrt_python)" "$(mrt_node)/operator_cli.py" --as "$name" "$@"
}

mrt_connector() {
    mrt_have_muretai || { mrt_install_hint; exit 1; }
    "$(mrt_python)" "$(mrt_node)/connector_cli.py" "$@"
}

# ------------------------------------------------------------------------ herdr
mrt_herdr() { "${HERDR_BIN_PATH:-herdr}" "$@"; }

# The action context herdr hands us, or "null" outside herdr.
mrt_ctx() {
    local key="$1"
    printf '%s' "${HERDR_PLUGIN_CONTEXT_JSON:-\{\}}" | "$(mrt_python)" -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: d={}
v=d.get(sys.argv[1])
print('' if v is None else v)
" "$key"
}

mrt_pause() {
    # Plugin panes close when their command exits, so a popup that printed something
    # useful must wait for the reader.
    printf '\n[enter to close] '
    read -r _ || true
}
