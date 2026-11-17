import type { EngineInterface } from "claude-code";

// The Python-free engine: the same rules as optimizer.py (finalize, the EGM
// prefix, the agent reminder) and hook_runner.py (the triggers), with the model
// called through the Claude Code session itself. No Python, no API key.

export const MODES = ["auto", "egm", "code", "agent"] as const;
export type Mode = (typeof MODES)[number];

const MODEL = "haiku";
const MAX_INPUT_CHARS = 20000;
const MAX_TOKENS = 16000; // room for a thinking model's reasoning as well as the prompt
const TIMEOUT_MS = 80_000;

type PromptFile = {
  system: string;
  modeRules: Record<Mode, string>;
  egmCommands: { brainstorm: string; draft: string; review: string };
  subagentMarker: string;
  subagentReminder: { en: string; he: string };
  brainstormWords: string[];
  reviewWords: string[];
};

let cached: PromptFile | undefined;

async function loadPrompt($: EngineInterface): Promise<PromptFile> {
  cached ??= JSON.parse(
    await $.fs.read(`${$.plugin.root}/prompt.json`),
  ) as PromptFile;

  return cached;
}

const PREFIX = /^\s*~opt(?:\s+|$)/;
const SUFFIX = /(?:^|\s)--opt\s*$/;
const MODE_SUFFIX = /(?:^|\s)--opt=(auto|egm|code|agent)\s*$/;

/** hook_runner.parse_trigger: whether a trigger is present, the prompt without it, and the mode. */
export function parseTrigger(text: string) {
  let mode: Mode = "auto";
  let triggered = false;
  let rest = text;
  const withMode = MODE_SUFFIX.exec(rest);

  if (withMode) {
    mode = withMode[1] as Mode;
    rest = rest.slice(0, withMode.index);
    triggered = true;
  } else {
    const plain = SUFFIX.exec(rest);

    if (plain) {
      rest = rest.slice(0, plain.index);
      triggered = true;
    }
  }

  const prefix = PREFIX.exec(rest);

  if (prefix) {
    rest = rest.slice(prefix[0].length);
    triggered = true;
  }

  return { triggered, text: triggered ? rest.trim() : text, mode };
}

function splitEgmPrefix(text: string, commands: readonly string[]) {
  const lines = text.trim().split("\n");
  const found: string[] = [];

  while (lines.length > 0) {
    const head = (lines[0] ?? "").trim();

    if (!head) {
      lines.shift();
      continue;
    }

    const command = commands.find(
      (c) => head === c || head.startsWith(`${c} `),
    );

    if (command === undefined) {
      break;
    }

    found.push(command);
    const rest = head.slice(command.length).trim();
    lines.shift();

    if (rest) {
      lines.unshift(rest);
      break;
    }
  }

  return { commands: found, body: lines.join("\n").trim() };
}

/** optimizer.finalize: make the mode's promises hold whatever the model returned. */
export function finalize(
  p: PromptFile,
  raw: string,
  answer: string,
  mode: Mode,
): string {
  const egm = p.egmCommands;
  const { commands, body: parsed } = splitEgmPrefix(answer, [
    egm.brainstorm,
    egm.draft,
    egm.review,
  ]);
  let body = parsed;
  let command: string | undefined;

  if (mode === "code") {
    command = undefined;
  } else if (commands.length > 0) {
    command = commands[0];
  } else if (mode === "egm") {
    const low = raw.toLowerCase();

    command = p.brainstormWords.some((w) => low.includes(w))
      ? egm.brainstorm
      : p.reviewWords.some((w) => low.includes(w))
        ? egm.review
        : egm.draft;
  }

  if (mode === "agent" && !body.includes(p.subagentMarker)) {
    const isHebrew = /[֐-׿]/.test(raw);

    body = `${body}\n\n${isHebrew ? p.subagentReminder.he : p.subagentReminder.en}`;
  }

  return command ? `${command}\n\n${body}` : body;
}

/** Returns the optimized prompt. Throws an Error whose message is fit to show. */
export async function optimize(
  $: EngineInterface,
  raw: string,
  mode: Mode = "auto",
): Promise<string> {
  if (!raw.trim()) {
    throw new Error("the prompt is empty");
  }

  if (raw.length > MAX_INPUT_CHARS) {
    throw new Error(`the prompt is longer than ${MAX_INPUT_CHARS} characters`);
  }

  const p = await loadPrompt($);
  const rule = p.modeRules[mode];
  const reply = await $.model.complete({
    model: MODEL,
    system: rule ? `${p.system}\n\n${rule}` : p.system,
    prompt: raw,
    maxTokens: MAX_TOKENS,
    timeoutMs: TIMEOUT_MS,
  });

  if (!reply.isAnswered) {
    throw new Error(
      reply.reason === "aborted"
        ? `no answer within ${TIMEOUT_MS / 1000} seconds`
        : `the model call failed (${reply.reason})`,
    );
  }

  if (!reply.text.trim()) {
    throw new Error("the model returned no text");
  }

  return finalize(p, raw, reply.text, mode);
}
