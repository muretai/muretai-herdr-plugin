#!/usr/bin/env python3
"""Run the node's operator CLI with its last argument read from a FILE, not from argv.

Why this file exists at all: on macOS `ps -axo command=` prints every process's argument
list to every user on the machine, and Linux's /proc/<pid>/cmdline is world-readable for
processes of the same user. A message body is the one thing this plugin handles that is
worth reading — a selection from a pane, an invite URL, a paste — so it must not be an
argument. `operator_cli.py dm <peer> <text>` takes it as one, so the plugin hands the CLI
its argv in memory instead of on the command line.

    run_op.py <operator_cli.py> <body-file> <args...>
      -> operator_cli.py <args...> <contents of body-file>

`sys.argv` is rewritten INSIDE this process; the kernel's copy — the one `ps` shows — is
the line above, which names the file and not its contents. bin/common.sh creates that
file with mode 600 and removes it when the call returns.

This is not a wrapper around the CLI's behaviour. The module is executed under the name
`__main__` exactly as `python operator_cli.py …` executes it, so its own argument parser,
its exit codes and its output are the ones you would get without this shim.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import os
import runpy
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stderr.write("usage: run_op.py <operator_cli.py> <body-file> <args...>\n")
        return 2
    op, body_file, rest = argv[1], argv[2], argv[3:]
    try:
        with open(body_file, "rb") as fh:
            body = fh.read().decode("utf-8", "replace")
    except OSError as e:
        sys.stderr.write(f"muretai: cannot read the message body ({e.__class__.__name__})\n")
        return 2
    # `python script.py` puts the script's directory on sys.path; runpy.run_path does
    # not, and operator_cli.py imports the node's own `agent` package.
    node = os.path.dirname(os.path.abspath(op))
    if node not in sys.path:
        sys.path.insert(0, node)
    sys.argv = [op] + rest + [body]
    runpy.run_path(op, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
