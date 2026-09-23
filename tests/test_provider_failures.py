import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from backend.ai_client import OpenRouterClient, PermanentOpenRouterError
from backend.video_processor import VideoProcessor
from backend.obsidian_transcriber import AudioChunk, ChunkResult
from tests.test_obsidian_transcriber import PartialFailureTranscriber

class ProviderFailureTests(unittest.TestCase):
    def client(self, *payloads):
        session=MagicMock()
        responses=[]
        for payload in payloads:
            r=MagicMock(ok=True,status_code=200); r.json.return_value=payload; responses.append(r)
        session.post.side_effect=responses
        return OpenRouterClient(api_key='test',session=session),session

    def test_http_200_embedded_error_retries_and_discards_partial_text(self):
        client,session=self.client(
            {'id':'failed-id','error':{'code':502,'message':'provider disconnected'},'choices':[{'finish_reason':'error','message':{'content':'partial'}}]},
            {'choices':[{'finish_reason':'stop','message':{'content':'complete'}}]})
        with patch('backend.ai_client.time.sleep'):
            self.assertEqual('complete',client.generate_text('hello').text)
        self.assertEqual(2,session.post.call_count)

    def test_choice_safety_with_empty_content_is_preserved_and_not_retried(self):
        client,session=self.client({'id':'trace-id','provider':'Google','choices':[{
            'finish_reason':'content_filter','native_finish_reason':'SAFETY',
            'error':{'code':403,'message':'SAFETY','metadata':{'error_type':'content_policy_violation'}},
            'message':{'content':''}}]})
        with self.assertRaisesRegex(PermanentOpenRouterError,'content_policy_violation') as raised:
            client.generate_text('hello')
        self.assertIn('trace-id',str(raised.exception))
        self.assertEqual(1,session.post.call_count)

    def test_error_finish_without_error_body_retries(self):
        client,session=self.client({'choices':[{'finish_reason':'error','message':{'content':'partial'}}]},
                                  {'choices':[{'finish_reason':'stop','message':{'content':'ok'}}]})
        with patch('backend.ai_client.time.sleep'):
            self.assertEqual('ok',client.generate_text('hi').text)
        self.assertEqual(2,session.post.call_count)

    def test_permanent_failure_not_retried_at_chunk_layer(self):
        t=PartialFailureTranscriber()
        with patch.object(t,'_gen_text',return_value=ChunkResult(error='403',retryable=False)) as call:
            result=t._transcribe_chunk_with_retry(AudioChunk(Path('x.mp3'),0,10),1)
        self.assertEqual(1,call.call_count)
        self.assertEqual('403',result.error)

    def test_original_language_beats_higher_bitrate_dub_and_keeps_fallbacks(self):
        formats=[
            {'format_id':'dub','language':'ml','format_note':'Malayalam','language_preference':-1,'abr':140,'acodec':'opus','vcodec':'none'},
            {'format_id':'original','language':'en-US','format_note':'English original (default)','language_preference':10,'abr':129,'acodec':'aac','vcodec':'none'},
            {'format_id':'original-low','language':'en-US','abr':64,'acodec':'aac','vcodec':'none'}]
        self.assertEqual(['original','original-low'],VideoProcessor()._build_format_candidates({'formats':formats,'format_id':'dub'},'bestaudio/best'))

    def test_single_language_preserves_bitrate_order(self):
        formats=[{'format_id':str(n),'abr':n,'acodec':'aac','vcodec':'none'} for n in (64,128)]
        self.assertEqual(['128','64'],VideoProcessor()._build_format_candidates({'formats':formats},None))

    def test_checkpoint_signature_invalidates_old_track_selection(self):
        self.assertEqual('original-language-v2',PartialFailureTranscriber()._checkpoint_signature([])['audio_selection_version'])
