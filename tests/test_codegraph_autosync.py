import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codegraph_autosync import (
    AutoSyncWatcher,
    DebouncedSyncState,
    WatchConfig,
    _matches_ignore,
    _parse_args,
    build_snapshot,
    changed_paths,
    run_init,
)


class DebouncedSyncStateTests(unittest.TestCase):
    def test_each_change_restarts_debounce(self) -> None:
        state = DebouncedSyncState()

        self.assertTrue(state.add_changes({"first.py"}, now=0.0))
        self.assertFalse(state.add_changes({"second.py"}, now=1.0))

        self.assertFalse(state.ready(now=1.5, debounce=1.5))
        self.assertTrue(state.ready(now=2.5, debounce=1.5))

    def test_new_changes_do_not_shorten_retry_delay(self) -> None:
        state = DebouncedSyncState()
        state.add_changes({"first.py"}, now=0.0)
        state.mark_failure(now=2.0, retry_delay=10.0)
        state.add_changes({"second.py"}, now=3.0)

        self.assertEqual(state.retry_at, 12.0)
        self.assertFalse(state.ready(now=5.0, debounce=1.5))
        self.assertTrue(state.ready(now=12.0, debounce=1.5))

    def test_success_clears_pending_batch(self) -> None:
        state = DebouncedSyncState()
        state.add_changes({"first.py"}, now=0.0)
        state.mark_failure(now=2.0, retry_delay=10.0)

        state.mark_success()

        self.assertFalse(state.pending)
        self.assertIsNone(state.last_change_at)
        self.assertEqual(state.retry_at, 0.0)


class FileDetectionTests(unittest.TestCase):
    def test_ignore_matching_is_case_insensitive(self) -> None:
        self.assertTrue(_matches_ignore(Path(".CodeGraph"), {".codegraph"}, ()))
        self.assertTrue(_matches_ignore(Path(".GIT/index"), {".git"}, ()))
        self.assertTrue(_matches_ignore(Path("scratch.PYC"), set(), ("*.pyc",)))

    def test_snapshot_ignores_generated_directories_and_detects_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / ".codegraph").mkdir()
            (root / "src" / "main.py").write_text("one", encoding="utf-8")
            (root / ".codegraph" / "index.db").write_text("generated", encoding="utf-8")
            before = build_snapshot(root)

            (root / "src" / "main.py").write_text("updated content", encoding="utf-8")
            (root / "new.py").write_text("new", encoding="utf-8")
            after = build_snapshot(root)

        self.assertNotIn(".codegraph/index.db", after)
        self.assertEqual(changed_paths(before, after), {"src/main.py", "new.py"})


class WatcherTests(unittest.TestCase):
    def test_sync_if_ready_preserves_pending_changes_after_failure(self) -> None:
        calls = []

        def fail_sync(root, codegraph_bin, sync_args):
            calls.append((root, codegraph_bin, sync_args))
            return False

        config = WatchConfig(root=Path.cwd(), debounce=1.0, retry_delay=5.0)
        watcher = AutoSyncWatcher(config, sync_fn=fail_sync)
        state = DebouncedSyncState()
        state.add_changes({"main.py"}, now=0.0)

        self.assertFalse(watcher._sync_if_ready(state, now=1.0))
        self.assertTrue(state.pending)
        self.assertEqual(state.retry_at, 6.0)
        self.assertEqual(len(calls), 1)

    @patch("codegraph_autosync.subprocess.run")
    def test_run_init_uses_current_directory_and_timeout(self, run) -> None:
        run.return_value.returncode = 0
        root = Path.cwd()

        self.assertTrue(run_init(root, "codegraph", timeout=17.0))

        self.assertEqual(run.call_args.args[0], ["codegraph", "init", "."])
        self.assertEqual(run.call_args.kwargs["cwd"], str(root))
        self.assertEqual(run.call_args.kwargs["timeout"], 17.0)

    def test_verbose_is_stored_in_config(self) -> None:
        config = _parse_args(["--verbose"])

        self.assertTrue(config.verbose)


if __name__ == "__main__":
    unittest.main()
