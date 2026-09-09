"""Refresh the yt-dlp cookie file from a read-only master copy."""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def is_youtube_auth_error(url: str, error: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or '').lower()
    youtube = host == 'youtu.be' or host == 'youtube.com' or host.endswith('.youtube.com')
    return youtube and any(marker in error.lower() for marker in (
        'sign in to confirm', 'cookies are no longer valid',
        'cookies have expired', 'login required',
    ))


def expired_login_fields(cookie_path: Path) -> list[str]:
    """Inspect expiry without returning cookie values; zero means session cookie."""
    fields: dict[str, list[int]] = {}
    for line in cookie_path.read_text(encoding='utf-8').splitlines():
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
        elif line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) != 7 or parts[0].lstrip('.') not in ('youtube.com', 'www.youtube.com'):
            continue
        if parts[5] in ('LOGIN_INFO', 'SID', 'SAPISID', '__Secure-1PSID', '__Secure-3PSID'):
            try:
                fields.setdefault(parts[5], []).append(int(parts[4]))
            except ValueError:
                continue
    now = time.time()
    return sorted(name for name, expires in fields.items()
                  if all(expiry != 0 and expiry <= now for expiry in expires))


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
        try:
            expired = expired_login_fields(cookie_path)
            if expired:
                logger.warning('YouTube Cookie 登录字段已过期：%s；请更新 Cookie 主文件', ', '.join(expired))
        except (OSError, UnicodeError):
            logger.warning('无法检查 YouTube Cookie 文件有效期：%s', cookie_path)
        return cookie_path
    return None
