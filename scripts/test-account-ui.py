#!/usr/bin/env python3
"""Compile the real SwiftUI model against an isolated fake core; never open Claude."""
import argparse
import os
from pathlib import Path
import platform
import shlex
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sdk', help='Optional matching macOS SDK path')
args = parser.parse_args()
sdk = args.sdk or subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
with tempfile.TemporaryDirectory(prefix='switcher-account-ui-') as folder:
    folder = Path(folder)
    source = (repo / 'app/main.swift').read_text().split('// MARK: - 视图')[0]
    (folder / 'Model.swift').write_text(source)
    keys = ['代理内核', 'TUN网卡', '出口IP', 'IP一致', '时区', '地区', 'IPv6', 'DNS',
            'WebRTC', '保镖', '规则置顶', '客户端语言', 'ASN属性', '生态可达性']
    (folder / 'rows').write_text(''.join(key + '=ok:fixture\n' for key in keys))
    (folder / 'status').write_text('current=A hasA=1 hasB=0\n')
    (folder / 'mode').write_text('failure')
    (folder / 'protected-mode').write_text('success')
    (folder / 'check-mode').write_text('success')
    (folder / 'status-mode').write_text('success')
    (folder / 'maintenance-mode').write_text('success')
    (folder / 'commands').write_text('')
    (folder / 'maintenance-fixture.py').write_text('''import json
from pathlib import Path
import sys
import time

root = Path(__file__).parent
behavior = (root / 'maintenance-mode').read_text().strip()
command = sys.argv[1]
argument = sys.argv[2] if len(sys.argv) > 2 else ''
if behavior == 'empty':
    sys.exit(0)
if behavior in ['bad-json', 'plain', 'fail-text']:
    print({'bad-json': '{invalid', 'plain': 'OK:unstructured output', 'fail-text': 'FAIL:fixture maintenance failed'}[behavior])
    sys.exit(1 if behavior == 'fail-text' else 0)
if behavior in ['failure', 'recovery-error']:
    print(json.dumps({'schema_version': 1, 'ok': False, 'code': 'fixture-error', 'message': 'Fixture maintenance failed', 'recovery_required': behavior == 'recovery-error'}))
    sys.exit(2)
tokens = {'cache': 'a' * 32, 'browser-reset': 'b' * 32, 'desktop-ids': 'c' * 32, 'native-ids': 'd' * 32}
scope = 'Dedicated fixture paths only'
if command == 'maintenance-backups':
    payload = {'backups': [
        {'backup_id': 'fixture-completed', 'mode': 'cache', 'created_at': 1792800000, 'label': 'Fixture cache backup', 'state': 'completed'},
        {'backup_id': 'fixture-recovery', 'mode': 'browser-reset', 'created_at': 1792800100, 'label': 'Fixture interrupted backup', 'state': 'recovery_required'},
    ]}
elif command == 'maintenance-apply':
    known = {token: (mode, 'clean') for mode, token in tokens.items()}
    known.update({'e' * 32: ('cache', 'restore'), 'f' * 32: ('browser-reset', 'recover')})
    assert argument in known
    mode, operation = known[argument]
    payload = {'mode': mode, 'operation': operation, 'backup_id': 'fixture-result', 'message': 'Fixture confirmed operation complete', 'recovery_required': False}
else:
    if command == 'maintenance-preview':
        mode, operation, token = argument, 'clean', tokens[argument]
    elif command == 'maintenance-restore-preview':
        assert argument == 'fixture-completed'
        mode, operation, token = 'cache', 'restore', 'e' * 32
    else:
        assert command == 'maintenance-recover-preview' and argument == 'fixture-recovery'
        mode, operation, token = 'browser-reset', 'recover', 'f' * 32
    payload = {'mode': mode, 'operation': operation, 'token': token, 'scope': scope,
               'items': [{'path': '~/.claude-switcher/fixture/Cache', 'bytes': 2048, 'operation': 'backup-and-remove'}],
               'item_count': 1, 'total_bytes': 2048, 'impact': 'Fixture only; no real account data',
               'expires_at': time.time() + (0.3 if behavior == 'short-expiry' else 600), 'can_apply': True}
    if behavior == 'no-items':
        payload.update(token='', items=[], item_count=0, total_bytes=0, expires_at=0, can_apply=False)
    if behavior == 'bad-token':
        payload['token'] = 'not-a-token'
    if behavior == 'expired':
        payload['expires_at'] = time.time() - 1
    if behavior == 'missing-field':
        payload.pop('impact')
    if behavior == 'wrong-mode':
        payload['mode'] = 'browser-reset'
    if behavior == 'unknown-mode':
        payload['mode'] = 'unknown'
    if behavior == 'wrong-operation':
        payload['operation'] = 'restore'
payload.update(schema_version=2 if behavior == 'schema2' else 1, ok=True)
print(json.dumps(payload))
sys.exit(7 if behavior == 'nonzero-success' else 0)
''')
    core = '''#!/bin/bash
root=__ROOT__
echo "$*" >> "$root/commands"
case "$1" in
 checkdetail)
   sleep 0.1
   if [ "$(cat "$root/check-mode")" = empty-state ]; then
     sed 's/^IPv6=.*/IPv6=:ok/' "$root/rows"
   else
     cat "$root/rows"
   fi
   case "$(cat "$root/check-mode")" in
     nonzero-complete) exit 7 ;;
     failure-line) echo 'FAIL:fixture scan failed after output' ;;
     duplicate) head -1 "$root/rows" ;;
   esac ;;
 status)
   case "$(cat "$root/status-mode")" in
     empty) exit 0 ;;
     missing-field) echo 'current=A hasA=1' ;;
     duplicate) echo 'current=A current=B hasA=1 hasB=0' ;;
     invalid-value) echo 'current=A hasA=invalid hasB=0' ;;
     nonzero-complete) cat "$root/status"; exit 7 ;;
     *) cat "$root/status" ;;
   esac ;;
 runner-fast) echo 'OK:fixture immediate exit' ;;
 runner-timeout) exec sleep 2 ;;
 fix) echo 'FIX:fixture complete' ;;
 maintenance-preview|maintenance-apply|maintenance-backups|maintenance-restore-preview|maintenance-recover-preview)
   sleep 0.15
   python3 "$root/maintenance-fixture.py" "$@" ;;
 protected-browser)
   sleep 0.15
   case "$(cat "$root/protected-mode")" in
     success) echo "OK:fixture protected ${2:-claude}" ;;
     failure) echo 'FAIL:fixture protected preflight failed'; exit 1 ;;
     nonzero-success) echo 'OK:fixture protected opened'; exit 7 ;;
     empty) exit 0 ;;
   esac ;;
 switch)
   sleep 0.15
   case "$(cat "$root/mode")" in
     failure) echo 'FAIL:fixture preflight failed'; exit 1 ;;
     empty) exit 0 ;;
     nonzero-success) echo "OK:已切换到账号$2 (0s)"; exit 7 ;;
     partial-failure) echo 'current=B hasA=1 hasB=1' > "$root/status"; echo 'FAIL:fixture open failed'; exit 1 ;;
     same-current) echo "INFO:当前已是账号$2" ;;
     note-success) echo "current=$2 hasA=1 hasB=1" > "$root/status"; echo 'NOTE:fixture initialized'; echo "OK:已切换到账号$2 (0s)" ;;
   esac ;;
 *) echo 'FAIL:unexpected mutation'; exit 99 ;;
esac
'''.replace('__ROOT__', shlex.quote(str(folder)))
    (folder / 'core.sh').write_text(core)
    (folder / 'core.sh').chmod(0o700)
    command = ['swiftc', '-parse-as-library', '-warnings-as-errors', '-target', platform.machine() + '-apple-macos13.0',
               '-sdk', sdk, '-framework', 'SwiftUI', '-framework', 'AppKit',
               str(folder / 'Model.swift'), str(repo / 'tests/AccountSelectionTests.swift'),
               '-o', str(folder / 'account-ui-tests')]
    subprocess.run(command, check=True, timeout=90)
    environment = os.environ.copy()
    (folder / 'home').mkdir()
    environment.update(HOME=str(folder / 'home'), CFFIXED_USER_HOME=str(folder / 'home'))
    subprocess.run([str(folder / 'account-ui-tests'), str(folder)], check=True, timeout=40, env=environment)
