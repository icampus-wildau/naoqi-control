#!/bin/bash
set -euo pipefail

sudo chown -R vscode:vscode /opt/venv
if [[ ! -x /opt/venv/bin/python ]]; then
  find /opt/venv -mindepth 1 -delete
  uv venv /opt/venv
fi
uv sync --locked --compile-bytecode
