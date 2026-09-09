#!/usr/bin/env bash
# Send a message to a peer. The body is whatever was selected in the pane, or typed here.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
name="$(mrt_agent)"

printf 'Send from %s\n' "$name"; mrt_rule
mrt_show "$name" connections
mrt_rule

printf '\nto (a name from the list above, or a DID): '
read -r target || exit 0
[ -n "$target" ] || { printf 'nothing sent.\n'; mrt_pause; exit 0; }

body="${MURETAI_SELECTED_TEXT:-}"
if [ -n "$body" ]; then
    # Shown through the same filter as anything else that was typed elsewhere: a
    # selection can be a paste of somebody else's output, escape sequences included.
    printf '\nmessage (from your selection):\n'
    printf '%s' "$body" | mrt_scrub
    printf '\n\nsend it? [y/N] '
    read -r ok || exit 0
    case "$ok" in y|Y|yes) ;; *) printf 'nothing sent.\n'; mrt_pause; exit 0;; esac
else
    printf 'message: '
    read -r body || exit 0
    [ -n "$body" ] || { printf 'nothing sent.\n'; mrt_pause; exit 0; }
fi

# `dm`, not `send`: only dm resolves a peer by the name `connections` prints, by a DID
# or a DID prefix, or by a stored alias. `send` takes an alias and nothing else.
#
# `mrt_op_body`, not `mrt_op`: the text goes to the CLI in a file it reads, so the
# message never appears in the process table. Everything else about the call is the same.
mrt_op_body "$name" "$body" dm "$target" || true
mrt_pause
