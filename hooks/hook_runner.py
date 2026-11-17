#!/usr/bin/env python3
"""Find the optimize trigger in a submitted prompt and rewrite the prompt.

Triggers: `--opt` at the end of the prompt, or `~opt ` at its start.
(`!` is never a trigger: Claude Code reads a leading `!` as Bash mode.)

Two ways to run it, both reading standard input:

  hook_runner.py --json   stdin is the raw prompt text. stdout is one JSON object
                          {"triggered", "optimized", "text", "error"}. Used by hooks/register.tsx,
                          which then replaces the prompt with "text".
  hook_runner.py          stdin is Claude Code's UserPromptSubmit hook JSON. stdout is that hook's
                          JSON answer. A settings hook cannot replace the prompt, so the optimized
                          prompt is attached as context the model is told to follow.

Either way the optimized prompt is also printed to stderr. Calls the network (Anthropic API)
only when a trigger is present.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import optimizer  # noqa: E402  (the mod's own engine, one folder up)

PREFIX = re.compile(r"^\s*~opt(?:\s+|$)")
SUFFIX = re.compile(r"(?:^|\s)--opt\s*$")
MODE_SUFFIX = re.compile(r"(?:^|\s)--opt=(auto|egm|code|agent)\s*$")


def parse_trigger(text):
    """Return (triggered, prompt_without_trigger, mode)."""
    mode = "auto"
    triggered = False
    match = MODE_SUFFIX.search(text)
    if match:
        mode = match.group(1)
        text = text[: match.start()]
        triggered = True
    else:
        match = SUFFIX.search(text)
        if match:
            text = text[: match.start()]
            triggered = True
    match = PREFIX.match(text)
    if match:
        text = text[match.end():]
        triggered = True
    return triggered, (text.strip() if triggered else text), mode


def rewrite(text, env=None, client_factory=None, err=None):
    """Return {"triggered", "optimized", "text", "error"} for one submitted prompt."""
    err = err if err is not None else sys.stderr
    triggered, stripped, mode = parse_trigger(text)
    result = {"triggered": triggered, "optimized": False, "text": text, "error": None}
    if not triggered:
        return result
    result["text"] = stripped
    try:
        optimized = optimizer.optimize(
            stripped,
            mode=mode,
            env=env,
            client_factory=client_factory,
            log=lambda line: print(line, file=err),
        )
    except optimizer.OptimizeError as exc:
        result["error"] = str(exc)
        print("prompt-optimizer: not optimized (%s); sending the prompt as typed" % exc, file=err)
        return result
    result["optimized"] = True
    result["text"] = optimized
    print("prompt-optimizer: optimized prompt\n" + "-" * 40 + "\n" + optimized + "\n" + "-" * 40, file=err)
    return result


def classic_answer(result):
    """The UserPromptSubmit settings-hook answer for a rewrite() result, or None to stay silent."""
    if not result["triggered"]:
        return None
    if not result["optimized"]:
        note = "Prompt optimizer: not optimized (%s). The prompt was sent as typed." % result["error"]
        return {"systemMessage": note}
    context = (
        "The user asked for their prompt to be optimized before you act on it. "
        "Treat the optimized prompt below as the request, in place of the text they typed "
        "(ignore the `--opt` / `~opt` marker in it).\n\n" + result["text"]
    )
    return {
        "systemMessage": "Prompt optimized:\n" + result["text"],
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context},
    }


def main(argv=None, env=None, client_factory=None, stdin=None, out=None, err=None):
    optimizer.utf8_streams()
    argv = sys.argv[1:] if argv is None else argv
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    data = optimizer.read_stdin(stdin if stdin is not None else sys.stdin)

    if "--json" in argv:
        json.dump(rewrite(data, env=env, client_factory=client_factory, err=err), out, ensure_ascii=False)
        return 0

    try:
        prompt = json.loads(data).get("prompt", "")
    except (ValueError, AttributeError):
        print("prompt-optimizer: hook input is not the UserPromptSubmit JSON; doing nothing", file=err)
        return 0  # never block a prompt
    if not isinstance(prompt, str):
        return 0
    answer = classic_answer(rewrite(prompt, env=env, client_factory=client_factory, err=err))
    if answer is not None:
        json.dump(answer, out, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
