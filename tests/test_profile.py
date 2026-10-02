import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import hub_config
import hub_profile


class ProfileTests(unittest.TestCase):
    def test_shared_files_update_live_and_credentials_stay_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'hub'; root.mkdir()
            source = Path(temp) / 'source'; source.mkdir()
            (source / 'skills/demo').mkdir(parents=True)
            (source / 'skills/demo/SKILL.md').write_text('shared skill')
            (source / 'AGENTS.md').write_text('user rules')
            (source / 'auth.json').write_text('source credential fixture')
            home = root / 'work'; home.mkdir()
            (home / 'auth.json').write_text('independent credential fixture')
            (home / 'skills').mkdir()
            (home / 'skills/local.txt').write_text('retained local skill')
            hub_config.save({'schemaVersion': 1, 'defaultAccount': 'work', 'accounts': {'work': {'label': 'Work', 'home': str(home)}}}, root)
            hub_profile.sync(source, root)
            (source / 'AGENTS.md').write_text('changed rules')
            self.assertEqual((home / 'AGENTS.md').read_text(), 'changed rules')
            self.assertEqual((home / 'skills/demo/SKILL.md').read_text(), 'shared skill')
            self.assertEqual((home / 'auth.json').read_text(), 'independent credential fixture')
            self.assertTrue(list(root.glob('profile-backups/*/work/skills/local.txt')))
            hub_config.add('extra', root=root)
            self.assertTrue((hub_config.home('extra', root) / 'skills').is_symlink())

    def test_only_noncredential_preferences_are_forwarded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'; source.mkdir()
            (source / 'config.toml').write_text('model="fixture"\ncli_auth_credentials_store="keyring"\n[plugins."demo@local"]\nenabled=true\n[mcp_servers.private]\nbearer_token="DO_NOT_SHARE"\n')
            hub_config.save({'schemaVersion': 1, 'defaultAccount': 'work', 'profileSource': str(source), 'accounts': {'work': {'label': 'Work', 'home': str(root/'work')}}}, root)
            args = hub_profile.arguments(root)
            self.assertIn('"model"="fixture"', args)
            self.assertIn('"plugins"."demo@local"."enabled"=true', args)
            self.assertNotIn('DO_NOT_SHARE', ' '.join(args))
            self.assertNotIn('credentials', ' '.join(args))


if __name__ == '__main__':
    unittest.main()
