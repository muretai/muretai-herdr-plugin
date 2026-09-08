#!/usr/bin/env bash
# Send a message to a peer. The body is whatever was selected in the pane, or typed here.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
name="$(mrt_agent)"

printf 'Send from %s\n' "$name"; mrt_rule
mrt_op "$name" connections || true
mrt_rule

printf '\nto (a name from the list above, or a DID): '
read -r target || exit 0
[ -n "$target" ] || { printf 'nothing sent.\n'; mrt_pause; exit 0; }

body="${MURETAI_SELECTED_TEXT:-}"
if [ -n "$body" ]; then
    printf '\nmessage (from your selection):\n%s\n\nsend it? [y/N] ' "$body"
    read -r ok || exit 0
    case "$ok" in y|Y|yes) ;; *) printf 'nothing sent.\n'; mrt_pause; exit 0;; esac
else
    printf 'message: '
    read -r body || exit 0
    [ -n "$body" ] || { printf 'nothing sent.\n'; mrt_pause; exit 0; }
fi

# `dm`, not `send`: only dm resolves a peer by the name `connections` prints, by a DID
# or a DID prefix, or by a stored alias. `send` takes an alias and nothing else.
mrt_op "$name" dm "$target" "$body" || true
mrt_pause
