import tomllib
import unittest
from pathlib import Path


class ProjectConfigTests(unittest.TestCase):
    def test_requests_is_declared_as_direct_dependency(self) -> None:
        data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        dependencies = data["project"]["dependencies"]

        self.assertTrue(
            any(dep.split(">=", 1)[0] == "requests" for dep in dependencies),
            "channel_monitor imports requests directly, so it must be a direct dependency",
        )


if __name__ == "__main__":
    unittest.main()
