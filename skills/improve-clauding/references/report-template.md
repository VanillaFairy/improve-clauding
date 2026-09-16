# Report template

File: `~/.improve-clauding/reports/YYYY-MM-DD-retro-NN.md`. Keep it under ~250 lines.
Write for the user (plain, short sentences). Evidence pointers are `[session#/turn#]` from
the inventory digest plus the session id once per finding.

```markdown
# Clauding retro NN - YYYY-MM-DD

Window: <first session date> -> <last session date> | sessions: N (claude X, cursor Y) | turns: N
Previous retro: <date or none> | inventory: <run dir>

## Scores (1-5, delta vs previous)

| axis | score | delta | one-line reason |
|---|---|---|---|
| token efficiency | | | |
| reusability | | | |
| wall-clock | | | |
| intelligence | | | |

North star: correct episodes / (user turns + tokens/10k) = <value> (prev <value>)

## Hard-fail flags

- none | <flag> [s/t] <evidence>

## Patterns to fix (max 10, ranked)

### 1. <pattern name>
- axis moved: <axis> | axis cost: <axis or none> | attribution: user|agent|env|model
- recurrence: N sessions ([s/t], [s/t], ...)
- evidence: "<quote>" (session <id>, <timestamp>)
- root cause: <one sentence>
- fix: <what the user does differently next time, one sentence>
- proposal: <destination> - <exact text or diff> | or "none (habit only)"

## Patterns to endorse (max 5)

### 1. <pattern name>
- axis: <axis> | win: <quantified>
- evidence: [s/t] "<quote>"
- template: <reusable prompt or workflow, if any>

## Recommendation follow-through (from previous retro)

| # | recommendation | status | evidence |
|---|---|---|---|
| | | adopted / partial / not adopted / unknown | |

## Proposals awaiting approval

Numbered list. Each: destination, target path, exact content. Nothing here has been applied.

## Notes

- sessions marked outcome-pending (<24h): [s], [s]
- parse issues / gaps: <cursor format unverified, N bad lines, ...>
```
