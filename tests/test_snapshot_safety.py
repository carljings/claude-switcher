"""Filesystem failure regressions. Only isolated fixtures and extracted functions run."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'core/claude-switch.sh'


def function_source(name):
    match = re.search(rf'(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}', SOURCE.read_text())
    if match is None:
        raise AssertionError('Missing shell function: ' + name)
    return match.group(0)


class SnapshotSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='snapshot-safety-')
        self.addCleanup(self.tmp.cleanup)
        self.fixture = Path(self.tmp.name)
        self.base = self.fixture / 'state'
        self.data = self.fixture / 'live'
        (self.base / 'accounts/A').mkdir(parents=True)
        (self.base / 'accounts/B').mkdir()
        self.data.mkdir()
        (self.base / 'accounts/A/marker').write_text('old-A')
        (self.base / 'accounts/B/marker').write_text('saved-B')
        (self.data / 'marker').write_text('live-A')

    def run_shell(self, code, injection='none'):
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(self.fixture),
               'BASE': str(self.base), 'DATA': str(self.data), 'FIXTURE': str(self.fixture),
               'INJECT': injection, 'LC_ALL': 'C'}
        harness = r'''
set -u
log() { printf '%s\n' "$*" >> "$FIXTURE/log"; }
check() { return 0; }
echo() {
    if [ "$INJECT" = "current_commit_error" ] && [ "$#" -eq 1 ] && { [ "$1" = A ] || [ "$1" = B ]; }; then return 23; fi
    command echo "$@"
}
printf() {
    if [ "$INJECT" = "record_write_error" ] && [ "$#" -eq 2 ] && [ "$1" = '%s\n' ] && { [ "$2" = A ] || [ "$2" = B ]; }; then return 23; fi
    command printf "$@"
}
copy_tree() {
    if [ "$INJECT" = "copy_error" ] || [ "$INJECT" = "load_error" ]; then
        mkdir -p "$2"
        printf partial > "$2/partial"
        return 43
    fi
    mkdir -p "$2" && cp -R "$1/." "$2/"
}
quit_claude() {
    printf called > "$FIXTURE/quit"
    [ "$INJECT" != "quit_error" ]
}
open() { printf called > "$FIXTURE/launched"; }
mv() {
    if [ "$1" = "$DATA" ]; then
        if [ "$INJECT" = "copy_error" ] || [ "$INJECT" = "first_move_error" ]; then return 23; fi
        if [ "$INJECT" = "partial_move_error" ]; then
            mkdir -p "$2"
            printf partial > "$2/partial"
            return 23
        fi
    fi
    if [ "$INJECT" = "final_rename_error" ] && [ "$1" = "$BASE/accounts/A.new" ] && [ "$2" = "$BASE/accounts/A" ]; then return 23; fi
    if [ "$INJECT" = "old_rename_error" ] && [ "$1" = "$BASE/accounts/A" ] && [ "$2" = "$BASE/accounts/A.previous" ]; then return 23; fi
    if [ "$INJECT" = "load_rename_error" ] && [ "$1" = "$DATA.new" ] && [ "$2" = "$DATA" ]; then return 23; fi
    if [ "$INJECT" = "current_commit_error" ] && [ "$1" = "$BASE/current.new" ] && [ "$2" = "$BASE/current" ]; then return 23; fi
    command mv "$@"
}
'''
        return subprocess.run(['/bin/bash', '-c', harness + '\n' + code], env=env,
                              cwd=self.fixture, text=True, capture_output=True, timeout=8)

    def archive(self, injection='none'):
        return self.run_shell(function_source('archive_current') + '\narchive_current A', injection)

    def switch(self, target='B', injection='none', override=''):
        return self.run_shell(function_source('archive_current') + '\n' + override + '\n'
                              + function_source('switch_to') + '\nswitch_to ' + target, injection)

    def assert_unchanged(self):
        self.assertEqual((self.data / 'marker').read_text(), 'live-A')
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'old-A')

    def test_final_archive_rename_failure_restores_both_copies(self):
        run = self.archive('final_rename_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertFalse((self.base / 'accounts/A.new').exists())
        self.assertFalse((self.base / 'accounts/A.previous').exists())

    def test_existing_archive_recovery_copies_are_not_deleted(self):
        for suffix in ['new', 'previous']:
            with self.subTest(suffix=suffix):
                pending = self.base / ('accounts/A.' + suffix)
                pending.mkdir()
                (pending / 'marker').write_text('only-recovery-copy')
                run = self.archive()
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assert_unchanged()
                self.assertEqual((pending / 'marker').read_text(), 'only-recovery-copy')
                pending.rename(self.fixture / ('reviewed-' + suffix))

    def test_old_archive_rename_failure_restores_live_copy(self):
        run = self.archive('old_rename_error')
        self.assertNotEqual(run.returncode, 0)
        self.assert_unchanged()

    def test_fallback_copy_failure_preserves_original_and_partial_copy(self):
        run = self.archive('copy_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertEqual((self.base / 'accounts/A.new/partial').read_text(), 'partial')

    def test_partial_move_failure_preserves_all_evidence(self):
        run = self.archive('partial_move_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertEqual((self.base / 'accounts/A.new/partial').read_text(), 'partial')

    def test_archive_success_and_copy_fallback_success(self):
        for injection in ['none', 'first_move_error']:
            with self.subTest(injection=injection):
                run = self.archive(injection)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
                self.assertFalse((self.base / 'accounts/A.previous').exists())
                self.assertFalse((self.base / 'accounts/A.new').exists())
                if not self.data.exists():
                    self.data.mkdir()
                    (self.data / 'marker').write_text('live-A')

    def test_switch_stops_if_archive_fails(self):
        (self.base / 'current').write_text('A')
        run = self.switch(override='archive_current() { return 23; }')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertEqual((self.base / 'current').read_text(), 'A')
        self.assertFalse((self.fixture / 'launched').exists())

    def test_first_enrollment_stops_if_archive_fails(self):
        run = self.switch(override='archive_current() { return 23; }')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertFalse((self.base / 'current').exists())
        self.assertFalse((self.fixture / 'launched').exists())

    def test_load_copy_failure_does_not_commit_or_launch(self):
        (self.base / 'current').write_text('A')
        run = self.switch(injection='load_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.base / 'current').read_text(), 'A')
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
        self.assertEqual((self.base / 'accounts/B/marker').read_text(), 'saved-B')
        self.assertEqual((Path(str(self.data) + '.new') / 'partial').read_text(), 'partial')
        self.assertFalse((self.fixture / 'launched').exists())

    def test_first_enrollment_restore_failure_does_not_commit_or_launch(self):
        run = self.switch(target='A', injection='load_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse((self.base / 'current').exists())
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
        self.assertEqual((Path(str(self.data) + '.new') / 'partial').read_text(), 'partial')
        self.assertFalse(self.data.exists())
        self.assertFalse((self.fixture / 'launched').exists())

    def test_archive_recovery_on_either_account_blocks_switch(self):
        (self.base / 'current').write_text('A')
        pending = self.base / 'accounts/B.previous'
        pending.mkdir()
        (pending / 'marker').write_text('only-recovery-copy')
        run = self.switch()
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertEqual((pending / 'marker').read_text(), 'only-recovery-copy')
        self.assertFalse((self.fixture / 'quit').exists())
        self.assertFalse((self.fixture / 'launched').exists())

    def test_invalid_current_marker_does_not_change_or_launch(self):
        (self.base / 'current').write_text('../unexpected')
        run = self.switch()
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertEqual((self.base / 'current').read_text(), '../unexpected')
        self.assertFalse((self.fixture / 'launched').exists())

    def test_existing_live_staging_blocks_before_archive(self):
        (self.base / 'current').write_text('A')
        pending = Path(str(self.data) + '.new')
        pending.mkdir()
        (pending / 'marker').write_text('only-pending-copy')
        run = self.switch()
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertEqual((pending / 'marker').read_text(), 'only-pending-copy')
        self.assertFalse((self.fixture / 'quit').exists())
        self.assertFalse((self.fixture / 'launched').exists())

    def test_load_final_rename_failure_keeps_recoverable_archives(self):
        (self.base / 'current').write_text('A')
        run = self.switch(injection='load_rename_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.base / 'current').read_text(), 'A')
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
        self.assertEqual((Path(str(self.data) + '.new') / 'marker').read_text(), 'saved-B')
        self.assertFalse((self.fixture / 'launched').exists())

    def test_successful_switch_loads_and_commits_target(self):
        (self.base / 'current').write_text('A')
        run = self.switch()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.base / 'current').read_text().strip(), 'B')
        self.assertEqual((self.data / 'marker').read_text(), 'saved-B')
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
        self.assertFalse((self.base / 'current.new').exists())
        self.assertTrue((self.fixture / 'launched').exists())

    def test_first_enrollment_commits_and_restores_same_account(self):
        run = self.switch(target='A')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.base / 'current').read_text().strip(), 'A')
        self.assertEqual((self.data / 'marker').read_text(), 'live-A')
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
        self.assertFalse((self.base / 'current.new').exists())
        self.assertTrue((self.fixture / 'launched').exists())

    def test_first_enrollment_commits_other_target_after_preserving_a(self):
        run = self.switch(target='B')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.base / 'current').read_text().strip(), 'B')
        self.assertEqual((self.data / 'marker').read_text(), 'saved-B')
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
        self.assertFalse((self.base / 'current.new').exists())
        self.assertTrue((self.fixture / 'launched').exists())

    def assert_subsequent_switches_blocked(self):
        def state():
            return {str(p.relative_to(self.fixture)): p.read_bytes()
                    for root in [self.base, self.data] if root.exists()
                    for p in root.rglob('*') if p.is_file()}
        before = state()
        for target in ['A', 'B']:
            with self.subTest(retry=target):
                run = self.switch(target=target)
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual(state(), before)
                self.assertFalse((self.fixture / 'launched').exists())

    def test_current_commit_failure_blocks_both_subsequent_targets(self):
        (self.base / 'current').write_text('A')
        (self.base / 'current').chmod(0o400)
        run = self.switch(injection='current_commit_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.base / 'current').read_text(), 'A')
        self.assertEqual((self.data / 'marker').read_text(), 'saved-B')
        self.assertEqual((self.base / 'accounts/A/marker').read_text(), 'live-A')
        self.assertFalse((self.fixture / 'launched').exists())
        self.assert_subsequent_switches_blocked()

    def test_first_enrollment_current_commit_failure_blocks_retries(self):
        run = self.switch(target='A', injection='current_commit_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.data / 'marker').read_text(), 'live-A')
        self.assertFalse((self.base / 'current').exists())
        self.assertEqual((self.base / 'current.new').read_text().strip(), 'A')
        self.assertFalse((self.fixture / 'launched').exists())
        self.assert_subsequent_switches_blocked()

    def test_current_record_is_prepared_before_any_profile_change(self):
        (self.base / 'current').write_text('A')
        run = self.switch(injection='record_write_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assert_unchanged()
        self.assertEqual((self.base / 'current').read_text(), 'A')
        self.assertFalse((self.fixture / 'quit').exists())
        self.assertFalse((self.fixture / 'launched').exists())

    def test_quit_failure_keeps_recovery_record_and_blocks_retries(self):
        (self.base / 'current').write_text('A')
        run = self.switch(injection='quit_error')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('恢复前不能再次切换', run.stdout)
        self.assert_unchanged()
        self.assertEqual((self.base / 'current.new').read_text().strip(), 'B')
        self.assert_subsequent_switches_blocked()

    def test_existing_pending_current_record_blocks_even_current_open(self):
        (self.base / 'current').write_text('A')
        (self.base / 'current.new').write_text('B')
        self.assert_subsequent_switches_blocked()
        self.assert_unchanged()
        self.assertFalse((self.fixture / 'quit').exists())

    def test_current_record_rejects_directories_and_all_symlinks(self):
        current = self.base / 'current'
        directory = self.fixture / 'record-directory'
        directory.mkdir()
        target_file = self.fixture / 'record-file'
        target_file.write_text('A')
        for kind in ['directory', 'directory-link', 'file-link', 'dangling-link']:
            with self.subTest(kind=kind):
                if kind == 'directory':
                    current.mkdir()
                    (current / 'marker').write_text('preserve-directory')
                else:
                    target = {'directory-link': directory, 'file-link': target_file,
                              'dangling-link': self.fixture / 'missing-record'}[kind]
                    current.symlink_to(target)
                run = self.switch()
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assert_unchanged()
                self.assertFalse((self.base / 'current.new').exists())
                self.assertFalse((self.fixture / 'quit').exists())
                self.assertFalse((self.fixture / 'launched').exists())
                if kind == 'directory':
                    self.assertEqual((current / 'marker').read_text(), 'preserve-directory')
                else:
                    self.assertEqual(current.readlink(), target)
                    self.assertEqual(target_file.read_text(), 'A')
                current.rename(self.fixture / ('reviewed-' + kind))


if __name__ == '__main__':
    unittest.main()
