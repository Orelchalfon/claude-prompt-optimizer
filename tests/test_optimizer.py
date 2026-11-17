"""Unit tests for optimizer.py and hooks/hook_runner.py. No network: the Anthropic client is mocked."""
import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MOD)
sys.path.insert(0, os.path.join(MOD, "hooks"))

import hook_runner  # noqa: E402
import optimizer  # noqa: E402

ENV = {"ANTHROPIC_API_KEY": "test-key"}
HEBREW_RAW = "תוסיף כפתור התחברות עם גוגל למסך הלוגין"
HEBREW_OPTIMIZED = "**מטרה**\nלהוסיף כפתור Google Sign-In למסך ההתחברות.\n\n**אימות**\nnpm test עובר."
ENGLISH_OPTIMIZED = "**Goal**\nAdd a retry to the fetch helper.\n\n**Verification**\npytest passes."


class NotFoundError(Exception):
    status_code = 404


class FakeClient:
    """Stands in for anthropic.Anthropic(): records each call and answers from a script."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=answer)], stop_reason="end_turn")


def run_cli(argv, answers, stdin_text=None, env=ENV, clip=None, capsys=None):
    client = FakeClient(answers)
    stdin = None
    if stdin_text is not None:
        stdin = io.TextIOWrapper(io.BytesIO(stdin_text.encode("utf-8")), encoding="cp1252")  # wrong on purpose
    code = optimizer.main(argv, env=env, client_factory=lambda: client, stdin=stdin, clip=clip)
    captured = capsys.readouterr()
    return code, captured.out, captured.err, client


# --- language -------------------------------------------------------------------------------


def test_english_prompt_is_sent_and_the_answer_printed_alone(capsys):
    code, out, _, client = run_cli(["--prompt", "add retry to fetch helper"], [ENGLISH_OPTIMIZED], capsys=capsys)
    assert code == 0
    assert out == ENGLISH_OPTIMIZED + "\n"
    assert client.calls[0]["messages"] == [{"role": "user", "content": "add retry to fetch helper"}]


def test_hebrew_prompt_survives_a_pipe_in_and_out(capsys):
    code, out, _, client = run_cli([], [HEBREW_OPTIMIZED], stdin_text=HEBREW_RAW, capsys=capsys)
    assert code == 0
    assert client.calls[0]["messages"][0]["content"] == HEBREW_RAW  # decoded as UTF-8, not the console code page
    assert out == HEBREW_OPTIMIZED + "\n"


def test_system_prompt_states_the_language_structure_and_output_rules():
    system = optimizer.build_system("auto")
    assert "Hebrew prompt becomes sharp technical Hebrew" in system
    assert "English prompt stays English" in system
    for heading in ("**Goal**", "**Target Files/Scope**", "**Technical Constraints**", "**Verification**"):
        assert heading in system
    assert "Output ONLY the optimized prompt text" in system


def test_positional_prompt_works_like_the_flag(capsys):
    code, out, _, client = run_cli(["add retry"], [ENGLISH_OPTIMIZED], capsys=capsys)
    assert (code, client.calls[0]["messages"][0]["content"]) == (0, "add retry")


# --- EGM and subagent injection -------------------------------------------------------------


def test_system_prompt_maps_each_intent_to_its_egm_command():
    system = optimizer.build_system("auto")
    assert "brainstorm or explore ideas -> /egm:egm-brainstorm" in system
    assert "design or architect a complex new system -> /egm:egm-draft" in system
    assert "audit, review or check existing code or designs -> /egm:egm-review" in system
    assert "`copywriter` and `qa` subagents via `run_subagent.py`" in system


def test_auto_mode_keeps_the_command_the_model_chose():
    answer = "/egm:egm-brainstorm\n\n" + ENGLISH_OPTIMIZED
    assert optimizer.finalize("brainstorm onboarding ideas", answer, "auto") == answer


def test_auto_mode_adds_no_command_of_its_own():
    assert optimizer.finalize("brainstorm ideas", ENGLISH_OPTIMIZED, "auto") == ENGLISH_OPTIMIZED


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("brainstorm ideas for onboarding", "/egm:egm-brainstorm"),
        ("תעשה סיעור מוחות על רעיונות לאונבורדינג", "/egm:egm-brainstorm"),
        ("audit the auth module", "/egm:egm-review"),
        ("תעבור על הקוד ותעשה בדיקה של ההרשאות", "/egm:egm-review"),
        ("architect a new billing system", "/egm:egm-draft"),
    ],
)
def test_egm_mode_always_opens_with_one_command(raw, expected):
    result = optimizer.finalize(raw, ENGLISH_OPTIMIZED, "egm")
    assert result.splitlines()[0] == expected
    assert result.count("/egm:") == 1


def test_a_repeated_command_is_collapsed_to_one():
    answer = "/egm:egm-review\n/egm:egm-review\n\n" + ENGLISH_OPTIMIZED
    assert optimizer.finalize("audit it", answer, "egm") == "/egm:egm-review\n\n" + ENGLISH_OPTIMIZED


def test_a_command_sharing_a_line_with_the_spec_is_split_off():
    result = optimizer.finalize("review it", "/egm:egm-review **Goal** check auth", "auto")
    assert result == "/egm:egm-review\n\n**Goal** check auth"


def test_code_mode_drops_a_command_the_model_added():
    answer = "/egm:egm-draft\n\n" + ENGLISH_OPTIMIZED
    assert optimizer.finalize("implement retry", answer, "code") == ENGLISH_OPTIMIZED


def test_agent_mode_appends_the_subagent_reminder_once():
    result = optimizer.finalize("fix the landing page copy", ENGLISH_OPTIMIZED, "agent")
    assert result.endswith(optimizer.SUBAGENT_REMINDER_EN)
    already = ENGLISH_OPTIMIZED + "\nRun copywriter and qa via run_subagent.py."
    assert optimizer.finalize("fix copy", already, "agent") == already


def test_agent_mode_reminder_follows_a_hebrew_prompt():
    assert optimizer.finalize(HEBREW_RAW, HEBREW_OPTIMIZED, "agent").endswith(optimizer.SUBAGENT_REMINDER_HE)


def test_mode_flag_reaches_the_system_prompt(capsys):
    _, out, _, client = run_cli(["--mode", "egm", "design a queue"], [ENGLISH_OPTIMIZED], capsys=capsys)
    assert "Mode egm" in client.calls[0]["system"]
    assert out.startswith("/egm:egm-draft\n")


# --- model choice and failures --------------------------------------------------------------


def test_default_model_env_override_and_flag(capsys):
    _, _, _, client = run_cli(["x"], ["ok"], capsys=capsys)
    assert client.calls[0]["model"] == "claude-3-5-haiku-latest"
    _, _, _, client = run_cli(["x"], ["ok"], env={**ENV, "PROMPT_OPTIMIZER_MODEL": "m-env"}, capsys=capsys)
    assert client.calls[0]["model"] == "m-env"
    _, _, _, client = run_cli(["x", "--model", "m-flag"], ["ok"], capsys=capsys)
    assert client.calls[0]["model"] == "m-flag"


def test_a_retired_default_model_falls_back(capsys):
    code, out, err, client = run_cli(["x"], [NotFoundError("gone"), "ok"], capsys=capsys)
    assert (code, out) == (0, "ok\n")
    assert [call["model"] for call in client.calls] == ["claude-3-5-haiku-latest", "claude-haiku-5-5"]
    assert "retrying with claude-haiku-5-5" in err


def test_a_chosen_model_that_is_missing_does_not_fall_back(capsys):
    code, out, err, client = run_cli(["x", "--model", "nope"], [NotFoundError("gone")], capsys=capsys)
    assert (code, out, len(client.calls)) == (1, "", 1)
    assert "NotFoundError" in err


def test_a_truncated_answer_is_an_error_not_a_prompt(capsys):
    client = FakeClient([])
    client.messages.create = lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="text", text="half a pro")], stop_reason="max_tokens"
    )
    code = optimizer.main(["x"], env=ENV, client_factory=lambda: client)
    captured = capsys.readouterr()
    assert (code, captured.out) == (1, "")
    assert "cut off" in captured.err


def test_missing_credentials_get_a_plain_message(capsys):
    def no_credentials():
        raise TypeError("Could not resolve authentication method. Expected one of api_key, ...")

    code = optimizer.main(["x"], env={"PROMPT_OPTIMIZER_BACKEND": "api"}, client_factory=no_credentials)
    assert code == 1
    assert capsys.readouterr().err == "error: no Anthropic credentials found; set ANTHROPIC_API_KEY\n"


def test_empty_and_oversized_prompts_are_refused_without_a_call(capsys):
    code, out, err, client = run_cli(["--prompt", "   "], [], capsys=capsys)
    assert (code, out, client.calls) == (1, "", [])
    assert "empty" in err
    code, _, err, client = run_cli(["--prompt", "x" * (optimizer.MAX_INPUT_CHARS + 1)], [], capsys=capsys)
    assert (code, client.calls) == (1, [])


def test_prompt_given_twice_is_a_usage_error(capsys):
    code, _, err, _ = run_cli(["a", "--prompt", "b"], [], capsys=capsys)
    assert code == 2


# --- Claude Code CLI backend (no API key) ------------------------------------------------------


class FakeCli:
    """Stands in for subprocess.run on `claude -p`."""

    def __init__(self, stdout="", returncode=0, stderr="", error=None):
        self.stdout, self.returncode, self.stderr, self.error = stdout, returncode, stderr, error
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(
            stdout=self.stdout.encode("utf-8"), stderr=self.stderr.encode("utf-8"), returncode=self.returncode
        )


def found(name):
    return "C:/bin/claude.exe"


def test_without_an_api_key_the_claude_cli_does_the_rewrite(capsys):
    cli = FakeCli(stdout=HEBREW_OPTIMIZED + "\n")
    env = {"PATH": "x", "CLAUDE_CODE_PLUGIN_DIRS": "C:/mods/prompt-optimizer"}
    code = optimizer.main(["--prompt", HEBREW_RAW], env=env, client_factory=None, runner=cli, which=found)
    assert (code, capsys.readouterr().out) == (0, HEBREW_OPTIMIZED + "\n")
    argv, kwargs = cli.calls[0]
    assert argv[:2] == ["C:/bin/claude.exe", "-p"]
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--system-prompt") + 1] == optimizer.build_system("auto") + optimizer.CLI_SYSTEM_SUFFIX
    assert argv[argv.index("--tools") + 1] == ""
    assert kwargs["input"].decode("utf-8") == HEBREW_RAW  # the prompt goes on stdin, never through a shell
    assert "CLAUDE_CODE_PLUGIN_DIRS" not in kwargs["env"]  # the child must not load this mod again
    assert kwargs["env"]["PATH"] == "x"


def test_an_api_key_selects_the_api_and_the_backend_can_be_forced(capsys):
    cli = FakeCli(stdout="from cli")
    client = FakeClient(["from api"])
    optimizer.main(["x"], env=ENV, client_factory=lambda: client, runner=cli, which=found)
    assert (len(client.calls), len(cli.calls)) == (1, 0)
    forced = {**ENV, "PROMPT_OPTIMIZER_BACKEND": "claude"}
    optimizer.main(["x"], env=forced, client_factory=lambda: client, runner=cli, which=found)
    assert (len(client.calls), len(cli.calls)) == (1, 1)
    assert "ANTHROPIC_API_KEY" not in cli.calls[0][1]["env"]  # the CLI uses the login, not the key
    optimizer.main(["x", "--backend", "api"], env=forced, client_factory=lambda: client, runner=cli, which=found)
    assert (len(client.calls), len(cli.calls)) == (2, 1)
    capsys.readouterr()


def test_cli_backend_honours_the_model_setting_and_mode_rules(capsys):
    cli = FakeCli(stdout=ENGLISH_OPTIMIZED)
    env = {"PROMPT_OPTIMIZER_MODEL": "sonnet"}
    code = optimizer.main(["design a queue", "--mode", "egm"], env=env, runner=cli, which=found)
    argv = cli.calls[0][0]
    assert code == 0
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "Mode egm" in argv[argv.index("--system-prompt") + 1]
    assert capsys.readouterr().out.startswith("/egm:egm-draft\n")


@pytest.mark.parametrize(
    "cli, which, expected",
    [
        (FakeCli(), lambda name: None, "not on PATH"),
        (FakeCli(returncode=1, stderr="warming up\nNot logged in"), found, "Claude Code failed: Not logged in"),
        (FakeCli(stdout="   "), found, "returned no text"),
        (FakeCli(error=subprocess.TimeoutExpired("claude", 80)), found, "did not answer within 80 seconds"),
    ],
)
def test_cli_backend_failures_are_plain_errors(cli, which, expected, capsys):
    code = optimizer.main(["x"], env={}, runner=cli, which=which)
    captured = capsys.readouterr()
    assert (code, captured.out) == (1, "")
    assert expected in captured.err


# --- clipboard ------------------------------------------------------------------------------


def test_clip_copies_the_result(capsys):
    copied = []
    code, out, err, _ = run_cli(["x", "--clip"], ["ok"], clip=lambda text: copied.append(text) or True, capsys=capsys)
    assert (code, out, copied) == (0, "ok\n", ["ok"])
    assert "copied to clipboard" in err


def test_windows_clipboard_gets_utf16_so_hebrew_survives():
    seen = {}

    def runner(argv, input, check, timeout):  # noqa: A002 (subprocess.run's own name)
        seen.update(argv=argv, data=input)

    assert optimizer.copy_to_clipboard(HEBREW_RAW, runner=runner, platform="win32")
    assert seen["argv"] == ["clip.exe"]
    assert seen["data"].decode("utf-16") == HEBREW_RAW


# --- hook trigger parsing -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("fix the login bug --opt", (True, "fix the login bug", "auto")),
        ("fix the login bug --opt  \n", (True, "fix the login bug", "auto")),
        ("~opt fix the login bug", (True, "fix the login bug", "auto")),
        ("  ~opt   fix the login bug", (True, "fix the login bug", "auto")),
        ("~opt\nfix the\nlogin bug", (True, "fix the\nlogin bug", "auto")),
        ("~opt fix it --opt", (True, "fix it", "auto")),
        ("design a queue --opt=egm", (True, "design a queue", "egm")),
        (HEBREW_RAW + " --opt", (True, HEBREW_RAW, "auto")),
        ("--opt", (True, "", "auto")),
    ],
)
def test_triggers_are_found_and_stripped(text, expected):
    assert hook_runner.parse_trigger(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "fix the login bug",
        "run with --optimize",
        "the --opt flag goes at the end",
        "use--opt",
        "~optimize this",
        "say ~opt in the middle",
        "!opt fix the login bug",  # `!` is Bash mode in Claude Code: never a trigger
        "!fix the login bug",
        "pass --opt=fast",
    ],
)
def test_text_without_a_trigger_is_left_exactly_as_typed(text):
    assert hook_runner.parse_trigger(text) == (False, text, "auto")


# --- hook runner ----------------------------------------------------------------------------


def run_hook(argv, stdin_text, answers):
    client = FakeClient(answers)
    out, err = io.StringIO(), io.StringIO()
    code = hook_runner.main(
        argv, env=ENV, client_factory=lambda: client, stdin=io.StringIO(stdin_text), out=out, err=err
    )
    return code, out.getvalue(), err.getvalue(), client


def test_json_mode_rewrites_a_triggered_prompt_and_shows_it_on_stderr():
    code, out, err, client = run_hook(["--json"], HEBREW_RAW + " --opt", [HEBREW_OPTIMIZED])
    assert code == 0
    assert json.loads(out) == {"triggered": True, "optimized": True, "text": HEBREW_OPTIMIZED, "error": None}
    assert client.calls[0]["messages"][0]["content"] == HEBREW_RAW  # the trigger never reaches the model
    assert HEBREW_OPTIMIZED in err


def test_json_mode_passes_an_untriggered_prompt_through_without_a_call():
    code, out, _, client = run_hook(["--json"], "fix the login bug", [])
    assert json.loads(out) == {"triggered": False, "optimized": False, "text": "fix the login bug", "error": None}
    assert client.calls == []


def test_json_mode_falls_back_to_the_stripped_prompt_when_the_api_fails():
    code, out, err, _ = run_hook(["--json"], "~opt fix the login bug", [RuntimeError("boom")])
    result = json.loads(out)
    assert code == 0
    assert (result["triggered"], result["optimized"], result["text"]) == (True, False, "fix the login bug")
    assert "boom" in result["error"]
    assert "sending the prompt as typed" in err


def test_settings_hook_mode_attaches_the_optimized_prompt_as_context():
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "fix the login bug --opt"})
    code, out, _, _ = run_hook([], payload, [ENGLISH_OPTIMIZED])
    answer = json.loads(out)
    assert code == 0
    assert answer["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert answer["hookSpecificOutput"]["additionalContext"].endswith(ENGLISH_OPTIMIZED)
    assert ENGLISH_OPTIMIZED in answer["systemMessage"]


def test_settings_hook_mode_is_silent_without_a_trigger_and_never_blocks():
    code, out, _, client = run_hook([], json.dumps({"prompt": "fix the login bug"}), [])
    assert (code, out, client.calls) == (0, "", [])
    code, out, _, _ = run_hook([], "not json", [])
    assert (code, out) == (0, "")
