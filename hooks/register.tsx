import type { EngineInterface, Register } from "claude-code";
import { Cancelled, optimize, parseTrigger } from "./optimize";

// Same triggers as hooks/hook_runner.py. Never `!`: Claude Code reads a
// leading `!` as Bash mode.
const TRIGGER = /^\s*~opt(\s|$)|(^|\s)--opt(=(auto|egm|code|agent))?\s*$/;
const USER_ORIGINS = new Set<string>(["composer", "sdk", "bridge"]);
// commands/opt.md skips its Python step when the arguments open with this.
const OPTIMIZED_MARK = "<!-- optimized -->";
// The plugin's `/prompt-optimizer:opt`, and `/opt` that setup.sh installs from the same file.
const OPT_COMMANDS = new Set<string>(["prompt-optimizer:opt", "opt"]);

let isBusy = false;

function reason(error: unknown): string {
  return (error instanceof Error ? error.message : String(error)).slice(0, 120);
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
    const optimized = await optimize($, text);
    const filled = await $.prompt.fill({ text: optimized, mode: "replace" });

    $.ui.toast(
      filled.isFilled
        ? "✨ Prompt optimized: review it, then send"
        : `Could not replace the draft (${filled.refusal ?? "refused"})`,
    );
  } catch (error) {
    $.ui.toast(`Prompt not optimized: ${reason(error)}`);
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

    const trigger = parseTrigger(e.text);

    if (!trigger.triggered) {
      return next(e);
    }

    $.ui.status("✨ Optimizing prompt…");

    try {
      const optimized = await optimize($, trigger.text, trigger.mode);
      $.ui.toast("✨ Prompt optimized");

      return next({ ...e, text: optimized });
    } catch (error) {
      // Not optimized: the prompt goes on without the trigger, as before.
      $.ui.toast(`Prompt not optimized (${reason(error)}); sent as typed`);

      return next({ ...e, text: trigger.text });
    } finally {
      $.ui.status(undefined);
    }
  }).catch(($, e, next) => {
    // A broken optimizer never blocks a prompt: it goes on as typed.
    $.ui.toast("Prompt optimizer could not run; sent exactly as typed");

    return next(e);
  });

  // `/prompt-optimizer:opt <prompt>`: optimize here, so commands/opt.md needs no Python.
  // On any failure the arguments pass on unchanged and opt.md runs optimize.sh.
  on("command.run", async ($, e, next) => {
    if (!OPT_COMMANDS.has(e.command) || !e.args.trim()) {
      return next(e);
    }

    $.ui.status("✨ Optimizing prompt…");

    try {
      const optimized = await optimize($, e.args);

      return next({ ...e, args: `${OPTIMIZED_MARK}\n${optimized}` });
    } catch (error) {
      // Dismissed questions: carry out the prompt as typed, never via optimize.sh, which can't ask.
      return next(
        error instanceof Cancelled
          ? { ...e, args: `${OPTIMIZED_MARK}\n${e.args}` }
          : e,
      );
    } finally {
      $.ui.status(undefined);
    }
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
