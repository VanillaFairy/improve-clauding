# Lenses

Each lens answers one question over the same inventory. Lenses are grouped into four
analyst assignments (A-D) so the LLM pass stays bounded. Every finding must carry:
lens, axis, aspect, attribution, harness, evidence (session#/turn#, timestamp, quote),
and a distinct-session recurrence count.

Axis and aspect both come from the closed lists in `axes.md`, and the pairing must be legal
per the matrix there. Before writing any finding, check `harness.md` for whether the aspect
is observable on that session's harness.

## Attribution (applies to every lens)

For each friction episode decide who caused it. Only the first bucket is a user habit.

| bucket | meaning | destination |
|---|---|---|
| user | underspecified prompt, no path, no success criterion, zero-info retry, wrong granularity, skipped plan mode, accepted unverified "done" | habit (report) or personal rule |
| agent | ignored an existing rule, hallucinated, skipped verification, wrong tool, stopped early | project/personal rule, skill patch, hook |
| environment | build system, network, flaky tool, OS quirk | tooling fix, canonical doc |
| model | refusal fallback, regression, capability gap | model/effort choice guidance |
| router | an automatic model selector chose the model, not the user | setup change, never a habit |

Evidence for "agent ignored a rule" requires quoting the rule (CLAUDE.md / AGENTS.md /
skill text). Otherwise it is "no rule existed" -> user or reusability finding.

Use `router` whenever the model was plausibly chosen automatically and the transcript does
not show the user picking it. See the attribution traps in `harness.md`: a session showing
several model strings is not evidence of the user switching models.

## Group A - Communication (analyst A)

1. **Prompt quality.** Intent stated, scope, paths, acceptance criteria, failing output included.
   Signals: `turns[].quality`, `low_quality_prompts`, corrections that follow a q<=1 prompt.
   Aspect: `prompt specificity`. Output: original -> rewrite pairs with a one-line "why better".
2. **Instruction persistence.** Same correction in >=2 sessions -> should be a rule or skill.
   Rule exists but still repeated -> dead or badly placed rule. Signals: flagged correction turns,
   `repeated_openers` (session-distinct), contents of `~/.claude/CLAUDE.md` and project rule files.
   Aspect: `reuse & extraction`.
3. **Task decomposition.** Too-broad asks (one prompt -> many files, long agent turn, then corrections);
   episodes that should have been split or planned. Signals: `lines_added`, `agent_seconds`, `plan_mode_used`.
   Aspect: `plan discipline` or `prompt specificity`.

## Group B - Orchestration (analyst B)

4. **Delegation.** Subagent use, plan mode before large changes, exploration done in the main
   context. Signals: `delegations`, `subagent_files`. Aspect: `delegation`.
5. **Concurrency.** Work that ran one step at a time when nothing depended on the previous
   result. Signals: `sequential_readonly_runs`, `max_tools_per_message`, `multi_tool_messages`,
   `parallel_delegations`, `sequential_delegation_runs`. Aspect: `parallelism`.
   Note that a flat delegation count cannot tell parallel from sequential - use the run
   counters, which now distinguish them.
6. **Clocks.** Agent, tool, and human clocks (`axes.md`, Wall-clock). Long gaps and elapsed
   time only; the *count* of nudges and interrupts belongs to lens 7.
7. **Attention.** Nudges, interrupts, user turns per episode, denials. Aspect:
   `autonomy & permissions` or `retries & loops`. Axis: Human attention.
8. **Session shape and spend.** Session length, more than one brief in a session
   (`briefs_in_session >= 2`), compactions, restarts of the same task in a new session.
   Price each: cost is calls x context size. Name the dollar figure per session
   `[spend.est_cost_usd]` and check how much went to subagents
   `[spend.est_cost_subagents_usd]` - delegation is not free, it just happens off-transcript.
   Aspects: `session length`, `session hygiene`, `cache continuity`, `context loading`,
   `tool output volume`, `model selection`, `reasoning budget`.
   Check `spend.cost_partial` before quoting any total, and check `harness.md` before
   turning session length or compactions into advice - both invert between harnesses.

## Group C - Correctness (analyst C)

9. **Verification.** Did the user demand evidence (build/test output) before accepting "done"?
   Did the agent claim completion without running anything? Later session fixing an earlier
   "completed" task? Signals: praise turns not preceded by a test/build tool call; `git.follow_up_fixes`.
   On Cursor you can see that a test ran but not whether it passed - say so rather than inferring.
10. **Outcome.** Reverts, fixups, PR rejections in the window after the session. Only for sessions
    with `outcome_pending == false` and `capabilities.cwd` true. Signals: `git.*`.
11. **Skill usage.** Installed skills that should have triggered and did not (compare prompt topic to
    skill descriptions); skills that fired and were then corrected (skill weak or wrong); skills never
    used (`skills_unseen`). Confirm the skill was installed for the harness the session used before
    calling it unused. Output: skill patch proposals with the exact text change.
12. **Safety.** Hard-fail flags from `axes.md`. Always listed, never ranked away. Only
    `--no-verify`, force push, and commits on a shared branch are detected; do not claim
    anything about secrets or destructive commands.

## Group D - Endorsement and trend (analyst D)

13. **Endorsement.** Clean sessions (`clean_candidate`), first-attempt successes, prompts worth
    templating, effective delegation. Quantify the win ("4 turns, 0 corrections, 11k out tokens
    for a 300-line change"). Turn the best prompts into reusable templates.
14. **Trend.** For each recommendation in the previous report: adopted / partial / not adopted /
    unknown, with evidence from this window. Per-axis score delta, and the north star in the form
    `axes.md` specifies for the harness.

## Root-cause step (mandatory before ranking)

For each candidate finding answer:
- Why does it recur? (missing skill, habit, architecture constraint, tooling gap, communication mismatch)
- Systemic or one-off? One-offs are dropped unless they are hard-fail flags.
- Which existing strength (from lens 13) could address it?

## Ranking

score = sessions x impact x severity, where:

- **sessions** is the distinct-session count, not the occurrence count.
- **impact** is the estimated dollars, turns, or waiting time saved per occurrence on the
  named axis. Compute it - it becomes the "expected gain" in the report.
- **severity** is 1 normally, and higher for episodes involving data loss, a commit on a
  shared branch, a force push, or a bypassed hook.

Habits outrank tooling at equal score. Hard-fail flags are reported regardless of score and
are never ranked away. Cap: 10 candidates to fix, 5 to endorse, before the report's own
tighter caps apply. Proposals are attached to findings, never free-floating.
