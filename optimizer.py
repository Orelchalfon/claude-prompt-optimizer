#!/usr/bin/env python3
"""Rewrite a rough prompt into a sharp, structured one with a cheap Claude model.

Two backends, chosen by PROMPT_OPTIMIZER_BACKEND (default: auto):
  claude  runs the Claude Code CLI (`claude -p`) on your Claude subscription login. No API key.
  api     calls the Anthropic API with ANTHROPIC_API_KEY (pay per use).
  auto    api when ANTHROPIC_API_KEY is set, otherwise claude.

Either way it calls the network. Prints only the optimized prompt on stdout.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_MODEL = "claude-3-5-haiku-latest"
FALLBACK_MODEL = "claude-haiku-5-5"
ENV_MODEL = "PROMPT_OPTIMIZER_MODEL"
ENV_BACKEND = "PROMPT_OPTIMIZER_BACKEND"
BACKENDS = ("auto", "claude", "api")
CLI_DEFAULT_MODEL = "haiku"  # Claude Code's alias for the current small model
# Claude Code tells the model about the folder the rewrite runs in. That is this tool's temp
# folder, not the user's project, and it must not leak into the optimized prompt.
CLI_SYSTEM_SUFFIX = (
    "\n\nYou may be shown details of your own environment: a working directory, platform, date, git status "
    "or available tools. They describe where this rewriting tool runs, not the user's project. Never mention "
    "them, never derive paths, constraints or checks from them, and never refer to yourself or to tools."
)
CLI_TIMEOUT_S = 80  # below the plugin hook's 90 s limit, so a stall ends in a clear error
MAX_INPUT_CHARS = 20000
MAX_TOKENS = 16000  # room for a thinking model's reasoning as well as the prompt
MODES = ("auto", "egm", "code", "agent")

# The prompt text lives in prompt.json, shared with the plugin (hooks/optimize.ts), so the two can't drift.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.json"), encoding="utf-8") as _f:
    _PROMPT = json.load(_f)

EGM_BRAINSTORM = _PROMPT["egmCommands"]["brainstorm"]
EGM_DRAFT = _PROMPT["egmCommands"]["draft"]
EGM_REVIEW = _PROMPT["egmCommands"]["review"]
EGM_COMMANDS = (EGM_BRAINSTORM, EGM_DRAFT, EGM_REVIEW)

SUBAGENT_MARKER = _PROMPT["subagentMarker"]
SUBAGENT_REMINDER_EN = _PROMPT["subagentReminder"]["en"]
SUBAGENT_REMINDER_HE = _PROMPT["subagentReminder"]["he"]
SYSTEM_PROMPT = _PROMPT["system"]
MODE_RULES = _PROMPT["modeRules"]
_BRAINSTORM_WORDS = tuple(_PROMPT["brainstormWords"])
_REVIEW_WORDS = tuple(_PROMPT["reviewWords"])
_HEBREW = re.compile(r"[֐-׿]")


def has_hebrew(text):
    return bool(_HEBREW.search(text))


def build_system(mode):
    rule = MODE_RULES[mode]
    return SYSTEM_PROMPT + ("\n\n" + rule if rule else "")


def pick_egm_command(raw):
    """Keyword guess, used only when --mode egm and the model gave no command."""
    low = raw.lower()
    if any(word in low for word in _BRAINSTORM_WORDS):
        return EGM_BRAINSTORM
    if any(word in low for word in _REVIEW_WORDS):
        return EGM_REVIEW
    return EGM_DRAFT


def split_egm_prefix(text):
    """Return (commands, body): the EGM command lines that open the text, and the rest."""
    lines = text.strip().splitlines()
    commands = []
    while lines:
        head = lines[0].strip()
        if not head:
            lines.pop(0)
            continue
        command = next((c for c in EGM_COMMANDS if head == c or head.startswith(c + " ")), None)
        if command is None:
            break
        commands.append(command)
        rest = head[len(command):].strip()
        lines.pop(0)
        if rest:
            lines.insert(0, rest)
            break
    return commands, "\n".join(lines).strip()


def finalize(raw, answer, mode):
    """Make the mode's promises hold whatever the model returned."""
    commands, body = split_egm_prefix(answer)
    if mode == "code":
        command = None
    elif commands:
        command = commands[0]
    elif mode == "egm":
        command = pick_egm_command(raw)
    else:
        command = None
    if mode == "agent" and SUBAGENT_MARKER not in body:
        reminder = SUBAGENT_REMINDER_HE if has_hebrew(raw) else SUBAGENT_REMINDER_EN
        body = body + "\n\n" + reminder
    return (command + "\n\n" + body) if command else body


