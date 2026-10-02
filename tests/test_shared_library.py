"""A shared sidebar must route chats to their owning account."""
import json
import subprocess
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import test_hub
from test_hub import hub


class SharedLibraryIntegration(test_hub.HubIntegration):
    def test_mouse_workflow_and_isolation(self):
        from hub_config import preferences
        preferences(self.root, sharedLibrary=True)
        hub.reload_config()
        hub.setup(reload=True)
        self.wait_for(lambda: all('Saved in ' + slot in self.sidebar_text('1') for slot in ('1', '2', '3')))
        lines = subprocess.run(['tmux', '-S', str(hub.SOCKET), 'capture-pane', '-p',
                                '-t', self.account_window('1')['sidebar']],
                               text=True, capture_output=True, check=True).stdout.splitlines()
        self.sidebar_click('1', 8, next(i for i, line in enumerate(lines) if 'Saved in 3' in line))
        self.wait_for(lambda: (self.root / '3/invoked.json').exists())
        self.wait_for(lambda: hub.tmux('list-clients', '-F', '#{session_name}') == 'codex-sub-3')
        invoked = json.loads((self.root / '3/invoked.json').read_text())
        self.assertEqual(invoked['home'], str(self.root / '3'))
        self.assertIsNone(invoked['api'])
        self.assertEqual(invoked['args'][:2], ['resume', '00000000-0000-0000-0000-000000000003'])
        self.wait_for(lambda: 'Saved in 1' in self.sidebar_text('3'))
        # The same source metadata is read by every account; no DB copy is needed.
        hub.update_state(lambda data: data.setdefault('names', {}).setdefault('1', {}).update(
            {'00000000-0000-0000-0000-000000000001': 'Renamed shared chat'}))
        self.wait_for(lambda: 'Renamed shared chat' in self.sidebar_text('3'))


class SharedLibraryIdentity(unittest.TestCase):
    def test_imported_desktop_history_is_visible_without_legacy_user_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with sqlite3.connect(root / 'state_5.sqlite') as db:
                db.execute('CREATE TABLE threads(id TEXT, title TEXT, cwd TEXT, archived INT, has_user_event INT, updated_at INT)')
                db.execute("INSERT INTO threads VALUES('imported', 'Imported', '/project', 0, 0, 1)")
                db.execute("INSERT INTO threads VALUES('empty', 'New chat', '/project', 0, 0, 1)")
            state = {'chats': {'a': {'imported': {'title': 'Research', 'cwd': '/project',
                                                'has_content': True, 'importedHistory': True}}}}
            with patch.object(hub, 'account_home', return_value=root), patch.object(hub, 'state', return_value=state):
                rows, error = hub.history('a')
            self.assertEqual(error, '')
            self.assertEqual([r['id'] for r in rows], ['imported'])

    def test_identical_thread_ids_do_not_merge_accounts_or_pins(self):
        sidebar = hub.Sidebar.__new__(hub.Sidebar)
        sidebar.fields = {}
        sidebar.data = {'pins': {'a': ['same'], 'b': []}}
        sidebar.live = []
        sidebar.saved = [{'slot': slot, 'id': 'same', 'title': slot, 'cwd': '/project', 'updated_at': 1}
                         for slot in ('a', 'b')]
        sidebar.projects = ['/project']
        sidebar.collapsed = []
        sidebar.archived = False
        rows = sidebar.rows()
        self.assertEqual([(r[2]['slot'], r[1]) for r in rows if r[0] == 'saved'], [('a', 'a'), ('b', 'b')])
        self.assertEqual(next(i for i, r in enumerate(rows) if r[1] == 'Pinned'), 0)
        self.assertGreater(next(i for i, r in enumerate(rows) if r[1] == 'b'),
                           next(i for i, r in enumerate(rows) if r[0] == 'folder'))
