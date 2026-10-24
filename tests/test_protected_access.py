import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('protected_access', ROOT / 'core/protected-access.py')
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class ProtectedAccessTests(unittest.TestCase):
    def test_browser_command_has_one_proxy_and_separate_profile(self):
        profile = Path('/tmp/private-edge-fixture')
        args = access.browser_command(profile)
        self.assertIn('--user-data-dir=' + str(profile), args)
        self.assertIn('--proxy-server=http://127.0.0.1:7897', args)
        self.assertFalse(any('direct://' in arg for arg in args))
        self.assertIn('--disable-quic', args)
        self.assertIn('--lang=en-US', args)
        self.assertIn('--force-webrtc-ip-handling-policy=disable_non_proxied_udp', args)

    def test_seed_does_not_replace_existing_profile_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            access.seed_profile(profile)
            prefs = profile / 'Default/Preferences'
            prefs.write_text('{"fixture":"existing-user-choice"}')
            access.seed_profile(profile)
            self.assertEqual(json.loads(prefs.read_text()), {'fixture': 'existing-user-choice'})

    def test_failed_preflight_never_launches_browser(self):
        with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access, 'preflight', side_effect=ValueError('private-token')), patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(access.main(), 1)
            launch.assert_not_called()
            self.assertNotIn('private-token', error.getvalue())

    def test_audit_reports_presence_without_secret_values(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            p = home / '.claude/settings.json'
            p.parent.mkdir()
            p.write_text(json.dumps({'env': {'ANTHROPIC_AUTH_TOKEN': 'never-print-this', 'ANTHROPIC_BASE_URL': 'https://example.com/api?key=hidden'}}))
            text = json.dumps(access.provider_audit(home))
            self.assertNotIn('never-print-this', text)
            self.assertNotIn('key=hidden', text)
            self.assertIn('example.com', text)

    def test_preference_baseline_blocks_a_changed_timezone_or_language(self):
        from subprocess import CompletedProcess
        with patch.object(access.os, 'readlink', return_value='/var/db/timezone/zoneinfo/Asia/Shanghai'):
            with self.assertRaises(ValueError):
                access.preference_baseline()
        with patch.object(access.os, 'readlink', return_value='/var/db/timezone/zoneinfo/America/Chicago'), patch.object(access.subprocess, 'run', side_effect=[CompletedProcess([], 0, 'en_US\n'), CompletedProcess([], 0, '(\n "zh-CN",\n "en-US"\n)')]):
            with self.assertRaises(ValueError):
                access.preference_baseline()
        with patch.object(access.os, 'readlink', return_value='/var/db/timezone/zoneinfo/America/Chicago'), patch.object(access.subprocess, 'run', side_effect=[CompletedProcess([], 0, 'en_US\n'), CompletedProcess([], 0, '(\n "en-US",\n "zh-Hans-CN"\n)')]):
            access.preference_baseline()

    def test_report_excludes_check_details_and_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            checks = home / '.claude-switcher/last-check.txt'
            checks.parent.mkdir()
            checks.write_text('出口IP=ok:private-ip\n生态可达性=warn:private-session\n')
            report = access.support_report(home)
            text = report.read_text()
            self.assertNotIn('private-ip', text)
            self.assertNotIn('private-session', text)
            self.assertFalse(json.loads(text)['account_permission_verified'])
            self.assertEqual(json.loads(text)['last_check']['row_states'], {'出口IP': 'ok', '生态可达性': 'warn'})
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
