# What "improve" means

Improve = more correct outcomes per unit of cost. Cost has two currencies (tokens, the
user's time). Quality has two levers (reuse, reasoning). Four axes. Every finding names
the axis it moves and the axis it costs.

## Axis 1 - Token efficiency

Goal: less money per completed task.

**The cost model, because it is counter-intuitive.** Every API call re-sends the whole
conversation, so spend is dominated by context re-read, not by what the model writes:

    cost ~ number of API calls x size of the context at each call

In the first real window measured here, cache reads were 86% of spend and output tokens
were a rounding error. Two consequences:

- **A high cache ratio is not efficiency.** It means each call was cheap *per token*. It says
  nothing about how many calls happened or how big the context was. Never rate this axis well
  because the cache ratio is high; `[cache_ratio]` is a diagnostic, not a score.
- **A long session is expensive even when it looks calm.** A 40-turn session re-reads its
  whole history on every one of hundreds of calls. Splitting a session saves real money;
  being terse inside one does not.

Headline number: `[spend.est_cost_usd]`. The two levers: `[spend.api_calls]` and
`[spend.avg_context_per_call]`. Quote dollars in the report - tokens mean nothing to a reader.

Signals (inventory fields in brackets):
- estimated cost, per session and for the window `[spend.est_cost_usd]`
- subagent spend, which is invisible in the main transcript `[spend.est_cost_subagents_usd]`
- calls and average context per call `[spend.api_calls, spend.avg_context_per_call]`
- spend in turns later corrected or reverted, which is pure waste `[turns[].tokens + flags.correction, git.reverted]`
- re-reads of the same file `[mechanical.re_read_turns]`
- retries that added no information `[mechanical.zero_info_retries]`
- compactions, and sessions running long past their topic `[mechanical.compactions, human_turns, span_hours]`

User habits it exposes: keeping one session open across unrelated tasks; pasting large output
instead of a path; exploring by hand in the main context instead of delegating; asking again
without adding anything.

Caveats: one API message is written as several JSONL records that each repeat the full
`usage`, so the inventory deduplicates by message id - never count records yourself. Claude
Code's own `cost-state` field is usually absent or zero; ignore it and use the estimate. The
estimate uses public list prices from `PRICES` in `inventory.py`, so treat it as an order of
magnitude and as a basis for comparison between retros.

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
