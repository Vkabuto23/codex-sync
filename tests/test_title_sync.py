import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import codex_sync


THREAD_ID = "019ffcfe-62da-7a60-ac89-2e6852cb326a"


class TitleSyncPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            codex_sync.os.environ,
            {"CODEX_SYNC_LOCAL_STATE_DIR": self.temporary.name},
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def test_decline_is_local_to_thread_and_persistent(self):
        self.assertFalse(codex_sync.title_sync_declined(THREAD_ID))
        path = codex_sync.set_title_sync_declined(THREAD_ID, True)
        self.assertIsNotNone(path)
        self.assertTrue(codex_sync.title_sync_declined(THREAD_ID))
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(payload, {"thread": THREAD_ID, "declined": True})

    def test_accept_clears_previous_decline(self):
        codex_sync.set_title_sync_declined(THREAD_ID, True)
        codex_sync.set_title_sync_declined(THREAD_ID, False)
        self.assertFalse(codex_sync.title_sync_declined(THREAD_ID))

    @patch.object(codex_sync, "emit")
    @patch.object(codex_sync, "app_server_thread_title", return_value="Похожий чат")
    @patch.object(codex_sync, "get_thread_id", return_value=THREAD_ID)
    def test_decline_command_records_do_not_ask_again(self, _thread, _title, emit):
        args = argparse.Namespace(
            thread_id=None,
            project="base project",
            chat="Исходный чат",
            accept=False,
            decline=True,
        )
        codex_sync.cmd_title_sync(args)
        self.assertTrue(codex_sync.title_sync_declined(THREAD_ID))
        self.assertFalse(emit.call_args.args[0]["ask_again_in_this_chat"])

    @patch.object(codex_sync, "emit")
    @patch.object(codex_sync, "app_server_set_thread_title", return_value="Исходный чат")
    @patch.object(codex_sync, "get_thread_id", return_value=THREAD_ID)
    def test_accept_command_renames_and_clears_decline(self, _thread, rename, emit):
        codex_sync.set_title_sync_declined(THREAD_ID, True)
        args = argparse.Namespace(
            thread_id=None,
            project="base project",
            chat="Исходный чат",
            accept=True,
            decline=False,
        )
        codex_sync.cmd_title_sync(args)
        rename.assert_called_once_with(THREAD_ID, "Исходный чат")
        self.assertFalse(codex_sync.title_sync_declined(THREAD_ID))
        self.assertEqual(emit.call_args.args[0]["action"], "renamed")

    @patch.object(codex_sync, "emit")
    @patch.object(codex_sync, "app_server_set_thread_title", return_value="Исходный чат")
    @patch.object(codex_sync, "get_thread_id", return_value=THREAD_ID)
    def test_empty_restore_renames_automatically(self, _thread, rename, emit):
        repo = Path(self.temporary.name) / "state-repo"
        target = repo / "projects" / "base project" / "Исходный чат"
        target.mkdir(parents=True)
        for name in ("sync.md", "context.md", "links.md"):
            (target / name).write_text(f"# {name}\n", encoding="utf-8")
        context = codex_sync.RepoContext(
            username="owner",
            full_name="owner/owner-codex-sync",
            url="https://example.invalid/state",
            path=repo,
        )
        args = argparse.Namespace(
            project="base project",
            chat="Исходный чат",
            current_project="base project",
            current_chat=None,
            project_root=None,
            thread_id=None,
            empty_chat=True,
        )
        with patch.object(codex_sync, "ensure_repository", return_value=context):
            codex_sync.cmd_restore(args)
        rename.assert_called_once_with(THREAD_ID, "Исходный чат")
        alignment = emit.call_args.args[0]["title_alignment"]
        self.assertTrue(alignment["renamed_empty_chat"])
        self.assertTrue(alignment["matches"])


if __name__ == "__main__":
    unittest.main()
