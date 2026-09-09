import tempfile
import unittest
from pathlib import Path
from backend.youtube_cookies import expired_login_fields, is_youtube_auth_error


class CookieHealthTests(unittest.TestCase):
    def test_expiry_handles_http_only_session_and_other_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'cookies.txt'
            p.write_text('# Netscape HTTP Cookie File\n'
                         '#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1\tSID\tsecret\n'
                         '.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tsecret\n'
                         '.example.com\tTRUE\t/\tTRUE\t1\tLOGIN_INFO\tsecret\n')
            self.assertEqual(['SID'], expired_login_fields(p))

    def test_auth_detection_is_scoped_to_youtube(self):
        error = "Sign in to confirm you're not a bot"
        self.assertTrue(is_youtube_auth_error('https://www.youtube.com/watch?v=x', error))
        self.assertFalse(is_youtube_auth_error('https://notyoutube.com/watch?v=x', error))
        self.assertFalse(is_youtube_auth_error('https://youtube.com/watch?v=x', 'Video unavailable'))
