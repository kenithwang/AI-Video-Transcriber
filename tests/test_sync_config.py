import unittest
from pathlib import Path

from backend.sync_config import build_rclone_copy_command, get_rclone_remote_path


class SyncConfigTests(unittest.TestCase):
    def test_remote_path_is_disabled_by_default(self) -> None:
        env = {}
        self.assertIsNone(get_rclone_remote_path(env))
        self.assertIsNone(build_rclone_copy_command(Path("note.md"), env))

    def test_remote_path_comes_from_environment(self) -> None:
        env = {"RCLONE_REMOTE_PATH": "remote:folder/subfolder/"}
        self.assertEqual("remote:folder/subfolder/", get_rclone_remote_path(env))
        self.assertEqual(
            ["rclone", "copy", "note.md", "remote:folder/subfolder/"],
            build_rclone_copy_command(Path("note.md"), env),
        )


if __name__ == "__main__":
    unittest.main()
