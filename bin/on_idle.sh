#!/usr/bin/env bash
# Fires when an agent's status changes. When one goes idle, look for new mail.
#
# WHY THIS DOES NOT RUN `turn-check`, which is the obvious choice.
# `turn-check` advances a cursor: the mail it shows is marked as already surfaced. Its
# output here would go to the plugin command log, which nobody reads -- so the mail
# would be marked seen and never seen. If the owner also runs muretai's Stop hook, that
# hook would then find nothing. `inbox --json` drains the relay exactly the same way and
# leaves the cursor alone, so the mail arrives locally AND is still waiting for whatever
# delivers it into the session.
#
# So this hook does one thing: it notices, and it tells the human. It never types into a
# pane, and it starts no process that outlives it. There is no timer here: the only
# thing that wakes it is an event from the herdr server the owner is already running.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

state="${HERDR_PLUGIN_STATE_DIR:-}"
[ -n "$state" ] || exit 0
mrt_have_muretai || exit 0

status="$(printf '%s' "${HERDR_PLUGIN_EVENT_JSON:-{\}}" | "$(mrt_python)" -c '
import json, sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
while isinstance(d, dict) and "agent_status" not in d:
    nxt = d.get("event") or d.get("data")
    if not isinstance(nxt, dict): break
    d = nxt
print(d.get("agent_status", "") if isinstance(d, dict) else "")
')"
[ "$status" = "idle" ] || exit 0

# Rate limit. Several panes settling at once is one interesting moment, not five.
stamp="$state/last_check"
now="$(date +%s)"
if [ -f "$stamp" ]; then
    last="$(cat "$stamp" 2>/dev/null || echo 0)"
    [ $(( now - ${last:-0} )) -ge 60 ] || exit 0
fi
printf '%s\n' "$now" > "$stamp"

name="$(mrt_agent 2>/dev/null)" || exit 0
seen_file="$state/last_message_id"
# COLD START: the first run must not announce the whole history. It records where the
# inbox is and says nothing; only mail that arrives after the plugin was installed is
# news. (Without this the first idle event reports every message the node ever received.)
first_run=0
[ -f "$seen_file" ] || first_run=1
seen="$(cat "$seen_file" 2>/dev/null || echo 0)"

summary="$(mrt_op "$name" inbox --json 2>/dev/null | "$(mrt_python)" -c '
import json, sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
seen = int(sys.argv[1] or 0)
latest = d.get("latest_id", 0)
new = [m for m in d.get("messages", [])
       if m.get("direction") == "in" and int(m.get("id", 0)) > seen]
if not new:
    print(f"0 {latest}")
    sys.exit(0)
who = sorted({(m.get("sender_label") or m.get("peer_name") or "someone") for m in new})
label = who[0] if len(who) == 1 else f"{len(who)} peers"
print(f"{len(new)} {latest} {label}")
' "$seen")" || exit 0

set -- $summary
count="${1:-0}"; latest="${2:-0}"; shift 2 || true; who="${*:-}"
printf '%s\n' "$latest" > "$seen_file"
[ "$first_run" -eq 0 ] || exit 0
[ "${count:-0}" -gt 0 ] || exit 0

mrt_herdr notification show "Muretai" \
    --body "$count new message(s) from ${who}" --sound request >/dev/null 2>&1 || true
printf 'muretai: %s new message(s) from %s\n' "$count" "$who"
