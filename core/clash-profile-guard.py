#!/usr/bin/env python3
"""Install opt-in final-profile guards and repair the current IPv6 flag; no app restart."""
import argparse
import datetime
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import re
import socket
import tempfile
from urllib.parse import quote

DEFAULT_SCRIPT_HASH = 'd60fb84abefb54e550bd1dead6ed16986b119d8b3890efd6f1ead9c6d151d45b'


def render(group, listener=None):
    return (Path(__file__).with_suffix('.js').read_text()
            .replace('__PROXY_GROUP_JSON__', json.dumps(group, ensure_ascii=True))
            .replace('__PROTECTED_LISTENER_JSON__', json.dumps(listener, ensure_ascii=True)).encode())


def protected_listener(policy, base):
    if 'protected_listener' not in policy:
        return None
    value = policy['protected_listener']
    if (not isinstance(value, dict) or set(value) != {'name', 'port', 'proxy'}
            or not isinstance(value['name'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value['name'])
            or type(value['port']) is not int or not 1024 <= value['port'] <= 65535
            or not isinstance(value['proxy'], str) or value['proxy'] == policy['group']
            or value['proxy'].upper() in ['DIRECT', 'REJECT', 'REJECT-DROP']):
        raise ValueError('invalid protected listener')
    nodes = policy.get('nodes')
    if not isinstance(nodes, dict):
        raise ValueError('invalid fixed-exit nodes')
    node = nodes.get(value['proxy'])
    fixed = base / 'expected-exit-ip'
    if (not isinstance(node, dict) or node.get('country') != 'US' or not fixed.is_file()
            or str(ipaddress.IPv4Address(node.get('ip'))) != str(ipaddress.IPv4Address(fixed.read_text().strip()))):
        raise ValueError('protected listener is not pinned to a US node')
    return value


def ipv6_off(raw):
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('invalid base configuration')
        data['ipv6'] = False
        return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()
    except json.JSONDecodeError:
        text, count = re.subn(r'(?m)^(ipv6:[ \t]*)(?:true|false)([ \t]*(?:#.*)?)$', r'\1false\2', raw.decode())
        if count != 1:
            raise ValueError('base IPv6 field not unique')
        return text.encode()


class Controller:
    def __init__(self, policy):
        self.address, self.secret = policy['controller_socket'], policy['controller_secret']
        if not isinstance(self.address, str) or not self.address.startswith('/') or not isinstance(self.secret, str) or any(c in self.secret for c in '\r\n'):
            raise ValueError('invalid controller')

    def request(self, method, path, payload=None):
        address = self.address
        class LocalHTTP(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(4)
                self.sock.connect(address)
        client = LocalHTTP('localhost', timeout=4)
        try:
            headers = {'Authorization': 'Bearer ' + self.secret, 'Content-Type': 'application/json'}
            client.request(method, path, json.dumps(payload) if payload is not None else None, headers)
            response = client.getresponse()
            raw = response.read(2097153)
            if response.status >= 300 or len(raw) > 2097152:
                raise ValueError('controller request failed')
            return json.loads(raw) if raw else None
        finally:
            client.close()


def atomic(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.guard-', delete=False) as file:
        file.write(content)
        temporary = Path(file.name)
    temporary.chmod(0o600)
    temporary.replace(path)


def repair(home, group):
    base = Path(home) / '.claude-switcher'
    clash = Path(home) / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
    policy = json.loads((base / 'exit-policy.json').read_text())
    names = policy.get('profile_guard_scripts')
    if policy.get('mode') != 'clash-selector' or policy.get('group') != group or not isinstance(names, list) or not names or len(names) > 10:
        raise ValueError('opt-in profile guard configuration is missing')
    state_file = base / 'profile-guard-owned.json'
    owned = json.loads(state_file.read_text()) if state_file.exists() else {}
    listener = protected_listener(policy, base)
    guard = render(group, listener)
    plans = []
    sha = lambda value: hashlib.sha256(value).hexdigest()
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.js', name):
            raise ValueError('invalid profile script filename')
        path = clash / 'profiles' / name
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('profile script symlink is not supported')
        old = path.read_bytes()
        if old != guard and sha(old) not in [DEFAULT_SCRIPT_HASH, owned.get(name)]:
            raise ValueError('existing custom script requires manual integration')
        plans.append((path, old, guard))
    config = clash / 'config.yaml'
    if config.is_symlink():
        raise ValueError('base configuration symlink is not supported')
    old_config = config.read_bytes()
    plans.append((config, old_config, ipv6_off(old_config)))
    client = Controller(policy)
    before = client.request('GET', '/configs')
    selected = client.request('GET', '/proxies/' + quote(group, safe=''))
    if before.get('mode') != 'rule' or before.get('tun', {}).get('enable') is not True or selected.get('type') != 'Selector' or selected.get('now') not in policy['nodes']:
        raise ValueError('rule/TUN/selector prerequisite failed')
    if listener and (listener['proxy'] != selected['now'] or listener['port'] == before.get('mixed-port')):
        raise ValueError('protected listener differs from the selected node or proxy port')
    changed = [(p, old, new) for p, old, new in plans if old != new]
    backup = base / 'network-repair-backups' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True, mode=0o700)
    for i, (p, old, new) in enumerate(changed):
        old_file = backup / (str(i) + '-' + p.name)
        old_file.write_bytes(old)
        old_file.chmod(0o600)
    try:
        if any(p.read_bytes() != old for p, old, new in plans):
            raise ValueError('concurrent configuration change')
        for path, old, new in changed:
            atomic(path, new)
        client.request('PATCH', '/configs', {'ipv6': False})
        after = client.request('GET', '/configs')
        if after.get('ipv6') is not False or after.get('tun', {}).get('enable') is not True or after.get('mode') != 'rule':
            raise ValueError('runtime IPv6 repair not confirmed')
        atomic(state_file, json.dumps({name: sha(guard) for name in names}).encode())
    except BaseException:
        for path, old, new in reversed(changed):
            if path.read_bytes() not in [old, new]:
                raise RuntimeError('rollback blocked by concurrent modification')
            atomic(path, old)
        client.request('PATCH', '/configs', {'ipv6': before.get('ipv6', True)})
        raise
    return {'scripts': len(names), 'files_changed': len(changed), 'ipv6_disabled': True,
            'previous_ipv6': before.get('ipv6'), 'profile_reload_required': bool(changed),
            'protected_listener_configured': listener is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', required=True)
    args = parser.parse_args()
    try:
        result = repair(Path.home(), args.group)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, http.client.HTTPException) as error:
        print('FAIL:订阅防护修复未完成（' + type(error).__name__ + '）；配置需核对，未放宽检查。')
        return 1
    print('FIX:订阅防护脚本已核对；内核IPv6已关闭。')
    if result['profile_reload_required']:
        print('FIX:订阅脚本将在Clash重新生成配置后生效；当前结果请重新扫描核实。')
    if result['previous_ipv6'] is not False:
        print('FIX:请退出并重新打开Clash，以同步其基础设置内存；只改当前内核不能保证后续重生成。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
