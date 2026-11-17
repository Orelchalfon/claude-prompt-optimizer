# prompt-optimizer

Rewrites a rough prompt into a sharp one before an agent acts on it. A small, fast Claude model
(Haiku by default) restructures the prompt into **Goal**,
**Target Files/Scope**, **Technical Constraints** and **Verification**, keeps its language
(Hebrew stays Hebrew, English stays English), and adds an EGM workflow command or a
subagent reminder when the prompt calls for one.

Four ways to use it:

| Way | Where | What happens |
| --- | --- | --- |
| `/opt <raw prompt>` | Claude Code, any surface | Optimizes the prompt, shows it, then carries it out. |
| `✨ Optimize` button | Claude Code, in the band above the prompt box | Replaces the draft in the prompt box with the optimized version, for you to review and send. |
| `<prompt> --opt` or `~opt <prompt>` | Claude Code, any surface | Strips the trigger, optimizes the prompt, and sends the optimized version to the agent. |
| `optimize.sh` / `optimize.ps1` / `python optimizer.py` | Any terminal (`agy`, `codex`, ...) | Prints the optimized prompt; `--clip` also copies it. |

`!` is never a trigger: Claude Code reads a leading `!` as Bash mode.

## What it touches

- **Network:** every optimization is one model call, through Claude Code or the Anthropic API (see Backends).
- **Processes:** the Claude Code hooks run this mod's `python` (`optimizer.py`, `hooks/hook_runner.py`).
  On the `claude` backend, `optimizer.py` runs the Claude Code CLI (`claude -p`) with no tools.
  `--clip` runs the system clipboard tool (`clip.exe`, `pbcopy`, `wl-copy`, `xclip` or `xsel`).
- **Files:** none, except `setup.sh`, which writes one file, `opt.md`, into the commands folder you name
  (default `./.claude/commands`).
- It reads no `.env` file.

## Install from the marketplace

In Claude Code (terminal or desktop app), run:

```
/plugin marketplace add Orelchalfon/claude-prompt-optimizer
/plugin install prompt-optimizer@orelchalfon
```

Then restart Claude Code. You get the `✨Prompt Optimize` button above the prompt box, the `--opt` / `~opt`
triggers and `/prompt-optimizer:opt`. The button works in the desktop app.

Needs: Python 3 on PATH (`python` or `python3`) and the Claude Code CLI (`claude`) on PATH and logged in.
No API key and no `pip install`: the default backend uses only the Python standard library.
Update later with `/plugin marketplace update orelchalfon`.

## Install from source

Dependencies are in `requirements.txt`: `anthropic` (only for the `api` backend), `pytest` and `ruff` (development).

```bash
git clone https://github.com/Orelchalfon/claude-prompt-optimizer
cd claude-prompt-optimizer
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Unix: .venv/bin/pip
```

### Backends: no API key needed

| Backend | How it calls the model | Cost | Needs |
| --- | --- | --- | --- |
| `claude` | Runs the Claude Code CLI headless (`claude -p --model haiku`, no tools) | Counts against your Claude subscription (Pro, Max) usage | `claude` on PATH and logged in |
| `api` | Calls the Anthropic API with the `anthropic` SDK | Pay per use | `ANTHROPIC_API_KEY` |

The default, `auto`, uses `api` when `ANTHROPIC_API_KEY` is set and `claude` otherwise. With a Claude
subscription and no API key there is nothing to configure. A rewrite takes about 5 to 10 seconds on the
`claude` backend.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROMPT_OPTIMIZER_BACKEND` | `auto` | `auto`, `claude` or `api`. Also `--backend` on the command line. |
| `PROMPT_OPTIMIZER_MODEL` | `haiku` (`claude`), `claude-3-5-haiku-latest` (`api`) | Model that rewrites the prompt. |
| `ANTHROPIC_API_KEY` | none | Only for the `api` backend. |

On the `claude` backend the child Claude Code process runs in the temp folder with your settings,
hooks, plugins and slash commands turned off, and the one-off call is not saved as a session.
On the `api` backend, if the default model no longer exists, the optimizer retries once with
`claude-haiku-5-5`. A model you chose yourself is never swapped.

### 1. The `/opt` command

```bash
cd <your project>
bash <path to>/claude-prompt-optimizer/setup.sh                              # this project only
bash <path to>/claude-prompt-optimizer/setup.sh --target ~/.claude/commands   # every project
```

`setup.sh` writes `opt.md` with this mod's absolute path filled in (a copy, not a symlink, so it works
on Windows without Developer Mode). Run it again if you move the mod; `--remove` deletes the file it
wrote. Start a new Claude Code session, then type `/opt add google login to the sign-in screen`.

### 2. The button and the `--opt` / `~opt` triggers

These come from the mod's hooks module (`hooks/register.tsx`), which Claude Code loads as a plugin:

```bash
claude --plugin-dir <path to>/claude-prompt-optimizer
```

For the desktop app and VS Code, which take no flag, name the folder in `~/.claude/settings.json`:

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "C:/Users/you/.../claude-prompt-optimizer" } }
```

