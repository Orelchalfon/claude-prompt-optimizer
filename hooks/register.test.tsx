import { expect, test } from "claude-code/testing";

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

test("a prompt ending in --opt enters rewritten", async ($, on) => {
  on("ui.status", () => ({ value: undefined }));
  on("ui.toast", () => ({ value: undefined }));
  const runs: { argv: readonly string[]; stdin?: string }[] = [];
  on("process.run", (_, e) => {
    runs.push({ argv: e.argv, stdin: e.init?.stdin });

    return {
      value: {
        exitCode: 0,
        stdout: JSON.stringify({
          triggered: true,
          optimized: true,
          text: "**Goal**\nFix the login bug.",
          error: null,
        }),
        stderr: "",
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    };
  });
  on("prompt.submit", (_, e) => ({ text: e.text }));

  // The desktop app and VS Code arrive as `sdk`, the terminal as `composer`.
  const fromApp = await $.prompt.submit({
    wait: false,
    origin: { kind: "sdk" },
    text: "fix the login bug --opt",
  });
  const entered = await $.prompt.submit({
    ...TYPED,
    text: "fix the login bug --opt",
  });

  expect(fromApp.text).toBe(entered.text);
  expect(entered.text).toBe("**Goal**\nFix the login bug.");
  expect(runs[0]?.argv.slice(1)).toEqual(["hooks/hook_runner.py", "--json"]);
  expect(runs[0]?.stdin).toBe("fix the login bug --opt");
});

test("a prompt with no trigger runs nothing and enters as typed", async ($, on) => {
  on("ui.status", () => ({ value: undefined }));
  on("ui.toast", () => ({ value: undefined }));
  let ran = 0;
  on("process.run", () => {
    ran += 1;

    return { deny: "not expected" };
  });
  on("prompt.submit", (_, e) => ({ text: e.text }));

  for (const text of ["fix the login bug", "run with --optimize", "!opt x"]) {
    expect((await $.prompt.submit({ ...TYPED, text })).text).toBe(text);
  }

  expect(ran).toBe(0);
});

test("a failing optimizer lets the prompt through as typed", async ($, on) => {
  on("ui.status", () => ({ value: undefined }));
  on("ui.toast", () => ({ value: undefined }));
  on("process.run", () => ({ deny: "python is missing" }));
  on("prompt.submit", (_, e) => ({ text: e.text }));

  const entered = await $.prompt.submit({ ...TYPED, text: "~opt fix it" });

  expect(entered.text).toBe("~opt fix it");
});

test("the Optimize button replaces the draft with the optimized prompt", async ($, on) => {
  on("ui.status", () => ({ value: undefined }));
  on("ui.toast", () => ({ value: undefined }));
  const fills: string[] = [];
  on("prompt.read", () => ({ value: { text: "fix login", cursor: 9 } }));
  on("process.run", (_, e) => ({
    value: {
      exitCode: 0,
      stdout: `optimized: ${e.init?.stdin}\n`,
      stderr: "",
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
  }));
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
