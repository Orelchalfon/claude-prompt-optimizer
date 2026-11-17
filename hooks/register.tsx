import type { EngineInterface, Register } from "claude-code";

// Same triggers as hooks/hook_runner.py, which stays the one that decides.
// Never `!`: Claude Code reads a leading `!` as Bash mode.
const TRIGGER = /^\s*~opt(\s|$)|(^|\s)--opt(=(auto|egm|code|agent))?\s*$/;
const TIMEOUT_MS = 90_000;
const USER_ORIGINS = new Set<string>(["composer", "sdk", "bridge"]);

type Rewrite = {
  triggered: boolean;
  optimized: boolean;
  text: string;
  error: string | null;
};

let python: string | undefined;
let isBusy = false;

// The mod's own venv first (Windows, then Unix), then the system Python: a
// marketplace install has no venv, and macOS/Linux often have only `python3`.
async function runPython(
  $: EngineInterface,
  args: readonly string[],
  stdin: string,
) {
  const root = $.plugin.root;
  const candidates = python
    ? [python]
    : [
        `${root}/.venv/Scripts/python.exe`,
        `${root}/.venv/bin/python`,
        "python",
        "python3",
      ];
  let failure: unknown;

  for (const candidate of candidates) {
    try {
      const result = await $.process.run([candidate, ...args], {
        cwd: root,
        stdin,
        timeoutMs: TIMEOUT_MS,
        env: { PYTHONIOENCODING: "utf-8" },
      });
      python = candidate;

      return result;
    } catch (error) {
      failure = error;
    }
  }

  throw failure;
}

async function optimizeDraft($: EngineInterface) {
  if (isBusy) {
    return;
  }

  const { text } = await $.prompt.read();

  if (!text.trim()) {
    // Empty also where a surface draws its own prompt box and shares no draft.
    $.ui.toast(
      "No draft to optimize. If you typed one, this app does not share it with plugins: end the prompt with --opt instead",
    );

    return;
  }

  isBusy = true;
  $.ui.status("✨ Optimizing prompt…");

  try {
    const { exitCode, stdout, stderr } = await runPython(
      $,
      ["optimizer.py"],
      text,
    );

    if (exitCode !== 0 || !stdout.trim()) {
      $.ui.toast(`Prompt not optimized: ${lastLine(stderr) || "no output"}`);

      return;
    }

    const filled = await $.prompt.fill({
      text: stdout.trim(),
      mode: "replace",
    });

    $.ui.toast(
      filled.isFilled
        ? "✨ Prompt optimized: review it, then send"
        : `Could not replace the draft (${filled.refusal ?? "refused"})`,
    );
  } catch {
    $.ui.toast("Prompt optimizer could not run Python; see the mod README");
  } finally {
    isBusy = false;
    $.ui.status(undefined);
  }
}

export const register: Register = (on) => {
  on("prompt.submit", async ($, e, next) => {
    // A person's own prompt: the terminal (`composer`), the desktop app and
    // VS Code (`sdk`), or Remote Control (`bridge`). Never a notification,
    // a scheduled prompt, another session's message or a plugin's.
    const isTyped = USER_ORIGINS.has(e.origin.kind) && !e.command && !e.isMeta;

    if (!isTyped || !TRIGGER.test(e.text)) {
      return next(e);
    }

    $.ui.status("✨ Optimizing prompt…");
    let rewrite: Rewrite;

    try {
      const { stdout } = await runPython(
        $,
        ["hooks/hook_runner.py", "--json"],
        e.text,
      );
      rewrite = JSON.parse(stdout) as Rewrite;
    } finally {
      $.ui.status(undefined);
    }

    if (!rewrite.triggered) {
      return next(e);
    }

    $.ui.toast(
      rewrite.optimized
        ? "✨ Prompt optimized"
        : `Prompt not optimized (${rewrite.error ?? "unknown error"}); sent as typed`,
    );

    return next({ ...e, text: rewrite.text });
  }).catch(($, e, next) => {
    // A broken optimizer never blocks a prompt: it goes on as typed.
    $.ui.toast("Prompt optimizer could not run; sent exactly as typed");

    return next(e);
  });

  // The API has no slot inside the composer's action bar (next to `+`), so the
  // button sits in the band directly above the prompt box, on every surface.
  on("ui.render", { component: "AbovePrompt" }, ($, e, next) => {
    if (e.props.hasSurvey) {
      return next(e);
    }

    const { Box, Button } = $.ui.resolve(e);

    return (
      <Box>
        <Button
          key='optimize'
          label='✨Prompt Optimize'
          onPress={() => optimizeDraft($)}
        />
      </Box>
    );
  });
};

function lastLine(text: string): string {
  const lines = text.trim().split("\n");

  return (lines[lines.length - 1] ?? "")
    .replace(/^error:\s*/, "")
    .slice(0, 120);
}
