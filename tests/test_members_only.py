import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import cli
from backend.channel_monitor import ChannelMonitor, VideoInfo
from backend.processed_store import ProcessedStore
from tests.test_failure_backoff import FakeYoutubeDL


class MembersOnlyTests(unittest.TestCase):
    def test_membership_restriction_is_persisted_and_removed_from_digest(self):
        for stage in ('probe', 'download'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config = root / 'channels.yaml'
                config.write_text('settings:\n  processing_delay: 0\nchannels:\n  - url: https://www.youtube.com/@demo\n    name: Demo\n')
                monitor = ChannelMonitor(config, store_path=root / 'processed.json')
                monitor._digest_path = root / 'digest.json'
                monitor._digest_path.write_text(json.dumps({'processed': {}, 'failed': {'v1': {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}}))
                video = VideoInfo(video_id='v1', url='https://www.youtube.com/watch?v=v1', title='Members', channel_id='demo', channel_name='Demo', upload_date=datetime.now(), duration=600)
                error = RuntimeError('Join this channel to get access to members-only content like this video, and other exclusive perks.')
                process = AsyncMock(side_effect=error)
                with patch.object(monitor, 'fetch_channel_videos', return_value=[video]), patch('backend.channel_monitor.prepare_youtube_cookiefile', return_value=None), patch('backend.channel_monitor.yt_dlp.YoutubeDL', FakeYoutubeDL), patch.object(FakeYoutubeDL, 'extract_info', side_effect=error if stage == 'probe' else None, return_value={'is_live': False}), patch('backend.pipeline.process_video', process):
                    result = asyncio.run(monitor.run_check(root))
                self.assertEqual(1, result['videos_skipped'])
                self.assertEqual(0, result['videos_processed'])
                self.assertEqual(stage == 'download', process.called)
                self.assertFalse((root / 'failed_videos.log').exists())
                self.assertEqual({}, json.loads(monitor._digest_path.read_text())['failed'])
                store = ProcessedStore(root / 'processed.json')
                self.assertTrue(store.is_processed('v1'))
                self.assertEqual('members_only', store.get_video_info('v1')['skip_reason'])
                self.assertTrue(store.get_video_info('v1')['sent'])
                self.assertEqual(0, store.get_failure_count('v1'))

    def test_unrelated_errors_are_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'channels.yaml'
            config.write_text('channels: []')
            monitor = ChannelMonitor(config, store_path=root / 'processed.json')
            video = VideoInfo(video_id='v1', url='https://www.youtube.com/watch?v=v1', title='Video', channel_id='demo', channel_name='Demo', upload_date=datetime.now(), duration=600)
            for error in ('Sign in to confirm you’re not a bot', 'HTTP Error 403', 'Private video', 'This video is unavailable'):
                self.assertFalse(monitor._skip_members_only(video, error))
            self.assertFalse(monitor.store.is_processed('v1'))

    def test_watch_statistics_do_not_count_skips_as_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'channels.yaml'
            config.write_text('channels: []')
            monitor = ChannelMonitor(config, store_path=root / 'processed.json')
            summary = dict(channels_checked=1, new_videos_found=1, videos_processed=0, videos_skipped=1, videos_sent=0, channel_errors=0, errors=[])
            with patch('backend.channel_monitor.ChannelMonitor', return_value=monitor), patch.object(monitor, 'run_check', AsyncMock(return_value=summary)):
                stats = asyncio.run(cli.run_watch_mode(config, root, None, False, False))
            self.assertEqual(0, stats['failed'])
            self.assertFalse(cli.watch_run_failed(stats))
            self.assertEqual('SUCCESS', cli.classify_watch_outcome(found=stats['found'], processed=stats['processed'], failed=stats['failed'], channel_errors=stats['channel_errors']))
