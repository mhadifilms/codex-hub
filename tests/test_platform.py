"""OS integration commands preserve Unicode and never interpolate shell input."""
import base64
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import hub_platform


class PlatformTests(unittest.TestCase):
    def test_macos_open_and_clipboard(self):
        with patch.object(hub_platform.sys, 'platform', 'darwin'), patch.object(hub_platform.shutil, 'which', return_value='/usr/bin/open'):
            self.assertEqual(hub_platform.open_command('/tmp/a b.png'), ['open','/tmp/a b.png'])
            self.assertEqual(hub_platform.open_command('/tmp/a b.txt', True), ['open','-t','/tmp/a b.txt'])
            self.assertEqual(hub_platform.clipboard_command(), ['pbcopy'])

    def test_linux_desktop_and_headless(self):
        with patch.object(hub_platform.sys, 'platform', 'linux'), patch.dict(hub_platform.os.environ, {}, clear=True):
            with patch.object(hub_platform.shutil, 'which', side_effect=lambda name: name if name in ('xdg-open','wl-copy') else None):
                self.assertEqual(hub_platform.open_command('https://example.com'), ['xdg-open','https://example.com'])
                self.assertEqual(hub_platform.clipboard_command(), ['wl-copy'])
            with patch.object(hub_platform.shutil, 'which', return_value=None):
                self.assertIsNone(hub_platform.clipboard_command())
                with self.assertRaises(ValueError): hub_platform.open_command('https://example.com')

    def test_wsl_path_and_literal_opening(self):
        with patch.object(hub_platform.sys, 'platform', 'linux'), patch.dict(hub_platform.os.environ, {'WSL_DISTRO_NAME':'Ubuntu'}, clear=True), patch.object(hub_platform.shutil, 'which', side_effect=lambda name: name if name == 'powershell.exe' else None):
            path = "/home/test/a';$(calc).png"
            with patch.object(hub_platform.subprocess, 'check_output', return_value="C:\\a';$(calc).png\n") as convert:
                args = hub_platform.open_command(path)
                convert.assert_called_once_with(['wslpath','-w',path],text=True)
            self.assertEqual(args[:4],['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand'])
            decoded = base64.b64decode(args[4]).decode('utf-16-le')
            self.assertEqual(decoded,"Start-Process -FilePath 'C:\\a'';$(calc).png'")
            self.assertIn('InputEncoding',hub_platform.clipboard_command()[-1])
            url_args = hub_platform.open_command('https://example.com/a?b=1&c=2')
            self.assertIn("'https://example.com/a?b=1&c=2'",base64.b64decode(url_args[4]).decode('utf-16-le'))
