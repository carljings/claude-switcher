#!/usr/bin/env python3
"""Read-only Clash route probes; no account credentials or configuration writes."""
import argparse
import concurrent.futures
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import time
from urllib.parse import quote

TARGETS = [('claude.ai', '/'), ('api.anthropic.com', '/v1/models')]


def public_text(value):
    return ''.join(c for c in str(value) if c.isprintable())[:300]


class Controller:
    def __init__(self, policy):
        self.address, self.secret = policy['controller_socket'], policy['controller_secret']
        if (not isinstance(self.address, str) or not self.address.startswith('/')
                or not isinstance(self.secret, str) or '\n' in self.secret or '\r' in self.secret):
            raise ValueError('invalid controller')

    def get(self, path):
        address = self.address

        class UnixHTTP(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(2)
                self.sock.connect(address)

        client = UnixHTTP('localhost', timeout=2)
        try:
            client.request('GET', path, headers={'Authorization': 'Bearer ' + self.secret})
            response = client.getresponse()
            raw = response.read(2097153)
            if response.status != 200 or len(raw) > 2097152:
                raise ValueError('controller unavailable')
            return json.loads(raw)
        finally:
            client.close()


def selected_identity(policy, selected, country):
    node = policy['nodes'][selected]
    ip, region = (node['ip'], node['country']) if isinstance(node, dict) else (node, country)
    if not isinstance(region, str) or not re.fullmatch('[A-Z]{2}', region):
        raise ValueError('invalid country')
    return str(ipaddress.IPv4Address(ip)), region


def matches_exit(connection, group, selected):
    chain = connection.get('chains', [])
    return (isinstance(chain, list) and selected in chain and (group is None or group in chain)
            and not any(str(n).upper() in ('DIRECT', 'REJECT', 'REJECT-DROP') for n in chain))


def probe(controller, port, host, path, group, selected, inbound=None, expected_exit=None):
    result = {'host': host, 'http_status': '000', 'transport_ok': False,
              'state': 'fail', 'detail': '目标TLS连接失败'}
    connection = http.client.HTTPSConnection('127.0.0.1', port, timeout=6,
                                              context=ssl.create_default_context())
    connection.set_tunnel(host, 443)
    try:
        connection.connect()
        source_port = str(connection.sock.getsockname()[1])
        # Read while our own TLS tunnel is open, matching host AND local source port.
        try:
            connections = controller.get('/connections')['connections']
            found = [c for c in connections if c.get('metadata', {}).get('host') == host
                     and str(c.get('metadata', {}).get('sourcePort')) == source_port]
            if len(found) != 1:
                result.update(state='warn', detail='探测连接未能在控制器中唯一核对')
            else:
                item = found[0]
                metadata = item.get('metadata', {})
                route_ok = (matches_exit(item, group, selected)
                            and (inbound is None or (metadata.get('inboundName') == inbound
                                 and str(metadata.get('inboundPort')) == str(port)
                                 and metadata.get('inboundIP') == '127.0.0.1'
                                 and metadata.get('specialProxy') == selected)))
                result.update(state='ok' if route_ok else 'fail',
                              detail='探测连接已核对' if route_ok else '探测连接未经过指定入口及所选出口',
                              chains=[public_text(n) for n in item.get('chains', [])],
                              rule=public_text(item.get('rule', '')),
                              rule_payload=public_text(item.get('rulePayload', '')))
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            result.update(state='warn', detail='控制器路由证据读取未完成')
        connection.request('GET', path, headers={'User-Agent': 'ClaudeSwitcher-NetworkAudit/1',
                                                'Connection': 'close'})
        response = connection.getresponse()
        result['http_status'] = str(response.status)
        result['transport_ok'] = True
        if expected_exit is not None:
            raw = response.read(16385)
            values = dict(line.split('=', 1) for line in raw.decode().splitlines() if '=' in line)
            if (response.status != 200 or len(raw) > 16384
                    or (values.get('ip'), values.get('loc')) != expected_exit):
                result.update(state='fail', detail='专用入口实际出口IP或国家不匹配')
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        result.update(state='fail', transport_ok=False, detail='目标TLS或HTTP传输失败')
    finally:
        connection.close()
    return result


def application_connections(connections, group, selected, desktop_only=False):
    observed = []
    for connection in connections:
        metadata = connection.get('metadata', {})
        host = str(metadata.get('host', '')).lower()
        if not any(host == d or host.endswith('.' + d) for d in
                   ['claude.ai', 'claude.com', 'anthropic.com', 'claudeusercontent.com']):
            continue
        process = str(metadata.get('processPath', ''))
        if process.startswith('/Applications/Claude.app/'):
            client = '桌面端'
        elif re.search(r'/(claude|claude\.exe)$', process):
            client = 'CLI'
        elif any(n in process for n in ['Microsoft Edge.app/', 'Google Chrome.app/', 'Safari.app/']):
            client = '浏览器'
        else:
            continue  # Unknown processes and our own probes aren't application evidence.
        if desktop_only and client != '桌面端':
            continue
        observed.append({'client': client, 'host': public_text(host),
                         'state': 'ok' if matches_exit(connection, group, selected) else 'fail',
                         'chains': [public_text(n) for n in connection.get('chains', [])],
                         'rule': public_text(connection.get('rule', '')),
                         'rule_payload': public_text(connection.get('rulePayload', ''))})
    return observed


def transit_selection(proxies, selected):
    names, seen = [], {selected}
    current = proxies.get(selected, {}).get('dialer-proxy')
    while current:
        if current in seen or len(names) >= 12:
            raise ValueError('proxy dependency loop')
        seen.add(current)
        names.append(public_text(current))
        entry = proxies.get(current)
        if not isinstance(entry, dict):
            raise ValueError('unknown proxy dependency')
        current = entry.get('now') or entry.get('dialer-proxy')
    return names


def exit_probe(port, expected_ip, expected_country):
    connection = http.client.HTTPSConnection('127.0.0.1', port, timeout=6,
                                              context=ssl.create_default_context())
    connection.set_tunnel('www.cloudflare.com', 443)
    try:
        connection.request('GET', '/cdn-cgi/trace', headers={'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200:
            return False
        data = response.read(16385)
        if len(data) > 16384:
            return False
        values = dict(line.split('=', 1) for line in data.decode().splitlines() if '=' in line)
        return values.get('ip') == expected_ip and values.get('loc') == expected_country
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def audit(home, group=None, country='US', guard=False, protected=False):
    policy_file = Path(home) / '.claude-switcher/exit-policy.json'
    report = {'schema_version': 1, 'state': 'warn', 'detail': '未配置控制器策略;实际路由未核验',
              'probes': [], 'observations': [], 'scope': 'unauthenticated_probe_routes'}
    if not policy_file.exists() and not policy_file.is_symlink():
        return report
    try:
        policy = json.loads(policy_file.read_text())
        group = group or policy['group']
        if policy.get('mode') != 'clash-selector' or policy['group'] != group:
            raise ValueError('invalid policy')
        controller = Controller(policy)
        selected = controller.get('/proxies/' + quote(group, safe=''))
        if selected.get('type') != 'Selector':
            raise ValueError('invalid selector')
        selected = selected['now']
        expected_ip, expected_country = selected_identity(policy, selected, country)
        pin = Path(home) / '.claude-switcher/expected-exit-ip'
        if protected and not pin.is_file():
            raise ValueError('protected entry requires fixed pin')
        if (pin.exists() or pin.is_symlink()) and expected_ip != str(ipaddress.IPv4Address(pin.read_text().strip())):
            raise ValueError('selected exit differs from fixed pin')
        config = controller.get('/configs')
        if config.get('mode') != 'rule' or config.get('tun', {}).get('enable') is not True or config.get('ipv6') is not False:
            report.update(state='fail', detail='控制器规则/TUN/IPv6严格基线不符或未确认')
            return report
        port = config.get('mixed-port') or config.get('port')
        if not protected and (type(port) is not int or not 0 < port < 65536):
            report['detail'] = '控制器未提供本机HTTP代理端口;实际路由未核验'
            return report
        proxies = controller.get('/proxies')['proxies']
        report.update(group=public_text(group), selected=public_text(selected),
                      transit_selection=transit_selection(proxies, selected))
        if protected:
            listener = policy['protected_listener']
            if (not isinstance(listener, dict) or not isinstance(listener.get('name'), str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', listener['name'])
                    or type(listener.get('port')) is not int or not 1024 <= listener['port'] < 65536
                    or listener['port'] in [config.get('mixed-port'), config.get('port')]
                    or listener.get('proxy') != selected or selected == group
                    or selected.upper() in ['DIRECT', 'REJECT', 'REJECT-DROP'] or expected_country != 'US'):
                raise ValueError('invalid protected listener')
            kind = proxies[selected].get('type')
            if (not isinstance(kind, str) or not kind
                    or kind.lower() in ['direct', 'reject', 'reject-drop', 'rejectdrop', 'selector',
                                        'urltest', 'fallback', 'loadbalance', 'relay', 'pass', 'compatible', 'unknown']
                    or isinstance(proxies[selected].get('all'), list)):
                raise ValueError('protected proxy must be a concrete outbound')
            port = listener['port']
            report.update(scope='unauthenticated_protected_listener_routes', protected_port=port,
                          protected_listener=public_text(listener['name']), protected_proxy=public_text(selected))
            targets = TARGETS + [('www.cloudflare.com', '/cdn-cgi/trace')]
        else:
            connections = controller.get('/connections')['connections']
            report['observations'] = application_connections(connections, group, selected, guard)
            targets = TARGETS[1:] if guard else TARGETS
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as pool:
            if protected:
                futures = [pool.submit(probe, controller, port, host, path, None, selected,
                                       inbound=listener['name'],
                                       expected_exit=(expected_ip, expected_country) if host == 'www.cloudflare.com' else None)
                           for host, path in targets]
            else:
                futures = [pool.submit(probe, controller, port, host, path, group, selected)
                           for host, path in targets]
            report['probes'] = [future.result() for future in futures]
        if guard and not protected and not exit_probe(port, expected_ip, expected_country):
            report.update(state='fail', detail='所选固定出口不可用或探测IP/国家不匹配')
            return report
        after = controller.get('/proxies/' + quote(group, safe=''))
        if after.get('now') != selected:
            report.update(state='warn', detail='核验期间选择组发生变化,请重试')
            return report
        evidence = report['probes'] + report['observations']
        if any(item['state'] == 'fail' for item in evidence):
            report.update(state='fail', detail='Claude探测或已观察应用连接未通过所选出口核验')
        elif any(item['state'] == 'warn' for item in evidence):
            report.update(state='warn', detail='部分探测连接缺少证据;实际应用路由未完整核验')
        elif protected:
            report.update(state='info', detail='专用入口探测已核对固定节点;仅探测证据,不按浏览器资料归因')
        else:
            detail = '探测连接经过' + public_text(group) + ' → ' + public_text(selected)
            if report['transit_selection']:
                detail += ';所选前置' + ' → '.join(report['transit_selection'])
            detail += (';已观察' + '、'.join(sorted({i['client'] for i in report['observations']}))
                       if report['observations'] else ';尚未观察真实应用连接')
            report.update(state='info', detail=detail)
        return report
    except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException):
        report.update(state='fail', detail='固定出口策略或控制器证据不可读;未完成路由核验')
        return report


def guard_state(report, path):
    """Persistent consecutive failures, independent of the launchd process lifetime."""
    target = Path(path)
    try:
        previous = json.loads(target.read_text())
    except (OSError, ValueError):
        previous = {}
    failures = previous.get('consecutive_failures', 0)
    if type(failures) is not int or failures < 0:
        failures = 0
    identity = previous.get('selection')
    if report.get('selected'):
        identity = hashlib.sha256(report['selected'].encode()).hexdigest()
        if identity != previous.get('selection'):
            failures = 0
    failures = failures + 1 if not report.get('idle') and report['state'] in ['warn', 'fail'] else 0
    snapshot = {'checked_at': int(time.time()), 'state': report['state'],
                'detail': '仅桌面进程级监测;无防火墙保证',
                'consecutive_failures': failures, 'terminate_desktop': failures >= 2,
                'network_verified': report['state'] == 'info', 'selection': identity}
    if report.get('idle'):
        snapshot.update(state='idle', network_verified=False)
    temporary = target.with_suffix('.tmp')
    with temporary.open('w') as handle:
        os.chmod(temporary, 0o644)
        json.dump(snapshot, handle)
    temporary.replace(target)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', default=str(Path.home()))
    parser.add_argument('--group')
    parser.add_argument('--country', default='US')
    parser.add_argument('--guard', action='store_true')
    parser.add_argument('--protected', action='store_true')
    parser.add_argument('--idle', action='store_true')
    parser.add_argument('--state-file')
    parser.add_argument('--tsv', action='store_true')
    args = parser.parse_args()
    report = ({'state': 'info', 'detail': '桌面端未运行;监测待命', 'probes': [], 'idle': True}
              if args.idle else audit(args.home, args.group, args.country, args.guard, args.protected))
    if args.state_file:
        state = guard_state(report, args.state_file)
        print('stop' if state['terminate_desktop'] else 'keep')
    elif args.tsv:
        print('route\t' + report['state'] + '\t' + public_text(report['detail']))
        for item in report['probes']:
            print({'claude.ai': 'web', 'api.anthropic.com': 'api'}.get(item['host'], 'exit') + '\t'
                  + item['http_status'] + '\t' + ('0' if item['transport_ok'] and item['http_status'] != '000' else '1'))
    else:
        print(json.dumps(report, ensure_ascii=False))
    return 1 if report['state'] == 'fail' else 0


if __name__ == '__main__':
    raise SystemExit(main())
