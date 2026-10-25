"""Exercise only the extracted App layout sections in a temporary HOME."""
from pathlib import Path
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'installer/安装.command'
UNINSTALLER = ROOT / 'installer/卸载.command'


@unittest.skipUnless(Path('/usr/libexec/PlistBuddy').is_file(), 'macOS App identity tool required')
class InstallerAppLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='installer-layout-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.app = self.home / 'Applications/Claude切换器.app'
        self.desktop = self.home / 'Desktop/Claude切换器.app'
        self.desktop.parent.mkdir()
        self.repo = self.home / 'source'
        (self.repo / 'app').mkdir(parents=True)
        (self.repo / 'app/main.swift').write_text('// fixture only')

    def bundle(self, path, marker, identifier='local.claude-switcher'):
        (path / 'Contents').mkdir(parents=True)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': identifier}))
        (path / 'marker').write_text(marker)

    def install(self, failure='none'):
        section = INSTALLER.read_text().split('# ---- 4. 实际 App', 1)[1].split('# ---- 5.', 1)[0]
        section = '# 实际 App' + section
        harness = r'''
H="$HOME"
pkill() { return 0; }
read() { return 0; }
swiftc() {
    [ "$FAILURE" != compile ] || return 1
    while [ "$#" -gt 0 ]; do
        if [ "$1" = -o ]; then printf fixture > "$2"; return 0; fi
        shift
    done
    return 1
}
codesign() {
    [ "$FAILURE" != signing ] || return 1
    if [ "$FAILURE" = final_verify ] && [ "${!#}" = "$H/Applications/Claude切换器.app" ]; then return 1; fi
    if [ "$FAILURE" = desktop_verify ] && [ "${!#}" = "$H/Desktop/Claude切换器.app" ]; then return 1; fi
    if [ "${!#}" = "$H/Applications/Claude切换器.app" ]; then
        case "$FAILURE" in
            concurrent_application)
                command rm -rf "$APP"
                mkdir -p "$APP"
                printf user-created > "$APP/marker"
                return 1 ;;
            cleanup_unknown_directory)
                command rm -rf "$APP_BACKUP/Applications.app"
                mkdir -p "$APP_BACKUP/Applications.app"
                printf user-created > "$APP_BACKUP/Applications.app/marker" ;;
            cleanup_unknown_link)
                command rm -rf "$APP_BACKUP/Applications.app"
                command ln -s "$H/external.app" "$APP_BACKUP/Applications.app" ;;
            cleanup_changed_identifier)
                /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier example.unrelated.app' \
                    "$APP_BACKUP/Applications.app/Contents/Info.plist" ;;
        esac
    fi
    return 0
}
mv() {
    if [ "$FAILURE" = replace ] && [ "$1" = "$APP_BUILD" ] && [ "$2" = "$APP" ]; then return 1; fi
    command mv "$@"
}
ln() {
    if [ "$FAILURE" = link ]; then return 1; fi
    if [ "$FAILURE" = concurrent_desktop ]; then
        mkdir -p "$DESKTOP_APP"
        printf user-created > "$DESKTOP_APP/marker"
        return 1
    fi
    command ln "$@"
}
'''
        env = dict(os.environ, HOME=str(self.home), REPO=str(self.repo), FAILURE=failure)
        return subprocess.run(['/bin/bash', '-c', harness + section], env=env,
                              capture_output=True, text=True, timeout=10)

    def uninstall_apps(self):
        section = UNINSTALLER.read_text().split('# ---- App 与桌面入口 ----', 1)[1].split('# ---- 用户态脚本 ----', 1)[0]
        return subprocess.run(['/bin/bash', '-c', section], env=dict(os.environ, HOME=str(self.home)),
                              capture_output=True, text=True, timeout=5)

    def backup(self):
        return next((self.home / '.claude-switcher/app-backups').glob('install.*'))

    def assert_no_staging(self):
        self.assertEqual(list((self.home / 'Applications').glob('.claude-switcher-build.*')), [])

    def test_unknown_application_or_desktop_target_is_preserved(self):
        for target in [self.app, self.desktop]:
            with self.subTest(target=target.name, location=target.parent.name):
                self.bundle(target, 'unrelated', 'example.unrelated.app')
                run = self.install()
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual((target / 'marker').read_text(), 'unrelated')
                self.assert_no_staging()
                shutil.rmtree(target)

    def test_compile_or_signature_failure_keeps_existing_app_and_entry(self):
        self.bundle(self.app, 'original')
        self.desktop.symlink_to(self.app)
        for failure in ['compile', 'signing']:
            with self.subTest(failure=failure):
                run = self.install(failure)
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual((self.app / 'marker').read_text(), 'original')
                self.assertTrue(self.desktop.is_symlink())
                self.assertEqual(self.desktop.readlink(), self.app)
                self.assert_no_staging()

    def test_commit_failures_restore_both_original_bundles(self):
        self.bundle(self.app, 'original-app')
        self.bundle(self.desktop, 'original-desktop')
        for failure in ['replace', 'link', 'final_verify', 'desktop_verify']:
            with self.subTest(failure=failure):
                run = self.install(failure)
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual((self.app / 'marker').read_text(), 'original-app')
                self.assertEqual((self.desktop / 'marker').read_text(), 'original-desktop')
                self.assertFalse(self.desktop.is_symlink())
                self.assert_no_staging()

    def test_success_removes_replaced_bundles_and_installs_desktop_link(self):
        self.bundle(self.app, 'original-app')
        self.bundle(self.desktop, 'original-desktop')
        run = self.install()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.app / 'Contents/MacOS/ClaudeSwitcher').read_text(), 'fixture')
        info = plistlib.loads((self.app / 'Contents/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleVersion'], '20261025.2')
        self.assertEqual(info['CFBundleShortVersionString'], '1.1.0')
        self.assertTrue(self.desktop.is_symlink())
        self.assertEqual(self.desktop.readlink(), self.app)
        self.assertEqual(list((self.home / '.claude-switcher/app-backups').iterdir()), [])
        self.assert_no_staging()

    def test_symlink_target_is_not_deleted_or_replaced(self):
        external = self.home / 'external.app'
        self.bundle(external, 'external')
        self.app.parent.mkdir(exist_ok=True)
        self.app.symlink_to(external)
        run = self.install()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((external / 'marker').read_text(), 'external')
        self.assertEqual(list((self.home / '.claude-switcher/app-backups').iterdir()), [])
        self.assertFalse(self.app.is_symlink())

    def test_success_does_not_scan_or_delete_historical_backups(self):
        historical = self.home / '.claude-switcher/app-backups/earlier/old.app'
        self.bundle(historical, 'historical')
        run = self.install()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((historical / 'marker').read_text(), 'historical')
        self.assertEqual(list(historical.parent.parent.glob('install.*')), [])
        self.assert_no_staging()

    def test_cleanup_preserves_changed_backup_identity_or_type(self):
        for failure in ['cleanup_unknown_directory', 'cleanup_unknown_link', 'cleanup_changed_identifier']:
            with self.subTest(failure=failure):
                self.bundle(self.app, 'original-app')
                external = self.home / 'external.app'
                self.bundle(external, 'external', 'example.unrelated.app')
                run = self.install(failure)
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual((self.app / 'Contents/MacOS/ClaudeSwitcher').read_text(), 'fixture')
                backup = self.backup() / 'Applications.app'
                if failure == 'cleanup_unknown_link':
                    self.assertTrue(backup.is_symlink())
                    self.assertEqual(backup.readlink(), external)
                else:
                    self.assertTrue(backup.is_dir())
                    self.assertEqual((backup / 'marker').read_text(),
                                     'original-app' if failure == 'cleanup_changed_identifier' else 'user-created')
                self.assertEqual((external / 'marker').read_text(), 'external')
                self.assert_no_staging()
                self.desktop.unlink()
                shutil.rmtree(self.app)
                shutil.rmtree(self.home / '.claude-switcher/app-backups')
                shutil.rmtree(external)

    def test_concurrent_application_is_not_moved_or_overwritten_during_rollback(self):
        self.bundle(self.app, 'original-app')
        self.bundle(self.desktop, 'original-desktop')
        run = self.install('concurrent_application')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.app / 'marker').read_text(), 'user-created')
        self.assertEqual((self.desktop / 'marker').read_text(), 'original-desktop')
        self.assertEqual((self.backup() / 'Applications.app/marker').read_text(), 'original-app')
        self.assertFalse((self.backup() / 'failed.app').exists())
        self.assert_no_staging()

    def test_concurrent_desktop_target_is_not_overwritten_during_rollback(self):
        self.bundle(self.app, 'original-app')
        self.bundle(self.desktop, 'original-desktop')
        run = self.install('concurrent_desktop')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.app / 'marker').read_text(), 'original-app')
        self.assertEqual((self.desktop / 'marker').read_text(), 'user-created')
        self.assertEqual((self.backup() / 'Desktop.app/marker').read_text(), 'original-desktop')
        self.assert_no_staging()

    def test_uninstall_preserves_unknown_targets_and_external_symlink_targets(self):
        self.bundle(self.app, 'unrelated', 'example.unrelated.app')
        self.desktop.symlink_to(self.app)
        run = self.uninstall_apps()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.app / 'marker').read_text(), 'unrelated')
        self.assertTrue(self.desktop.is_symlink())
        self.desktop.unlink()
        shutil.rmtree(self.app)
        external = self.home / 'external.app'
        self.bundle(external, 'external')
        self.app.symlink_to(external)
        self.desktop.symlink_to(self.app)
        run = self.uninstall_apps()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(self.desktop.is_symlink())
        self.assertFalse(self.app.is_symlink())
        self.assertEqual((external / 'marker').read_text(), 'external')

    def test_uninstall_removes_only_own_app_and_canonical_dangling_link(self):
        self.bundle(self.app, 'own-app')
        self.desktop.symlink_to(self.app)
        run = self.uninstall_apps()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.desktop.is_symlink())
        self.desktop.symlink_to(self.app)
        run = self.uninstall_apps()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(self.desktop.is_symlink())


if __name__ == '__main__':
    unittest.main()
