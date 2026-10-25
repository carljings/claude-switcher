#!/usr/bin/env python3
"""Dedicated browser/CLI entries and non-secret configuration audit. No login data access."""
import argparse
import datetime
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

EDGE = Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')
PROFILE_NAME = 'Claude Protected Edge'
SANDBOX = Path('/usr/bin/sandbox-exec')
EXTERNAL_CHECKS = {
    'ippure': ('IPPure', 'https://ippure.com/claude'),
    'ping0': ('Ping0', 'https://ping0.cc/ip/'),
}
FONT_GUARD_HASHES = {
    'manifest.json': 'a9c60f75a28ea8e6ddc77ca80254bba706f16256af8bb175761894b352672eb0',
    'font-guard.js': '3bec18a170268ea01a949d2433c5ee66b2c1e0c962075811e30b8a0f061f381c',
    'LICENSE': '53d05e285330c42c54c2cd5d3c58953eda640379cdcf47a3a53497f5a76f3995',
}
DENIED_PERMISSIONS = ('geolocation', 'geolocation_with_options', 'local_fonts', 'media_stream_mic',
                      'media_stream_camera', 'sensors', 'background_sync')


def font_guard_path():
    directory = Path(__file__).with_name('font-guard')
    if directory.is_symlink() or directory.parent.is_symlink() or ',' in str(directory):
        raise ValueError('font guard directory is invalid')
    for name, digest in FONT_GUARD_HASHES.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('font guard integrity check failed')
    return directory


def browser_command(profile, url='https://claude.ai/', port=17897):
    extension = str(font_guard_path())
    return [str(EDGE), '--user-data-dir=' + str(profile), '--profile-directory=Default', '--no-first-run',
            '--no-default-browser-check', '--lang=en-US', '--accept-lang=en-US,en',
            '--disable-extensions-except=' + extension, '--load-extension=' + extension,
            '--proxy-server=http://127.0.0.1:' + str(port),
            '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
            '--webrtc-ip-handling-policy=disable_non_proxied_udp', '--disable-quic', url]


def required_preferences():
    return {'webrtc': {'ip_handling_policy': 'disable_non_proxied_udp'},
            'dns_over_https': {'mode': 'off'},
            'intl': {'accept_languages': 'en-US,en', 'selected_languages': 'en-US,en'},
            'net': {'network_prediction_options': 2},
            'profile': {'cookie_controls_mode': 1,
                        'default_content_setting_values': dict({key: 2 for key in DENIED_PERMISSIONS},
                            geolocation_with_options={'approximate': 2, 'precise': 2})}}


def merge_required(prefs, required):
    for key, value in required.items():
        if isinstance(value, dict):
            if not isinstance(prefs.setdefault(key, {}), dict):
                raise ValueError('invalid preference object')
            merge_required(prefs[key], value)
        else:
            prefs[key] = value


def hardened_preferences(prefs):
    if not isinstance(prefs, dict):
        raise ValueError('invalid preferences')
    merge_required(prefs, required_preferences())
    prefs['intl']['forced_languages'] = []
    settings = prefs['profile'].setdefault('content_settings', {})
    if not isinstance(settings, dict):
        raise ValueError('invalid content settings')
    for scope in ['exceptions', 'partitioned_exceptions']:
        if not isinstance(settings.setdefault(scope, {}), dict):
            raise ValueError('invalid permission exceptions')
        for key in DENIED_PERMISSIONS:
            settings[scope][key] = {}
    return prefs


