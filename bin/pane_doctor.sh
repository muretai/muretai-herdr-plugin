#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
name="$(mrt_agent)"
printf 'muretai doctor - %s\n' "$name"; mrt_rule
mrt_op "$name" doctor || true
mrt_pause