def resolve_model(model_arg, env):
    """Return (model, is_default). Only a default model gets the fallback."""
    if model_arg:
        return model_arg, False
    if env.get(ENV_MODEL):
        return env[ENV_MODEL], False
    return DEFAULT_MODEL, True


def make_client():
    try:
        import anthropic  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise OptimizeError(
            "the API backend needs the `anthropic` package; "
            "install it with `pip install anthropic` or use the `claude` backend"
        ) from exc

    return anthropic.Anthropic()


def is_not_found(exc):
    return exc.__class__.__name__ == "NotFoundError" or getattr(exc, "status_code", None) == 404


def ask(client, model, system, text, max_tokens):
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": text}],
    )
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        raise RuntimeError("the model declined to rewrite this prompt")
    if stop_reason == "max_tokens":
        raise RuntimeError("the answer was cut off at max_tokens; not using a truncated prompt")
    parts = [block.text for block in message.content if getattr(block, "type", "text") == "text"]
    return "".join(parts)


class OptimizeError(Exception):
    """A failure with a message fit to show the user."""


def resolve_backend(backend_arg, env):
    """Return "claude" or "api"."""
    backend = backend_arg or env.get(ENV_BACKEND) or "auto"
    if backend not in BACKENDS:
        raise OptimizeError("unknown backend %r (choose from %s)" % (backend, ", ".join(BACKENDS)))
    if backend == "auto":
        return "api" if env.get("ANTHROPIC_API_KEY") else "claude"
    return backend


