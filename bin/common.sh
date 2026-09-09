#!/usr/bin/env bash
# Shared resolution for every action in this plugin. Sourced, never executed.
#
# It answers two questions that must stay apart:
#   WHICH agent  -- from the agents.d descriptors (lib/agents_d.py), which are pointers
#                   and carry no command, path or environment to run.
#   WHERE muretai -- from the environment and convention, never from a descriptor.
#
# It also holds the guards that a caller must not be trusted to remember.

set -euo pipefail

PLUGIN_ROOT="${HERDR_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# GUARD 3: identify ourselves on every command we spawn. Without this the owner's
# `doctor` reports that something on this machine drives the node anonymously.
export MURETAI_CLIENT="muretai-herdr-plugin"

mrt_die() { printf '%s\n' "$*" >&2; exit 1; }

mrt_rule() { printf '%*s\n' 60 '' | tr ' ' -; }

# ------------------------------------------------------------------ safe paths
# The three questions we ask of anything we are about to BELIEVE (a config we parse) or
# RUN (the node tree). They are the same three lib/agents_d.py asks of a descriptor, and
# for the same reason: a file that another user can replace is a file that speaks for
# them, not for you.
#
# `find -maxdepth 0` rather than `stat`, because `stat` has no spelling that means the
# same thing on macOS and on Linux, and this plugin claims both.
mrt_why_unsafe() {
    local p="$1" me
    if [ -L "$p" ]; then printf 'it is a symbolic link'; return 0; fi
    [ -e "$p" ] || return 1          # absent is not unsafe; the caller handles absence
    me="$(id -u)"
    if [ -n "$(find "$p" -maxdepth 0 -perm -0002 2>/dev/null)" ]; then
        printf 'it is writable by everyone'; return 0
    fi
    if [ -z "$(find "$p" -maxdepth 0 \( -user "$me" -o -user 0 \) 2>/dev/null)" ]; then
        printf 'it is owned by another user'; return 0
    fi
    return 1
}

# ---------------------------------------------------------------- plugin config
# A two-key file the owner may write. Parsed, never sourced: a config file that is
# executed is a config file with exec rights.
#   agent=<name>
#   node=/path/to/muretai-node
#
# `node=` is the reason the file's PERMISSIONS matter as much as its syntax. It names a
# directory this plugin then runs `operator_cli.py` out of, so a config anyone can write
# is a way to run anyone's code as you. The gate runs once, here, at source time: doing
# it inside mrt_config would either repeat the warning per key or print it inside a
# subshell where nobody would see it.
MRT_CONFIG_FILE=""
mrt_config_init() {
    local dir="${HERDR_PLUGIN_CONFIG_DIR:-}" file why
    [ -n "$dir" ] || return 0
    file="$dir/config"
    [ -e "$file" ] || [ -L "$file" ] || return 0
    if why="$(mrt_why_unsafe "$file")"; then
        printf 'muretai: ignoring the plugin config at %s -- %s.\n' "$file" "$why" >&2
        printf '         A config that names node= chooses what runs as you.\n' >&2
        return 0
    fi
    MRT_CONFIG_FILE="$file"
}
mrt_config_init

