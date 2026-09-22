import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import inventory


NOW = dt.datetime(2026, 9, 23, tzinfo=dt.timezone.utc)


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def analyze_records(records, tool="claude", tmp=None, **meta_extra):
    """Parse + analyze a one-file transcript and return the session record."""
    root = Path(tmp) if tmp else Path(tempfile.mkdtemp())
    transcript = root / "session.jsonl"
    write_jsonl(transcript, records)
    meta = {
        "tool": tool,
        "path": str(transcript),
        "session_id": "session",
        "project_slug": "project",
        "subagent_files": 0,
        "subagent_paths": [],
    }
    meta.update(meta_extra)
    events, misc = inventory.parse_session(meta)
    return inventory.analyze(meta, events, misc, NOW)


def assistant(msg_id, blocks, model="claude-sonnet-4-20250514", usage=None, ts=None, effort=None):
    message = {"role": "assistant", "id": msg_id, "model": model, "content": blocks}
    if usage is not None:
        message["usage"] = usage
    record = {"type": "assistant", "message": message}
    if ts:
        record["timestamp"] = ts
    if effort:
        record["effort"] = effort
    return record


def user(text, ts=None):
    record = {"type": "user", "message": {"role": "user", "content": text}}
    if ts:
        record["timestamp"] = ts
    return record


def cursor_user(text, when="10:00 AM"):
    return {
        "role": "user",
        "message": {
            "content": [{
                "type": "text",
                "text": (
                    f"<timestamp>Tuesday, Sep 22, 2026, {when} (UTC+2)</timestamp>"
                    f"<user_query>{text}</user_query>"
                ),
            }],
        },
    }


def latest_run_dir(home):
    return sorted((Path(home) / "runs").glob("*"))[-1]


