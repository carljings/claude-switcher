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
    def setUp(self):
        policy_paths = patch.object(access, 'managed_policy_paths', return_value=[])
        policy_paths.start()
        self.addCleanup(policy_paths.stop)

    def test_browser_command_has_one_proxy_and_separate_profile(self):
        profile = Path('/tmp/private-edge-fixture')
        args = access.browser_command(profile)
        self.assertIn('--user-data-dir=' + str(profile), args)
        self.assertIn('--proxy-server=http://127.0.0.1:17897', args)
        self.assertFalse(any('direct://' in arg for arg in args))
        self.assertIn('--disable-quic', args)
        self.assertIn('--lang=en-US', args)
        self.assertIn('--accept-lang=en-US,en', args)
        self.assertIn('--disable-extensions', args)
        self.assertIn('--force-webrtc-ip-handling-policy=disable_non_proxied_udp', args)
        self.assertIn('--webrtc-ip-handling-policy=disable_non_proxied_udp', args)
        self.assertIn('--profile-directory=Default', args)

    def test_preflight_requires_protected_route_evidence_and_returns_its_port(self):
        policy = {'mode': 'clash-selector', 'group': 'Fixture',
                  'protected_listener': {'name': 'FixtureProtected', 'port': 17897, 'proxy': 'Fixed'}}
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / '.claude-switcher').mkdir()
            (home / '.claude-switcher/exit-policy.json').write_text(json.dumps(policy))
            module = SimpleNamespace(audit=Mock())
            with patch.object(access, 'preference_baseline'), patch.object(access, 'load_network_audit', return_value=module):
                for report in [{'state': 'fail'}, {'state': 'warn'}, {'state': 'info'},
                               {'state': 'info', 'protected_port': 7897}]:
                    with self.subTest(report=report):
                        module.audit.return_value = report
                        with self.assertRaises(ValueError):
                            access.preflight(home)
                module.audit.return_value = {'state': 'info', 'protected_port': 17897}
                self.assertEqual(access.preflight(home), 17897)
                module.audit.assert_called_with(home, group='Fixture', country='US', protected=True)
                del policy['protected_listener']
                (home / '.claude-switcher/exit-policy.json').write_text(json.dumps(policy))
                with self.assertRaises(ValueError):
                    access.preflight(home)

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
            for selected in ['en-US,en,zh-CN', 'en-US,en,zh-Hant-TW,en-GB,sr-Latn-RS,es-419,ca-ES-valencia']:
                with self.subTest(selected=selected):
                    data = json.loads(original)
                    data['intl']['selected_languages'] = selected
                    changed = json.dumps(data)
                    prefs.write_text(changed)
                    access.profile_baseline(profile)
                    self.assertEqual(prefs.read_text(), changed)
            for selected in [['en-US', 'en'], 'en-US,zh-CN,en', 'en-US,en,zh_CN',
                             'en-US,en,zh--CN', 'en-US,en,zh-CN;invalid', 'en-US,en,en-u',
                             'en-US,en,en-GB,']:
                with self.subTest(invalid_selected=selected):
                    data = json.loads(original)
                    data['intl']['selected_languages'] = selected
                    changed = json.dumps(data)
                    prefs.write_text(changed)
                    with self.assertRaises(ValueError):
                        access.profile_baseline(profile)
                    self.assertEqual(prefs.read_text(), changed)
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
                         current.replace('--accept-lang=en-US,en', ''),
                         current.replace('--disable-extensions', ''),
                         current.replace('--webrtc-ip-handling-policy=disable_non_proxied_udp', ''),
                         current.replace('http://127.0.0.1:17897', 'http://127.0.0.1:17898'),
                         current.replace('https://claude.ai/', '--proxy-bypass-list=* https://claude.ai/'),
                         current.replace('https://claude.ai/', '--load-extension=/fixture/extension https://claude.ai/'),
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
                with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight', return_value=17897), patch.object(access, 'running_browser', return_value=False), patch.object(access, failure, side_effect=ValueError('private-token')), patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stderr(io.StringIO()) as error:
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
            with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight', return_value=17897), patch.object(access, 'running_browser', return_value=True), patch.object(access, 'seed_profile') as seed, patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stdout(io.StringIO()) as output:
                launch.return_value.wait.return_value = 0
                self.assertEqual(access.main(), 0)
                seed.assert_not_called()
                self.assertIn('已请求打开', output.getvalue())

    def test_new_browser_still_running_is_an_open_request(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            binary = home / 'edge'
            binary.touch()
            with patch.dict(access.os.environ, {'FIXTURE_KEEP': 'fixture-value', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'LC_CTYPE': 'C.UTF-8'}, clear=True), patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight', return_value=17897), patch.object(access, 'running_browser', return_value=False), patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stdout(io.StringIO()) as output:
                launch.return_value.wait.side_effect = access.subprocess.TimeoutExpired([], 0.5)
                self.assertEqual(access.main(), 0)
                self.assertIn('已请求打开', output.getvalue())
                env = launch.call_args.kwargs['env']
                for name in ['LANG', 'LC_ALL', 'LC_CTYPE']:
                    self.assertEqual(env[name], 'en_US.UTF-8')
                self.assertEqual(env['TZ'], 'America/Chicago')
                self.assertEqual(env['FIXTURE_KEEP'], 'fixture-value')
                self.assertNotIn('fixture-value', output.getvalue())

    def test_immediate_browser_failure_is_not_reported_as_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            binary = home / 'edge'
            binary.touch()
            with patch('sys.argv', ['protected-access.py', 'browser']), patch.object(access.Path, 'home', return_value=home), patch.object(access, 'EDGE', binary), patch.object(access, 'preflight', return_value=17897), patch.object(access, 'running_browser', return_value=False), patch.object(access.subprocess, 'Popen') as launch, contextlib.redirect_stderr(io.StringIO()) as error, contextlib.redirect_stdout(io.StringIO()) as output:
                launch.return_value.wait.return_value = 7
                self.assertEqual(access.main(), 1)
                self.assertNotIn('已请求打开', output.getvalue())
                self.assertIn('未完成启动', error.getvalue())

    def test_strong_privacy_defaults_and_exception_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            access.seed_profile(profile)
            path = profile / 'Default/Preferences'
            original = path.read_text()
            values = json.loads(original)
            self.assertEqual(values['net']['network_prediction_options'], 2)
            self.assertEqual(values['profile']['cookie_controls_mode'], 1)
            for kind in access.DENIED_PERMISSIONS:
                expected = {'approximate': 2, 'precise': 2} if kind == 'geolocation_with_options' else 2
                self.assertEqual(values['profile']['default_content_setting_values'][kind], expected)
                for scope in ['exceptions', 'partitioned_exceptions']:
                    changed = json.loads(original)
                    changed['profile']['content_settings'][scope][kind] = {'https://fixture.invalid,*': {'setting': 1}}
                    path.write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):
                        access.profile_baseline(profile)
            for forced in [['zh-CN'], 'en-US']:
                changed = json.loads(original)
                changed['intl']['forced_languages'] = forced
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    access.profile_baseline(profile)
            values['intl']['forced_languages'] = ['en-US', 'en']
            values['profile']['content_settings']['exceptions']['geolocation'] = {'https://fixture.invalid,*': {'setting': 2}}
            values['profile']['content_settings']['exceptions']['geolocation_with_options'] = {
                'https://fixture.invalid,*': {'setting': {'approximate': 2, 'precise': 2}}}
            path.write_text(json.dumps(values))
            access.profile_baseline(profile)

    def test_harden_backs_up_exact_preferences_and_preserves_other_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            profile = home / 'Library/Application Support' / access.PROFILE_NAME
            path = profile / 'Default/Preferences'
            path.parent.mkdir(parents=True)
            original = json.dumps({'fixture': {'keep': 'user-choice'}, 'intl': {'selected_languages': 'zh-CN'},
                'profile': {'content_settings': {'exceptions': {'geolocation': {'fixture': {'setting': 1}},
                                                               'cookies': {'keep': {'setting': 1}}}}}})
            path.write_text(original)
            with patch.object(access, 'running_browser', return_value=False):
                backup = access.harden_profile(home, profile, 17897)
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            values = json.loads(path.read_text())
            self.assertEqual(values['fixture'], {'keep': 'user-choice'})
            self.assertEqual(values['profile']['content_settings']['exceptions']['cookies'], {'keep': {'setting': 1}})
            self.assertEqual(values['profile']['content_settings']['exceptions']['geolocation'], {})
            access.profile_baseline(profile)

    def test_harden_refuses_a_running_profile_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            profile = home / 'profile'
            access.seed_profile(profile)
            path = profile / 'Default/Preferences'
            original = path.read_bytes()
            with patch.object(access, 'running_browser', return_value=True):
                with self.assertRaises(ValueError):
                    access.harden_profile(home, profile, 17897)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((home / '.claude-switcher/profile-preference-backups').exists())

    def test_harden_failure_or_new_process_preserves_preferences_and_backup(self):
        for failure in ['atomic_write', 'process_started']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                profile = home / 'profile'
                access.seed_profile(profile)
                path = profile / 'Default/Preferences'
                original = path.read_bytes()
                with patch.object(access, 'running_browser', side_effect=[False, failure == 'process_started']), patch.object(access, 'atomic_preferences', side_effect=OSError('fixture failure')) as write:
                    with self.assertRaises((OSError, ValueError)):
                        access.harden_profile(home, profile, 17897)
                    if failure == 'process_started':
                        write.assert_not_called()
                self.assertEqual(path.read_bytes(), original)
                backups = list((home / '.claude-switcher/profile-preference-backups').glob('*.json'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)

    def test_known_managed_policy_conflicts_fail_without_changing_plist(self):
        import plistlib
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            path = home / 'managed.plist'
            for value in [{'ProxySettings': {'ProxyMode': 'direct'}},
                          {'WebRtcIPHandlingUrl': [{'url': '*', 'handling': 'default'}]},
                          {'ExtensionInstallForcelist': ['fixture-extension;https://fixture.invalid']},
                          {'DefaultGeolocationSetting': 1},
                          {'DefinePreferredLanguages': 'zh-CN,en'},
                          {'DefinePreferredLanguages': 'en-GB'},
                          {'DefinePreferredLanguages': 'en-US,en,zh-CN'}]:
                raw = plistlib.dumps(value)
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    access.managed_policy_baseline(home, paths=[path])
                self.assertEqual(path.read_bytes(), raw)
            path.write_bytes(plistlib.dumps({'WebRtcLocalhostIpHandling': 'disable_non_proxied_udp',
                                            'DnsOverHttpsMode': 'off', 'DefaultGeolocationSetting': 2}))
            access.managed_policy_baseline(home, paths=[path])
            for languages in ['', 'en-US', 'en-US,en']:
                path.write_bytes(plistlib.dumps({'DefinePreferredLanguages': languages}))
                access.managed_policy_baseline(home, paths=[path])

    def test_cli_uses_tcp_only_sandbox_and_overrides_inherited_proxy_and_locale(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'native-cli'
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o700)
            sandbox = Path(folder) / 'sandbox-exec'
            sandbox.touch()
            sandbox.chmod(0o700)
            bad = {'https_proxy': 'http://fixture.invalid:99', 'NO_PROXY': '*', 'TZ': 'Asia/Shanghai',
                   'LANG': 'zh_CN.UTF-8', 'CLAUDE_SECURESTORAGE_CONFIG_DIR': '/fixture/private-scope',
                   'CLAUDE_CONFIG_DIR': '/fixture/native-config'}
            with patch.dict(access.os.environ, bad, clear=True), patch.object(access, 'SANDBOX', sandbox), patch.object(access.os, 'execve') as execute:
                access.launch_cli([str(binary), '--version'], 17897)
            executable, args, env = execute.call_args.args
            self.assertEqual(executable, str(sandbox))
            self.assertEqual(args[-2:], [str(binary), '--version'])
            self.assertIn('(remote tcp "localhost:17897")', args[2])
            for operation in ['appleevent-send', 'lsopen']:
                with self.subTest(operation=operation):
                    self.assertIn('(deny ' + operation + ')', args[2])
            with self.subTest(environment='securestorage_override'):
                self.assertFalse('CLAUDE_SECURESTORAGE_CONFIG_DIR' in env)
            self.assertEqual(env['CLAUDE_CONFIG_DIR'], '/fixture/native-config')
            for name in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
                self.assertEqual(env[name], 'http://127.0.0.1:17897')
            self.assertEqual(env['NO_PROXY'], 'localhost,127.0.0.1,::1')
            self.assertEqual(env['no_proxy'], env['NO_PROXY'])
            self.assertEqual(env['TZ'], 'America/Chicago')
            self.assertEqual(env['LANG'], 'en_US.UTF-8')
            self.assertEqual(env['LC_ALL'], 'en_US.UTF-8')

    def test_cli_missing_sandbox_or_relative_program_never_executes(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'native-cli'
            binary.touch()
            binary.chmod(0o700)
            with patch.object(access.os, 'execve') as execute:
                with self.assertRaises(ValueError):
                    access.launch_cli(['relative-cli'], 17897)
                with patch.object(access, 'SANDBOX', Path(folder) / 'missing-sandbox'):
                    with self.assertRaises(ValueError):
                        access.launch_cli([str(binary)], 17897)
                execute.assert_not_called()

    def test_cli_action_passes_arguments_only_after_preflight(self):
        with patch('sys.argv', ['protected-access.py', 'cli', '/fixture/native-cli', '--version']), patch.object(access, 'preflight', return_value=17897), patch.object(access, 'launch_cli') as launch:
            self.assertEqual(access.main(), 0)
            launch.assert_called_once_with(['/fixture/native-cli', '--version'], 17897)
        with patch('sys.argv', ['protected-access.py', 'cli', '/fixture/native-cli', '--secret-fixture']), patch.object(access, 'preflight', side_effect=ValueError('private-token')), patch.object(access, 'launch_cli') as launch, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(access.main(), 1)
            launch.assert_not_called()
            self.assertNotIn('private-token', error.getvalue())
            self.assertNotIn('--secret-fixture', error.getvalue())

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
