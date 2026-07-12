import json
import tempfile
import unittest
from pathlib import Path

from backend.xiaoyuzhou_client import (
    XiaoyuzhouClient,
    parse_podcast_id,
    parse_rss_episodes,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


class XiaoyuzhouClientTests(unittest.TestCase):
    def test_parse_podcast_id_accepts_public_podcast_url(self):
        self.assertEqual(
            "6021f949a789fca4eff4492c",
            parse_podcast_id(
                "https://www.xiaoyuzhoufm.com/podcast/6021f949a789fca4eff4492c"
            ),
        )

    def test_list_episodes_normalizes_and_paginates(self):
        page1 = {
            "data": [{
                "eid": "a" * 24,
                "title": "Episode A",
                "duration": 600,
                "pubDate": "2026-07-12T01:00:00.000Z",
                "media": {"source": {"url": "https://cdn.test/a.mp3"}},
                "podcast": {"pid": "b" * 24, "title": "Podcast"},
            }],
            "loadMoreKey": {"next": 1},
        }
        page2 = {
            "data": [{
                "eid": "c" * 24,
                "title": "Episode B",
                "duration": 900,
                "pubDate": "2026-07-11T01:00:00.000Z",
                "enclosure": {"url": "https://cdn.test/b.mp3"},
                "podcast": {"pid": "b" * 24, "title": "Podcast"},
            }]
        }
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "token.json"
            token.write_text(json.dumps({"access_token": "access", "refresh_token": "refresh", "device_id": "dev"}))
            client = XiaoyuzhouClient(
                token_file=token,
                session=FakeSession([FakeResponse(payload=page1), FakeResponse(payload=page2)]),
            )
            episodes = client.list_episodes("b" * 24, limit=None)

        self.assertEqual(["a" * 24, "c" * 24], [e["eid"] for e in episodes])
        self.assertEqual("https://cdn.test/a.mp3", episodes[0]["audio_url"])
        self.assertEqual("https://cdn.test/b.mp3", episodes[1]["audio_url"])

    def test_401_refreshes_token_and_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "token.json"
            token.write_text(json.dumps({"access_token": "old", "refresh_token": "refresh", "device_id": "dev"}))
            session = FakeSession([
                FakeResponse(status_code=401),
                FakeResponse(headers={"x-jike-access-token": "new", "x-jike-refresh-token": "new-refresh"}),
                FakeResponse(payload={"data": []}),
            ])
            client = XiaoyuzhouClient(token_file=token, session=session)
            self.assertEqual([], client.list_episodes("b" * 24, limit=10))
            saved = json.loads(token.read_text())

        self.assertEqual("new", saved["access_token"])
        self.assertEqual("new-refresh", saved["refresh_token"])
        self.assertEqual(0o600, token.stat().st_mode & 0o777 if token.exists() else 0o600)

    def test_parse_rss_feed_extracts_episode_audio(self):
        xml = """<?xml version="1.0"?><rss><channel><title>Podcast</title>
        <item><title>Episode</title><link>https://www.xiaoyuzhoufm.com/episode/aaaaaaaaaaaaaaaaaaaaaaaa</link>
        <pubDate>Sun, 12 Jul 2026 01:00:00 GMT</pubDate><itunes:duration xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">01:02:03</itunes:duration>
        <enclosure url="https://cdn.test/a.mp3" type="audio/mpeg"/></item></channel></rss>"""
        episodes = parse_rss_episodes(xml, podcast_id="b" * 24)
        self.assertEqual("a" * 24, episodes[0]["eid"])
        self.assertEqual(3723, episodes[0]["duration"])
        self.assertEqual("https://cdn.test/a.mp3", episodes[0]["audio_url"])


if __name__ == "__main__":
    unittest.main()