class CursorDiscoveryTests(unittest.TestCase):
    def test_discovers_nested_sessions_and_subagents(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = inventory.CURSOR_PROJECTS
            self.addCleanup(setattr, inventory, "CURSOR_PROJECTS", old_root)
            inventory.CURSOR_PROJECTS = Path(tmp)

            transcripts = Path(tmp) / "c-work-project" / "agent-transcripts"
            nested = transcripts / "session-1" / "session-1.jsonl"
            subagent = transcripts / "session-1" / "subagents" / "sub-1.jsonl"
            legacy = transcripts / "session-2.jsonl"
            write_jsonl(nested, [])
            write_jsonl(subagent, [])
            write_jsonl(legacy, [])

            sessions = {item["session_id"]: item for item in inventory.discover_cursor()}

            self.assertEqual({"session-1", "session-2"}, set(sessions))
            self.assertEqual(1, sessions["session-1"]["subagent_files"])
            self.assertEqual([str(subagent)], sessions["session-1"]["subagent_paths"])
            self.assertEqual(0, sessions["session-2"]["subagent_files"])


class CursorParsingTests(unittest.TestCase):
    def test_parses_cursor_prompts_tools_timestamps_and_interrupts(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            records = [
                {
                    "role": "user",
                    "message": {
                        "content": [{
                            "type": "text",
                            "text": (
                                "<open_and_recently_viewed_files>noise</open_and_recently_viewed_files>"
                                "<timestamp>Tuesday, Sep 22, 2026, 10:00 AM (UTC+2)</timestamp>"
                                "<user_query>Fix foo.py and verify tests.</user_query>"
                            ),
                        }],
                    },
                },
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Shell",
                                "input": {
                                    "command": "python -m unittest",
                                    "working_directory": tmp,
                                },
                            },
                            {
                                "type": "tool_use",
                                "name": "CallDynamicTool",
                                "input": {
                                    "namespace": "cursor",
                                    "toolName": "Subagent",
                                    "arguments": {"description": "Check tests"},
                                },
                            },
                        ],
                    },
                },
                {"type": "turn_ended", "status": "success"},
                {
                    "role": "user",
                    "message": {
                        "content": [{
                            "type": "text",
                            "text": (
                                "<timestamp>Tuesday, Sep 22, 2026, 10:10 AM (UTC+2)</timestamp>"
                                "<user_query>No, use bar.py instead.</user_query>"
                            ),
                        }],
                    },
                },
                {
                    "role": "assistant",
                    "message": {
                        "content": [{
                            "type": "tool_use",
                            "name": "ApplyPatch",
                            "input": {"patch": "..."},
                        }],
                    },
                },
                {"type": "turn_ended", "status": "error", "error": "User aborted request"},
            ]
            write_jsonl(transcript, records)
            meta = {
                "tool": "cursor",
                "path": str(transcript),
                "session_id": "session",
                "project_slug": "c-work-project",
                "subagent_files": 0,
                "subagent_paths": [],
            }

            events, misc = inventory.parse_session(meta)
            session = inventory.analyze(
                meta,
                events,
                misc,
                dt.datetime(2026, 9, 23, tzinfo=dt.timezone.utc),
            )

            prompts = [event for event in events if event["kind"] == "prompt"]
            tool_names = [
                tool["name"]
                for event in events if event["kind"] == "assistant"
                for tool in event["tool_uses"]
            ]
            self.assertEqual(
                ["Fix foo.py and verify tests.", "No, use bar.py instead."],
                [prompt["text"] for prompt in prompts],
            )
            self.assertEqual("2026-09-22T08:00:00+00:00", session["start"])
            self.assertEqual("2026-09-22T08:10:00+00:00", session["end"])
            self.assertEqual(["Shell", "Subagent", "ApplyPatch"], tool_names)
            self.assertEqual(tmp, session["cwd"])
            self.assertEqual(2, session["human_turns"])
            self.assertEqual(1, session["mechanical"]["delegations"])
            self.assertEqual(1, session["mechanical"]["interrupts"])
            self.assertEqual(1, session["mechanical"]["corrections"])
            self.assertIsNone(session["duration_min"])
            self.assertFalse(session["capabilities"]["usage"])
            self.assertFalse(session["capabilities"]["exact_timing"])
            self.assertFalse(session["capabilities"]["tool_results"])
            self.assertEqual(0, session["spend"]["est_cost_usd"])

    def test_records_non_user_cursor_turn_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            write_jsonl(transcript, [
                {
                    "role": "user",
                    "message": {
                        "content": [{
                            "type": "text",
                            "text": (
                                "<timestamp>Tuesday, Sep 22, 2026, 10:00 AM (UTC+2)</timestamp>"
                                "<user_query>Run the build.</user_query>"
                            ),
                        }],
                    },
                },
                {"type": "turn_ended", "status": "error", "error": "[resource_exhausted] Error"},
            ])
            meta = {
                "tool": "cursor",
                "path": str(transcript),
                "session_id": "session",
                "project_slug": "project",
                "subagent_files": 0,
                "subagent_paths": [],
            }

            events, misc = inventory.parse_session(meta)
            session = inventory.analyze(
                meta,
                events,
                misc,
                dt.datetime(2026, 9, 23, tzinfo=dt.timezone.utc),
            )

            self.assertEqual(1, session["mechanical"]["turn_failures"])
            self.assertEqual(
                {"[resource_exhausted] Error": 1},
                session["mechanical"]["turn_failure_reasons"],
            )


