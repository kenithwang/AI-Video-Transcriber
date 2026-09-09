import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class UpdateRollbackTests(unittest.TestCase):
    def test_failed_install_restores_lock_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy('update_ytdlp.sh', root)
            for name in ('pyproject.toml', '.python-version'):
                (root / name).write_text('fixture')
            (root / 'uv.lock').write_text('old lock')
            (root / '.venv').mkdir()
            (root / '.venv/marker').write_text('working environment')
            fake = root / 'fake-uv'
            fake.write_text("""#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
if '--directory' in args:
    stage = Path(args[args.index('--directory') + 1])
    if args[0] == 'lock':
        (stage / 'uv.lock').write_text('new lock')
    else:
        binary = Path(os.environ['UV_PROJECT_ENVIRONMENT']) / 'bin/python'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\\nexit 0\\n'.replace('\\n', chr(10)))
        binary.chmod(0o755)
else:
    (Path('.venv') / 'marker').write_text('broken environment')
    sys.exit(1)
""")
            fake.chmod(0o755)
            result = subprocess.run(['bash', str(root / 'update_ytdlp.sh')], env={**os.environ, 'UV': str(fake)}, capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual('old lock', (root / 'uv.lock').read_text())
            self.assertEqual('working environment', (root / '.venv/marker').read_text())
            self.assertIn('restored previous', (root / 'temp/update_ytdlp.log').read_text())
