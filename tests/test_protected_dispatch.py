"""Exercise shell dispatch with an isolated helper; no installed state or accounts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


CORE = Path(__file__).resolve().parents[1] / 'core/claude-switch.sh'


class ProtectedDispatchTests(unittest.TestCase):
    def invoke(self, arguments, helper_exit=0):
        with tempfile.TemporaryDirectory(prefix='protected-dispatch-') as folder:
            home = Path(folder)
            base = home / '.claude-switcher'
            base.mkdir()
            (base / 'protected-access.py').write_text(
                'import json, sys\nprint(json.dumps(sys.argv[1:]))\n'
                'raise SystemExit(' + str(helper_exit) + ')\n')
            result = subprocess.run(['/bin/bash', str(CORE)] + arguments,
                                    env=dict(os.environ, HOME=str(home)),
                                    capture_output=True, text=True, timeout=10)
            self.assertFalse((base / 'accounts').exists())
            return result

    def test_cli_preserves_binary_path_spaces_and_native_options(self):
        arguments = ['/fixture/Native CLI', '--settings', '/fixture/settings file.json', '--version']
        result = self.invoke(['protected-cli'] + arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['cli'] + arguments)

    def test_profile_hardening_has_an_explicit_non_account_action(self):
        result = self.invoke(['protected-harden'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['harden'])

    def test_helper_failure_is_not_changed_to_shell_success(self):
        result = self.invoke(['protected-cli', '/fixture/native'], helper_exit=9)
        self.assertEqual(result.returncode, 9)


if __name__ == '__main__':
    unittest.main()