- **Button.** Claude Code has no plugin slot inside the composer's action bar, so `✨ Optimize` sits in
  the band directly above the prompt box, not next to `+`, and plugin buttons take a text label only
  (no `sparkles` icon setting; the ✨ is part of the label). The button needs the surface to share its
  draft with plugins. The terminal does. The plugin API says a surface that draws its own prompt box
  may not; there the button reports "No draft to optimize", and the `--opt` trigger is the way to go.
  **Not yet tried in the desktop app or VS Code.**
- **Triggers.** `fix the login bug --opt` or `~opt fix the login bug`. The message in the transcript
  becomes the optimized prompt, which is how you see the upgrade, and a toast confirms it.
  (`hook_runner.py` also writes the optimized prompt to stderr, but the plugin host does not display
  a child process's stderr; it shows when you run the script yourself or as a settings hook.)
  `--opt=egm`, `--opt=code` and `--opt=agent` pick a mode.
- If the optimizer fails (not logged in, no network), the prompt goes to the agent as you typed it, minus the
  trigger, and a toast says why. If Python itself cannot start, it goes exactly as typed, trigger
  included. A prompt is never blocked.
- When the optimized prompt opens with an EGM command, a rewritten prompt does not run as a slash
  command; the agent reads the command line as an instruction to use that skill. `/opt` handles this
  the same way.

With the plugin loaded, `commands/opt.md` should also appear as `/prompt-optimizer:opt` (not yet
tried; `setup.sh` is the tested route to `/opt`).

**Settings-hook alternative.** If you do not want to load the plugin, `hooks/hook_runner.py` also speaks
the classic `UserPromptSubmit` protocol. A settings hook cannot replace a prompt, so the optimized
prompt is attached as context that the agent is told to follow. Use one or the other, not both:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "timeout": 60,
        "command": "\"<mod>/.venv/Scripts/python.exe\" \"<mod>/hooks/hook_runner.py\"" }] }
    ]
  }
}
```

### 3. Terminal use (`agy`, `codex`, anything)

```bash
./optimize.sh "add google login to the sign-in screen"            # Git Bash, macOS, Linux
./optimize.sh --mode egm --clip "design a billing service"
echo "תוסיף כפתור התחברות עם גוגל" | ./optimize.sh
```

```powershell
.\optimize.ps1 "add google login to the sign-in screen" --clip
.venv\Scripts\python optimizer.py --prompt "raw prompt" --mode code
```

`optimize.ps1` waits for standard input to close when a launcher leaves it open (PowerShell does this
for any `-File` script). From such a launcher use `optimize.sh`, call `python optimizer.py` directly,
or redirect stdin.

The optimized prompt is the only thing on stdout; notes and errors go to stderr. Exit code is 0 on
success, 1 on a failure, 2 on wrong usage.

## Modes

| `--mode` | Behavior |
| --- | --- |
| `auto` (default) | The model decides whether an EGM command or the subagent reminder applies. |
| `egm` | The result always opens with exactly one of `/egm:egm-brainstorm`, `/egm:egm-draft`, `/egm:egm-review`. |
| `code` | Implementation spec; never opens with an EGM command. |
| `agent` | Multi-agent workspace; always ends with the reminder to run the `copywriter` and `qa` subagents via `run_subagent.py`. |

In `auto`, the rules the model follows are: brainstorm or explore ideas → `/egm:egm-brainstorm`;
design or architect a complex new system → `/egm:egm-draft`; audit or check existing code or designs →
`/egm:egm-review`; UI or marketing text, or implementation in a multi-agent workspace → the subagent reminder.

## Files

| File | Purpose |
| --- | --- |
| `optimizer.py` | The engine and command line. |
| `hooks/hook_runner.py` | Finds the `--opt` / `~opt` trigger and rewrites the prompt. |
| `hooks/register.tsx`, `hooks/hooks.json`, `.claude-plugin/plugin.json` | Claude Code plugin: the submit hook and the button. |
| `.claude-plugin/marketplace.json` | Makes this repo a marketplace, so `/plugin install` works. |
| `commands/opt.md`, `setup.sh` | The `/opt` command and its installer. |
| `optimize.sh`, `optimize.ps1` | Terminal wrappers: the mod's own `.venv` if there is one, else the system Python. |
| `tests/test_optimizer.py`, `hooks/register.test.tsx` | Tests. |

## Tests

```bash
.venv/Scripts/python -m pytest          # 57 tests, model calls mocked, no network
.venv/Scripts/python -m ruff check .
claude plugin validate .
claude plugin test .                    # 4 tests of the submit hook and the button
```

## License

MIT. See `LICENSE`.