class PricingTests(unittest.TestCase):
    def test_unknown_family_has_no_price(self):
        self.assertEqual("sonnet", inventory.model_family("claude-sonnet-4-20250514"))
        self.assertEqual("opus", inventory.model_family("claude-opus-4-1-20250805"))
        for unpriced in ("composer-2.5", "gpt-5.6-sol-high", "grok-4.7-high-fast",
                         "gemini-3-pro", "claude-fable-5-1-thinking-high", None, ""):
            self.assertIsNone(inventory.model_family(unpriced), unpriced)

    def test_usage_family_key_falls_back_to_raw_model_string(self):
        self.assertEqual("sonnet", inventory.usage_family_key("claude-sonnet-4-20250514"))
        self.assertEqual("composer-2.5", inventory.usage_family_key("composer-2.5"))
        self.assertEqual("unknown", inventory.usage_family_key(None))

    def test_estimate_cost_skips_unpriced_families(self):
        usd, unpriced = inventory.estimate_cost({
            "sonnet": {"in": 1_000_000, "out": 0, "cache_write": 0, "cache_read": 0},
            "composer-2.5": {"in": 2_000_000, "out": 1_000_000},
        })
        self.assertEqual(3.0, usd)
        self.assertEqual({"composer-2.5": 3_000_000}, unpriced)

    def test_estimate_cost_is_exact_when_every_family_is_priced(self):
        usd, unpriced = inventory.estimate_cost({
            "sonnet": {"in": 1_000_000, "out": 1_000_000, "cache_write": 0, "cache_read": 0},
        })
        self.assertEqual(18.0, usd)
        self.assertEqual({}, unpriced)

    def test_session_spend_flags_partial_cost_and_names_the_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [{"type": "text", "text": "ok"}],
                          model="claude-sonnet-4-20250514",
                          usage={"input_tokens": 1_000_000},
                          ts="2026-09-22T10:01:00Z"),
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("m2", [{"type": "text", "text": "ok"}],
                          model="composer-2.5",
                          usage={"input_tokens": 1_000_000},
                          ts="2026-09-22T10:03:00Z"),
            ], tmp=tmp)

            spend = session["spend"]
            # the composer million is excluded, not billed at the sonnet rate
            self.assertEqual(3.0, spend["est_cost_usd"])
            self.assertTrue(spend["cost_partial"])
            self.assertEqual(["composer-2.5"], spend["unpriced_families"])
            self.assertEqual(1_000_000, spend["unpriced_tokens"])
            self.assertFalse(session["capabilities"]["pricing"])

    def test_fully_priced_session_is_not_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [{"type": "text", "text": "ok"}],
                          usage={"input_tokens": 1_000_000},
                          ts="2026-09-22T10:01:00Z"),
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("m2", [{"type": "text", "text": "ok"}],
                          usage={"output_tokens": 1_000_000},
                          ts="2026-09-22T10:03:00Z"),
            ], tmp=tmp)

            self.assertEqual(18.0, session["spend"]["est_cost_usd"])
            self.assertFalse(session["spend"]["cost_partial"])
            self.assertEqual([], session["spend"]["unpriced_families"])
            self.assertTrue(session["capabilities"]["pricing"])


class CompactionCapabilityTests(unittest.TestCase):
    def test_cursor_compactions_are_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                cursor_user("Fix the parser module.", "10:00 AM"),
                cursor_user("Now run the tests.", "10:05 AM"),
            ], tool="cursor", tmp=tmp)

            self.assertFalse(session["capabilities"]["compactions"])
            self.assertEqual(0, session["mechanical"]["compactions"])

    def test_claude_compactions_are_available_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:01:00Z"),
                {"type": "summary", "summary": "compacted"},
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("m2", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:03:00Z"),
            ], tmp=tmp)

            self.assertTrue(session["capabilities"]["compactions"])
            self.assertEqual(1, session["mechanical"]["compactions"])


