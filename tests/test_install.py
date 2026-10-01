"""Source installation works at a custom prefix and keeps user data on uninstall."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_install_upgrade_uninstall(self):
        with tempfile.TemporaryDirectory(prefix='hub install ') as folder:
            root = Path(folder)
            prefix, state = root/'prefix with spaces', root/'settings'
            backend = root/'codex'
            backend.write_text('#!/bin/sh\nexit 0\n')
            backend.chmod(0o700)
            env = {**os.environ, 'CODEX_HUB_ROOT': str(state), 'CODEX_HUB_PYTHON': sys.executable,
                   'CODEX_HUB_CODEX': str(backend)}
            subprocess.run(['sh',str(REPO/'install.sh'),'--prefix',str(prefix),'--no-deps'],env=env,check=True,capture_output=True)
            launcher = prefix/'bin/codex-hub'
            self.assertEqual(subprocess.check_output([str(launcher),'--version'],env=env,text=True).strip(),(REPO/'VERSION').read_text().strip())
            self.assertTrue((prefix/'share/codex-hub/hub_platform.py').is_file())
            self.assertEqual((state/'tmux.conf').read_text(),(REPO/'tmux.conf').read_text())
            config = state/'config.json'
            data = json.loads(config.read_text())
            data['accounts']['default']['label'] = 'My workspace'
            config.write_text(json.dumps(data))
            marker = state/'saved-chat.txt'
            marker.write_text('retained')
            subprocess.run(['sh',str(REPO/'install.sh'),'--prefix',str(prefix),'--no-deps'],env=env,check=True,capture_output=True)
            self.assertEqual(json.loads(config.read_text())['accounts']['default']['label'],'My workspace')
            subprocess.run(['sh',str(REPO/'uninstall.sh'),'--prefix',str(prefix)],env=env,check=True,capture_output=True)
            self.assertFalse(launcher.exists())
            self.assertFalse((prefix/'share/codex-hub').exists())
            self.assertEqual(marker.read_text(),'retained')
            self.assertTrue(config.exists())
