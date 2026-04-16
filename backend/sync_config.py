import os
from collections.abc import Mapping
from pathlib import Path


RCLONE_REMOTE_PATH_ENV = "RCLONE_REMOTE_PATH"


def get_rclone_remote_path(env: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if env is None else env
    value = source.get(RCLONE_REMOTE_PATH_ENV, "")
    remote_path = value.strip()
    return remote_path or None


def build_rclone_copy_command(
    local_path: Path,
    env: Mapping[str, str] | None = None,
) -> list[str] | None:
    remote_path = get_rclone_remote_path(env)
    if not remote_path:
        return None
    return ["rclone", "copy", str(local_path), remote_path]
