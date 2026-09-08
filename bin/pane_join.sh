#!/usr/bin/env bash
# Accept an invite link. Reached by Ctrl+click on a link in any pane, or from the menu.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
name="$(mrt_agent)"

link="${MURETAI_JOIN_URL:-}"
printf 'Join with an invite - %s\n' "$name"; mrt_rule
if [ -n "$link" ]; then
    printf 'link: %s\n\naccept it as %s? [y/N] ' "$link" "$name"
    read -r ok || exit 0
    case "$ok" in y|Y|yes) ;; *) printf 'not accepted.\n'; mrt_pause; exit 0;; esac
else
    printf 'paste the invite link: '
    read -r link || exit 0
    [ -n "$link" ] || { printf 'nothing to accept.\n'; mrt_pause; exit 0; }
fi

printf '\n'
mrt_op "$name" invite accept "$link" || true
mrt_pause
