# Improve Clauding

Improve Clauding reviews how you use Claude Code and Cursor.

It reads your recent chats and gives you a short report:

- What you could do better
- What you already do well
- Which habits waste time or tokens
- Simple ideas for better rules, skills, agents, or hooks

Cursor reviews include your prompts, agent replies, tool calls, subagents, and failed
turns. Cursor transcripts do not currently include token costs, exact timing, or tool
results, so reports mark those values as unavailable.

It also tells the difference between your mistakes and tool or model problems.
It never changes your setup by itself.

## Why use it?

It is hard to notice the same problems across many chats.
This plugin finds those patterns for you.

The goal is simple: get better results with less time and effort.

## Install

In Claude Code:

```
/plugin install improve-clauding@vanillafairy
```

In Cursor, put this folder here:

```
~/.cursor/plugins/local/improve-clauding
```

## Use

Run:

```
/improve-clauding:improve-clauding
```

That is all. It reviews every new session since your last report.

You can also choose what to review:

```
/improve-clauding:improve-clauding 10
/improve-clauding:improve-clauding --since 2026-09-01
/improve-clauding:improve-clauding --all
/improve-clauding:improve-clauding prompts
```

- `10` reviews your last 10 sessions.
- `--since` reviews sessions after a date.
- `--all` reviews every session it can find.
- `prompts` reviews only your prompts. You can also use `delegation`, `skills`, or `endorse`.

Reports are saved in:

```
~/.improve-clauding/reports/
```
