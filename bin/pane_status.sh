#!/usr/bin/env bash
# Who this machine is on Muretai, and who it can reach.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

name="$(mrt_agent)"
printf 'Muretai\n'; mrt_rule

"$(mrt_python)" "$PLUGIN_ROOT/lib/agents_d.py" table "$name"

printf '\nnode    %s\n' "$(mrt_node)"
printf 'acting  %s\n\n' "$name"

mrt_rule
mrt_op "$name" connections || true
mrt_pause
