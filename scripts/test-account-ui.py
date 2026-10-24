#!/usr/bin/env python3
"""Compile the real SwiftUI model against an isolated fake core; never open Claude."""
import argparse
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
    (folder / 'commands').write_text('')
    core = '''#!/bin/bash
root=__ROOT__
echo "$*" >> "$root/commands"
case "$1" in
 checkdetail) sleep 0.1; cat "$root/rows" ;;
 status) cat "$root/status" ;;
 account-note) echo 'Account permission not verified' ;;
 fix) echo 'FIX:fixture complete' ;;
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
    command = ['swiftc', '-parse-as-library', '-target', platform.machine() + '-apple-macos13.0',
               '-sdk', sdk, '-framework', 'SwiftUI', '-framework', 'AppKit',
               str(folder / 'Model.swift'), str(repo / 'tests/AccountSelectionTests.swift'),
               '-o', str(folder / 'account-ui-tests')]
    subprocess.run(command, check=True, timeout=90)
    subprocess.run([str(folder / 'account-ui-tests'), str(folder)], check=True, timeout=25)
