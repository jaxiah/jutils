"""
tests/test_pomo_debrief.py

Tests for pomo_debrief.py helper functions and detection logic.
Uses tests/fixtures/tasknotes_data.json (synthetic data).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pomo_debrief import (
    count_today_pomos_for_task,
    fmt_time,
    is_completed_work,
    load_pomo_history,
    task_display_name,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tasknotes_data.json"


# ---------------------------------------------------------------------------
# fmt_time
# ---------------------------------------------------------------------------


class TestFmtTime(unittest.TestCase):
    def test_standard_iso(self):
        self.assertEqual(fmt_time("2026-04-18T10:25:00+08:00"), "[2026-04-18 Sat 10:25]")

    def test_midnight(self):
        self.assertEqual(fmt_time("2026-01-01T00:00:00+08:00"), "[2026-01-01 Thu 00:00]")

    def test_invalid_returns_original(self):
        self.assertEqual(fmt_time("not-a-date"), "not-a-date")

    def test_empty_returns_empty(self):
        self.assertEqual(fmt_time(""), "")


# ---------------------------------------------------------------------------
# is_completed_work
# ---------------------------------------------------------------------------


class TestIsCompletedWork(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_completed_work({"type": "work", "completed": True}))

    def test_break_type(self):
        self.assertFalse(is_completed_work({"type": "break", "completed": True}))

    def test_not_completed(self):
        self.assertFalse(is_completed_work({"type": "work", "completed": False}))

    def test_missing_fields(self):
        self.assertFalse(is_completed_work({}))


# ---------------------------------------------------------------------------
# task_display_name
# ---------------------------------------------------------------------------


class TestTaskDisplayName(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(
            task_display_name("TaskNotes/Tasks/wmma single-stage kernel understanding.md"),
            "wmma single-stage kernel understanding",
        )

    def test_chinese(self):
        self.assertEqual(
            task_display_name("TaskNotes/Tasks/ca.advanced.md"),
            "ca.advanced",
        )


# ---------------------------------------------------------------------------
# load_pomo_history (real fixture)
# ---------------------------------------------------------------------------


class TestLoadPomoHistory(unittest.TestCase):
    def setUp(self):
        self.cfg = {"data_json_path": str(FIXTURE)}

    def test_returns_list(self):
        history = load_pomo_history(self.cfg)
        self.assertIsInstance(history, list)

    def test_nonempty(self):
        history = load_pomo_history(self.cfg)
        self.assertGreater(len(history), 0)

    def test_entries_have_expected_fields(self):
        history = load_pomo_history(self.cfg)
        entry = history[0]
        self.assertIn("type", entry)
        self.assertIn("completed", entry)
        self.assertIn("startTime", entry)
        self.assertIn("taskPath", entry)

    def test_missing_file_returns_empty(self):
        cfg = {"data_json_path": "/nonexistent/path/data.json"}
        self.assertEqual(load_pomo_history(cfg), [])


# ---------------------------------------------------------------------------
# count_today_pomos_for_task (real fixture)
# ---------------------------------------------------------------------------


class TestCountTodayPomos(unittest.TestCase):
    def setUp(self):
        self.cfg = {"data_json_path": str(FIXTURE)}
        self.history = load_pomo_history(self.cfg)

    def test_nonexistent_task_returns_zero(self):
        count = count_today_pomos_for_task(self.history, "TaskNotes/Tasks/nonexistent.md")
        self.assertEqual(count, 0)

    def test_count_is_nonnegative(self):
        if not self.history:
            self.skipTest("fixture has no history")
        task_path = self.history[0].get("taskPath", "")
        count = count_today_pomos_for_task(self.history, task_path)
        self.assertGreaterEqual(count, 0)


# ---------------------------------------------------------------------------
# Detection logic: last_count based new entry detection
# ---------------------------------------------------------------------------


class TestDetectionLogic(unittest.TestCase):
    """
    Simulate the run() detection logic without the GUI or file I/O.
    Verify that history[last_count:] correctly identifies new entries.
    """

    BASE_ENTRY = {
        "type": "work",
        "completed": True,
        "startTime": "2026-04-18T10:00:00+08:00",
        "endTime": "2026-04-18T10:25:00+08:00",
        "taskPath": "TaskNotes/Tasks/some task.md",
    }

    def _make_entry(self, minute: int) -> dict:
        e = dict(self.BASE_ENTRY)
        e["startTime"] = f"2026-04-18T10:{minute:02d}:00+08:00"
        return e

    def test_baseline_sees_nothing(self):
        history = [self._make_entry(0), self._make_entry(25)]
        last_count = len(history)  # baseline established
        new_entries = history[last_count:]
        self.assertEqual(new_entries, [])

    def test_one_new_entry_detected(self):
        history = [self._make_entry(0), self._make_entry(25)]
        last_count = len(history)
        # simulate new pomo added
        history.append(self._make_entry(50))
        new_entries = [e for e in history[last_count:] if is_completed_work(e)]
        self.assertEqual(len(new_entries), 1)
        self.assertEqual(new_entries[0]["startTime"], "2026-04-18T10:50:00+08:00")
        last_count = len(history)
        # no more new entries
        self.assertEqual(history[last_count:], [])

    def test_break_entry_not_triggered(self):
        history = [self._make_entry(0)]
        last_count = len(history)
        break_entry = {"type": "break", "completed": True, "taskPath": "TaskNotes/Tasks/some task.md"}
        history.append(break_entry)
        new_entries = [e for e in history[last_count:] if is_completed_work(e)]
        self.assertEqual(new_entries, [])

    def test_multiple_new_entries(self):
        history = [self._make_entry(0)]
        last_count = len(history)
        history.append(self._make_entry(25))
        history.append(self._make_entry(50))
        new_entries = [e for e in history[last_count:] if is_completed_work(e)]
        self.assertEqual(len(new_entries), 2)


# ---------------------------------------------------------------------------
# Markdown formatting logic
# ---------------------------------------------------------------------------


class TestMarkdownFormatting(unittest.TestCase):
    """Test the single-line vs multi-line bullet formatting."""

    def _format(self, text: str, time_range: str = "RANGE") -> str:
        stripped = text.strip()
        lines = stripped.splitlines()
        if len(lines) <= 1:
            return f"- {time_range} {stripped}"
        else:
            indented = "\n".join(f"  {l}" for l in lines)
            return f"- {time_range}\n{indented}"

    def test_single_line(self):
        result = self._format("hello world")
        self.assertEqual(result, "- RANGE hello world")

    def test_multiline(self):
        result = self._format("line one\nline two\nline three")
        expected = "- RANGE\n  line one\n  line two\n  line three"
        self.assertEqual(result, expected)

    def test_strips_leading_trailing_whitespace(self):
        result = self._format("  hello  ")
        self.assertEqual(result, "- RANGE hello")

    def test_empty_after_strip_single_line(self):
        result = self._format("   ")
        self.assertEqual(result, "- RANGE ")


if __name__ == "__main__":
    unittest.main()
