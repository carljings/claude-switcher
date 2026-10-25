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
        for failure in ['replace', 'link', 'final_verify']:
            with self.subTest(failure=failure):
                run = self.install(failure)
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual((self.app / 'marker').read_text(), 'original-app')
                self.assertEqual((self.desktop / 'marker').read_text(), 'original-desktop')
                self.assertFalse(self.desktop.is_symlink())
                self.assert_no_staging()

    def test_success_preserves_old_bundles_and_installs_desktop_link(self):
        self.bundle(self.app, 'original-app')
        self.bundle(self.desktop, 'original-desktop')
        run = self.install()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.app / 'Contents/MacOS/ClaudeSwitcher').read_text(), 'fixture')
        self.assertTrue(self.desktop.is_symlink())
        self.assertEqual(self.desktop.readlink(), self.app)
        backup = self.backup()
        self.assertEqual((backup / 'Applications.app/marker').read_text(), 'original-app')
        self.assertEqual((backup / 'Desktop.app/marker').read_text(), 'original-desktop')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assert_no_staging()

    def test_symlink_target_is_not_deleted_or_replaced(self):
        external = self.home / 'external.app'
        self.bundle(external, 'external')
        self.app.parent.mkdir(exist_ok=True)
        self.app.symlink_to(external)
        run = self.install()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((external / 'marker').read_text(), 'external')
        self.assertTrue((self.backup() / 'Applications.app').is_symlink())
        self.assertFalse(self.app.is_symlink())

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
