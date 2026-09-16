# What "improve" means

Improve = more correct outcomes per unit of cost. Cost has two currencies (tokens, the
user's time). Quality has two levers (reuse, reasoning). Four axes. Every finding names
the axis it moves and the axis it costs.

## Axis 1 - Token efficiency

Goal: fewer tokens per completed task. Not fewer tokens per session.

Signals (inventory fields in brackets):
- output tokens and cache ratio per session `[tokens, cache_ratio]`; low cache ratio = context churn
- tokens spent in turns later corrected or reverted (waste) `[turns[].tokens + flags.correction, git.reverted]`
- re-reads of the same file `[mechanical.re_read_turns]`
- zero-information retries `[mechanical.zero_info_retries]`
- compactions per session `[mechanical.compactions]`
- long sessions that drift across topics `[duration_min, human_turns, repeated topic switches in turns]`

User habits it exposes: pasting instead of referencing paths; not delegating exploration to
subagents; running one session past its topic; asking for restatements; verbose back-and-forth
instead of one specified prompt.

Caveat: JSONL output-token totals can be incomplete. Compare ratios and deltas between retros,
not absolute cost.

## Axis 2 - Actionable reusability

Goal: any composite action that recurs gets extracted once and reused.

Signals:
- repeated prompt openers across sessions `[repeated_openers]`
- corrections with the same content in >=2 sessions (read flagged turns)
- repeated tool-call sequences (configure -> build -> test -> read log) `[turns[].tools]`
- repeated setup preambles at session start `[turns[0].text across sessions]`
- extracted assets that never fire `[skills_unseen]`; skills that fire but are then corrected

Destination rule (see destinations.md): rule / skill / agent / hook / canonical doc.

Metric: recurrence count x turns saved per occurrence. Extract when payback is under ~3
occurrences.

## Axis 3 - Wall-clock time

Goal: less elapsed time per task. Three clocks; fixes differ.

- Agent clock `[agent_active_sec, turns[].agent_seconds]`: sequential read-only tool runs
  that could be parallel `[sequential_readonly_runs]`; long single-context runs where a
  subagent fan-out would be faster; retries after tool errors `[tool_errors]`.
- Tool clock `[tool_ms]`: build/test/configure waits. Fix is caching or narrower targets,
  not prompting.
- Human clock `[human_wait_sec, long_gaps, mechanical.nudges, interrupts]`: turns the user
  spent saying "continue"/"yes" (autonomy not granted up front, or the agent stopped when it
  should not have); time between agent finishing and user answering; number of user turns
  per episode. This is the babysitting cost and the one most under the user's control.

## Axis 4 - Intelligence optimization

Definition: the agent had the right context, the right thinking budget, and the right
decomposition for the difficulty of the task, so the first attempt was correct.

Signals:
- first-attempt success: turns with edits/commits and no following correction
- corrections per episode `[mechanical.corrections]`, follow-up-fix sessions `[git.follow_up_fixes]`, reverts `[git.reverted]`
- plan mode before multi-file changes `[mechanical.plan_mode_used, lines_added]`
- effort/thinking on hard tasks vs trivial ones `[efforts, thinking_chars]`; over-thinking trivial tasks costs axis 1, under-thinking hard ones costs axis 4
- context quality per prompt: intent stated, constraint accessible, failing output included `[turns[].quality]`
- model choice per task `[models]`

User habits it exposes: skipping plan mode on multi-file changes; not pasting the failing
output; accepting "done" without evidence; one model/effort for everything.

## Tensions - state them in every retro

- Tokens vs intelligence: more context and thinking cost tokens. "Cut tokens" must show quality held.
- Tokens vs wall-clock: parallel subagents cut time and multiply tokens.
- Reusability vs everything: extraction costs a session now to save later. Only above the recurrence threshold.
- Human clock vs intelligence: granting autonomy saves turns but removes correction points. Show where autonomy was safe (good) and where it produced a revert (bad).

## Hard-fail flags (not an axis; always report)

`--no-verify`, force-push, commits on main/master, destructive shell commands, secrets in
prompts. `[mechanical.no_verify, force_push, on_main_with_commits]`

## North star

correct episodes / (user turns + normalized tokens). Track per retro; report the delta.
