"""Portable configuration and native Markdown behavior checks."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import hub_config
from hub_markdown import render


class ConfigTests(unittest.TestCase):
    def test_explicit_backend_and_scroll_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            hub_config.initialize(root)
            hub_config.preferences(root, codexBinary=sys.executable, scrollLines=3)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(hub_config.executable(root), sys.executable)
            self.assertEqual(hub_config.load(root)['scrollLines'], 3)
            with self.assertRaises(ValueError):
                hub_config.preferences(root, scrollLines=0)

    def test_arbitrary_accounts_and_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            hub_config.initialize(root)
            for ident in ('personal', 'work', 'sandbox', 'extra', 'fifth'):
                hub_config.add(ident, label=ident.title(), root=root)
            hub_config.update('work', label='Work', default=True, root=root)
            data = hub_config.load(root)
            self.assertEqual(data['defaultAccount'], 'work')
            self.assertEqual(len(data['accounts']), 6)
            self.assertEqual(hub_config.home('work', root), root / 'accounts/work')
            self.assertEqual(hub_config.session('personal', root), 'codex-hub-personal')
            hub_config.remove('work', root)
            self.assertTrue((root / 'accounts/work/config.toml').is_file())
            self.assertEqual(hub_config.load(root)['defaultAccount'], 'default')
            with self.assertRaises(ValueError):
                hub_config.add('../escape', root=root)

    def test_legacy_homes_are_discovered_without_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name in ('1', '2', '10'):
                directory = root / name
                directory.mkdir()
                (directory / 'config.toml').write_text('')
            config = hub_config.initialize(root)
            self.assertEqual(set(config['accounts']), {'1', '2', '10'})
            self.assertEqual(hub_config.session('10', root), 'codex-sub-10')
            self.assertEqual(config['accounts']['10']['label'], 'Account 10')

    def test_bad_config_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / 'config.json').write_text('{broken')
            with self.assertRaisesRegex(ValueError, 'Invalid JSON'):
                hub_config.load(root)


class MarkdownTests(unittest.TestCase):
    def test_native_styling_tables_code_and_links(self):
        markdown = '# Heading\n\n**Bold** and *italic*, `code` and [Docs](https://example.com/docs).\n\n> Quoted text\n\n- First\n- Second\n\n```python\nprint("hello")\n```\n\n| Item | State |\n| --- | --- |\n| Chat | Ready |'
        lines = render(markdown, 54)
        segments = [segment for line in lines for segment in line]
        text = '\n'.join(''.join(s.text for s in line) for line in lines)
        self.assertNotIn('**', text)
        self.assertNotIn('```', text)
        self.assertIn('Heading', text)
        self.assertIn('Quoted text', text)
        self.assertIn('Ready', text)
        self.assertTrue(any(s.style and s.style.bold and 'Bold' in s.text for s in segments))
        self.assertTrue(any(s.style and s.style.italic and 'italic' in s.text for s in segments))
        self.assertTrue(any(s.style and s.style.link == 'https://example.com/docs' for s in segments))
        self.assertTrue(any(s.style and s.style.color and 'print' in s.text for s in segments))
        self.assertTrue(all(sum(s.cell_length for s in line) <= 54 for line in lines))