class ToolOutputSizeTests(unittest.TestCase):
    def test_counts_tool_output_chars_and_big_outputs(self):
        big = "x" * inventory.BIG_TOOL_OUTPUT_CHARS
        small = "y" * 100
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Read config.py and summarize it.", "2026-09-22T10:00:00Z"),
                assistant("m1", [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "config.py"}},
                    {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "setup.py"}},
                ], ts="2026-09-22T10:01:00Z"),
                {"type": "user", "timestamp": "2026-09-22T10:01:30Z", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": big},
                    {"type": "tool_result", "tool_use_id": "t2", "content": small},
                ]}},
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("m2", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:03:00Z"),
            ], tmp=tmp)

            first = session["turns"][0]
            self.assertEqual(inventory.BIG_TOOL_OUTPUT_CHARS + 100, first["tool_result_chars"])
            self.assertEqual(1, first["big_tool_outputs"])
            self.assertEqual(inventory.BIG_TOOL_OUTPUT_CHARS + 100,
                             session["mechanical"]["tool_output_chars"])
            self.assertEqual(1, session["mechanical"]["big_tool_outputs"])

    def test_tool_output_size_is_none_when_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                cursor_user("Fix the parser module.", "10:00 AM"),
                cursor_user("Now run the tests.", "10:05 AM"),
            ], tool="cursor", tmp=tmp)

            self.assertFalse(session["capabilities"]["tool_results"])
            self.assertIsNone(session["mechanical"]["tool_output_chars"])
            self.assertIsNone(session["mechanical"]["big_tool_outputs"])
            self.assertIsNone(session["turns"][0]["tool_result_chars"])
            self.assertIsNone(session["turns"][0]["big_tool_outputs"])

    def test_short_chars_rounds_to_k(self):
        self.assertEqual("?", inventory.short_chars(None))
        self.assertEqual("999", inventory.short_chars(999))
        self.assertEqual("41k", inventory.short_chars(41234))


class ToolBatchingTests(unittest.TestCase):
    def test_tracks_max_and_multi_tool_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [
                    {"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "a.py"}},
                    {"type": "tool_use", "id": "b", "name": "Read", "input": {"file_path": "b.py"}},
                    {"type": "tool_use", "id": "c", "name": "Grep", "input": {"pattern": "x"}},
                ], ts="2026-09-22T10:01:00Z"),
                assistant("m2", [
                    {"type": "tool_use", "id": "d", "name": "Read", "input": {"file_path": "c.py"}},
                ], ts="2026-09-22T10:01:30Z"),
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("m3", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:03:00Z"),
            ], tmp=tmp)

            first = session["turns"][0]
            self.assertEqual(3, first["max_tools_per_message"])
            self.assertEqual(1, first["multi_tool_messages"])
            self.assertEqual(3, session["mechanical"]["max_tools_per_message"])
            self.assertEqual(1, session["mechanical"]["multi_tool_messages"])
            # the pre-existing signal is unchanged
            self.assertEqual(0, session["mechanical"]["sequential_readonly_runs"])


class DelegationShapeTests(unittest.TestCase):
    def test_parallel_batch_is_not_counted_as_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Investigate the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [
                    {"type": "tool_use", "id": "a", "name": "Task", "input": {"description": "one"}},
                    {"type": "tool_use", "id": "b", "name": "Task", "input": {"description": "two"}},
                    {"type": "tool_use", "id": "c", "name": "Read", "input": {"file_path": "a.py"}},
                ], ts="2026-09-22T10:01:00Z"),
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("m2", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:03:00Z"),
            ], tmp=tmp)

            self.assertEqual(2, session["mechanical"]["delegations"])
            self.assertEqual(2, session["mechanical"]["parallel_delegations"])
            self.assertEqual(0, session["mechanical"]["sequential_delegation_runs"])

    def test_sequential_single_delegate_messages_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Investigate the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [
                    {"type": "tool_use", "id": "a", "name": "Task", "input": {"description": "one"}},
                ], ts="2026-09-22T10:01:00Z"),
                assistant("m2", [
                    {"type": "tool_use", "id": "b", "name": "Task", "input": {"description": "two"}},
                ], ts="2026-09-22T10:01:30Z"),
                assistant("m3", [
                    {"type": "tool_use", "id": "c", "name": "Task", "input": {"description": "three"}},
                ], ts="2026-09-22T10:02:00Z"),
                user("Now run the tests.", "2026-09-22T10:03:00Z"),
                assistant("m4", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:04:00Z"),
            ], tmp=tmp)

            self.assertEqual(3, session["mechanical"]["delegations"])
            self.assertEqual(0, session["mechanical"]["parallel_delegations"])
            self.assertEqual(2, session["mechanical"]["sequential_delegation_runs"])


