# Lenses

Each lens answers one question over the same inventory. Lenses are grouped into four
analyst assignments (A-D) so the LLM pass stays bounded. Every finding must carry:
lens, axis moved, axis cost, attribution, evidence (session#/turn#, timestamp, quote),
recurrence count.

## Attribution (applies to every lens)

For each friction episode decide who caused it. Only the first bucket is a user habit.

| bucket | meaning | destination |
|---|---|---|
| user | underspecified prompt, no path, no success criterion, zero-info retry, wrong granularity, skipped plan mode, accepted unverified "done" | habit (report) or personal rule |
| agent | ignored an existing rule, hallucinated, skipped verification, wrong tool, stopped early | project/personal rule, skill patch, hook |
| environment | build system, network, flaky tool, OS quirk | tooling fix, canonical doc |
| model | refusal fallback, regression, capability gap | model/effort choice guidance |

Evidence for "agent ignored a rule" requires quoting the rule (CLAUDE.md / AGENTS.md /
skill text). Otherwise it is "no rule existed" -> user or reusability finding.

## Group A - Communication (analyst A)

1. **Prompt quality.** Intent stated, scope, paths, acceptance criteria, failing output included.
   Signals: `turns[].quality`, `low_quality_prompts`, corrections that follow a q<=1 prompt.
   Output: original -> rewrite pairs with a one-line "why better" (existence / salience / actionability).
2. **Instruction persistence.** Same correction in >=2 sessions -> should be a rule or skill.
   Rule exists but still repeated -> dead or badly placed rule. Signals: flagged correction turns,
   `repeated_openers`, contents of `~/.claude/CLAUDE.md` and project rule files.
3. **Task decomposition.** Too-broad asks (one prompt -> many files, long agent turn, then corrections);
   episodes that should have been split or planned. Signals: `lines_added`, `agent_seconds`, `plan_mode_used`.

## Group B - Orchestration (analyst B)

4. **Delegation.** Subagent/Task use, plan mode before large changes, parallel vs sequential,
   exploration done in main context. Signals: `delegations`, `subagent_files`, `sequential_readonly_runs`.
5. **Wall-clock.** Agent / tool / human clocks (axes.md). Nudges, interrupts, long gaps, turn counts per episode.
6. **Session hygiene.** Session length, topic drift inside one session, compactions, restarts of the
   same task in a new session (look for near-identical openers within 48h).

## Group C - Correctness (analyst C)

7. **Verification.** Did the user demand evidence (build/test output) before accepting "done"?
   Did the agent claim completion without running anything? Later session fixing an earlier
   "completed" task? Signals: praise turns not preceded by a test/build tool call; `git.follow_up_fixes`.
8. **Outcome.** Reverts, fixups, PR rejections in the window after the session. Only for sessions
   with `outcome_pending == false`. Signals: `git.*`.
9. **Skill usage.** Installed skills that should have triggered and did not (compare prompt topic to
   skill descriptions); skills that fired and were then corrected (skill weak or wrong); skills never
   used (`skills_unseen`). Output: skill patch proposals with the exact text change.
10. **Safety.** Hard-fail flags from axes.md. Always listed, never ranked away.

## Group D - Endorsement and trend (analyst D)

11. **Endorsement.** Clean sessions (`clean_candidate`), first-attempt successes, prompts worth
    templating, effective delegation. Quantify the win ("4 turns, 0 corrections, 11k out tokens
    for a 300-line change"). Turn the best prompts into reusable templates.
12. **Trend.** For each recommendation in the previous report: adopted / partial / not adopted /
    unknown, with evidence from this window. Per-axis score delta.

## Root-cause step (mandatory before ranking)

For each candidate finding answer:
- Why does it recur? (missing skill, habit, architecture constraint, tooling gap, communication mismatch)
- Systemic or one-off? One-offs are dropped unless they are hard-fail flags.
- Which existing strength (from lens 11) could address it?

## Ranking

score = recurrence x impact, where impact is the estimated turns or tokens saved per occurrence
on the moved axis. Cap: 10 patterns to fix, 5 to endorse, all hard-fail flags. Proposals are
attached to findings, never free-floating.
