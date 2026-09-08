"""Refresh the yt-dlp cookie file from a read-only master copy."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def prepare_youtube_cookiefile(
    cookiefile: Optional[str] = None,
    master: Optional[str] = None,
) -> Optional[Path]:
    """Copy the master cookie file over the runtime file and return that path.

    yt-dlp writes back into cookiefile. Keep login cookies in YDL_COOKIE_MASTER
    and hand yt-dlp a disposable copy at YDL_COOKIEFILE.
    """
    cookiefile = cookiefile if cookiefile is not None else os.getenv("YDL_COOKIEFILE")
    master = master if master is not None else os.getenv("YDL_COOKIE_MASTER")
    if not cookiefile:
        return None

    cookie_path = Path(cookiefile).expanduser()
    if master:
        master_path = Path(master).expanduser()
        if master_path.exists():
            cookie_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(master_path, cookie_path)
            try:
                os.chmod(cookie_path, 0o600)
            except OSError:
                pass
        else:
            logger.warning("YDL_COOKIE_MASTER 指定的文件不存在: %s", master_path)

    if cookie_path.exists():
        return cookie_path
    return None
