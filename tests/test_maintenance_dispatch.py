"""Public maintenance dispatch stays outside accounts and requires a guarded switch."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CORE = Path(__file__).resolve().parents[1] / 'core/claude-switch.sh'


class MaintenanceDispatchTests(unittest.TestCase):
    def invoke(self, arguments, helper_exit=0):
        with tempfile.TemporaryDirectory(prefix='maintenance-dispatch-') as folder:
            home = Path(folder)
            base = home / '.claude-switcher'
            base.mkdir()
            marker = base / 'calls.json'
            (base / 'local-maintenance.py').write_text(
                'import json, sys\nfrom pathlib import Path\n'
                'args=sys.argv[1:]\n'
                'Path(__file__).with_name("calls.json").write_text(json.dumps(args))\n'
                'print(json.dumps(args))\n'
                'raise SystemExit(' + str(helper_exit) + ')\n')
            result = subprocess.run(['/bin/bash', str(CORE)] + arguments,
                                    env=dict(os.environ, HOME=str(home), CLAUDE_SWITCHER_MAINTENANCE_FD=''),
                                    capture_output=True, text=True, timeout=10)
            calls = json.loads(marker.read_text()) if marker.exists() else None
            self.assertFalse((base / 'accounts').exists())
            return result, calls

    def test_fixed_maintenance_commands_are_forwarded_without_account_operations(self):
        for command, args, expected in [
            ('maintenance-preview', ['cache'], ['preview', 'cache']),
            ('maintenance-apply', ['a' * 32], ['apply', 'a' * 32]),
            ('maintenance-backups', [], ['backups']),
            ('maintenance-restore-preview', ['b' * 32], ['preview-restore', 'b' * 32]),
            ('maintenance-recover-preview', ['c' * 32], ['preview-recover', 'c' * 32]),
        ]:
            with self.subTest(command=command):
                result, calls = self.invoke([command] + args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, expected)

    def test_public_switch_acquires_scope_guard_instead_of_switching_directly(self):
        for target in ['A', 'B']:
            result, calls = self.invoke(['switch', target])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, ['guard-switch', target])

    def test_invalid_switch_does_not_reach_guard_or_create_accounts(self):
        for args in [['switch'], ['switch', 'C'], ['switch', 'A', 'extra']]:
            result, calls = self.invoke(args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(calls)
            self.assertIn('FAIL:', result.stdout)

    def test_hidden_switch_cannot_bypass_lock_verification(self):
        result, calls = self.invoke(['_maintenance-switch', 'A'], helper_exit=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['verify-lock', 'desktop', ''])
        self.assertIn('FAIL:', result.stdout)
        self.assertNotIn('["verify-lock"', result.stdout)

    def test_backend_failure_exit_is_preserved(self):
        result, _ = self.invoke(['maintenance-apply', 'a' * 32], helper_exit=7)
        self.assertEqual(result.returncode, 7)

    def test_real_scope_descriptor_survives_guarded_child_and_is_released(self):
        with tempfile.TemporaryDirectory(prefix='maintenance-guard-child-') as folder:
            home = Path(folder).resolve()
            source = home / 'source'
            source.mkdir()
            module = source / 'local-maintenance.py'
            module.write_bytes((CORE.parent / 'local-maintenance.py').read_bytes())
            fake_core = source / 'claude-switch.sh'
            fake_core.write_text('''#!/bin/bash
[ "$1" = _maintenance-switch ] || exit 91
python3 "$(dirname "$0")/local-maintenance.py" verify-lock desktop "$CLAUDE_SWITCHER_MAINTENANCE_FD" >/dev/null || exit 92
printf 'OK:fixture-current=%s\n' "$2"
''')
            env = dict(os.environ, HOME=str(home))
            result = subprocess.run([sys.executable, str(module), 'guard-switch', 'B'],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), 'OK:fixture-current=B')
            self.assertFalse((home / '.claude-switcher/accounts').exists())
            # A second process can take the same exclusive scope after child exit.
            again = subprocess.run([sys.executable, str(module), 'guard-switch', 'A'],
                                   env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertEqual(again.stdout.strip(), 'OK:fixture-current=A')


if __name__ == '__main__':
    unittest.main()