class BriefsInSessionTests(unittest.TestCase):
    def test_counts_separate_briefs(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:01:00Z"),
                # >2h later: a fresh brief, not a follow-up
                user("Different job: write the release notes.", "2026-09-22T14:00:00Z"),
                assistant("m2", [{"type": "text", "text": "ok"}], ts="2026-09-22T14:01:00Z"),
            ], tmp=tmp)

            self.assertEqual(2, session["mechanical"]["briefs_in_session"])
            self.assertEqual(session["mechanical"]["openers"],
                             session["mechanical"]["briefs_in_session"])

    def test_follow_up_inside_a_live_thread_is_one_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = analyze_records([
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("m1", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:01:00Z"),
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("m2", [{"type": "text", "text": "ok"}], ts="2026-09-22T10:03:00Z"),
            ], tmp=tmp)

            self.assertEqual(1, session["mechanical"]["briefs_in_session"])


class ModelStringTests(unittest.TestCase):
    def test_short_model_strips_release_date(self):
        self.assertEqual("claude-opus-4-1", inventory.short_model("claude-opus-4-1-20250805"))
        self.assertEqual("claude-sonnet-4", inventory.short_model("claude-sonnet-4-20250514"))
        self.assertEqual("composer-2.5", inventory.short_model("composer-2.5"))
        self.assertEqual("-", inventory.short_model(None))

    def test_top_key_picks_the_most_common_value(self):
        self.assertEqual("high", inventory.top_key({"high": 5, "low": 2}))
        self.assertIsNone(inventory.top_key({}))
        self.assertIsNone(inventory.top_key(None))


class EndToEndOutputTests(unittest.TestCase):
    """Run main() over synthetic transcripts and read what the analysts read."""

    def _run(self, tmp, roots):
        home = Path(tmp) / "home"
        for attr in ("CLAUDE_PROJECTS", "CURSOR_PROJECTS"):
            self.addCleanup(setattr, inventory, attr, getattr(inventory, attr))
            setattr(inventory, attr, Path(tmp) / "absent" / attr)
        code = inventory.main(["--home", str(home), "--roots", roots,
                               "--all", "--no-git", "--quiet"])
        self.assertEqual(0, code)
        run_dir = latest_run_dir(home)
        return run_dir, json.loads((run_dir / "inventory.json").read_text(encoding="utf-8"))

    def test_repeated_openers_count_sessions_and_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = Path(tmp) / "roots"
            write_jsonl(roots / "s1.jsonl", [
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("a1", [{"type": "text", "text": "ok"}],
                          usage={"input_tokens": 1000}, ts="2026-09-22T10:01:00Z", effort="high"),
                user("Refactor the parser module again, differently.", "2026-09-22T10:02:00Z"),
                assistant("a2", [{"type": "text", "text": "ok"}],
                          usage={"output_tokens": 1000}, ts="2026-09-22T10:03:00Z", effort="high"),
            ])
            write_jsonl(roots / "s2.jsonl", [
                user("Refactor the parser module please.", "2026-09-22T11:00:00Z"),
                assistant("b1", [{"type": "text", "text": "ok"}], model="composer-2.5",
                          usage={"input_tokens": 1_000_000}, ts="2026-09-22T11:01:00Z", effort="medium"),
                user("Check the build output now.", "2026-09-22T11:02:00Z"),
                assistant("b2", [{"type": "text", "text": "ok"}], model="composer-2.5",
                          usage={"output_tokens": 1000}, ts="2026-09-22T11:03:00Z", effort="medium"),
            ])
            run_dir, inv = self._run(tmp, str(roots))

            repeated = {row[0]: (row[1], row[2]) for row in inv["repeated_openers"]}
            # 2 distinct sessions, 3 occurrences overall
            self.assertEqual((2, 3), repeated["refactor the parser module"])
            # a one-session opener never qualifies, however often it repeats
            self.assertNotIn("check the build output", repeated)

            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("- 2 sessions, 3 times: refactor the parser module", summary)

    def test_summary_surfaces_models_efforts_and_partial_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = Path(tmp) / "roots"
            write_jsonl(roots / "s1.jsonl", [
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("a1", [{"type": "text", "text": "ok"}],
                          usage={"input_tokens": 1_000_000}, ts="2026-09-22T10:01:00Z", effort="high"),
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("a2", [{"type": "text", "text": "ok"}], model="composer-2.5",
                          usage={"input_tokens": 1_000_000}, ts="2026-09-22T10:03:00Z", effort="high"),
            ])
            run_dir, inv = self._run(tmp, str(roots))

            self.assertEqual(["composer-2.5"], inv["summary"]["unpriced_models"])
            self.assertEqual({"high": 2}, inv["summary"]["efforts"])
            self.assertIn("claude-sonnet-4-20250514", inv["summary"]["models"])

            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("## Models and effort", summary)
            self.assertIn("claude-sonnet-4-20250514 1", summary)
            self.assertIn("high 2", summary)
            self.assertIn("| # | tool | model | effort |", summary)
            self.assertIn("| claude-sonnet-4 |", summary)
            self.assertIn(
                "COST PARTIAL: no list price for composer-2.5; "
                "those tokens are excluded from every dollar figure",
                summary,
            )
            # the composer million is not billed at sonnet rates
            self.assertEqual(3.0, inv["summary"]["spend"]["est_cost_usd"])

    def test_slices_carry_models_and_efforts_per_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = Path(tmp) / "roots"
            write_jsonl(roots / "s1.jsonl", [
                user("Refactor the parser module please.", "2026-09-22T10:00:00Z"),
                assistant("a1", [
                    {"type": "tool_use", "id": "a", "name": "Task", "input": {"description": "one"}},
                    {"type": "tool_use", "id": "b", "name": "Task", "input": {"description": "two"}},
                ], usage={"input_tokens": 1000}, ts="2026-09-22T10:01:00Z", effort="high"),
                user("Now run the tests.", "2026-09-22T10:02:00Z"),
                assistant("a2", [{"type": "text", "text": "ok"}],
                          usage={"output_tokens": 1000}, ts="2026-09-22T10:03:00Z", effort="high"),
            ])
            run_dir, inv = self._run(tmp, str(roots))

            for group, name in (("a", "communication"), ("b", "orchestration"),
                                ("c", "correctness"), ("d", "endorsement")):
                text = (run_dir / f"slice-{group}-{name}.md").read_text(encoding="utf-8")
                self.assertIn("- models: {'claude-sonnet-4-20250514'", text)
                self.assertIn("'high': 2}", text)

            slice_b = (run_dir / "slice-b-orchestration.md").read_text(encoding="utf-8")
            self.assertIn("2 in parallel batches, 0 sequential run-ons", slice_b)
            self.assertIn("max tools per message 2", slice_b)
            self.assertIn("briefs in session 1", slice_b)

    def test_cursor_window_reports_compactions_as_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            projects = Path(tmp) / "cursor"
            transcripts = projects / "c-work-project" / "agent-transcripts"
            write_jsonl(transcripts / "s1" / "s1.jsonl", [
                cursor_user("Refactor the parser module.", "10:00 AM"),
                cursor_user("Now run the tests.", "10:05 AM"),
            ])
            for attr, value in (("CLAUDE_PROJECTS", Path(tmp) / "absent"),
                                ("CURSOR_PROJECTS", projects)):
                self.addCleanup(setattr, inventory, attr, getattr(inventory, attr))
                setattr(inventory, attr, value)

            self.assertEqual(0, inventory.main(["--home", str(home), "--all",
                                                "--no-git", "--quiet"]))
            run_dir = latest_run_dir(home)
            inv = json.loads((run_dir / "inventory.json").read_text(encoding="utf-8"))

            self.assertEqual(1, inv["summary"]["coverage"]["compactions_unknown"])
            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("compactions unavailable for these transcripts", summary)
            self.assertNotIn("compactions 0", summary)
            self.assertIn("tool-output size unavailable", summary)

            slice_b = (run_dir / "slice-b-orchestration.md").read_text(encoding="utf-8")
            self.assertIn("compactions unavailable", slice_b)


if __name__ == "__main__":
    unittest.main()
