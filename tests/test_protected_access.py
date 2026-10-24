import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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
        self.assertIn('--webrtc-ip-handling-policy=disable_non_proxied_udp', args)
        self.assertIn('--profile-directory=Default', args)

    def test_preflight_rejects_wrong_or_unverified_claude_routes(self):
        from subprocess import CompletedProcess
        policy = {'mode': 'clash-selector', 'controller_socket': '/tmp/fixture.sock',
                  'controller_secret': 'not-a-real-secret', 'group': 'Fixture',
                  'nodes': {'Node': {'ip': '192.0.2.20', 'country': 'US'}}}

        class LocalController:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, method, path, headers):
                self.path = path

            def getresponse(self):
                value = ({'mode': 'rule', 'tun': {'enable': True}, 'ipv6': False,
                          'mixed-port': 7897} if self.path == '/configs'
                         else {'type': 'Selector', 'now': 'Node'})
                return SimpleNamespace(status=200, read=lambda size: json.dumps(value).encode())

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / '.claude-switcher').mkdir()
            (home / '.claude-switcher/exit-policy.json').write_text(json.dumps(policy))
            module = SimpleNamespace(audit=Mock())
            with patch.object(access, 'preference_baseline'), patch.object(access.http.client, 'HTTPConnection', LocalController), patch.object(access.subprocess, 'run', return_value=CompletedProcess([], 0, 'ip=192.0.2.20\nloc=US\n')), patch.object(access, 'load_network_audit', return_value=module):
                for state in ['fail', 'warn', None]:
                    with self.subTest(state=state):
                        module.audit.return_value = {'state': state}
                        with self.assertRaises(ValueError):
                            access.preflight(home)
                module.audit.return_value = {'state': 'info'}
                access.preflight(home)
                self.assertEqual(module.audit.call_count, 4)

    def test_missing_route_module_fails_closed(self):
        with patch.object(access.importlib.util, 'spec_from_file_location', return_value=None):
            with self.assertRaises(ValueError):
                access.load_network_audit()

    def test_seed_does_not_replace_existing_profile_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            access.seed_profile(profile)
            prefs = profile / 'Default/Preferences'
            prefs.write_text('{"fixture":"existing-user-choice"}')
            access.seed_profile(profile)
            self.assertEqual(json.loads(prefs.read_text()), {'fixture': 'existing-user-choice'})

    def test_profile_drift_is_rejected_without_overwriting_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            access.seed_profile(profile)
            access.profile_baseline(profile)
            prefs = profile / 'Default/Preferences'
            original = prefs.read_text()
            for group, key, value in [('webrtc', 'ip_handling_policy', 'default'),
                                      ('dns_over_https', 'mode', 'automatic'),
                                      ('intl', 'accept_languages', 'zh-CN,en'),
                                      ('intl', 'selected_languages', 'zh-CN,en')]:
                with self.subTest(group=group, key=key):
                    data = json.loads(original)
                    data[group][key] = value
                    changed = json.dumps(data)
                    prefs.write_text(changed)
                    with self.assertRaises(ValueError):
                        access.profile_baseline(profile)
                    self.assertEqual(prefs.read_text(), changed)

    def test_existing_dedicated_process_must_use_current_safety_flags(self):
        from subprocess import CompletedProcess
        profile = Path('/tmp/Claude Protected Edge')
        current = '123 ' + ' '.join(access.browser_command(profile)) + '\n'
        ordinary = '124 ' + str(access.EDGE) + ' --profile-directory=Default\n'
        with patch.object(access.subprocess, 'run') as run:
            run.return_value = CompletedProcess([], 0, ordinary)
            self.assertFalse(access.running_browser(profile))
            run.return_value = CompletedProcess([], 0, ordinary + current)
            self.assertTrue(access.running_browser(profile))
            for text in [current.replace('--disable-quic', ''),
                         current.replace('--webrtc-ip-handling-policy=disable_non_proxied_udp', ''),
                         current.replace('http://127.0.0.1:7897', 'http://127.0.0.1:7898'),
                         current.replace('https://claude.ai/', '--proxy-bypass-list=* https://claude.ai/'),
                         current.replace('https://claude.ai/', '--proxy-server=direct:// https://claude.ai/')]:
                with self.subTest(command=text):
                    run.return_value = CompletedProcess([], 0, text)
                    with self.assertRaises(ValueError):
                        access.running_browser(profile)
            run.return_value = CompletedProcess([], 1, '', 'private-process-details')
            with self.assertRaises(ValueError):
                access.running_browser(profile)
            run.return_value = CompletedProcess([], 0, '')
            with self.assertRaises(ValueError):
                access.running_browser(profile)

    def test_invalid_profile_or_old_process_never_launches_browser(self):
        for failure in ['profile_baseline', 'running_browser']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                binary = home / 'edge'
                binary.touch()
                with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight'), patch.object(access, 'running_browser', return_value=False), patch.object(access, failure, side_effect=ValueError('private-token')), patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(access.main(), 1)
                    launch.assert_not_called()
                    self.assertNotIn('private-token', error.getvalue())

    def test_running_profile_is_not_seeded_and_correct_process_can_be_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            binary = home / 'edge'
            binary.touch()
            profile = home / 'Library/Application Support' / access.PROFILE_NAME
            access.seed_profile(profile)
            with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight'), patch.object(access, 'running_browser', return_value=True), patch.object(access, 'seed_profile') as seed, patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stdout(io.StringIO()) as output:
                launch.return_value.wait.return_value = 0
                self.assertEqual(access.main(), 0)
                seed.assert_not_called()
                self.assertIn('已请求打开', output.getvalue())

    def test_new_browser_still_running_is_an_open_request(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            binary = home / 'edge'
            binary.touch()
            with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight'), patch.object(access, 'running_browser', return_value=False), patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stdout(io.StringIO()) as output:
                launch.return_value.wait.side_effect = access.subprocess.TimeoutExpired([], 0.5)
                self.assertEqual(access.main(), 0)
                self.assertIn('已请求打开', output.getvalue())

    def test_immediate_browser_failure_is_not_reported_as_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            binary = home / 'edge'
            binary.touch()
            with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight'), patch.object(access, 'running_browser', return_value=False), patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stderr(io.StringIO()) as error, contextlib.redirect_stdout(io.StringIO()) as output:
                launch.return_value.wait.return_value = 7
                self.assertEqual(access.main(), 1)
                self.assertNotIn('已请求打开', output.getvalue())
                self.assertIn('未完成启动', error.getvalue())

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
