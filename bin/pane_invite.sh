#!/usr/bin/env bash
# Invite someone. Minting spends part of a scarce allotment, so the free list comes first.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
name="$(mrt_agent)"

printf 'Muretai invites - %s\n' "$name"; mrt_rule
printf 'Live invites you have already paid for:\n\n'
mrt_op "$name" invite list || true

mrt_rule
printf '\nMinting a new invite spends one from your allotment; the list above is free\n'
printf 'to re-copy. Mint a new one anyway? [y/N] '
read -r ok || exit 0
case "$ok" in
    y|Y|yes)
        printf '\n'
        # `invite create` exits 0 even when it fails -- the failure is a line on stdout.
        # So the exit status is not the signal here; the printed block is.
        mrt_op "$name" invite create || true
        ;;
    *) printf 'nothing minted.\n' ;;
esac
mrt_pause
