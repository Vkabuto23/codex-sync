import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import codex_sync


class GitHubAccessTests(unittest.TestCase):
    @patch.object(codex_sync, "require_program", return_value="/usr/bin/gh")
    @patch.object(codex_sync, "run")
    def test_network_failure_is_not_reported_as_logout(self, run, _program):
        run.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="error connecting to api.github.com\ncheck your internet connection",
        )
        with self.assertRaisesRegex(codex_sync.SyncError, "approved system/escalated access"):
            codex_sync.github_username()

    @patch.object(codex_sync, "require_program", return_value="/usr/bin/gh")
    @patch.object(codex_sync, "run")
    def test_http_401_is_reported_as_real_auth_failure(self, run, _program):
        run.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="gh: Bad credentials (HTTP 401)",
        )
        with self.assertRaisesRegex(codex_sync.SyncError, "gh auth login"):
            codex_sync.github_username()

    @patch.object(codex_sync, "require_program", return_value="/usr/bin/gh")
    @patch.object(codex_sync, "run")
    def test_success_returns_valid_login(self, run, _program):
        run.return_value = SimpleNamespace(returncode=0, stdout="Vkabuto23\n", stderr="")
        self.assertEqual(codex_sync.github_username(), "Vkabuto23")
        run.assert_called_once_with(["gh", "api", "user", "--jq", ".login"], check=False)


if __name__ == "__main__":
    unittest.main()
