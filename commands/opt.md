---
description: Optimize a rough prompt into a sharp spec, then carry it out
argument-hint: <raw prompt>
---

The user wants the rough prompt below optimized, then carried out.

1. Run this one Bash command. Replace the line `RAW_PROMPT_GOES_HERE` with the raw prompt, copied character for character (keep its language, quotes and line breaks). The quoted heredoc passes it on standard input, so nothing in it is read by the shell:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/optimize.sh" <<'PROMPT_OPTIMIZER_EOF'
RAW_PROMPT_GOES_HERE
PROMPT_OPTIMIZER_EOF
```

2. Show the user the optimized prompt the command printed, in a quote block, under the line "Optimized prompt:".
3. Then treat that optimized prompt as the user's request and carry it out. If its first line is a slash command such as `/egm:egm-brainstorm`, `/egm:egm-draft` or `/egm:egm-review`, invoke that skill with the rest of the prompt as its input.

If the command fails, show its error and carry out the raw prompt as written.

Raw prompt:

$ARGUMENTS
