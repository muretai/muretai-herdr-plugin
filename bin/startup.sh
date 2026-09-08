#!/usr/bin/env bash
# Runs once per session restore. It paints nothing and changes nothing: it records one
# line in the plugin log so that "is this plugin working" has an answer that does not
# require reproducing a failure.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if ! mrt_have_muretai; then
    printf 'muretai: no node at %s -- actions will explain how to install one\n' "$(mrt_node)"
    exit 0
fi
if name="$(mrt_agent 2>/dev/null)"; then
    printf 'muretai: ready, acting as %s (node %s)\n' "$name" "$(mrt_node)"
else
    printf 'muretai: node at %s, but no agent chosen yet (set agent= in the plugin config)\n' "$(mrt_node)"
fi
