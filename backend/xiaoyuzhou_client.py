"""Read-only Xiaoyuzhou podcast client with RSSHub fallback."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from defusedxml import ElementTree as ET

import requests


API_BASE = "https://api.xiaoyuzhoufm.com"
PODCAST_ID_RE = re.compile(r"^[a-f0-9]{24}$")
PODCAST_PATH_RE = re.compile(r"/podcast/([a-f0-9]{24})(?:/|$)")


def parse_podcast_id(value: str) -> Optional[str]:
    """Return a 24-character podcast id from an id or public podcast URL."""
    value = (value or "").strip().lower()
    if PODCAST_ID_RE.fullmatch(value):
        return value
    parsed = urlparse(value)
    if not parsed.hostname or not (
        parsed.hostname == "xiaoyuzhoufm.com"
        or parsed.hostname.endswith(".xiaoyuzhoufm.com")
    ):
        return None
    match = PODCAST_PATH_RE.search(parsed.path)
    return match.group(1) if match else None


def _duration_seconds(value: str) -> int:
    value = (value or "").strip()
    if not value:
        return 0
    if value.isdigit():
        return int(value)
    try:
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return 0
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def _child_text(element: ET.Element, local_name: str) -> str:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == local_name:
            return (child.text or "").strip()
    return ""


def parse_rss_episodes(content: str, podcast_id: str) -> list[dict[str, Any]]:
    """Normalize an RSSHub Xiaoyuzhou feed into episode dictionaries."""
    root = ET.fromstring(content)
    channel = next(
        (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "channel"),
        None,
    )
    if channel is None:
        raise ValueError("RSS feed does not contain a channel")
    podcast_title = _child_text(channel, "title") or "Unknown Podcast"
    episodes: list[dict[str, Any]] = []
    for item in channel:
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        link = _child_text(item, "link")
        match = re.search(r"/episode/([a-f0-9]{24})(?:/|$)", link)
        if not match:
            continue
        enclosure_url = ""
        for child in item:
            if child.tag.rsplit("}", 1)[-1] == "enclosure":
                enclosure_url = child.attrib.get("url", "")
                break
        pub_date = _child_text(item, "pubDate")
        if pub_date:
            try:
                pub_date = parsedate_to_datetime(pub_date).isoformat()
            except (TypeError, ValueError):
                pass
        episodes.append(
            {
                "eid": match.group(1),
                "pid": podcast_id,
                "podcast_title": podcast_title,
                "title": _child_text(item, "title") or "Untitled Episode",
                "duration": _duration_seconds(_child_text(item, "duration")),
                "pub_date": pub_date,
                "audio_url": enclosure_url,
                "episode_url": link,
            }
        )
    return episodes


class XiaoyuzhouClient:
    """Minimal read-only client for subscription monitoring."""

    def __init__(
        self,
        token_file: Path | str | None = None,
        session: requests.Session | None = None,
        rsshub_base_url: str | None = None,
        rsshub_key: str | None = None,
        timeout: int = 30,
    ) -> None:
        configured_token = os.getenv("XIAOYUZHOU_TOKEN_FILE")
        self.token_file = Path(
            token_file
            or configured_token
            or Path.home() / ".local/state/xiaoyuzhou/token.json"
        ).expanduser()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.rsshub_base_url = (
            rsshub_base_url
            if rsshub_base_url is not None
            else os.getenv("RSSHUB_BASE_URL", "http://127.0.0.1:1200")
        ).rstrip("/")
        self.rsshub_key = (
            rsshub_key if rsshub_key is not None else os.getenv("RSSHUB_KEY", "")
        )
        self.credentials = self._load_credentials()

    def _load_credentials(self) -> dict[str, Any]:
        if not self.token_file.exists():
            return {}
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Unable to read Xiaoyuzhou credentials") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Invalid Xiaoyuzhou credential format")
        return data

    def _save_credentials(self) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp_name = tempfile.mkstemp(
            dir=self.token_file.parent, prefix=".xiaoyuzhou-", suffix=".tmp"
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.credentials, handle, ensure_ascii=False, indent=2)
            os.replace(temp_name, self.token_file)
            os.chmod(self.token_file, 0o600)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _headers(self, access_token: str | None = None) -> dict[str, str]:
        headers = {
            "os": "android",
            "os-version": "28",
            "manufacturer": "Xiaomi",
            "model": "MI 6",
            "applicationid": "app.podcast.cosmos",
            "app-version": "2.99.1",
            "app-buildno": "1362",
            "User-Agent": "Xiaoyuzhou/2.99.1(android 28)",
            "content-type": "application/json;charset=utf-8",
        }
        device_id = self.credentials.get("device_id")
        if not device_id:
            device_id = str(uuid.uuid4())
            self.credentials["device_id"] = device_id
        headers["x-jike-device-id"] = device_id
        if access_token:
            headers["x-jike-access-token"] = access_token
        return headers

    def _refresh(self) -> None:
        refresh_token = self.credentials.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Xiaoyuzhou login expired; SMS login is required")
        headers = self._headers()
        headers["x-jike-refresh-token"] = refresh_token
        response = self.session.post(
            f"{API_BASE}/app_auth_tokens.refresh",
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise RuntimeError("Unable to refresh Xiaoyuzhou login")
        body = response.json() if response.text else {}
        access = response.headers.get("x-jike-access-token") or body.get(
            "x-jike-access-token"
        )
        new_refresh = response.headers.get("x-jike-refresh-token") or body.get(
            "x-jike-refresh-token"
        )
        if not access:
            raise RuntimeError("Xiaoyuzhou refresh response did not contain a token")
        self.credentials["access_token"] = access
        if new_refresh:
            self.credentials["refresh_token"] = new_refresh
        self._save_credentials()

    def _api_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = self.credentials.get("access_token")
        if not access_token:
            raise RuntimeError("Xiaoyuzhou is not logged in")

        def request() -> requests.Response:
            return self.session.post(
                f"{API_BASE}{path}",
                headers=self._headers(self.credentials.get("access_token")),
                json=payload,
                timeout=self.timeout,
            )

        response = request()
        if response.status_code == 401:
            self._refresh()
            response = request()
        if response.status_code != 200:
            raise RuntimeError(f"Xiaoyuzhou API returned HTTP {response.status_code}")
        return response.json()

    def list_episodes(
        self, podcast_id: str, limit: int | None = 30
    ) -> list[dict[str, Any]]:
        """List newest episodes, following the API cursor when needed."""
        if not parse_podcast_id(podcast_id):
            raise ValueError("Invalid Xiaoyuzhou podcast id")
        episodes: list[dict[str, Any]] = []
        load_more_key: Any = None
        while True:
            payload: dict[str, Any] = {
                "pid": podcast_id,
                "limit": "25",
                "order": "desc",
            }
            if load_more_key:
                payload["loadMoreKey"] = load_more_key
            data = self._api_post("/v1/episode/list", payload)
            page = data.get("data") or []
            for raw in page:
                podcast = raw.get("podcast") or {}
                media = raw.get("media") or {}
                source = media.get("source") or {}
                enclosure = raw.get("enclosure") or {}
                eid = raw.get("eid")
                if not eid:
                    continue
                episodes.append(
                    {
                        "eid": eid,
                        "pid": podcast.get("pid") or podcast_id,
                        "podcast_title": podcast.get("title") or "Unknown Podcast",
                        "title": raw.get("title") or "Untitled Episode",
                        "duration": raw.get("duration") or 0,
                        "pub_date": raw.get("pubDate") or "",
                        "audio_url": source.get("url") or enclosure.get("url") or "",
                        "episode_url": f"https://www.xiaoyuzhoufm.com/episode/{eid}",
                    }
                )
                if limit is not None and len(episodes) >= limit:
                    return episodes[:limit]
            load_more_key = data.get("loadMoreKey")
            if not page or not load_more_key:
                break
        return episodes

    def list_episodes_with_fallback(
        self, podcast_id: str, limit: int | None = 30
    ) -> list[dict[str, Any]]:
        """Use the account API first and local RSSHub when auth/API fails."""
        try:
            return self.list_episodes(podcast_id, limit=limit)
        except (requests.RequestException, RuntimeError):
            if not self.rsshub_base_url:
                raise
        params = {"key": self.rsshub_key} if self.rsshub_key else None
        response = self.session.get(
            f"{self.rsshub_base_url}/xiaoyuzhou/podcast/{podcast_id}",
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=max(self.timeout, 60),
        )
        if response.status_code != 200:
            raise RuntimeError(f"RSSHub returned HTTP {response.status_code}")
        episodes = parse_rss_episodes(response.text, podcast_id)
        return episodes if limit is None else episodes[:limit]
