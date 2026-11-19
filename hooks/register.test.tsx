import { expect, test } from "claude-code/testing";
import type { RenderSurface } from "claude-code";

// The shape of prompt.json (a hooks module can't import JSON; the Python tests load the real file).
const PROMPT = {
  system: "You rewrite a developer's rough prompt.",
  clarify: "You check a developer's rough prompt.",
  modeRules: { auto: "", egm: "Mode egm.", code: "Mode code.", agent: "Mode agent." },
  egmCommands: {
    brainstorm: "/egm:egm-brainstorm",
    draft: "/egm:egm-draft",
    review: "/egm:egm-review",
  },
  subagentMarker: "run_subagent.py",
  subagentReminder: { en: "Run run_subagent.py.", he: "להריץ run_subagent.py." },
  brainstormWords: ["brainstorm"],
  reviewWords: ["review"],
};

const BAND = {
  plugin: "prompt-optimizer",
  component: "AbovePrompt",
  props: {
    hasSurvey: false,
    isCollapsed: false,
    isWorking: false,
    maxRows: 4,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 4 },
    view: {},
  },
} as const;

const TYPED = { wait: false, origin: { kind: "composer" } } as const;
const USAGE = {
  input_tokens: 1,
  output_tokens: 1,
  cache_read_input_tokens: 0,
  cache_creation_input_tokens: 0,
};

type On = Parameters<Parameters<typeof test>[1]>[1];

const VAGUE = {
  questions: [
    { question: "What should improve?", header: "Focus", options: ["Speed", "Readability"] },
  ],
};

// The rewrite answers `optimized: <prompt>` and is recorded; the clarify check
// answers `clarify` (no questions by default) and is not. `surfaces` are drawn.
function fakeModel(
  on: On,
  clarify: object = { questions: [] },
  surfaces: RenderSurface[] = ["terminal"],
) {
  const calls: { model: string; prompt: string; system: string }[] = [];
  on("fs.read", (_, e) =>
    /[\\/]prompt\.json$/.test(e.path)
      ? { value: JSON.stringify(PROMPT) }
      : { deny: `unexpected read of ${e.path}` },
  );
  on("session.surfaces", () => ({ value: surfaces }));
  on("model.complete", (_, e) => {
    if (e.system === PROMPT.clarify) {
      return {
        value: { isAnswered: true, text: JSON.stringify(clarify), usage: USAGE },
      };
    }

    calls.push({ model: e.model, prompt: e.prompt, system: String(e.system ?? "") });

    return {
      value: { isAnswered: true, text: `optimized: ${e.prompt}`, usage: USAGE },
    };
  });
  on("ui.status", () => ({ value: undefined }));
  on("ui.toast", () => ({ value: undefined }));

  return calls;
}

test("a prompt ending in --opt enters rewritten, with no Python", async ($, on) => {
  const calls = fakeModel(on);
  on("process.run", () => ({ deny: "no process may run" }));
  on("prompt.submit", (_, e) => ({ text: e.text }));

  // The desktop app and VS Code arrive as `sdk`, the terminal as `composer`.
  const fromApp = await $.prompt.submit({
    wait: false,
    origin: { kind: "sdk" },
    text: "fix the login bug --opt",
  });
  const entered = await $.prompt.submit({
    ...TYPED,
    text: "~opt fix the login bug",
  });

  expect(fromApp.text).toBe("optimized: fix the login bug");
  expect(entered.text).toBe("optimized: fix the login bug");
  expect(calls[0]?.model).toBe("haiku");
  expect(calls[0]?.system).toContain("You rewrite a developer's rough prompt");
});

test("--opt=egm puts an EGM command first even when the model gives none", async ($, on) => {
  fakeModel(on);
  on("prompt.submit", (_, e) => ({ text: e.text }));

  const entered = await $.prompt.submit({
    ...TYPED,
    text: "review the payment code --opt=egm",
  });

  expect(entered.text).toBe(
    "/egm:egm-review\n\noptimized: review the payment code",
  );
});

test("a prompt with no trigger calls no model and enters as typed", async ($, on) => {
  const calls = fakeModel(on);
  on("prompt.submit", (_, e) => ({ text: e.text }));

  for (const text of ["fix the login bug", "run with --optimize", "!opt x"]) {
    expect((await $.prompt.submit({ ...TYPED, text })).text).toBe(text);
  }

  expect(calls.length).toBe(0);
});

test("a failing model lets the prompt through without the trigger", async ($, on) => {
  on("ui.status", () => ({ value: undefined }));
  on("ui.toast", () => ({ value: undefined }));
  on("model.complete", () => ({
    value: {
      isAnswered: false,
      reason: "api-error",
      status: 529,
      error: "overloaded",
      usage: USAGE,
    },
  }));
  on("prompt.submit", (_, e) => ({ text: e.text }));

  const entered = await $.prompt.submit({ ...TYPED, text: "~opt fix it" });

  expect(entered.text).toBe("fix it");
});

