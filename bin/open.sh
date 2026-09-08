#!/usr/bin/env bash
# Every user-facing action lands here. It opens the matching plugin pane.
#
# Why the indirection: an action's stdout goes to the plugin command log, which nobody
# is watching. Anything a person must READ or ANSWER has to be a pane. So an action is
# one line -- open my pane -- and the pane does the work where it can be seen.
#
# The action's invocation context does not reach the pane on its own, so the parts the
# pane needs are forwarded explicitly with --env.

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

entry="${1:?usage: open.sh <pane-entrypoint>}"

args=(plugin pane open --plugin muretai.network --entrypoint "$entry")

# Forward only what a pane uses, and only when herdr actually gave it to us.
[ -n "${HERDR_PLUGIN_CLICKED_URL:-}" ] && args+=(--env "MURETAI_JOIN_URL=${HERDR_PLUGIN_CLICKED_URL}")
sel="$(mrt_ctx selected_text)"
[ -n "$sel" ] && args+=(--env "MURETAI_SELECTED_TEXT=${sel}")
kind="$(mrt_ctx focused_pane_agent)"
[ -n "$kind" ] && args+=(--env "MURETAI_PANE_AGENT=${kind}")

if ! out="$(mrt_herdr "${args[@]}" 2>&1)"; then
    # ui_busy is the ordinary case (Settings or Copy mode is open), not a crash.
    printf 'could not open the %s pane: %s\n' "$entry" "$out" >&2
    exit 1
fi
