import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import inventory


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


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


if __name__ == "__main__":
    unittest.main()