test("/prompt-optimizer:opt gets the optimized prompt as its arguments", async ($, on) => {
  fakeModel(on);
  const seen: string[] = [];
  on("command.run", (_, e) => {
    seen.push(`${e.command}|${e.args}`);

    return { text: "" };
  });

  await $.command.run({ command: "prompt-optimizer:opt", args: "add a logout button" });
  await $.command.run({ command: "help", args: "" });

  expect(seen).toEqual([
    "prompt-optimizer:opt|<!-- optimized -->\noptimized: add a logout button",
    "help|",
  ]);
});

test("the Optimize button replaces the draft with the optimized prompt", async ($, on) => {
  fakeModel(on);
  const fills: string[] = [];
  on("prompt.read", () => ({ value: { text: "fix login", cursor: 9 } }));
  on("prompt.fill", (_, e) => {
    fills.push(`${e.mode ?? "replace"}:${e.text}`);

    return { isFilled: true, text: e.text, cursor: e.text.length };
  });

  for (const surface of ["terminal", "desktop", "vscode"] as const) {
    const ui = await $.ui.mount({ ...BAND, surface });
    const button = await ui.find({ type: "Button", key: "optimize" });

    expect(button?.props.label).toBe("✨Prompt Optimize");
    await ui.press({ key: "optimize" });
    await ui.unmount();
  }

  expect(fills).toEqual([
    "replace:optimized: fix login",
    "replace:optimized: fix login",
    "replace:optimized: fix login",
  ]);
});

test("a vague prompt asks checkbox questions first and optimizes with the answers", async ($, on) => {
  const calls = fakeModel(on, VAGUE);
  const asked: unknown[] = [];
  on("tool.call", { tool: "AskUserQuestion" }, (_, e) => {
    asked.push(e.questions);

    return {
      result: {
        questions: e.questions,
        answers: { "What should improve?": "Speed,Readability" },
      },
    };
  });
  on("prompt.submit", (_, e) => ({ text: e.text }));

  const entered = await $.prompt.submit({ ...TYPED, text: "make it better --opt" });

  expect(asked).toEqual([
    [expect.objectContaining({ question: "What should improve?", multiSelect: true })],
  ]);
  expect(calls[0]?.prompt).toBe(
    "make it better\n\nClarifications from the user:\n- What should improve? Speed,Readability",
  );
  expect(entered.text).toBe(`optimized: ${calls[0]?.prompt}`);
});

test("a clear prompt is optimized without any question", async ($, on) => {
  fakeModel(on);
  let isAsked = false;
  on("tool.call", { tool: "AskUserQuestion" }, () => {
    isAsked = true;

    return { deny: "should not ask" };
  });
  on("prompt.submit", (_, e) => ({ text: e.text }));

  const entered = await $.prompt.submit({
    ...TYPED,
    text: "add a retry to fetchJson in src/api.ts --opt",
  });

  expect(isAsked).toBe(false);
  expect(entered.text).toBe("optimized: add a retry to fetchJson in src/api.ts");
});

test("dismissing the questions optimizes nothing", async ($, on) => {
  const calls = fakeModel(on, VAGUE);
  on("tool.call", { tool: "AskUserQuestion" }, () => ({ deny: "dismissed" }));
  on("prompt.submit", (_, e) => ({ text: e.text }));
  const seen: string[] = [];
  on("command.run", (_, e) => {
    seen.push(e.args);

    return { text: "" };
  });
  const fills: string[] = [];
  on("prompt.read", () => ({ value: { text: "make it better", cursor: 14 } }));
  on("prompt.fill", (_, e) => {
    fills.push(e.text);

    return { isFilled: true, text: e.text, cursor: e.text.length };
  });

  const entered = await $.prompt.submit({ ...TYPED, text: "make it better --opt" });
  await $.command.run({ command: "prompt-optimizer:opt", args: "make it better" });
  const ui = await $.ui.mount({ ...BAND, surface: "desktop" });
  await ui.press({ key: "optimize" });
  await ui.unmount();

  expect(entered.text).toBe("make it better");
  // opt.md skips its Python step and carries out the prompt as typed.
  expect(seen).toEqual(["<!-- optimized -->\nmake it better"]);
  expect(fills).toEqual([]);
  expect(calls.length).toBe(0);
});

test("a headless run with no surface skips the questions", async ($, on) => {
  const calls = fakeModel(on, VAGUE, []);
  on("prompt.submit", (_, e) => ({ text: e.text }));

  const entered = await $.prompt.submit({ ...TYPED, text: "make it better --opt" });

  expect(entered.text).toBe("optimized: make it better");
  expect(calls.length).toBe(1);
});