def atomic_preferences(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.protected-prefs-', delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            temporary.chmod(0o600)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def seed_profile(profile):
    prefs = profile / 'Default/Preferences'
    if not prefs.exists():
        if prefs.is_symlink() or prefs.parent.is_symlink() or profile.is_symlink():
            raise ValueError('profile symlink is not supported')
        profile.mkdir(parents=True, mode=0o700, exist_ok=True)
        prefs.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        atomic_preferences(prefs, json.dumps(hardened_preferences({})).encode())


def profile_baseline(profile):
    path = profile / 'Default/Preferences'
    if path.is_symlink() or path.parent.is_symlink() or profile.is_symlink():
        raise ValueError('profile symlink is not supported')
    prefs = json.loads(path.read_text())
    required = required_preferences()
    # Edge persists UI fallback languages; --accept-lang pins the effective list.
    del required['intl']['selected_languages']
    def matches(value, required):
        return isinstance(value, dict) and all(
            matches(value.get(key), expected) if isinstance(expected, dict)
            else type(value.get(key)) is type(expected) and value.get(key) == expected
            for key, expected in required.items())
    if not matches(prefs, required):
        raise ValueError('dedicated profile baseline mismatch')
    selected = prefs['intl'].get('selected_languages')
    ui_language = (r'[A-Za-z]{2,8}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?'
                   r'(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*')
    if not isinstance(selected, str):
        raise ValueError('selected language baseline mismatch')
    languages = selected.split(',')
    if languages[:2] != ['en-US', 'en'] or any(not re.fullmatch(ui_language, lang) for lang in languages[2:]):
        raise ValueError('selected language baseline mismatch')
    forced = prefs['intl'].get('forced_languages', [])
    if not isinstance(forced, list) or any(lang not in ['en-US', 'en'] for lang in forced):
        raise ValueError('forced language baseline mismatch')
    settings = prefs['profile'].get('content_settings', {})
    if not isinstance(settings, dict):
        raise ValueError('invalid content settings')
    for scope in ['exceptions', 'partitioned_exceptions']:
        exceptions = settings.get(scope, {})
        if not isinstance(exceptions, dict):
            raise ValueError('invalid permission exceptions')
        for kind in DENIED_PERMISSIONS:
            entries = exceptions.get(kind, {})
            expected = required['profile']['default_content_setting_values'][kind]
            if not isinstance(entries, dict) or any(not isinstance(entry, dict)
                    or type(entry.get('setting')) is not type(expected) or entry['setting'] != expected
                    for entry in entries.values()):
                raise ValueError('permission exception baseline mismatch')


def running_browser(profile, port=17897):
    result = subprocess.run(['/bin/ps', '-ww', '-axo', 'pid=,command='],
                            capture_output=True, text=True, timeout=3)
    if result.returncode or not result.stdout.strip():
        raise ValueError('browser process state unavailable')
    found = False
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            raise ValueError('invalid browser process state')
        command = fields[1]
        if not command.startswith(str(EDGE) + ' ') or str(profile) not in command:
            continue
        found = True
        required = [flag for flag in browser_command(profile, port=port)[2:-1]
                    if flag.startswith(('--profile-directory=', '--lang=', '--proxy-server=',
                                        '--accept-lang=', '--disable-extensions-except=', '--load-extension=',
                                        '--force-webrtc-ip-handling-policy=', '--webrtc-ip-handling-policy=',
                                        '--disable-quic'))]
        for flag in required:
            name = flag.split('=', 1)[0]
            count = len(re.findall(r'(?<!\S)' + re.escape(name) + r'(?==|\s|$)', command))
            if count != 1 or not re.search(r'(?<!\S)' + re.escape(flag) + r'(?=\s|$)', command):
                raise ValueError('dedicated browser process baseline mismatch')
        if re.search(r'(?<!\S)--(?:proxy-bypass-list|proxy-pac-url|proxy-auto-detect|no-proxy-server|load-component-extension|disable-extensions)(?:=|\s|$)', command):
            raise ValueError('dedicated browser process proxy override')
    return found


def harden_profile(home, profile, port):
    if running_browser(profile, port):
        raise ValueError('dedicated browser is running')
    path = profile / 'Default/Preferences'
    if path.is_symlink() or path.parent.is_symlink() or profile.is_symlink():
        raise ValueError('profile symlink is not supported')
    original = path.read_bytes() if path.exists() else b'{}'
    updated = json.dumps(hardened_preferences(json.loads(original)), ensure_ascii=False).encode()
    backup_dir = home / '.claude-switcher/profile-preference-backups'
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    backup = backup_dir / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    with backup.open('xb') as handle:
        backup.chmod(0o600)
        handle.write(original)
    profile.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if (path.read_bytes() if path.exists() else b'{}') != original or running_browser(profile, port):
        raise ValueError('profile changed during hardening')
    atomic_preferences(path, updated)
    return backup


def managed_policy_paths(home):
    return [Path('/Library/Managed Preferences/com.microsoft.Edge.plist'),
            Path('/Library/Managed Preferences') / home.name / 'com.microsoft.Edge.plist',
            Path('/Library/Preferences/com.microsoft.Edge.plist'),
            home / 'Library/Preferences/com.microsoft.Edge.plist']


def managed_policy_baseline(home, paths=None):
    safe_values = {'WebRtcLocalhostIpHandling': 'disable_non_proxied_udp', 'DnsOverHttpsMode': 'off',
                   'NetworkPredictionOptions': 2, 'DefaultGeolocationSetting': 2, 'DefaultLocalFontsSetting': 2,
                   'DefaultSensorsSetting': 2}
    overrides = ['ProxySettings', 'ProxyMode', 'ProxyServer', 'ProxyPacUrl', 'ProxyBypassList',
                 'WebRtcIPHandlingUrl', 'WebRtcLocalIpsAllowedUrls', 'DnsOverHttpsTemplates',
                 'ExtensionInstallForcelist', 'ExtensionSettings', 'GeolocationAllowedForUrls',
                 'PreciseGeolocationAllowedForUrls', 'LocalFontsAllowedForUrls',
                 'AudioCaptureAllowedUrls', 'VideoCaptureAllowedUrls', 'ForcedLanguages']
    for path in managed_policy_paths(home) if paths is None else paths:
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            raise ValueError('managed policy symlink is not supported')
        values = plistlib.loads(path.read_bytes())
        if not isinstance(values, dict) or any(key in values and values[key] != expected
                for key, expected in safe_values.items()) or any(values.get(key) not in [None, '', [], {}]
                for key in overrides) or values.get('DefinePreferredLanguages') not in [None, '', 'en-US', 'en-US,en']:
            raise ValueError('managed browser policy requires review')


def load_network_audit():
    spec = importlib.util.spec_from_file_location('claude_switcher_network_audit',
                                                Path(__file__).with_name('network-audit.py'))
    if spec is None or spec.loader is None:
        raise ValueError('route module unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    listener = policy.get('protected_listener', {})
    port = listener.get('port') if isinstance(listener, dict) else None
    if policy.get('mode') != 'clash-selector' or type(port) is not int or not 1024 <= port < 65536:
        raise ValueError('dedicated listener configuration is missing')
    routes = load_network_audit().audit(home, group=policy['group'], country='US', protected=True)
    if routes.get('state') != 'info' or routes.get('protected_port') != port:
        raise ValueError('dedicated fixed-exit routes not verified')
    return port


def launch_cli(command, port):
    if command and command[0] == '--':
        command = command[1:]
    if (not command or not Path(command[0]).is_absolute() or not Path(command[0]).is_file()
            or not os.access(command[0], os.X_OK) or not SANDBOX.is_file()
            or not os.access(SANDBOX, os.X_OK) or type(port) is not int or not 1024 <= port < 65536):
        raise ValueError('native CLI or network sandbox unavailable')
    proxy = 'http://127.0.0.1:' + str(port)
    env = dict(os.environ)
    env.pop('CLAUDE_SECURESTORAGE_CONFIG_DIR', None)
    for name in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        env[name] = proxy
    env.update(NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
               TZ='America/Chicago', LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8')
    policy = ('(version 1)(allow default)(deny network-outbound)(deny appleevent-send)(deny lsopen)'
              '(allow network-outbound (remote tcp "localhost:' + str(port) + '"))')
    os.execve(str(SANDBOX), [str(SANDBOX), '-p', policy] + command, env)


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
    parser.add_argument('action', choices=['browser', 'check', 'harden', 'cli', 'provider-audit', 'report'])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    target = None
    if args.action == 'browser' and args.command:
        if len(args.command) != 1 or args.command[0] not in EXTERNAL_CHECKS:
            print('外部检测仅接受固定站点ippure或ping0，不接受网址或其他参数。', file=sys.stderr)
            return 2
        target = EXTERNAL_CHECKS[args.command[0]]
    elif args.command and args.action != 'cli':
        print('此操作不接受附加参数。', file=sys.stderr)
        return 2
    home = Path.home()
    if args.action == 'report':
        print(str(support_report(home)))
        return 0
    if args.action == 'provider-audit':
        print(json.dumps(provider_audit(home), ensure_ascii=False))
        return 0
    failure = '专用入口预检失败，未启动。请检查Chicago/en-US严格基线、专用代理入口、固定出口及Claude实际目标路由。'
    try:
        port = preflight(home)
        if args.action == 'check':
            print('专用入口固定出口预检通过；未验证账号权限。')
            return 0
        if args.action == 'cli':
            failure = '原生CLI严格入口未能启动；不会降级为直接联网。请检查官方CLI路径及本机网络沙箱。'
            launch_cli(args.command, port)
            return 0
        failure = '专用Edge受管策略需要核对，未启动或改写资料。请检查edge://policy中的代理、WebRTC、权限和强制扩展策略。'
        managed_policy_baseline(home)
        profile = home / 'Library/Application Support' / PROFILE_NAME
        if args.action == 'harden':
            failure = '专用资料加固未完成；请先正常关闭专用Edge并核对相关策略，原资料和已生成备份保留。'
            harden_profile(home, profile, port)
            print('专用Edge隐私设置已加固；原偏好已保存到本机私有备份，登录资料未清理。')
            return 0
        if not EDGE.is_file():
            raise ValueError('Edge unavailable')
        failure = '专用字体过滤组件未通过完整性检查，未启动。请修复随切换器安装的font-guard目录。'
        font_guard_path()
        failure = '专用Edge运行参数未通过检查，未发起打开请求。请先正常关闭专用浏览器窗口，再重试；普通Edge无需关闭。'
        running = running_browser(profile, port)
        failure = '专用浏览器资料未通过检查，未启动。请先关闭专用Edge并显式执行protected-harden；已有资料未被覆盖。'
        if not running:
            seed_profile(profile)
        profile_baseline(profile)
        failure = '专用Edge未完成启动，请关闭专用窗口后重试。'
        url = target[1] if target else 'https://claude.ai/'
        process = subprocess.Popen(browser_command(profile, url=url, port=port), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True, close_fds=True,
                                   env=dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8',
                                            LC_CTYPE='en_US.UTF-8', TZ='America/Chicago'))
        try:
            if process.wait(timeout=0.5) != 0 or not running_browser(profile, port):
                raise ValueError('dedicated browser launch failed')
        except subprocess.TimeoutExpired:
            pass  # The directly launched browser is still running.
        if target:
            print('已请求通过专用Edge打开' + target[0] + '外部检测；请在网页查看结果，切换器未读取检测分数。账号权限未验证。')
        else:
            print('已请求打开专用Edge；使用固定代理和已校验字体过滤组件，请刷新指定网站核对效果。账号权限未验证。')
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, http.client.HTTPException, subprocess.TimeoutExpired):
        print(failure, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
