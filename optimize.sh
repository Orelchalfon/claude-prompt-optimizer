#!/usr/bin/env bash
# Run the prompt optimizer with the mod's own venv. For any terminal or CLI agent (agy, codex, ...).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: optimize.sh [--mode auto|egm|code|agent] [--model ID] [--backend B] [--clip] ["raw prompt"]
       echo "raw prompt" | optimize.sh [options]

Prints the optimized prompt on stdout. Uses Claude Code on your Claude login, or the
Anthropic API when ANTHROPIC_API_KEY is set.

  --mode MODE   auto (default), egm, code or agent.
  --model ID    Model to use (default: $PROMPT_OPTIMIZER_MODEL, then haiku).
  --backend B   auto (default), claude or api.
  --clip        Also copy the result to the clipboard.
  -h, --help    Show this help.
USAGE
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac

if [ -x "${here}/.venv/Scripts/python.exe" ]; then py="${here}/.venv/Scripts/python.exe"
elif [ -x "${here}/.venv/bin/python" ]; then py="${here}/.venv/bin/python"
# A marketplace install has no venv; the default `claude` backend needs only the standard library.
elif py="$(command -v python3 || command -v python)"; then :
else
  echo "error: no Python found. Install Python 3, or create ${here}/.venv: python -m venv .venv, then pip install -r requirements.txt" >&2
  exit 1
fi

exec "$py" "${here}/optimizer.py" "$@"
