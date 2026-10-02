import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import hub_control as control


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = {'accounts': {'work': {'home': str(self.root / 'home')}}}
        self.tasks = [{'account': 'work', 'thread': 'chat', 'prompt': 'Continue the assigned goal.'}]
        self.window = {'slot': 'work', 'thread': 'chat', 'busy': '0', 'control': '1'}
        self.last = {'work:chat': {'busy': '0', 'at': time.time() - 3600}}
        self.reloaded = []

    def tearDown(self):
        self.temp.cleanup()

    def check(self, status='active'):
        with patch.object(control, 'goal', return_value={'status': status}):
            return control.check(self.root, self.config, self.tasks, lambda: [self.window],
                                 self.reloaded.append, self.last)

    def test_busy_paused_complete_and_limits_never_resume(self):
        for status in ('paused', 'complete', 'usageLimited', 'budgetLimited', 'blocked'):
            self.check(status)
        self.window['busy'] = '1'
        self.check()
        self.assertFalse(list(self.root.rglob('*.pending')))

    def test_stalled_active_goal_requests_one_continuation(self):
        self.assertEqual(self.check()[0]['goal'], 'continuation requested')
        self.last['work:chat']['at'] -= 3600
        self.check()
        self.assertEqual(len(list(self.root.rglob('*.pending'))), 1)
        command = json.loads(next(self.root.rglob('*.pending')).read_text())
        self.assertTrue(command['requireActive'])

    def test_drafts_queues_and_uncertain_dispatch_are_preserved(self):
        state = self.root / 'tui-state/work/chat.json'
        state.parent.mkdir(parents=True)
        for saved in ({'draft': {'text': 'User draft'}}, {'queues': {'work:chat': ['queued']}}):
            state.write_text(json.dumps(saved))
            self.last['work:chat']['at'] -= 3600
            self.check()
            self.assertFalse(list(self.root.rglob('*.pending')))
        state.write_text('{}')
        control.write(control.directory(self.root, 'work', 'chat') / 'old.result', {'status': 'uncertain'})
        self.last['work:chat']['at'] -= 3600
        self.assertIn('manual check', self.check()[0]['goal'])
        self.assertFalse(list(self.root.rglob('*.pending')))

    def test_old_frontend_reloads_only_after_idle_checks(self):
        self.window['control'] = ''
        self.check()
        self.assertEqual(self.reloaded, [self.window])
        self.assertFalse(list(self.root.rglob('*.pending')))

    def test_failover_requires_verified_capacity_and_preserves_pause(self):
        config = {'accounts': {'work': {'home': str(self.root/'work')}, 'spare': {'home': str(self.root/'spare')}}}
        plan = {'tasks': self.tasks}
        moved = []
        def transfer(source, target, thread):
            moved.append((source, target, thread))
            return {'goal': {'objective': 'Same existing objective'}}
        with patch.object(control, 'goal', return_value={'status': 'paused'}):
            control.failover(self.root, plan, config, {'work': {'remainingPercent': 0}, 'spare': {'remainingPercent': 80}}, lambda:[self.window], transfer)
        self.assertFalse(moved)
        with patch.object(control, 'goal', return_value={'status': 'usageLimited'}):
            control.failover(self.root, plan, config, {'work': {'remainingPercent': 0}, 'spare': {'error': 'unavailable'}}, lambda:[self.window], transfer)
            self.assertFalse(moved)
            control.failover(self.root, plan, config, {'work': {'remainingPercent': 0}, 'spare': {'remainingPercent': 80}}, lambda:[self.window], transfer)
        self.assertEqual(moved, [('work', 'spare', 'chat')])
        self.assertEqual(plan['tasks'][0]['account'], 'spare')


if __name__ == '__main__':
    unittest.main()
