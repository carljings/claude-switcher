"""Maintenance behavior in disposable HOME directories; never use real profiles."""
import importlib.util
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('local_maintenance', ROOT / 'core/local-maintenance.py')
maintenance = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = maintenance
spec.loader.exec_module(maintenance)
CHECK_PROCESSES = maintenance.ensure_closed


class LocalMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='switcher-maintenance-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = (Path(self.temp.name) / 'home').resolve()
        self.home.mkdir(mode=0o700)
        self.profile = self.home / 'Library/Application Support/Claude Protected Edge'
        self.desktop = self.home / 'Library/Application Support/Claude'
        self.native = self.home / '.claude-native-greencloud'
        self.manager = maintenance.Maintenance(self.home)
        self.closed = patch.object(maintenance, 'ensure_closed', return_value=None)
        self.closed.start()
        self.addCleanup(self.closed.stop)

    def put(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        path.chmod(0o600)
        return path

    def put_json(self, path, data):
        return self.put(path, json.dumps(data))

    def apply_mode(self, mode):
        preview = self.manager.preview(mode)
        self.assertTrue(preview['ok'])
        self.assertTrue(preview['can_apply'])
        self.assertEqual(preview['mode'], mode)
        result = self.manager.apply(preview['token'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['mode'], mode)
        return result

    def find_backup_bytes(self, backup_id, content):
        folder = self.manager.root / 'backups' / backup_id
        return [p for p in folder.rglob('*')
                if p.is_file() and not p.is_symlink() and p.read_bytes() == content]

    def test_oversize_scan_stops_before_creating_an_unreadable_plan_or_backup(self):
        target = self.put(self.desktop / 'ant-did', b'fixture-id')
        with patch.object(maintenance, 'MAX_SCAN', 1):
            with self.assertRaises(maintenance.MaintenanceError) as caught:
                self.manager.preview('desktop-ids')
        self.assertEqual(caught.exception.code, 'scan_too_large')
        self.assertEqual(target.read_bytes(), b'fixture-id')
        self.assertEqual(list((self.manager.root / 'plans').glob('*.json')), [])
        self.assertEqual(self.manager.backups()['backups'], [])
        with maintenance.entry_lock(self.home, 'desktop'):
            pass

    def test_backup_refuses_changed_target_order_or_paths_without_modifying_data(self):
        first = self.put(self.desktop / 'ant-did', b'original-first-id')
        second = self.put(self.desktop / 'ant-device-registry.json', b'original-second-id')
        cleaned = self.apply_mode('desktop-ids')
        self.put(first, b'new-current-first-id')
        self.put(second, b'new-current-second-id')
        folder = self.manager.root / 'backups' / cleaned['backup_id']
        before = {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        variants = [[second, first], [first, self.desktop / 'different-future-id']]
        for targets in variants:
            with self.subTest(targets=targets), patch.object(self.manager, '_targets', return_value=targets):
                with self.assertRaises(maintenance.MaintenanceError) as caught:
                    self.manager.preview_restore(cleaned['backup_id'])
                self.assertEqual(caught.exception.code, 'incompatible_record')
            self.assertEqual(first.read_bytes(), b'new-current-first-id')
            self.assertEqual(second.read_bytes(), b'new-current-second-id')
            self.assertFalse((self.desktop / 'different-future-id').exists())
            self.assertEqual({str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}, before)

    def test_plan_refuses_target_order_change_before_apply(self):
        first = self.put(self.desktop / 'ant-did', b'first-id')
        second = self.put(self.desktop / 'ant-device-registry.json', b'second-id')
        plan = self.manager.preview('desktop-ids')
        with patch.object(self.manager, '_targets', return_value=[second, first]):
            with self.assertRaises(maintenance.MaintenanceError) as caught:
                self.manager.apply(plan['token'])
        self.assertEqual(caught.exception.code, 'incompatible_record')
        self.assertEqual(first.read_bytes(), b'first-id')
        self.assertEqual(second.read_bytes(), b'second-id')
        self.assertEqual(self.manager.backups()['backups'], [])

    def test_no_matching_targets_is_a_noop_for_each_scope(self):
        for mode in ['cache', 'browser-reset', 'desktop-ids', 'native-ids']:
            with self.subTest(mode=mode):
                result = self.manager.preview(mode)
                self.assertTrue(result['ok'])
                self.assertFalse(result['can_apply'])
                self.assertFalse(result['token'])
                self.assertEqual(result['item_count'], 0)
        self.assertEqual(self.manager.backups()['backups'], [])
        self.assertFalse((self.home / '.claude-switcher/accounts').exists())

    def test_preview_does_not_disclose_values_or_change_targets(self):
        original = b'private-machine-id-fixture'
        target = self.put(self.native / '.machine-id', original)
        self.put_json(self.native / '.claude.json', {
            'machineID': 'private-json-id-fixture',
            'oauthAccount': {'token': 'private-oauth-fixture'},
        })
        result = self.manager.preview('native-ids')
        encoded = json.dumps(result)
        self.assertNotIn('private-machine-id-fixture', encoded)
        self.assertNotIn('private-json-id-fixture', encoded)
        self.assertNotIn('private-oauth-fixture', encoded)
        self.assertNotIn(str(self.home), encoded)
        self.assertGreater(result['total_bytes'], 0)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(self.manager.backups()['backups'], [])

    def test_cache_cleanup_keeps_login_history_and_unlisted_files(self):
        cache = self.put(self.profile / 'Default/Cache/item', b'cached-page')
        code = self.put(self.profile / 'Default/Code Cache/item', b'compiled-code')
        keep = {
            'Default/Network/Cookies': b'cookie-fixture',
            'Default/Login Data': b'password-db-fixture',
            'Default/Bookmarks': b'bookmark-fixture',
            'Default/History': b'history-fixture',
            'Local State': b'local-state-fixture',
            'Default/OtherData/item': b'unrelated-fixture',
        }
        for name, value in keep.items():
            self.put(self.profile / name, value)
        result = self.apply_mode('cache')
        self.assertFalse(cache.exists())
        self.assertFalse(code.exists())
        for name, value in keep.items():
            self.assertEqual((self.profile / name).read_bytes(), value)
        self.assertTrue(self.find_backup_bytes(result['backup_id'], b'cached-page'))

    def test_browser_reset_creates_hardened_fresh_profile_and_retains_old_data(self):
        self.put(self.profile / 'Default/Network/Cookies', b'old-cookies')
        self.put(self.profile / 'Local State', b'old-encryption-metadata')
        self.put(self.profile / 'Profile 1/Bookmarks', b'other-profile-bookmarks')
        with patch.object(maintenance.subprocess, 'Popen', side_effect=AssertionError('must not open browser')):
            result = self.apply_mode('browser-reset')
        self.assertFalse((self.profile / 'Default/Network/Cookies').exists())
        self.assertFalse((self.profile / 'Local State').exists())
        self.assertFalse((self.profile / 'Profile 1').exists())
        prefs = json.loads((self.profile / 'Default/Preferences').read_text())
        self.assertEqual(prefs['intl']['accept_languages'], 'en-US,en')
        self.assertEqual(prefs['webrtc']['ip_handling_policy'], 'disable_non_proxied_udp')
        self.assertEqual(prefs['dns_over_https']['mode'], 'off')
        self.assertEqual(prefs['profile']['default_content_setting_values']['local_fonts'], 2)
        self.assertTrue(self.find_backup_bytes(result['backup_id'], b'old-cookies'))
        self.assertTrue(self.find_backup_bytes(result['backup_id'], b'other-profile-bookmarks'))

    def test_desktop_id_reset_only_removes_two_named_files(self):
        self.put(self.desktop / 'ant-did', b'desktop-device-id')
        self.put(self.desktop / 'ant-device-registry.json', b'{"fixture":"device-registry"}')
        cookies = self.put(self.desktop / 'Network/Cookies', b'desktop-login')
        unrelated = self.put(self.desktop / 'config.json', b'other-settings')
        archive = self.put(self.home / '.claude-switcher/accounts/A/ant-did', b'archived-id')
        self.apply_mode('desktop-ids')
        self.assertFalse((self.desktop / 'ant-did').exists())
        self.assertFalse((self.desktop / 'ant-device-registry.json').exists())
        self.assertEqual(cookies.read_bytes(), b'desktop-login')
        self.assertEqual(unrelated.read_bytes(), b'other-settings')
        self.assertEqual(archive.read_bytes(), b'archived-id')

    def test_desktop_marker_accepts_only_missing_or_valid_account_values(self):
        marker = self.home / '.claude-switcher/current'
        target = self.put(self.desktop / 'ant-did', b'current-device')
        for value in [None, 'A\n', 'B\n']:
            with self.subTest(valid=value):
                if marker.exists():
                    marker.unlink()
                if value is not None:
                    self.put(marker, value)
                self.assertTrue(self.manager.preview('desktop-ids')['can_apply'])
        for value in ['', 'C', 'A B', 'unknown']:
            with self.subTest(invalid=value):
                self.put(marker, value)
                with self.assertRaises(maintenance.MaintenanceError):
                    self.manager.preview('desktop-ids')
                self.assertEqual(target.read_bytes(), b'current-device')
        marker.unlink()
        marker.mkdir()
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview('desktop-ids')
        marker.rmdir()
        other = self.put(self.home / 'other-current', 'A')
        marker.symlink_to(other)
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview('desktop-ids')
        self.assertEqual(target.read_bytes(), b'current-device')

    def test_desktop_account_change_invalidates_preview(self):
        marker = self.put(self.home / '.claude-switcher/current', 'A')
        target = self.put(self.desktop / 'ant-did', b'account-a-id')
        plan = self.manager.preview('desktop-ids')
        marker.write_text('B')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'account-a-id')

    def test_desktop_backup_cannot_be_restored_into_another_account(self):
        marker = self.put(self.home / '.claude-switcher/current', 'A')
        target = self.put(self.desktop / 'ant-did', b'account-a-id')
        cleaned = self.apply_mode('desktop-ids')
        record = next(b for b in self.manager.backups()['backups']
                      if b['backup_id'] == cleaned['backup_id'])
        self.assertIn('档案A', record['label'].replace(' ', ''))
        marker.write_text('B')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview_restore(cleaned['backup_id'])
        self.assertFalse(target.exists())
        marker.write_text('A')
        preview = self.manager.preview_restore(cleaned['backup_id'])
        self.assertTrue(self.manager.apply(preview['token'])['ok'])
        self.assertEqual(target.read_bytes(), b'account-a-id')

    def test_restore_preview_lists_saved_targets_even_when_live_files_are_absent(self):
        self.put(self.desktop / 'ant-did', b'first-saved-id')
        self.put(self.desktop / 'ant-device-registry.json', b'second-saved-id')
        cleaned = self.apply_mode('desktop-ids')
        preview = self.manager.preview_restore(cleaned['backup_id'])
        self.assertEqual(preview['item_count'], 2)
        self.assertEqual({Path(item['path']).name for item in preview['items']},
                         {'ant-did', 'ant-device-registry.json'})
        self.assertGreaterEqual(preview['total_bytes'], len(b'first-saved-idsecond-saved-id'))

    def test_native_reset_preserves_oauth_mcp_and_default_provider(self):
        original = {'userID': 'local-user-id', 'machineID': 'local-machine-id',
                    'anonymousId': 'local-anonymous-id',
                    'oauthAccount': {'accountUuid': 'retained-account'},
                    'mcpServers': {'fixture': {'command': 'echo', 'args': ['a']}},
                    'projects': {'fixture-project': {'accepted': True}},
                    'nested': {'machineID': 'not-a-top-level-id'}}
        self.put_json(self.native / '.claude.json', original)
        self.put(self.native / '.user-id', b'user-id-file')
        self.put(self.native / '.machine-id', b'machine-id-file')
        glm = self.put(self.home / '.claude/settings.json', b'default-glm-credentials-fixture')
        default = self.put(self.home / '.claude.json', b'default-global-fixture')
        keychain = self.put(self.home / 'Library/Keychains/login.keychain-db', b'keychain-fixture')
        self.apply_mode('native-ids')
        updated = json.loads((self.native / '.claude.json').read_text())
        self.assertEqual(updated, {k: v for k, v in original.items()
                                   if k not in ['userID', 'machineID', 'anonymousId']})
        self.assertFalse((self.native / '.user-id').exists())
        self.assertFalse((self.native / '.machine-id').exists())
        self.assertEqual(glm.read_bytes(), b'default-glm-credentials-fixture')
        self.assertEqual(default.read_bytes(), b'default-global-fixture')
        self.assertEqual(keychain.read_bytes(), b'keychain-fixture')

    def test_native_candidate_absent_never_falls_back_to_default_claude(self):
        default = self.put_json(self.home / '.claude.json', {'machineID': 'default-id'})
        provider = self.put(self.home / '.claude/.machine-id', b'default-provider-id')
        result = self.manager.preview('native-ids')
        self.assertFalse(result['can_apply'])
        self.assertEqual(json.loads(default.read_text()), {'machineID': 'default-id'})
        self.assertEqual(provider.read_bytes(), b'default-provider-id')

    def test_native_json_without_id_fields_is_not_rewritten(self):
        raw = b'{ "oauthAccount" : { "uuid": "retained" }, "value" : 123 }\n'
        target = self.put(self.native / '.claude.json', raw)
        result = self.manager.preview('native-ids')
        self.assertFalse(result['can_apply'])
        self.assertEqual(target.read_bytes(), raw)

    def test_malformed_duplicate_and_oversize_json_are_rejected(self):
        for raw in [b'{broken', b'{"machineID":"one","machineID":"two"}',
                    b'[]', b' ' * (16 * 1024 * 1024 + 1)]:
            with self.subTest(size=len(raw)):
                target = self.put(self.native / '.claude.json', raw)
                with self.assertRaises(maintenance.MaintenanceError):
                    self.manager.preview('native-ids')
                self.assertEqual(target.read_bytes(), raw)

    def test_modified_file_after_preview_stops_before_any_change(self):
        first = self.put(self.desktop / 'ant-did', b'first-id')
        second = self.put(self.desktop / 'ant-device-registry.json', b'old-registry')
        plan = self.manager.preview('desktop-ids')
        second.write_bytes(b'new-registry')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.apply(plan['token'])
        self.assertEqual(first.read_bytes(), b'first-id')
        self.assertEqual(second.read_bytes(), b'new-registry')

    def test_new_previously_missing_target_invalidates_preview(self):
        first = self.put(self.desktop / 'ant-did', b'first-id')
        plan = self.manager.preview('desktop-ids')
        new = self.put(self.desktop / 'ant-device-registry.json', b'newly-created')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.apply(plan['token'])
        self.assertEqual(first.read_bytes(), b'first-id')
        self.assertEqual(new.read_bytes(), b'newly-created')

    def test_new_descendant_invalidates_a_directory_preview(self):
        original = self.put(self.profile / 'Default/Cache/one', b'original-cache')
        plan = self.manager.preview('cache')
        added = self.put(self.profile / 'Default/Cache/two', b'new-cache')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.apply(plan['token'])
        self.assertEqual(original.read_bytes(), b'original-cache')
        self.assertEqual(added.read_bytes(), b'new-cache')

    def test_replaced_target_with_same_bytes_is_stale(self):
        target = self.put(self.desktop / 'ant-did', b'same-id')
        plan = self.manager.preview('desktop-ids')
        target.rename(self.desktop / 'original-moved-away')
        self.put(target, b'same-id')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'same-id')

    def test_links_inside_target_and_linked_profile_are_rejected(self):
        outside = self.put(self.home / 'outside/data', b'outside-data')
        cache = self.profile / 'Default/Cache'
        cache.mkdir(parents=True)
        (cache / 'linked').symlink_to(outside)
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview('cache')
        (cache / 'linked').unlink()
        self.profile.rename(self.profile.with_name('saved-profile'))
        self.profile.symlink_to(self.profile.with_name('saved-profile'))
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview('browser-reset')
        self.assertEqual(outside.read_bytes(), b'outside-data')

    def test_hardlinked_target_is_rejected(self):
        outside = self.put(self.home / 'outside-id', b'hardlinked-id')
        self.desktop.mkdir(parents=True)
        os.link(outside, self.desktop / 'ant-did')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview('desktop-ids')
        self.assertEqual(outside.read_bytes(), b'hardlinked-id')

    def test_special_file_is_rejected_without_opening_it(self):
        self.desktop.mkdir(parents=True)
        os.mkfifo(self.desktop / 'ant-did', 0o600)
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview('desktop-ids')
        self.assertTrue(stat.S_ISFIFO((self.desktop / 'ant-did').lstat().st_mode))

    def test_wrong_owner_is_rejected(self):
        self.put(self.desktop / 'ant-did', b'owned-fixture')
        uid = os.getuid()
        with patch.object(maintenance.os, 'getuid', return_value=uid + 1):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.preview('desktop-ids')

    def test_expired_and_replayed_tokens_do_not_mutate(self):
        target = self.put(self.desktop / 'ant-did', b'old-id')
        with patch.object(maintenance.time, 'time', return_value=1000000000):
            expired = self.manager.preview('desktop-ids')
        with patch.object(maintenance.time, 'time', return_value=1000000601):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(expired['token'])
        self.assertEqual(target.read_bytes(), b'old-id')
        fresh = self.manager.preview('desktop-ids')
        self.manager.apply(fresh['token'])
        self.put(target, b'new-id-after-cleanup')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.apply(fresh['token'])
        self.assertEqual(target.read_bytes(), b'new-id-after-cleanup')

    def test_plan_tampering_and_invalid_tokens_are_rejected(self):
        target = self.put(self.desktop / 'ant-did', b'protected-id')
        plan = self.manager.preview('desktop-ids')
        path = self.manager.root / 'plans' / (plan['token'] + '.json')
        original = path.read_bytes()
        self.assertIn(b'desktop-ids', original)
        path.write_bytes(original.replace(b'desktop-ids', b'browser-reset'))
        for token in [plan['token'], '../escape', 'not-a-token', '0' * 32]:
            with self.subTest(token=token):
                with self.assertRaises(maintenance.MaintenanceError):
                    self.manager.apply(token)
        self.assertEqual(target.read_bytes(), b'protected-id')

    def test_scope_lock_blocks_second_apply_and_releases_after_exit(self):
        target = self.put(self.desktop / 'ant-did', b'locked-id')
        plan = self.manager.preview('desktop-ids')
        with maintenance.entry_lock(self.home, 'desktop'):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(plan['token'])
            self.assertEqual(target.read_bytes(), b'locked-id')
        self.assertTrue(self.manager.apply(plan['token'])['ok'])

    def test_native_shared_entry_locks_coexist_but_exclude_maintenance(self):
        target = self.put(self.native / '.machine-id', b'native-id-with-active-entry')
        plan = self.manager.preview('native-ids')
        with maintenance.entry_lock(self.home, 'native', shared=True):
            with maintenance.entry_lock(self.home, 'native', shared=True):
                with self.assertRaises(maintenance.MaintenanceError):
                    self.manager.preview('native-ids')
                with self.assertRaises(maintenance.MaintenanceError):
                    self.manager.apply(plan['token'])
                self.assertEqual(target.read_bytes(), b'native-id-with-active-entry')
        self.assertTrue(self.manager.apply(plan['token'])['ok'])

    def test_shared_entry_locks_are_rejected_for_desktop_and_browser(self):
        for scope in ['desktop', 'browser']:
            with self.subTest(scope=scope):
                with self.assertRaises(maintenance.MaintenanceError):
                    with maintenance.entry_lock(self.home, scope, shared=True):
                        pass

    def test_running_process_prevents_preview_or_apply(self):
        target = self.put(self.desktop / 'ant-did', b'not-cleaned')
        plan = self.manager.preview('desktop-ids')
        with patch.object(maintenance, 'ensure_closed',
                          side_effect=maintenance.MaintenanceError('running', '请先退出客户端')):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.preview('desktop-ids')
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'not-cleaned')

    def test_process_scan_blocks_actual_client_executables_without_echoing_argv(self):
        edge = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        fixtures = [
            ('browser', edge, edge + ' --user-data-dir=' + str(self.profile) + ' --no-proxy-server private-argv-fixture'),
            ('desktop', '/Applications/Claude.app/Contents/MacOS/Claude', 'Claude private-argv-fixture'),
            ('native', '/fixture/claude/versions/2.1.310', 'claude private-argv-fixture'),
            ('native', '/opt/homebrew/bin/node', 'node /fixture/node_modules/@anthropic-ai/claude-code/cli.js private-argv-fixture'),
        ]
        for scope, executable, arguments in fixtures:
            with self.subTest(scope=scope, executable=executable):
                rows = [maintenance.subprocess.CompletedProcess([], 0, str(os.getuid()) + ' 90001 ' + executable + '\n'),
                        maintenance.subprocess.CompletedProcess([], 0, '90001 ' + arguments + '\n')]
                with patch.object(maintenance.subprocess, 'run', side_effect=rows):
                    with self.assertRaises(maintenance.MaintenanceError) as raised:
                        CHECK_PROCESSES(self.home, scope)
                self.assertNotIn('private-argv-fixture', str(raised.exception))

    def test_ordinary_edge_does_not_block_dedicated_profile_maintenance(self):
        edge = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        rows = [maintenance.subprocess.CompletedProcess([], 0, str(os.getuid()) + ' 90001 ' + edge + '\n'),
                maintenance.subprocess.CompletedProcess([], 0, '90001 ' + edge + ' --user-data-dir=' + str(self.home / 'Library/Application Support/Microsoft Edge') + '\n')]
        with patch.object(maintenance.subprocess, 'run', side_effect=rows):
            CHECK_PROCESSES(self.home, 'browser')

    def test_missing_relevant_process_arguments_is_not_treated_as_closed(self):
        edge = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        rows = [maintenance.subprocess.CompletedProcess([], 0, str(os.getuid()) + ' 90001 ' + edge + '\n'),
                maintenance.subprocess.CompletedProcess([], 0, '90002 /bin/zsh\n')]
        with patch.object(maintenance.subprocess, 'run', side_effect=rows):
            with self.assertRaises(maintenance.MaintenanceError):
                CHECK_PROCESSES(self.home, 'browser')

    def test_process_scan_failure_is_not_treated_as_closed(self):
        rows = [maintenance.subprocess.CompletedProcess([], 1, ''),
                maintenance.subprocess.CompletedProcess([], 0, '')]
        with patch.object(maintenance.subprocess, 'run', side_effect=rows):
            with self.assertRaises(maintenance.MaintenanceError):
                CHECK_PROCESSES(self.home, 'desktop')

    def test_failure_at_each_desktop_move_restores_originals(self):
        real_rename = maintenance._rename
        for fail_at in [1, 2]:
            with self.subTest(fail_at=fail_at):
                first = self.put(self.desktop / 'ant-did', b'first-original')
                second = self.put(self.desktop / 'ant-device-registry.json', b'second-original')
                plan = self.manager.preview('desktop-ids')
                calls = 0
                def failing(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == fail_at:
                        raise OSError('injected rename failure')
                    return real_rename(source, destination)
                with patch.object(maintenance, '_rename', side_effect=failing):
                    with self.assertRaises(maintenance.MaintenanceError):
                        self.manager.apply(plan['token'])
                self.assertEqual(first.read_bytes(), b'first-original')
                self.assertEqual(second.read_bytes(), b'second-original')
                self.assertTrue(self.manager.preview('desktop-ids')['can_apply'])

    def test_failure_after_rename_is_inferred_and_rolled_back(self):
        target = self.put(self.desktop / 'ant-did', b'moved-original')
        plan = self.manager.preview('desktop-ids')
        real_rename = maintenance._rename
        failed = False
        def fail_after(source, destination):
            nonlocal failed
            result = real_rename(source, destination)
            if not failed:
                failed = True
                raise OSError('injected failure after move')
            return result
        with patch.object(maintenance, '_rename', side_effect=fail_after):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'moved-original')

    def test_cross_volume_move_failure_does_not_fall_back_to_copy_and_delete(self):
        target = self.put(self.desktop / 'ant-did', b'cross-volume-original')
        plan = self.manager.preview('desktop-ids')
        with patch.object(maintenance, '_rename', side_effect=OSError(errno.EXDEV, 'fixture cross volume')):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'cross-volume-original')

    def test_failure_committing_success_restores_original_data(self):
        target = self.put(self.desktop / 'ant-did', b'original-before-commit')
        plan = self.manager.preview('desktop-ids')
        real_write = self.manager._write
        failed = False
        def fail_commit(path, value):
            nonlocal failed
            if value.get('state') == 'completed' and not failed:
                failed = True
                raise OSError('injected success record failure')
            return real_write(path, value)
        with patch.object(self.manager, '_write', side_effect=fail_commit):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'original-before-commit')
        self.assertTrue(self.manager.preview('desktop-ids')['can_apply'])

    def test_interrupted_automatic_rollback_never_publishes_partial_success(self):
        targets = {
            self.put(self.desktop / 'ant-did', b'first-before-rollback-interruption'): b'first-before-rollback-interruption',
            self.put(self.desktop / 'ant-device-registry.json', b'second-before-rollback-interruption'): b'second-before-rollback-interruption',
        }
        plan = self.manager.preview('desktop-ids')
        real_write = self.manager._write
        commit_failed = interrupted = False
        def fail_commit_then_interrupt_rollback(path, value):
            nonlocal commit_failed, interrupted
            if value.get('state') == 'completed' and not commit_failed:
                commit_failed = True
                raise OSError('fixture final success record failure')
            result = real_write(path, value)
            if commit_failed and not interrupted and len(value.get('steps', [])) == 1:
                interrupted = True
                raise KeyboardInterrupt('fixture interruption after inverse checkpoint')
            return result
        with patch.object(self.manager, '_write', side_effect=fail_commit_then_interrupt_rollback):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.apply(plan['token'])
        self.assertTrue(commit_failed and interrupted)
        pending = [b for b in self.manager.backups()['backups'] if b['state'] == 'recovery_required']
        self.assertEqual(len(pending), 1)
        for target, original in targets.items():
            self.assertTrue((target.exists() and target.read_bytes() == original)
                            or self.find_backup_bytes(pending[0]['backup_id'], original))
        with self.assertRaises(maintenance.MaintenanceError):
            with maintenance.entry_lock(self.home, 'desktop'):
                pass
        recovery = self.manager.preview_recover(pending[0]['backup_id'])
        self.assertTrue(self.manager.apply(recovery['token'])['ok'])
        for target, original in targets.items():
            self.assertEqual(target.read_bytes(), original)
        with maintenance.entry_lock(self.home, 'desktop'):
            pass

    def test_initial_journal_failure_does_not_poison_backup_listing_or_entry_lock(self):
        target = self.put(self.desktop / 'ant-did', b'untouched-initial-write')
        plan = self.manager.preview('desktop-ids')
        real_write = self.manager._write
        failed = False
        def fail_initial_journal(path, value):
            nonlocal failed
            if Path(path).name == 'record.json' and value.get('state') == 'applying' and not value.get('steps') and not failed:
                failed = True
                raise OSError('injected initial journal failure')
            return real_write(path, value)
        with patch.object(self.manager, '_write', side_effect=fail_initial_journal):
            with self.assertRaises((maintenance.MaintenanceError, OSError)):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'untouched-initial-write')
        self.assertEqual(self.manager.backups()['backups'], [])
        with maintenance.entry_lock(self.home, 'desktop'):
            pass
        self.assertTrue(self.manager.preview('desktop-ids')['can_apply'])

    def test_journal_publish_failure_leaves_live_data_and_scope_usable(self):
        target = self.put(self.desktop / 'ant-did', b'untouched-publish-failure')
        plan = self.manager.preview('desktop-ids')
        with patch.object(maintenance, '_publish', side_effect=OSError('injected publish failure')):
            with self.assertRaises((maintenance.MaintenanceError, OSError)):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'untouched-publish-failure')
        self.assertEqual(self.manager.backups()['backups'], [])
        with maintenance.entry_lock(self.home, 'desktop'):
            pass
        self.assertTrue(self.manager.preview('desktop-ids')['can_apply'])

    def test_interruption_after_journal_publish_has_recoverable_record(self):
        target = self.put(self.desktop / 'ant-did', b'untouched-published-journal')
        plan = self.manager.preview('desktop-ids')
        real_publish = maintenance._publish
        def interrupt_after_publish(source, destination):
            real_publish(source, destination)
            raise KeyboardInterrupt('fixture abrupt interruption')
        with patch.object(maintenance, '_publish', side_effect=interrupt_after_publish):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'untouched-published-journal')
        pending = [b for b in self.manager.backups()['backups'] if b['state'] == 'recovery_required']
        self.assertEqual(len(pending), 1)
        with self.assertRaises(maintenance.MaintenanceError):
            with maintenance.entry_lock(self.home, 'desktop'):
                pass
        recovery = self.manager.preview_recover(pending[0]['backup_id'])
        self.assertTrue(recovery['can_apply'])
        self.assertTrue(self.manager.apply(recovery['token'])['ok'])
        self.assertEqual(target.read_bytes(), b'untouched-published-journal')
        with maintenance.entry_lock(self.home, 'desktop'):
            pass

    def interrupt_restore_before_final_commit(self):
        target = self.put(self.desktop / 'ant-did', b'original-before-interrupted-restore')
        cleaned = self.apply_mode('desktop-ids')
        self.put(target, b'new-current-before-interrupted-restore')
        plan = self.manager.preview_restore(cleaned['backup_id'])
        real_write = self.manager._write
        def interrupt_new_success(path, value):
            if value.get('state') == 'completed' and Path(path).parent.name != cleaned['backup_id']:
                raise KeyboardInterrupt('fixture interrupt between old consumed and new success')
            return real_write(path, value)
        with patch.object(self.manager, '_write', side_effect=interrupt_new_success):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.apply(plan['token'])
        pending = [b for b in self.manager.backups()['backups'] if b['state'] == 'recovery_required']
        self.assertEqual(len(pending), 1)
        return target, cleaned['backup_id'], pending[0]['backup_id']

    def test_interrupted_restore_commit_can_recover_and_reuse_original_backup(self):
        target, original, pending = self.interrupt_restore_before_final_commit()
        with self.assertRaises(maintenance.MaintenanceError):
            with maintenance.entry_lock(self.home, 'desktop'):
                pass
        recovery = self.manager.preview_recover(pending)
        self.assertTrue(self.manager.apply(recovery['token'])['ok'])
        self.assertEqual(target.read_bytes(), b'new-current-before-interrupted-restore')
        again = self.manager.preview_restore(original)
        self.assertTrue(self.manager.apply(again['token'])['ok'])
        self.assertEqual(target.read_bytes(), b'original-before-interrupted-restore')

    def test_interrupted_restore_recovery_metadata_stays_pending_until_retry(self):
        target, original, pending = self.interrupt_restore_before_final_commit()
        recovery = self.manager.preview_recover(pending)
        real_write = self.manager._write
        def interrupt_old_backup_refresh(path, value):
            if value.get('state') == 'completed' and Path(path).parent.name == original:
                raise KeyboardInterrupt('fixture interruption before original backup refresh')
            return real_write(path, value)
        with patch.object(self.manager, '_write', side_effect=interrupt_old_backup_refresh):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.apply(recovery['token'])
        self.assertEqual(target.read_bytes(), b'new-current-before-interrupted-restore')
        with self.assertRaises(maintenance.MaintenanceError):
            with maintenance.entry_lock(self.home, 'desktop'):
                pass
        retry = self.manager.preview_recover(pending)
        self.assertTrue(self.manager.apply(retry['token'])['ok'])
        again = self.manager.preview_restore(original)
        self.assertTrue(self.manager.apply(again['token'])['ok'])
        self.assertEqual(target.read_bytes(), b'original-before-interrupted-restore')

    def test_failed_restore_keeps_original_backup_usable(self):
        target = self.put(self.desktop / 'ant-did', b'original-saved-id')
        cleaned = self.apply_mode('desktop-ids')
        self.put(target, b'new-current-id')
        plan = self.manager.preview_restore(cleaned['backup_id'])
        real_rename = maintenance._rename
        calls = 0
        def fail_after_second_move(source, destination):
            nonlocal calls
            calls += 1
            result = real_rename(source, destination)
            if calls == 2:
                raise OSError('injected restore move failure')
            return result
        with patch.object(maintenance, '_rename', side_effect=fail_after_second_move):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'new-current-id')
        self.assertTrue(self.find_backup_bytes(cleaned['backup_id'], b'original-saved-id'))
        again = self.manager.preview_restore(cleaned['backup_id'])
        self.assertTrue(self.manager.apply(again['token'])['ok'])
        self.assertEqual(target.read_bytes(), b'original-saved-id')

    def test_restore_metadata_failure_does_not_consume_original_backup(self):
        target = self.put(self.desktop / 'ant-did', b'original-restorable-id')
        cleaned = self.apply_mode('desktop-ids')
        self.put(target, b'current-before-restore')
        plan = self.manager.preview_restore(cleaned['backup_id'])
        real_write = self.manager._write
        failed = False
        def fail_after_consumed_record(path, value):
            nonlocal failed
            result = real_write(path, value)
            if value.get('state') == 'consumed' and not failed:
                failed = True
                raise OSError('injected consumed record acknowledgment failure')
            return result
        with patch.object(self.manager, '_write', side_effect=fail_after_consumed_record):
            with self.assertRaises(maintenance.MaintenanceError):
                self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'current-before-restore')
        again = self.manager.preview_restore(cleaned['backup_id'])
        self.assertTrue(self.manager.apply(again['token'])['ok'])
        self.assertEqual(target.read_bytes(), b'original-restorable-id')

    def test_conflicting_new_target_preserves_both_and_requires_recovery(self):
        target = self.put(self.desktop / 'ant-did', b'original-before-conflict')
        plan = self.manager.preview('desktop-ids')
        real_rename = maintenance._rename
        failed = False
        def collide(source, destination):
            nonlocal failed
            result = real_rename(source, destination)
            if not failed:
                failed = True
                self.put(target, b'concurrent-user-data')
                raise OSError('injected conflict')
            return result
        with patch.object(maintenance, '_rename', side_effect=collide):
            with self.assertRaises(maintenance.MaintenanceError) as raised:
                self.manager.apply(plan['token'])
        self.assertTrue(raised.exception.recovery_required)
        self.assertEqual(target.read_bytes(), b'concurrent-user-data')
        pending = [b for b in self.manager.backups()['backups'] if b['state'] == 'recovery_required']
        self.assertEqual(len(pending), 1)
        self.assertTrue(self.find_backup_bytes(pending[0]['backup_id'], b'original-before-conflict'))
        with self.assertRaises(maintenance.MaintenanceError):
            with maintenance.entry_lock(self.home, 'desktop'):
                pass
        target.rename(self.desktop / 'saved-concurrent-data')
        recovery = self.manager.preview_recover(pending[0]['backup_id'])
        result = self.manager.apply(recovery['token'])
        self.assertTrue(result['ok'])
        self.assertEqual(target.read_bytes(), b'original-before-conflict')
        self.assertEqual((self.desktop / 'saved-concurrent-data').read_bytes(), b'concurrent-user-data')

    def test_restore_preserves_new_profile_as_another_backup(self):
        cookie = self.put(self.profile / 'Default/Network/Cookies', b'original-cookies')
        cleaned = self.apply_mode('browser-reset')
        self.put(cookie, b'new-session-cookies')
        self.put(self.profile / 'Default/Bookmarks', b'new-bookmarks')
        preview = self.manager.preview_restore(cleaned['backup_id'])
        self.assertEqual(preview['operation'], 'restore')
        result = self.manager.apply(preview['token'])
        self.assertEqual(cookie.read_bytes(), b'original-cookies')
        self.assertTrue(self.find_backup_bytes(result['backup_id'], b'new-session-cookies'))
        self.assertTrue(self.find_backup_bytes(result['backup_id'], b'new-bookmarks'))
        undo = self.manager.preview_restore(result['backup_id'])
        self.manager.apply(undo['token'])
        self.assertEqual(cookie.read_bytes(), b'new-session-cookies')
        self.assertEqual((self.profile / 'Default/Bookmarks').read_bytes(), b'new-bookmarks')

    def test_native_restore_merges_only_id_fields_into_current_json(self):
        config = self.put_json(self.native / '.claude.json', {
            'userID': 'original-id', 'machineID': 'original-machine',
            'oauthAccount': {'uuid': 'old-oauth'}, 'projects': {'old': True},
        })
        result = self.apply_mode('native-ids')
        current = {'userID': 'fresh-id', 'anonymousId': 'fresh-anonymous',
                   'oauthAccount': {'uuid': 'new-oauth'}, 'projects': {'new': True},
                   'mcpServers': {'new': {'command': 'fixture'}}}
        self.put_json(config, current)
        restore = self.manager.preview_restore(result['backup_id'])
        restored = self.manager.apply(restore['token'])
        expected = {k: v for k, v in current.items() if k not in ['userID', 'anonymousId']}
        expected.update(userID='original-id', machineID='original-machine')
        self.assertEqual(json.loads(config.read_text()), expected)
        undo = self.manager.preview_restore(restored['backup_id'])
        self.manager.apply(undo['token'])
        self.assertEqual(json.loads(config.read_text()), current)

    def test_changed_restore_target_and_tampered_backup_are_refused(self):
        target = self.put(self.desktop / 'ant-did', b'original-for-backup')
        result = self.apply_mode('desktop-ids')
        self.put(target, b'current-before-preview')
        plan = self.manager.preview_restore(result['backup_id'])
        target.write_bytes(b'current-after-preview')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.apply(plan['token'])
        self.assertEqual(target.read_bytes(), b'current-after-preview')
        saved = self.find_backup_bytes(result['backup_id'], b'original-for-backup')
        self.assertEqual(len(saved), 1)
        saved[0].write_bytes(b'tampered-backup')
        with self.assertRaises(maintenance.MaintenanceError):
            self.manager.preview_restore(result['backup_id'])
        self.assertEqual(target.read_bytes(), b'current-after-preview')

    @unittest.skipUnless(sys.platform == 'darwin' or sys.platform.startswith('linux'),
                         'exclusive no-follow rename is supported on macOS/Linux')
    def test_late_restore_destination_cannot_replace_new_user_data(self):
        target = self.put(self.desktop / 'ant-did', b'original-before-late-destination')
        cleaned = self.apply_mode('desktop-ids')
        plan = self.manager.preview_restore(cleaned['backup_id'])
        real_rename = maintenance._rename
        injected = False
        def create_destination_then_move(source, destination):
            nonlocal injected
            if Path(destination) == target and not injected:
                injected = True
                self.put(target, b'late-created-user-data')
            return real_rename(source, destination)
        with patch.object(maintenance, '_rename', side_effect=create_destination_then_move):
            with self.assertRaises(maintenance.MaintenanceError) as raised:
                self.manager.apply(plan['token'])
        self.assertTrue(raised.exception.recovery_required)
        self.assertEqual(target.read_bytes(), b'late-created-user-data')
        self.assertTrue(self.find_backup_bytes(cleaned['backup_id'], b'original-before-late-destination'))
        self.assertTrue(any(b['state'] == 'recovery_required'
                            for b in self.manager.backups()['backups']))

    @unittest.skipUnless(sys.platform == 'darwin' or sys.platform.startswith('linux'),
                         'exclusive no-follow rename is supported on macOS/Linux')
    def test_late_restore_parent_symlink_cannot_redirect_data_outside_scope(self):
        target = self.put(self.desktop / 'ant-did', b'original-before-parent-race')
        cleaned = self.apply_mode('desktop-ids')
        plan = self.manager.preview_restore(cleaned['backup_id'])
        outside = self.home / 'outside-restore-scope'
        witness = self.put(outside / 'leave-me', b'outside-data')
        real_rename = maintenance._rename
        injected = False
        def replace_parent_then_move(source, destination):
            nonlocal injected
            if Path(destination) == target and not injected:
                injected = True
                target.parent.rename(target.parent.with_name('Claude-before-race'))
                target.parent.symlink_to(outside, target_is_directory=True)
            return real_rename(source, destination)
        with patch.object(maintenance, '_rename', side_effect=replace_parent_then_move):
            with self.assertRaises(maintenance.MaintenanceError) as raised:
                self.manager.apply(plan['token'])
        self.assertTrue(raised.exception.recovery_required)
        self.assertTrue(target.parent.is_symlink())
        self.assertFalse((outside / 'ant-did').exists())
        self.assertEqual(witness.read_bytes(), b'outside-data')
        self.assertTrue(self.find_backup_bytes(cleaned['backup_id'], b'original-before-parent-race'))

    def test_state_and_backup_metadata_are_private_and_results_are_redacted(self):
        self.put(self.desktop / 'ant-did', b'sensitive-identifier-fixture')
        preview = self.manager.preview('desktop-ids')
        result = self.manager.apply(preview['token'])
        listing = self.manager.backups()
        self.assertNotIn('sensitive-identifier-fixture', json.dumps([preview, result, listing]))
        self.assertEqual(stat.S_IMODE(self.manager.root.stat().st_mode), 0o700)
        for p in self.manager.root.rglob('*.json'):
            if '/before/' not in str(p) and '/new/' not in str(p):
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600, str(p))
        for child in ['plans', 'backups']:
            self.assertEqual(stat.S_IMODE((self.manager.root / child).stat().st_mode), 0o700)


if __name__ == '__main__':
    unittest.main()
