"""Execute the daemon against fake processes; never touch system services."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BodyguardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.bin = self.folder / 'bin'
        self.bin.mkdir()
        self.calls = self.folder / 'calls'
        self.report = self.folder / 'report.json'
        self.report.write_text(json.dumps({'state': 'info', 'selected': 'Fixed-A'}))
        helper = self.folder / 'network-audit.py'
        helper.write_text(
            "import json,runpy,sys\nfrom pathlib import Path\n"
            + "functions=runpy.run_path(" + repr(str(ROOT / 'core/network-audit.py')) + ")\n"
            + "report=json.loads(Path(" + repr(str(self.report)) + ").read_text())\n"
            + "if '--idle' in sys.argv: report={'state':'info','idle':True}\n"
            + "snapshot=functions['guard_state'](report,sys.argv[sys.argv.index('--state-file')+1])\n"
            + "print('stop' if snapshot['terminate_desktop'] else 'keep')\n")
        for name, body in {
            'pgrep': 'test "DOLLAR{DESKTOP_RUNNING:-1}" = 1\n',
            'pkill': 'printf \'%s\\n\' "$*" >> ' + shlex.quote(str(self.calls)) + '\n',
            'logger': 'exit 0\n',
        }.items():
            path = self.bin / name
            path.write_text('#!/bin/sh\n' + body.replace('DOLLAR', '$'))
            path.chmod(0o755)
        source = (ROOT / 'daemons/claude-bodyguard.sh').read_text()
        source = source.replace('__HOME__', str(self.folder)).replace('__PROXY_MODE__', 'clash-verge')
        source = source.replace('/Library/Application Support/claude-switcher', str(self.folder))
        source = source.replace('/usr/bin/python3', shlex.quote(sys.executable))
        source = source.replace('/usr/bin/logger', 'logger')
        self.daemon = self.folder / 'daemon.sh'
        self.daemon.write_text(source)

    def run_guard(self, running='1'):
        result = subprocess.run(['/bin/bash', str(self.daemon)],
                                env=dict(os.environ, PATH=str(self.bin)+os.pathsep+os.defpath,
                                         DESKTOP_RUNNING=running),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.folder / 'guard-status.json').read_text())

    def test_two_failures_stop_only_the_desktop_main_process(self):
        self.report.write_text(json.dumps({'state': 'fail', 'selected': 'Fixed-A'}))
        self.assertFalse(self.run_guard()['terminate_desktop'])
        self.assertFalse(self.calls.exists())
        self.assertTrue(self.run_guard()['terminate_desktop'])
        calls = self.calls.read_text().splitlines()
        self.assertEqual(calls, ['-f ^/Applications/Claude.app/Contents/MacOS/Claude([[:space:]]|$)'])

    def test_two_missing_evidence_results_stop_only_the_desktop_main_process(self):
        self.report.write_text(json.dumps({'state': 'warn', 'selected': 'Fixed-A'}))
        self.assertFalse(self.run_guard()['terminate_desktop'])
        self.assertFalse(self.calls.exists())
        self.assertTrue(self.run_guard()['terminate_desktop'])
        self.assertEqual(self.calls.read_text().splitlines(),
                         ['-f ^/Applications/Claude.app/Contents/MacOS/Claude([[:space:]]|$)'])

    def test_recovery_prevents_a_second_independent_failure_from_terminating(self):
        self.report.write_text(json.dumps({'state': 'fail', 'selected': 'Fixed-A'}))
        self.run_guard()
        self.report.write_text(json.dumps({'state': 'info', 'selected': 'Fixed-A'}))
        self.run_guard()
        self.report.write_text(json.dumps({'state': 'fail', 'selected': 'Fixed-A'}))
        self.run_guard()
        self.assertFalse(self.calls.exists())

    def test_idle_is_not_reported_as_live_exit_verification(self):
        state = self.run_guard(running='0')
        self.assertEqual(state['state'], 'idle')
        self.assertFalse(state['network_verified'])
        self.assertFalse(self.calls.exists())


if __name__ == '__main__':
    unittest.main()
