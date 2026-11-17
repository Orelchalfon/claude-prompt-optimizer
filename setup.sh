#!/usr/bin/env bash
# Install the /opt slash command: write commands/opt.md, with this mod's path filled in,
# into a .claude/commands folder.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: setup.sh [--target DIR] [--force] [--remove]

Writes opt.md into DIR so that /opt works in Claude Code.

  --target DIR  A commands folder. Default: ./.claude/commands (the project you run this from).
                Use ~/.claude/commands to get /opt in every project.
  --force       Overwrite an opt.md that this script did not write.
  --remove      Delete the opt.md this script wrote, and nothing else.
  -h, --help    Show this help.

The file is a copy, not a symlink: it holds this mod's absolute path. Run setup.sh again
if you move the mod.
USAGE
}

target="./.claude/commands" force=0 remove=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --force) force=1 ;;
    --remove) remove=1 ;;
    --target)
      [ $# -ge 2 ] || { echo "error: --target needs a value" >&2; exit 2; }
      target="$2"; shift ;;
    *) echo "error: unknown argument $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

marker="<!-- installed by prompt-optimizer/setup.sh -->"
dest="${target}/opt.md"

if [ "$remove" -eq 1 ]; then
  [ -f "$dest" ] || { echo "nothing to remove: $dest"; exit 0; }
  grep -qF "$marker" "$dest" || { echo "error: $dest was not written by this script; not touching it" >&2; exit 1; }
  rm "$dest"
  echo "removed: $dest"
  exit 0
fi

# Git Bash on Windows: the command file needs a native path (C:/...), not /c/...
mod_dir="$here"
if (cd "$here" && pwd -W >/dev/null 2>&1); then mod_dir="$(cd "$here" && pwd -W)"; fi

if [ -e "$dest" ] && [ "$force" -eq 0 ] && ! grep -qF "$marker" "$dest"; then
  echo "error: $dest exists and was not written by this script. Use --force to overwrite it." >&2
  exit 1
fi

mkdir -p "$target"
esc="$(printf '%s' "$mod_dir" | sed -e 's/[\\&|]/\\&/g')"
{
  sed -e "s|\${CLAUDE_PLUGIN_ROOT}|${esc}|g" "${here}/commands/opt.md"
  printf '\n%s\n' "$marker"
} > "$dest"
echo "installed: $dest (runs ${mod_dir}/optimize.sh)"
echo "Restart Claude Code, or start a new session, then type: /opt <raw prompt>"