def ask_claude_cli(model, system, text, env, runner=None, which=None):
    """Rewrite through the Claude Code CLI, headless, on the user's own Claude login."""
    exe = (which or shutil.which)("claude")
    if not exe:
        raise OptimizeError("the Claude Code CLI (`claude`) is not on PATH; install it or set ANTHROPIC_API_KEY")
    argv = [
        exe, "-p",
        "--model", model,
        "--system-prompt", system + CLI_SYSTEM_SUFFIX,
        "--tools", "",  # a rewrite needs no tools
        "--no-session-persistence",  # keep these one-off calls out of the session list
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--setting-sources", "",  # no hooks, plugins or project settings in the child
        "--output-format", "text",
    ]  # fmt: skip
    # The child must not load this mod again, and must use the login, not a stray key.
    child_env = {k: v for k, v in env.items() if k not in ("CLAUDE_CODE_PLUGIN_DIRS", "ANTHROPIC_API_KEY")}
    try:
        done = (runner or subprocess.run)(
            argv,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=CLI_TIMEOUT_S,
            cwd=tempfile.gettempdir(),  # no project CLAUDE.md in the child's context
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise OptimizeError("Claude Code did not answer within %d seconds" % CLI_TIMEOUT_S) from exc
    except OSError as exc:
        raise OptimizeError("could not run Claude Code: %s" % exc) from exc
    out = done.stdout.decode("utf-8", errors="replace").strip()
    if done.returncode != 0:
        detail = (done.stderr.decode("utf-8", errors="replace").strip() or out).splitlines()
        raise OptimizeError("Claude Code failed: %s" % (detail[-1] if detail else "exit %d" % done.returncode))
    return out


def optimize(
    raw, mode="auto", model_arg=None, env=None, client_factory=None, log=None, backend=None, runner=None, which=None
):
    """Return the optimized prompt. Raises OptimizeError on bad input or a backend failure."""
    env = os.environ if env is None else env
    client_factory = client_factory or make_client
    if mode not in MODES:
        raise OptimizeError("unknown mode %r (choose from %s)" % (mode, ", ".join(MODES)))
    if not raw.strip():
        raise OptimizeError("the prompt is empty")
    if len(raw) > MAX_INPUT_CHARS:
        raise OptimizeError("the prompt is longer than %d characters" % MAX_INPUT_CHARS)
    system = build_system(mode)
    if resolve_backend(backend, env) == "claude":
        answer = ask_claude_cli(model_arg or env.get(ENV_MODEL) or CLI_DEFAULT_MODEL, system, raw, env, runner, which)
        if not answer.strip():
            raise OptimizeError("Claude Code returned no text")
        return finalize(raw, answer, mode)
    model, is_default = resolve_model(model_arg, env)
    try:
        client = client_factory()
        try:
            answer = ask(client, model, system, raw, MAX_TOKENS)
        except Exception as exc:
            if not (is_default and is_not_found(exc)):
                raise
            if log:
                log("note: model %s not found, retrying with %s" % (model, FALLBACK_MODEL))
            answer = ask(client, FALLBACK_MODEL, system, raw, MAX_TOKENS)
    except Exception as exc:
        if "authentication method" in str(exc):
            raise OptimizeError("no Anthropic credentials found; set ANTHROPIC_API_KEY") from exc
        raise OptimizeError("%s: %s" % (exc.__class__.__name__, exc)) from exc
    if not answer.strip():
        raise OptimizeError("the model returned no text")
    return finalize(raw, answer, mode)


def clipboard_command(platform=None):
    """Return (argv, encoding) for this platform's clipboard tool, or None."""
    import shutil

    platform = platform or sys.platform
    if platform.startswith("win"):
        return ["clip.exe"], "utf-16"  # clip.exe reads UTF-16 with a BOM; UTF-8 breaks Hebrew
    if platform == "darwin":
        return ["pbcopy"], "utf-8"
    for argv in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(argv[0]):
            return argv, "utf-8"
    return None


def copy_to_clipboard(text, runner=None, platform=None):
    """Copy text to the system clipboard. Returns True on success."""
    found = clipboard_command(platform)
    if found is None:
        return False
    argv, encoding = found
    runner = runner or subprocess.run
    try:
        runner(argv, input=text.encode(encoding), check=True, timeout=10)
    except Exception:
        return False
    return True


def read_stdin(stream):
    """Read the prompt from a pipe as UTF-8, whatever the console code page is."""
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", errors="replace").lstrip("﻿")
    return stream.read()


def utf8_streams():
    for stream in (sys.stdout, sys.stderr):  # Hebrew-safe output in a pipe on Windows
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv=None, env=None, client_factory=None, stdin=None, clip=None, runner=None, which=None):
    utf8_streams()
    parser = argparse.ArgumentParser(description="Rewrite a rough prompt into a sharp, structured one.")
    parser.add_argument("text", nargs="?", help="the raw prompt (or use --prompt, or standard input)")
    parser.add_argument("--prompt", help="the raw prompt")
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument(
        "--model",
        help="model (default: $%s, then %s on the claude backend, %s on the api backend)"
        % (ENV_MODEL, CLI_DEFAULT_MODEL, DEFAULT_MODEL),
    )
    parser.add_argument("--backend", choices=BACKENDS, help="default: $%s, then auto" % ENV_BACKEND)
    parser.add_argument("--clip", action="store_true", help="also copy the result to the clipboard")
    args = parser.parse_args(argv)

    if args.prompt is not None and args.text is not None:
        print("error: give the prompt once: as an argument or with --prompt", file=sys.stderr)
        return 2
    raw = args.prompt if args.prompt is not None else args.text
    if raw is None:
        stream = stdin if stdin is not None else sys.stdin
        if stream.isatty():
            print("error: give the prompt as an argument, with --prompt, or on standard input", file=sys.stderr)
            return 2
        raw = read_stdin(stream)

    try:
        result = optimize(
            raw,
            mode=args.mode,
            model_arg=args.model,
            env=env,
            client_factory=client_factory,
            log=lambda line: print(line, file=sys.stderr),
            backend=args.backend,
            runner=runner,
            which=which,
        )
    except OptimizeError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print(result)
    if args.clip:
        if (clip or copy_to_clipboard)(result):
            print("copied to clipboard", file=sys.stderr)
        else:
            print("warning: could not copy to the clipboard", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
