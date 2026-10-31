"""Exercise real check/checkdetail commands with fake network and an isolated HOME."""
import os
import http.server
import json
from pathlib import Path
import shlex
import subprocess
import socketserver
import tempfile
import time
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'core/claude-switch.sh'


class EnvironmentCheckTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '_trash').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '_trash')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.home, self.bin = self.folder / 'home', self.folder / 'bin'
        self.bin.mkdir()
        self.base = self.home / '.claude-switcher'
        self.base.mkdir(parents=True)
        (self.home / 'Library/Logs').mkdir(parents=True)
        clash = self.home / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        clash.mkdir(parents=True)
        (clash / 'clash-verge.yaml').write_text('rules:\n  - DOMAIN-SUFFIX,claude.ai,IpEqual\n')
        (self.base / 'stun-probe.py').write_text("import os\nprint(os.environ.get('FAKE_STUN', 'RESULT:192.0.2.20'))\n")
        (self.base / 'network-audit.py').write_text("print('route\\tinfo\\t隔离测试的已核验探测连接')\n")
        self.fake('curl', r'''
headers=""; next_header=0; fail_http=0; write_status=0
for value do
 if [ "$next_header" = 1 ]; then headers="$value"; next_header=0; fi
 [ "$value" = '-D' ] && next_header=1
 [ "$value" = '-f' ] && fail_http=1
 [ "$value" = '-w' ] && write_status=1
 last=$value
done
[ -n "$headers" ] && printf '%s\n' "${FAKE_WEB_HEADER:-}" > "$headers"
printf '%s\n' "$last" >> "$FAKE_CURL_LOG"
case "$last" in
 *cdn-cgi/trace) printf 'ip=%s\nloc=%s\n' "${FAKE_IP-192.0.2.20}" "${FAKE_COUNTRY:-US}";;
 *ipinfo.io/*json)
  if [ "${FAKE_ASN_JSON+x}" = x ]; then
   printf '%s' "$FAKE_ASN_JSON"
  else
   printf '{\n "ip":"%s",\n "org":"%s"\n}\n' "${FAKE_ASN_IP-192.0.2.20}" "${FAKE_ORG-AS174 Cogent Communications, LLC}"
  fi
  [ "$write_status" = 1 ] && printf '\n%s' "${FAKE_ASN_STATUS:-200}"
  if [ "$fail_http" = 1 ] && [ "${FAKE_ASN_STATUS:-200}" -ge 400 ]; then exit 22; fi
  exit "${FAKE_ASN_EXIT:-0}";;
 *api.anthropic.com*) printf '%s' "${FAKE_API_STATUS:-401}"; exit "${FAKE_HTTP_EXIT:-0}";;
 *claude.ai*) printf '%s' "${FAKE_WEB_STATUS:-200}"; exit "${FAKE_HTTP_EXIT:-0}";;
 *) exit 90;;
esac
''')
        self.fake('ifconfig', "printf 'inet 198.18.0.1\n'\n")
        self.fake('pgrep', 'exit 0\n')
        self.fake('dig', "printf '198.18.0.9\n'\n")
        self.fake('readlink', "printf '/var/db/timezone/zoneinfo/%s\\n' \"${FAKE_TZ:-America/New_York}\"\n")
        self.fake('networksetup', "printf 'IPv6: Off\n'\n")
        self.fake('launchctl', 'exit 0\n')
        self.fake('defaults', "case \"$*\" in *AppleLocale*) echo \"${FAKE_LOCALE:-en_US}\";; *) echo \"${FAKE_LANGUAGE:-en-US}\";; esac\n")
        self.fake('sleep', 'exit 0\n')
        for name in ['open', 'osascript', 'sudo', 'pkill', 'killall']:
            self.fake(name, 'echo called >> ' + shlex.quote(str(self.folder / 'unexpected-action')) + '\nexit 99\n')
        self.curl_log = self.folder / 'curl-urls'
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.defpath,
                        FAKE_CURL_LOG=str(self.curl_log))

    def fake(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o755)

    def run_check(self, command='checkdetail', **values):
        result = subprocess.run(['/bin/bash', str(SCRIPT), command], env=dict(self.env, **values),
                                capture_output=True, text=True, timeout=12)
        self.assertFalse((self.folder / 'unexpected-action').exists())
        return result

    def row(self, key, **values):
        result = self.run_check(**values)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {line.split('=', 1)[0]: line.split('=', 1)[1] for line in result.stdout.splitlines()
                if '=' in line and not line.startswith('#')}
        self.assertEqual(len(rows), 14, result.stdout)
        return rows[key]

    def test_unknown_org_is_unverified_not_datacenter(self):
        row = self.row('ASN属性')
        self.assertTrue(row.startswith('warn:'), row)
        self.assertIn('待核验', row)
        self.assertNotIn('机房', row)

    def test_region_preferences_follow_the_users_strict_launch_baseline(self):
        values = dict(FAKE_TZ='Asia/Shanghai', FAKE_LOCALE='zh_CN', FAKE_LANGUAGE='zh-CN')
        for key in ['时区', '地区', '客户端语言']:
            self.assertTrue(self.row(key, **values).startswith('fail:'))
        self.assertNotEqual(self.run_check('check', **values).returncode, 0)

    def test_fix_does_not_change_region_preferences_or_claim_stun_silence_is_safe(self):
        result = self.run_check('fix', FAKE_TZ='Asia/Shanghai', FAKE_LOCALE='zh_CN',
                                FAKE_LANGUAGE='zh-CN', FAKE_STUN='RESULT:NONE')
        self.assertNotIn('零暴露', result.stdout)
        self.assertNotIn('UDP不出网', result.stdout)
        self.assertIn('STUN无响应', result.stdout)

    def test_route_mismatch_blocks_both_paths_and_cannot_be_hidden_by_reviews(self):
        self.reviewed()
        (self.base / 'network-audit.py').write_text("print('route\\tfail\\t探测连接未经过所选出口')\n")
        self.assertTrue(self.row('规则置顶').startswith('fail:'))
        self.assertNotEqual(self.run_check('check').returncode, 0)

    def test_successful_route_row_only_claims_probe_scope(self):
        row = self.row('规则置顶')
        self.assertTrue(row.startswith('ok:'), row)
        self.assertIn('本次探测通过', row)
        self.assertNotIn('全部应用', row)

    def test_route_evidence_is_explicitly_unverified_without_a_controller(self):
        (self.base / 'network-audit.py').unlink()
        row = self.row('规则置顶')
        self.assertTrue(row.startswith('fail:'), row)
        self.assertIn('未核验', row)

    def test_fake_ip_is_mapping_information_not_a_proof_of_dns_path(self):
        row = self.row('DNS')
        self.assertTrue(row.startswith('info:'), row)
        self.assertIn('未单独验证', row)

    def test_known_isp_name_does_not_claim_physical_residential_access(self):
        row = self.row('ASN属性', FAKE_ORG='AS7922 Comcast Cable Communications, LLC')
        self.assertTrue(row.startswith('ok:'), row)
        self.assertIn('仅名称匹配', row)

    def test_empty_org_remains_unknown(self):
        self.assertEqual(self.row('ASN属性', FAKE_ORG=''), 'warn:未获取ASN归属')

    def test_asn_lookup_explicitly_queries_the_cloudflare_ip(self):
        row = self.row('ASN属性', FAKE_IP='198.51.100.7', FAKE_ASN_IP='198.51.100.7',
                       FAKE_ORG='AS7922 Comcast Cable Communications, LLC')
        self.assertTrue(row.startswith('ok:'), row)
        self.assertIn('仅名称匹配', row)
        urls = [url for url in self.curl_log.read_text().splitlines() if 'ipinfo.io/' in url]
        self.assertEqual(urls, ['https://ipinfo.io/198.51.100.7/json'])

    def test_asn_response_must_identify_the_exact_target_ip(self):
        for response_ip in ['198.51.100.8', '192.0.2.020', None, 3221226004]:
            with self.subTest(response_ip=response_ip):
                body = json.dumps({'ip': response_ip, 'org': 'AS7922 Comcast Cable'}, indent=2)
                self.assertEqual(self.row('ASN属性', FAKE_ASN_JSON=body), 'warn:未获取ASN归属')

    def test_invalid_asn_target_never_sends_an_asn_request(self):
        for target in ['', 'invalid', '192.0.2.020', '256.0.2.20', '::1', '192.0.2.20/24',
                       '192.0.2.20?query=1', ' 192.0.2.20']:
            with self.subTest(target=target):
                self.curl_log.write_text('')
                self.assertEqual(self.row('ASN属性', FAKE_IP=target), 'warn:未获取ASN归属')
                self.assertNotIn('ipinfo.io/', self.curl_log.read_text())

    def test_malformed_asn_response_remains_unknown(self):
        for body in ['{"org":"AS7922 Comcast Cable",', '[]', 'null',
                     json.dumps({'ip': '192.0.2.20'}),
                     json.dumps({'org': 'AS7922 Comcast Cable'})]:
            with self.subTest(body=body):
                self.assertEqual(self.row('ASN属性', FAKE_ASN_JSON=body), 'warn:未获取ASN归属')

    def test_failed_asn_transport_or_http_response_cannot_supply_an_org(self):
        for values in [dict(FAKE_ASN_EXIT='28'), dict(FAKE_ASN_STATUS='302'),
                       dict(FAKE_ASN_STATUS='429'), dict(FAKE_ASN_STATUS='503')]:
            with self.subTest(values=values):
                self.assertEqual(self.row('ASN属性', FAKE_ORG='AS7922 Comcast Cable', **values),
                                 'warn:未获取ASN归属')

    def test_asn_org_must_be_a_bounded_printable_nonempty_string(self):
        for org in [None, 123, ['Comcast'], '', '   ', 'AS7922 Comcast\nCable',
                    'AS7922 Comcast\rCable', 'AS7922 Comcast\tCable', 'AS7922 Comcast\x1b[0m',
                    'AS7922 Comcast\x7f', 'x' * 301]:
            with self.subTest(org=org):
                body = json.dumps({'ip': '192.0.2.20', 'org': org})
                self.assertEqual(self.row('ASN属性', FAKE_ASN_JSON=body), 'warn:未获取ASN归属')

    def test_asn_history_remains_information_when_live_attribution_is_unknown(self):
        self.reviewed()
        row = self.row('ASN属性', FAKE_ASN_IP='198.51.100.8', FAKE_ORG='AS7922 Comcast Cable')
        self.assertTrue(row.startswith('info:'), row)
        self.assertIn('截图', row)
        self.assertIn('未验证物理接入', row)
        self.assertIn('实时归属未知', row)
        self.assertNotIn('Comcast', row)

    def test_stun_silence_without_policy_blocks_in_strict_mode(self):
        row = self.row('WebRTC', FAKE_STUN='RESULT:NONE')
        self.assertTrue(row.startswith('fail:'), row)
        self.assertIn('无响应', row)
        self.assertNotIn('零暴露', row)
        self.assertNotEqual(self.run_check('check', FAKE_STUN='RESULT:NONE').returncode, 0)

    def test_stun_mismatch_still_blocks_launch_check(self):
        self.assertTrue(self.row('WebRTC', FAKE_STUN='RESULT:198.51.100.8').startswith('fail:'))
        self.assertNotEqual(self.run_check('check', FAKE_STUN='RESULT:198.51.100.8').returncode, 0)

    def test_stun_matching_ip_passes(self):
        self.assertTrue(self.row('WebRTC').startswith('ok:'))

    def test_403_is_restricted_not_a_proof_of_account_suspension(self):
        row = self.row('生态可达性', FAKE_WEB_STATUS='403')
        self.assertTrue(row.startswith('warn:'), row)
        self.assertIn('403', row)
        self.assertNotIn('封号', row)
        self.assertEqual(self.run_check('check', FAKE_WEB_STATUS='403').returncode, 0)

    def test_unauthenticated_api_401_does_not_verify_an_account(self):
        row = self.row('生态可达性')
        self.assertTrue(row.startswith('ok:'), row)
        self.assertIn('账号未验证', row)

    def test_rate_limit_and_server_errors_are_differentiated(self):
        for code, label in [('429', '限流'), ('503', '服务端')]:
            with self.subTest(code=code):
                row = self.row('生态可达性', FAKE_API_STATUS=code)
                self.assertTrue(row.startswith('warn:'), row)
                self.assertIn(label, row)

    def test_transport_failure_is_a_failure_even_with_an_http_status(self):
        self.assertTrue(self.row('生态可达性', FAKE_HTTP_EXIT='60').startswith('fail:'))
        self.assertNotEqual(self.run_check('check', FAKE_HTTP_EXIT='60').returncode, 0)

    def test_fixed_exit_match_and_mismatch_are_checked_in_both_commands(self):
        pin = self.base / 'expected-exit-ip'
        pin.write_text('192.0.2.20\n')
        self.assertTrue(self.row('出口IP').startswith('ok:'))
        self.assertEqual(self.run_check('check').returncode, 0)
        self.assertTrue(self.row('出口IP', FAKE_IP='192.0.2.21').startswith('fail:'))
        self.assertNotEqual(self.run_check('check', FAKE_IP='192.0.2.21').returncode, 0)
        self.assertEqual(pin.read_text(), '192.0.2.20\n')

    def test_invalid_or_dangling_fixed_exit_config_is_never_ignored(self):
        pin = self.base / 'expected-exit-ip'
        for value in ['', 'wrong', '192.0.2.20\n192.0.2.21', '::1']:
            with self.subTest(value=value):
                pin.write_text(value)
                self.assertTrue(self.row('出口IP').startswith('fail:'))
                self.assertNotEqual(self.run_check('check').returncode, 0)
        pin.unlink()
        pin.symlink_to(self.folder / 'missing')
        self.assertTrue(self.row('出口IP').startswith('fail:'))

    def test_country_guard_remains_required_with_a_matching_pin(self):
        (self.base / 'expected-exit-ip').write_text('192.0.2.20')
        self.assertTrue(self.row('出口IP', FAKE_COUNTRY='GB').startswith('fail:'))
        self.assertNotEqual(self.run_check('check', FAKE_COUNTRY='GB').returncode, 0)

    def test_history_reports_distinct_ips_and_preserves_prior_entries(self):
        history = self.base / 'iphistory.log'
        now = int(time.time())
        history.write_text(''.join(f'198.51.100.{i} {now}\n' for i in range(1, 4)))
        row = self.row('IP一致')
        self.assertIn('4个不同IP', row)
        self.assertNotIn('变化4次', row)
        self.assertIn('198.51.100.1', history.read_text())

    def reviewed(self, ip='192.0.2.20', **changes):
        record = {'history_ack_before': int(time.time())-10,
                  'web_login_confirmed_on': '2026-10-22',
                  'ip_type_review': 'IPPure/Ping0截图标注住宅;其他数据库有冲突;未验证物理接入'}
        record.update(changes)
        (self.base / 'reviewed-checks.json').write_text(json.dumps({'exits': {ip: record}}))

    def test_acknowledged_history_is_retained_without_a_warning(self):
        now = int(time.time())
        history = self.base / 'iphistory.log'
        history.write_text(''.join(f'198.51.100.{i} {now-20}\n' for i in range(1, 4)))
        self.reviewed()
        row = self.row('IP一致')
        self.assertTrue(row.startswith('ok:'), row)
        self.assertIn('已确认', row)
        self.assertIn('与上次一致', row)
        self.assertIn('198.51.100.1', history.read_text())

    def test_new_history_after_acknowledgement_still_warns(self):
        self.reviewed()
        now = int(time.time())
        (self.base / 'iphistory.log').write_text(''.join(f'198.51.100.{i} {now}\n' for i in range(1, 4)))
        self.assertTrue(self.row('IP一致').startswith('warn:'))

    def test_ip_type_and_web_confirmation_are_information_not_verification(self):
        self.reviewed()
        row = self.row('ASN属性')
        self.assertTrue(row.startswith('info:'), row)
        self.assertIn('截图', row)
        self.assertIn('未验证物理接入', row)
        row = self.row('生态可达性', FAKE_WEB_STATUS='403')
        self.assertTrue(row.startswith('warn:'), row)
        self.assertIn('旧IP登录备注', row)
        self.assertIn('2026-10-22', row)
        self.assertIn('未携带凭据', row)

    def test_removed_account_note_does_not_display_private_observation(self):
        private = self.base / 'account-observations.json'
        original = json.dumps({'observations': [
            {'client': 'claude_web', 'state': 'on_hold', 'source': 'user_report',
             'reported_on': '2026-10-23', 'private_marker': 'never-display-this'}]})
        private.write_text(original)
        result = self.run_check('account-note')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'INFO:账号状态备注已移除')
        self.assertNotIn('on hold', result.stdout)
        self.assertNotIn('never-display-this', result.stdout)
        self.assertEqual(private.read_text(), original)

    def test_review_is_bound_to_one_ip(self):
        self.reviewed(ip='192.0.2.99')
        self.assertTrue(self.row('ASN属性').startswith('warn:'))
        self.assertTrue(self.row('生态可达性', FAKE_WEB_STATUS='403').startswith('warn:'))

    def test_corrupt_review_does_not_hide_warnings(self):
        (self.base / 'reviewed-checks.json').write_text('{invalid')
        self.assertTrue(self.row('ASN属性').startswith('warn:'))
        self.assertTrue(self.row('生态可达性', FAKE_WEB_STATUS='403').startswith('warn:'))

    def test_manual_confirmation_does_not_hide_errors_or_stun_leaks(self):
        self.reviewed()
        for code in ['403', '429', '503']:
            self.assertTrue(self.row('生态可达性', FAKE_API_STATUS=code, FAKE_WEB_STATUS='403').startswith('warn:'))
        self.assertTrue(self.row('生态可达性', FAKE_WEB_STATUS='403', FAKE_HTTP_EXIT='60').startswith('fail:'))
        self.assertTrue(self.row('WebRTC', FAKE_STUN='RESULT:198.51.100.8').startswith('fail:'))
        (self.base / 'expected-exit-ip').write_text('192.0.2.99')
        self.assertNotEqual(self.run_check('check').returncode, 0)

    def test_future_acknowledgement_is_ignored(self):
        self.reviewed(history_ack_before=int(time.time())+10000)
        now = int(time.time())
        (self.base / 'iphistory.log').write_text(''.join(f'198.51.100.{i} {now}\n' for i in range(1, 4)))
        self.assertTrue(self.row('IP一致').startswith('warn:'))

    def stun_rules(self):
        return ([{'type': 'AND', 'payload': f'((Network,udp) && (DstPort,{port}))', 'proxy': 'REJECT'}
                 for port in [3478, 5349, 19302]] +
                [{'type': 'AND', 'payload': f'((Network,udp) && (Domain,{host}))', 'proxy': 'REJECT'}
                 for host in ['stun.miwifi.com', 'stun.chat.bilibili.com', 'stun.l.google.com', 'stun.cloudflare.com']])

    def test_stun_silence_with_verified_reject_policy_is_information(self):
        state, _, _ = self.selector_policy()
        state['rules'] = self.stun_rules()
        row = self.row('WebRTC', FAKE_STUN='RESULT:NONE')
        self.assertTrue(row.startswith('info:'), row)
        self.assertIn('4个STUN', row)
        self.assertIn('3478/5349/19302', row)
        self.assertIn('浏览器', row)
        self.assertNotIn('零泄露', row)
        self.assertNotIn('STUN无响应', self.run_check('check', FAKE_STUN='RESULT:NONE').stdout)

    def test_missing_overridden_or_inactive_reject_policy_still_warns(self):
        state, _, _ = self.selector_policy()
        rules = self.stun_rules()
        for variant in [dict(rules=rules[:-1], mode='rule', tun={'enable': True}),
                        dict(rules=[{'type': 'Match', 'payload': '', 'proxy': 'DIRECT'}]+rules, mode='rule', tun={'enable': True}),
                        dict(rules=rules, mode='global', tun={'enable': True}),
                        dict(rules=rules, mode='rule', tun={'enable': False})]:
            state.update(variant)
            self.assertTrue(self.row('WebRTC', FAKE_STUN='RESULT:NONE').startswith('fail:'))

    def test_domain_only_or_direct_port_policy_cannot_mask_silent_stun(self):
        state, _, _ = self.selector_policy()
        state['rules'] = self.stun_rules()[3:]
        self.assertTrue(self.row('WebRTC', FAKE_STUN='RESULT:NONE').startswith('fail:'))
        state['rules'] = self.stun_rules()
        state['rules'][0]['proxy'] = 'DIRECT'
        self.assertTrue(self.row('WebRTC', FAKE_STUN='RESULT:NONE').startswith('fail:'))

    def test_fingerprint_is_read_only_and_unknown_hardware_is_not_a_pass(self):
        fonts = self.home / 'Library/Fonts'
        fonts.mkdir(parents=True)
        (fonts / 'msyh-test.ttf').write_bytes(b'fixture')
        self.fake('system_profiler', 'echo invalid-json\n')
        self.fake('sysctl', 'exit 1\n')
        result = self.run_check('fingerprint')
        self.assertEqual(result.returncode, 0)
        self.assertIn('msyh-test.ttf', result.stdout)
        self.assertIn('GPU=info:未获取', result.stdout)
        self.assertIn('不能判断', result.stdout)
        self.assertNotIn('虚拟机=ok:物理机', result.stdout)
        self.assertFalse((self.base / 'accounts').exists())
        self.assertFalse((self.base / 'lastip').exists())

    def test_reject_rule_check_never_overrides_a_measured_leak(self):
        state, _, _ = self.selector_policy()
        state['rules'] = self.stun_rules()
        self.assertTrue(self.row('WebRTC', FAKE_STUN='RESULT:198.51.100.8').startswith('fail:'))
        self.assertNotEqual(self.run_check('check', FAKE_STUN='RESULT:198.51.100.8').returncode, 0)

    def selector_policy(self, selected='Fixed-A'):
        temp = tempfile.TemporaryDirectory(prefix='cs-policy-', dir='/tmp')
        self.addCleanup(temp.cleanup)
        address = str(Path(temp.name) / 's')
        state = {'now': selected, 'mode': 'rule', 'tun': {'enable': True}, 'rules': []}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in ['/proxies/IpEqual', '/configs', '/rules'] or self.headers.get('Authorization') != 'Bearer private-controller-secret':
                    self.send_error(401)
                    return
                response = {'/proxies/IpEqual': {'type': 'Selector', 'now': state['now']},
                            '/configs': {'mode': state['mode'], 'tun': state['tun']},
                            '/rules': {'rules': state['rules']}}[self.path]
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = socketserver.UnixStreamServer(address, Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(close)
        policy = {'mode': 'clash-selector', 'group': 'IpEqual',
                  'nodes': {'Fixed-A': '192.0.2.20', 'Fixed-B': '192.0.2.21'},
                  'controller_socket': address, 'controller_secret': 'private-controller-secret'}
        path = self.base / 'exit-policy.json'
        path.write_text(json.dumps(policy))
        return state, path, policy

    def test_expected_exit_follows_the_selected_node_without_relearning_actual_ip(self):
        selected, _, _ = self.selector_policy()
        self.assertEqual(self.run_check('expected-exit').stdout.strip(), '192.0.2.20')
        self.assertFalse((self.base / 'accounts').exists())
        selected['now'] = 'Fixed-B'
        self.assertEqual(self.run_check('expected-exit').stdout.strip(), '192.0.2.21')
        self.assertTrue(self.row('出口IP', FAKE_IP='192.0.2.21').startswith('ok:'))
        self.assertTrue(self.row('出口IP', FAKE_IP='192.0.2.20').startswith('fail:'))
        self.assertNotEqual(self.run_check('check', FAKE_IP='192.0.2.20').returncode, 0)

    def test_fixed_pin_also_constrains_a_configured_selector(self):
        selected, _, _ = self.selector_policy()
        (self.base / 'expected-exit-ip').write_text('192.0.2.20')
        self.assertEqual(self.run_check('expected-exit').stdout.strip(), '192.0.2.20')
        selected['now'] = 'Fixed-B'
        self.assertNotEqual(self.run_check('expected-exit').returncode, 0)
        self.assertTrue(self.row('出口IP', FAKE_IP='192.0.2.21').startswith('fail:'))
        self.assertNotEqual(self.run_check('check', FAKE_IP='192.0.2.21').returncode, 0)

    def test_custom_update_does_not_download_or_replace_files(self):
        marker = self.folder / 'update-network-called'
        self.fake('curl', 'touch ' + shlex.quote(str(marker)) + '\nexit 99\n')
        before = SCRIPT.read_bytes()
        result = self.run_check('update')
        self.assertEqual(result.returncode, 0)
        self.assertIn('禁用远程覆盖更新', result.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(SCRIPT.read_bytes(), before)

    def run_account_open(self, target, **values):
        return subprocess.run(['/bin/bash', str(SCRIPT), 'switch', target],
                              env=dict(self.env, **values), capture_output=True, text=True, timeout=12)

    def test_account_open_rechecks_before_touching_the_current_archive(self):
        (self.base / 'current').write_text('A')
        data = self.home / 'Library/Application Support/Claude'
        data.mkdir()
        (data / 'fixture').write_text('account-A-fixture')
        result = self.run_account_open('B', FAKE_TZ='Asia/Shanghai')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FAIL:', result.stdout)
        self.assertEqual((self.base / 'current').read_text(), 'A')
        self.assertEqual((data / 'fixture').read_text(), 'account-A-fixture')
        self.assertFalse((self.folder / 'unexpected-action').exists())

    def test_current_account_open_failure_is_not_reported_as_success(self):
        (self.base / 'current').write_text('A')
        self.fake('open', 'exit 17\n')
        result = self.run_account_open('A')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FAIL:未能打开Claude', result.stdout)
        self.assertNotIn('INFO:当前已是账号', result.stdout)
        self.assertEqual((self.base / 'current').read_text(), 'A')

    def test_confirmed_cloudflare_challenge_is_scoped_information(self):
        row = self.row('生态可达性', FAKE_WEB_STATUS='403', FAKE_API_STATUS='401', FAKE_WEB_HEADER='CF-Mitigated: challenge\r')
        self.assertTrue(row.startswith('info:'), row)
        self.assertIn('账号权限未验证', row)

    def test_unconfirmed_web_block_remains_warning(self):
        row = self.row('生态可达性', FAKE_WEB_STATUS='403', FAKE_API_STATUS='401', FAKE_WEB_HEADER='Server: cloudflare')
        self.assertTrue(row.startswith('warn:'), row)

    def test_challenge_marker_does_not_clear_api_denial(self):
        row = self.row('生态可达性', FAKE_WEB_STATUS='403', FAKE_API_STATUS='403', FAKE_WEB_HEADER='cf-mitigated: challenge')
        self.assertTrue(row.startswith('warn:'), row)

    def test_new_archive_open_failure_keeps_the_actual_profile_and_previous_archive(self):
        (self.base / 'current').write_text('A')
        data = self.home / 'Library/Application Support/Claude'
        data.mkdir()
        (data / 'fixture').write_text('account-A-fixture')
        self.fake('pgrep', 'case "$*" in *verge-mihomo*) exit 0;; *) exit 1;; esac\n')
        self.fake('open', 'exit 17\n')
        result = self.run_account_open('B')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FAIL:已切换到账号B，但未能打开Claude', result.stdout)
        self.assertEqual((self.base / 'current').read_text().strip(), 'B')
        self.assertEqual((self.base / 'accounts/A/fixture').read_text(), 'account-A-fixture')
        self.assertTrue(data.is_dir())
        self.assertFalse((self.folder / 'unexpected-action').exists())

    def test_invalid_account_does_not_run_preflight_or_open(self):
        marker = self.folder / 'invalid-account-network'
        self.fake('curl', 'touch ' + shlex.quote(str(marker)) + '\nexit 99\n')
        result = self.run_account_open('../invalid')
        self.assertEqual(result.returncode, 2)
        self.assertIn('FAIL:账号必须为A或B', result.stdout)
        self.assertFalse(marker.exists())
        self.assertFalse((self.folder / 'unexpected-action').exists())

    def test_unknown_selected_node_never_falls_back_to_legacy_pin(self):
        self.selector_policy('Unconfigured-node')
        (self.base / 'expected-exit-ip').write_text('192.0.2.20')
        result = self.run_check('expected-exit')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('private-controller-secret', result.stdout + result.stderr)
        self.assertTrue(self.row('出口IP').startswith('fail:'))

    def test_invalid_selector_group_or_unreachable_controller_fails_closed(self):
        _, path, policy = self.selector_policy()
        for changed in [dict(policy, group='Wrong group'), dict(policy, controller_socket='/tmp/nonexistent-cs-policy.sock'),
                        dict(policy, nodes={'Fixed-A': 'invalid'})]:
            with self.subTest(changed=changed['group']):
                path.write_text(json.dumps(changed))
                result = self.run_check('expected-exit')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('private-controller-secret', result.stdout + result.stderr)
                self.assertTrue(self.row('出口IP').startswith('fail:'))

    def test_expected_exit_without_a_policy_is_read_only_and_requires_configuration(self):
        result = self.run_check('expected-exit')
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.base / 'accounts').exists())

    def test_selected_country_is_verified_without_changing_system_timezone(self):
        _, path, policy = self.selector_policy('Fixed-B')
        policy['nodes']['Fixed-B'] = {'ip': '192.0.2.21', 'country': 'JP'}
        path.write_text(json.dumps(policy))
        values = dict(FAKE_IP='192.0.2.21', FAKE_COUNTRY='JP', FAKE_STUN='RESULT:192.0.2.21')
        self.assertTrue(self.row('出口IP', **values).startswith('ok:'))
        self.assertEqual(self.run_check('check', **values).returncode, 0)
        self.assertTrue(self.row('出口IP', FAKE_IP='192.0.2.21', FAKE_COUNTRY='US').startswith('fail:'))


if __name__ == '__main__':
    unittest.main()