mrt_config() {
    local key="$1"
    [ -n "$MRT_CONFIG_FILE" ] || return 0
    sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$MRT_CONFIG_FILE" \
        | head -1 | tr -d '\r'
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
#
# It is also an EXECUTABLE PATH derived from a configurable directory, which is the one
# thing this plugin promises never to do with untrusted input. So the venv is used only
# out of a bin/ directory that passes the same test the config file passed. The symlink
# check is on the directory and not on `python` itself: inside a virtualenv that file is
# normally a link to the base interpreter, and refusing it would refuse every venv.
mrt_python() {
    local node venv; node="$(mrt_node)"
    venv="$node/.venv/bin/python"
    if [ -x "$venv" ] && ! mrt_why_unsafe "$node/.venv/bin" >/dev/null; then
        printf '%s\n' "$venv"
    else
        printf 'python3\n'
    fi
}

# The state tree holds keys/. It follows MURETAI_STATE_DIR when the owner set one,
# and otherwise is the node tree, which is what a standard install gives.
mrt_state() {
    if [ -n "${MURETAI_STATE_DIR:-}" ]; then printf '%s\n' "$MURETAI_STATE_DIR"
    else mrt_node; fi
}

mrt_have_muretai() { [ -f "$(mrt_node)/operator_cli.py" ]; }

# GUARD 4: the tree we are about to execute out of is yours. Checked once per process,
# and as a STATEMENT rather than inside a `$( )`, so that a refusal stops the pane
# instead of returning an empty string to it.
MRT_NODE_OK=""
mrt_assert_node() {
    [ -z "$MRT_NODE_OK" ] || return 0
    local node why
    node="$(mrt_node)"
    if why="$(mrt_why_unsafe "$node")"; then
        mrt_die "muretai: refusing to run anything from ${node} -- ${why}."
    fi
    if why="$(mrt_why_unsafe "$node/operator_cli.py")"; then
        mrt_die "muretai: refusing to run ${node}/operator_cli.py -- ${why}."
    fi
    MRT_NODE_OK=1
}

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

# GUARD 0: a name is spent twice -- as `--as <name>` and as the segment in
# `keys/<name>.key` -- so it must be a NAME and not a path. `../../outside` used to
# satisfy the existence check below by pointing at a file outside keys/ entirely.
#
# Two checks, on purpose. The `case` is the structural half: it needs no interpreter, so
# it holds even where python3 is missing. lib/agents_d.py holds the whole rule -- the
# node's `paths.check_key_name`, including the folding a case-insensitive filesystem
# does -- and it is asked rather than copied, because a rule that exists twice is a rule
# that will disagree with itself.
mrt_check_name() {
    local name="${1:-}" shown
    # The refusal PRINTS the name, and a name we are refusing is one we have no reason
    # to trust with a terminal. `tr -d` rather than a quoting expansion, because the
    # bash on a stock mac is 3.2 and has neither ${x@Q} nor ${x,,}.
    shown="$(printf '%s' "$name" | tr -d '[:cntrl:]')"
    case "$name" in
        ""|.|..|.*|*/*|*\\*|*[[:cntrl:]]*)
            mrt_die "muretai: refusing the agent name '${shown}': it must be a plain name,
not a path. A name with a slash, a leading dot or a control character would point the key
check somewhere other than at one file inside keys/." ;;
    esac
    "$(mrt_python)" "$PLUGIN_ROOT/lib/agents_d.py" check-name "$name" \
        || mrt_die "muretai: refusing the agent name '${shown}'."
}

# GUARD 1, the most important line in this repo. `operator_cli.py --as <typo>` does not
# fail: it MINTS a brand-new identity with an empty inbox and reports it as yours. So no
# command runs until its key file is already there -- and until the name is one that can
# only ever mean a file INSIDE keys/.
mrt_assert_key() {
    local name="$1" key
    mrt_check_name "$name"
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
    mrt_assert_node
    mrt_assert_key "$name"
    # A body does not travel here. `dm <peer> <text>` would put the text in argv, and
    # every user on a mac can read argv; mrt_op_body exists so that it does not have to.
    # Structural rather than documented: the next caller reads the code, not the note.
    if [ "${1:-}" = "dm" ] && [ "$#" -gt 2 ]; then
        mrt_die "muretai: internal -- a dm body must go through mrt_op_body, not argv."
    fi
    "$(mrt_python)" "$(mrt_node)/operator_cli.py" --as "$name" "$@"
}

# A read-only command whose output goes straight into a pane.
#
# The guards run in the FUNCTION's shell, before the pipeline, on purpose: a guard that
# fails inside `cmd | filter` would only kill the subshell, and the pane would carry on
# as if it had asked nothing. `|| true` after the filter is the old behaviour -- a node
# that answers with an error has still answered, and the pane prints that answer.
mrt_show() {
    local name="$1"; shift
    mrt_have_muretai || { mrt_install_hint; exit 1; }
    mrt_assert_node
    mrt_assert_key "$name"
    "$(mrt_python)" "$(mrt_node)/operator_cli.py" --as "$name" "$@" 2>&1 | mrt_scrub || true
}

# The same call, with the last argument -- the message body -- handed over in a file
# instead of on the command line.
#
# `ps -axo command=` on macOS shows every process's arguments to every user on the
# machine, and /proc/<pid>/cmdline does the same for your own processes on Linux. The
# body of a dm is a selection out of a pane: a paste, an invite URL, a sentence you did
# not intend to publish to the process table. lib/run_op.py rebuilds argv inside the
# python process, where nothing outside can read it.
mrt_op_body() {
    local name="$1" body="$2"; shift 2
    local tmp rc=0
    mrt_have_muretai || { mrt_install_hint; exit 1; }
    mrt_assert_node
    mrt_assert_key "$name"
    tmp="$(mktemp "${TMPDIR:-/tmp}/muretai-body.XXXXXX")" \
        || mrt_die "muretai: could not create a temporary file for the message body"
    chmod 600 "$tmp"
    printf '%s' "$body" > "$tmp"
    "$(mrt_python)" "$PLUGIN_ROOT/lib/run_op.py" "$(mrt_node)/operator_cli.py" "$tmp" \
        --as "$name" "$@" 2>&1 | mrt_scrub || rc=$?
    rm -f "$tmp"
    return "$rc"
}

mrt_connector() {
    mrt_have_muretai || { mrt_install_hint; exit 1; }
    mrt_assert_node
    "$(mrt_python)" "$(mrt_node)/connector_cli.py" "$@"
}

# GUARD 5: everything the node prints back carries text a peer typed. A pane is a
# terminal, so an ESC in a sender's display name is not a character -- it repaints the
# row above, which is the whole of a spoofing attack. One filter, at the one place the
# output is printed.
mrt_scrub() { "$(mrt_python)" "$PLUGIN_ROOT/lib/scrub.py"; }

# ------------------------------------------------------------------------ state
# A plugin state file is small, ours, and rewritten often -- which makes it the easiest
# thing on the machine to aim somewhere else. Write access to the state directory used
# to be enough to turn the idle hook into "overwrite any file the plugin user can
# write": the redirection followed the symlink and put a unix timestamp in the target.
#
# `mktemp` in the same directory and then `mv` is the fix: rename(2) replaces the NAME,
# it does not follow the link that was sitting on it.
mrt_state_write() {
    local file="$1" value="$2" tmp
    if [ -L "$file" ]; then
        printf 'muretai: not writing %s -- it is a symbolic link.\n' "$file" >&2
        return 1
    fi
    tmp="$(mktemp "${file}.XXXXXX")" || return 1
    printf '%s\n' "$value" > "$tmp"
    mv -f "$tmp" "$file"
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
