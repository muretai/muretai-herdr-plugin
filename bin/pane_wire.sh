#!/usr/bin/env bash
# Show how to give the agent in this pane the muretai tools.
#
# This pane PRINTS and never runs: wiring writes into a coding agent's own config, and a
# plugin from an unreviewed marketplace should not edit that behind a confirmation
# prompt. You run the line yourself, having read it.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
name="$(mrt_agent)"
node="$(mrt_node)"
py="$(mrt_python)"
kind="${MURETAI_PANE_AGENT:-}"

printf 'Wire an agent to Muretai\n'; mrt_rule
printf 'agent in that pane : %s\n' "${kind:-unknown}"
printf 'muretai identity   : %s\n\n' "$name"

printf 'The muretai MCP server is this command:\n\n'
printf '    %s %s/agent_mcp.py --as %s\n\n' "$py" "$node" "$name"

case "$kind" in
    openclaw|hermes)
        printf 'For %s, muretai wires it for you:\n\n' "$kind"
        printf '    %s %s/connector_cli.py --framework %s --as %s wire\n\n' "$py" "$node" "$kind" "$name"
        ;;
    *)
        printf 'Add that command as an MCP server the way %s documents.\n' "${kind:-your agent}"
        printf 'The muretai side needs nothing further.\n\n'
        ;;
esac
printf 'Guides: https://docs.muretai.com\n'
mrt_pause
