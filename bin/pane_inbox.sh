#!/usr/bin/env bash
# The conversation, most recent last.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
name="$(mrt_agent)"
printf 'Muretai inbox - %s\n' "$name"; mrt_rule
mrt_op "$name" inbox || true
mrt_pause
