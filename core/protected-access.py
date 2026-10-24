#!/usr/bin/env python3
"""Dedicated browser entry and non-secret configuration audit. No login data access."""
import argparse
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.parse import quote, urlsplit

EDGE = Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')
PROFILE_NAME = 'Claude Protected Edge'


def browser_command(profile, url='https://claude.ai/', port=7897):
    return [str(EDGE), '--user-data-dir=' + str(profile), '--no-first-run',
            '--no-default-browser-check', '--lang=en-US', '--proxy-server=http://127.0.0.1:' + str(port),
            '--force-webrtc-ip-handling-policy=disable_non_proxied_udp', '--disable-quic', url]


def seed_profile(profile):
    prefs = profile / 'Default/Preferences'
    if not prefs.exists():
        profile.mkdir(parents=True, mode=0o700, exist_ok=True)
        prefs.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        prefs.write_text(json.dumps({'webrtc': {'ip_handling_policy': 'disable_non_proxied_udp'},
                                     'dns_over_https': {'mode': 'off'},
                                     'intl': {'accept_languages': 'en-US,en', 'selected_languages': 'en-US,en'}}))
        prefs.chmod(0o600)


def preference_baseline():
    if os.readlink('/etc/localtime') != '/var/db/timezone/zoneinfo/America/Chicago':
        raise ValueError('timezone baseline mismatch')
    values = []
    for key in ['AppleLocale', 'AppleLanguages']:
        result = subprocess.run(['/usr/bin/defaults', 'read', '-g', key],
                                capture_output=True, text=True, timeout=3)
        if result.returncode:
            raise ValueError('preferences unavailable')
        values.append(result.stdout.strip())
    first_language = values[1].translate(str.maketrans('', '', '()"')).split(',')[0].strip()
    if values[0] != 'en_US' or first_language != 'en-US':
        raise ValueError('locale/language baseline mismatch')


def preflight(home):
    preference_baseline()
    policy = json.loads((home / '.claude-switcher/exit-policy.json').read_text())
    if policy.get('mode') != 'clash-selector':
        raise ValueError('invalid policy')
    address, secret = policy['controller_socket'], policy['controller_secret']
    if not isinstance(address, str) or not address.startswith('/') or any(c in secret for c in '\r\n'):
        raise ValueError('invalid controller')

    class LocalHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(3)
            self.sock.connect(address)

    def get(path):
        client = LocalHTTP('localhost', timeout=3)
        try:
            client.request('GET', path, headers={'Authorization': 'Bearer ' + secret})
            response = client.getresponse()
            if response.status != 200:
                raise ValueError('controller unavailable')
            return json.loads(response.read(2097152))
        finally:
            client.close()

    config = get('/configs')
    if config.get('mode') != 'rule' or config.get('tun', {}).get('enable') is not True or config.get('ipv6') is not False:
        raise ValueError('rule/TUN baseline mismatch')
    selected = get('/proxies/' + quote(policy['group'], safe=''))
    if selected.get('type') != 'Selector':
        raise ValueError('invalid selector')
    identity = policy['nodes'][selected['now']]
    port = config.get('mixed-port')
    if port != 7897 or not isinstance(identity, dict):
        raise ValueError('proxy port or identity mismatch')
    fixed = home / '.claude-switcher/expected-exit-ip'
    if (fixed.exists() or fixed.is_symlink()) and identity['ip'] != str(ipaddress.IPv4Address(fixed.read_text().strip())):
        raise ValueError('dedicated entry fixed exit mismatch')
    result = subprocess.run(['/usr/bin/curl', '-q', '--proxy', 'http://127.0.0.1:7897',
                             '--noproxy', '', '-fsS', '--connect-timeout', '4', '--max-time', '10',
                             'https://www.cloudflare.com/cdn-cgi/trace'],
                            capture_output=True, text=True, timeout=13)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or values.get('ip') != identity['ip'] or values.get('loc') != identity['country']:
        raise ValueError('fixed exit mismatch')
    if get('/proxies/' + quote(policy['group'], safe='')).get('now') != selected['now']:
        raise ValueError('selector changed')


def provider_audit(home):
    records = []
    for scope in ['.claude/settings.json', '.claude-native-greencloud/settings.json']:
        try:
            env = json.loads((home / scope).read_text()).get('env', {})
            records.append({'scope': scope, 'endpoint_host': urlsplit(env.get('ANTHROPIC_BASE_URL') or '').hostname,
                            'credential_fields_nonempty': {k: bool(env.get(k)) for k in
                             ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN']}})
        except (OSError, ValueError, TypeError, AttributeError):
            records.append({'scope': scope, 'state': 'unavailable'})
    return {'scope': 'settings files only; not active-process or account permission verification', 'records': records}


def support_report(home):
    import datetime
    report = provider_audit(home)
    report['generated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['account_permission_verified'] = False
    report['scope'] = 'local configuration snapshot; no credentials, network capture or account validation'
    checks = home / '.claude-switcher/last-check.txt'
    try:
        rows = {}
        for line in checks.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                state = value.split(':', 1)[0]
                if state in ['ok', 'info', 'warn', 'fail']:
                    rows[key] = state
        report['last_check'] = {'modified_at': datetime.datetime.fromtimestamp(checks.stat().st_mtime, datetime.timezone.utc).isoformat(), 'row_states': rows}
    except OSError:
        report['last_check'] = {'state': 'unavailable'}
    try:
        guard = json.loads(Path('/Library/Application Support/claude-switcher/guard-status.json').read_text())
        report['desktop_monitor'] = {key: guard.get(key) for key in ['checked_at', 'state', 'network_verified', 'consecutive_failures']}
    except (OSError, ValueError, TypeError):
        report['desktop_monitor'] = {'state': 'unavailable'}
    folder = home / '.claude-switcher/reports'
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = folder / ('local-check-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['browser', 'check', 'provider-audit', 'report'])
    args = parser.parse_args()
    home = Path.home()
    if args.action == 'report':
        print(str(support_report(home)))
        return 0
    if args.action == 'provider-audit':
        print(json.dumps(provider_audit(home), ensure_ascii=False))
        return 0
    try:
        preflight(home)
        if args.action == 'check':
            print('专用入口固定出口预检通过；未验证账号权限。')
            return 0
        if not EDGE.is_file():
            raise ValueError('Edge unavailable')
        profile = home / 'Library/Application Support' / PROFILE_NAME
        seed_profile(profile)
        subprocess.Popen(browser_command(profile), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        print('已请求打开专用Edge；使用独立资料目录，请通过官方页面登录。')
        return 0
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, subprocess.TimeoutExpired):
        print('专用入口预检失败，未启动浏览器。请检查芝加哥时区、美国地区/英文首选语言、Clash规则/TUN及锁定的固定出口。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
