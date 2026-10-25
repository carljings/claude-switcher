"""Exercise only the font-component installation block in temporary directories."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / 'installer/安装.command'


class FontComponentInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='font-component-install-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.target = self.home / '.claude-switcher/font-guard'
        self.target.mkdir(parents=True)
        (self.target / 'old-marker').write_text('original-component')
        self.repo = Path(self.temp.name) / 'source'
        component = self.repo / 'core/font-guard'
        component.mkdir(parents=True)
        (component / 'manifest.json').write_text('{"fixture":"new-component"}')
        (component / 'font-guard.js').write_text('// fixture only')
        (component / 'LICENSE').write_text('fixture license')

    def install(self, failure='none'):
        source = INSTALLER.read_text()
        section = '# 字体组件单独暂存' + source.split('# 字体组件单独暂存', 1)[1].split('chmod +x "$H/.local/bin/claude-switch.sh"', 1)[0]
        harness = r'''
mv() {
    if [ "$1" = "$FONT_STAGE/font-guard" ] && [ "$2" = "$FONT_GUARD" ]; then
        if [ "$FAILURE" = move_changed ]; then
            mkdir -p "$FONT_GUARD"
            printf concurrent > "$FONT_GUARD/unrelated-marker"
            return 23
        fi
        [ "$FAILURE" != move ] || return 23
    fi
    command mv "$@"
    local result=$?
    if [ "$result" = 0 ] && [ "$1" = "$FONT_GUARD" ] && [ "$FAILURE" = after_backup ]; then
        mkdir -p "$FONT_GUARD"
        printf concurrent > "$FONT_GUARD/unrelated-marker"
    fi
    return "$result"
}
'''
        return subprocess.run(['/bin/bash', '-c', harness + section],
                              env=dict(os.environ, H=str(self.home), REPO=str(self.repo), FAILURE=failure),
                              capture_output=True, text=True, timeout=5)

    def backup(self):
        return next((self.home / '.claude-switcher/component-backups').glob('font-guard.*')) / 'font-guard'

    def assert_no_staging(self):
        self.assertEqual(list((self.home / '.claude-switcher').glob('.font-guard-install.*')), [])

    def test_success_installs_component_and_preserves_old_backup(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('new-component', (self.target / 'manifest.json').read_text())
        self.assertEqual((self.backup() / 'old-marker').read_text(), 'original-component')
        self.assert_no_staging()

    def test_concurrent_target_after_backup_is_not_used_as_a_container(self):
        result = self.install('after_backup')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'unrelated-marker').read_text(), 'concurrent')
        self.assertFalse((self.target / 'font-guard').exists())
        self.assertFalse((self.target / 'manifest.json').exists())
        self.assertEqual((self.backup() / 'old-marker').read_text(), 'original-component')
        self.assert_no_staging()

    def test_failed_move_does_not_restore_into_a_concurrent_target(self):
        result = self.install('move_changed')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'unrelated-marker').read_text(), 'concurrent')
        self.assertFalse((self.target / 'font-guard').exists())
        self.assertFalse((self.target / 'old-marker').exists())
        self.assertEqual((self.backup() / 'old-marker').read_text(), 'original-component')
        self.assert_no_staging()

    def test_failed_move_restores_original_only_when_target_remains_absent(self):
        result = self.install('move')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'old-marker').read_text(), 'original-component')
        self.assertFalse((self.target / 'font-guard').exists())
        self.assertFalse((self.target / 'manifest.json').exists())
        self.assert_no_staging()


if __name__ == '__main__':
    unittest.main()
