#!/bin/bash
# Claude 账号切换器 - 核心脚本 (通用版)
# 用法: claude-switch.sh check | status | switch A|B | checkdetail | fix | set-region | update [--auto] | diagnose-proxy
set -u
export LC_ALL=en_US.UTF-8

# 随现有单脚本更新分发;在任何账号状态读写、审计/修复/启动之前分派。
if [ "${1:-}" = "diagnose-proxy" ]; then
    shift
    exec "${CLAUDE_SWITCHER_PYTHON:-python3}" - "$@" <<'PY_PROXY_DIAGNOSE'
"""Read-only transport diagnostics for an explicitly selected HTTP/SOCKS proxy."""
import argparse
import concurrent.futures
import ipaddress
import json
import math
import os
import subprocess
from urllib.parse import urlsplit


TARGETS = (
    ("anthropic_api", "https://api.anthropic.com/v1/models"),
    ("claude_web", "https://claude.ai/"),
)


def select_proxy(args, environ):
    if args.proxy is not None:
        value, source = args.proxy, "argument"
    elif args.config is not None:
        with open(args.config, encoding="utf-8") as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise ValueError("invalid config")
        value, source = config.get("proxy_url"), "config"
    else:
        value, source = environ.get("CLAUDE_SWITCHER_PROXY_URL"), "environment"
    if not isinstance(value, str) or not value.strip():
        raise ValueError("proxy required")
    value = value.strip()
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid proxy")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https", "socks5", "socks5h")
            or not parsed.hostname or parsed.port is None
            or not 0 < parsed.port < 65536
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("invalid proxy")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.lower() == "localhost"
    # Do not include proxy addresses, credentials, or private config paths in reports.
    public = {"scheme": parsed.scheme, "port": parsed.port,
              "host_scope": "loopback" if loopback else "remote",
              "authentication_configured": parsed.username is not None,
              "source": source}
    return value, public


def probe(name, url, proxy, environ):
    # -q ignores curlrc. Pass proxy credentials over stdin, never in argv/reports.
    quoted = proxy.replace("\\", "\\\\").replace('"', '\\"')
    config = 'proxy = "' + quoted + '"\n'
    args = ["curl", "-q", "--config", "-", "-sS", "-o", os.devnull,
            "--proto", "=https", "--noproxy", "", "--connect-timeout", "6",
            "--max-time", "12", "-w",
            "%{http_code}\t%{http_connect}\t%{ssl_verify_result}\t%{time_appconnect}\t%{time_total}",
            url]
    keep = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE", "SYSTEMROOT"}
    clean_env = {k: v for k, v in environ.items() if k in keep}
    result = {"name": name, "url": url, "transport_reached": False,
              "access": "unknown"}
    try:
        process = subprocess.run(args, input=config, env=clean_env, capture_output=True,
                                 text=True, timeout=15)
        fields = process.stdout.strip().split()
        status, connect, verify = map(int, fields[:3])
        tls, elapsed = map(float, fields[3:5])
        if (not 0 <= status <= 599 or not 0 <= connect <= 599 or verify < 0
                or not math.isfinite(tls) or not math.isfinite(elapsed)
                or tls < 0 or elapsed < 0):
            raise ValueError("invalid probe metrics")
        reached = process.returncode == 0 and status > 0 and verify == 0 and tls > 0
        access = ("unauthenticated" if status == 401 else
                  "access_restricted" if status in (403, 407) else
                  "server_error" if status >= 500 else "http_response")
        result.update(curl_exit=process.returncode, http_status=status,
                      proxy_connect_status=connect, tls_verified=reached,
                      elapsed_seconds=elapsed, transport_reached=reached,
                      access=access if reached else "unknown")
    except subprocess.TimeoutExpired:
        result["error"] = "probe_timeout"
    except OSError:
        result["error"] = "curl_unavailable"
    except (ValueError, IndexError):
        result["error"] = "invalid_probe_output"
    return result


class DiagnosticParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error can echo private URLs or paths from argv.
        raise ValueError("invalid arguments")


def main(argv=None, environ=None):
    parser = DiagnosticParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--proxy", help="explicit proxy URL including a port")
    choice.add_argument("--config", help="private JSON file containing proxy_url")
    environ = os.environ if environ is None else environ
    report = {"schema_version": 1, "mode": "proxy_diagnostics",
              "scope": "unauthenticated_transport_only",
              "account_status": "not_evaluated", "leak_protection": "not_evaluated",
              "launch_allowed": None, "application_started": False,
              "system_modified": False}
    try:
        args = parser.parse_args(argv)
        proxy, public = select_proxy(args, environ)
    except (OSError, ValueError, TypeError):
        report.update(state="configuration_error", error="invalid_or_missing_proxy",
                      hint="Use --proxy, --config, or CLAUDE_SWITCHER_PROXY_URL; an explicit port is required.")
        print(json.dumps(report, ensure_ascii=False))
        return 2
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(probe, name, url, proxy, environ) for name, url in TARGETS]
        checks = [f.result() for f in futures]
    reached = all(check["transport_reached"] for check in checks)
    report.update(proxy=public, checks=checks,
                  state="transport_reached" if reached else "transport_failed")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if reached else 1


if __name__ == "__main__":
    raise SystemExit(main())
PY_PROXY_DIAGNOSE
fi

# ============ 安装时可配置项(安装程序会自动改写) ============
PROXY_MODE="clash-verge"       # 代理客户端: clash-verge|shadowrocket|sing-box|clashx|surge|auto
PROXY_GROUP="IpEqual"          # Clash 代理组名(安装时自动探测)
COUNTRY_TARGET="US"            # 目标出口国家(安装时按出口自动识别)
TZ_TARGET="America/New_York"   # 本地严格基线,不是官方封禁规则
LOCALE_TARGET="en_US"          # 本地严格地区格式基线
# ============================================================

DATA="$HOME/Library/Application Support/Claude"
BASE="$HOME/.claude-switcher"
LOG="$HOME/Library/Logs/claude-switch.log"
CLASH_DIR="$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev"
ROUTE_MISSED=""
case "${1:-}" in expected-exit|network-report|fingerprint|account-note|support-report|protected-check|protected-browser|provider-audit) ;; *) mkdir -p "$BASE/accounts" ;; esac

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >>"$LOG"; }

# TUN 在线判定:存在 fake-ip 网段地址即视为 TUN 已接管(兼容各种 TUN 设备名)
tun_up() { ifconfig 2>/dev/null | grep -q 'inet 198\.18\.'; }

# 代理客户端显示名(供检查细节输出)
proxy_name() {
    case "$PROXY_MODE" in
        clash-verge)  echo "Clash Verge" ;;
        shadowrocket) echo "Shadowrocket" ;;
        sing-box)     echo "sing-box" ;;
        clashx)       echo "ClashX" ;;
        surge)        echo "Surge" ;;
        auto)         echo "代理客户端" ;;
        *)            echo "$PROXY_MODE" ;;
    esac
}

# 可 open -a 启动的客户端 App 名(sing-box/auto 无标准 App,返回空)
proxy_app_name() {
    case "$PROXY_MODE" in
        clash-verge)  echo "Clash Verge" ;;
        shadowrocket) echo "Shadowrocket" ;;
        clashx)       echo "ClashX" ;;
        surge)        echo "Surge" ;;
        *)            echo "" ;;
    esac
}

# Shadowrocket 在 Mac 上表现为 VPN 配置;launchd/非图形环境下 scutil 可能查不到该行,此时以 TUN 判定为准(避免误杀)
shadowrocket_up() {
    nc=$(scutil --nc list 2>/dev/null)
    if echo "$nc" | grep -q 'com.liguangming.Shadowrocket'; then
        echo "$nc" | grep 'com.liguangming.Shadowrocket' | grep -q '(Connected)'
    else
        tun_up
    fi
}

# 代理内核在线判定:按安装时识别的客户端分派;auto 时任一命中即活
proxy_alive() {
    case "$PROXY_MODE" in
        clash-verge)  pgrep -f verge-mihomo >/dev/null 2>&1 ;;
        shadowrocket) shadowrocket_up ;;
        sing-box)     pgrep -f sing-box >/dev/null 2>&1 ;;
        clashx)       pgrep -x ClashX >/dev/null 2>&1 || pgrep -f clash >/dev/null 2>&1 ;;
        surge)        pgrep -f Surge >/dev/null 2>&1 ;;
        auto)         pgrep -f verge-mihomo >/dev/null 2>&1 || shadowrocket_up \
                      || pgrep -f sing-box >/dev/null 2>&1 \
                      || pgrep -x ClashX >/dev/null 2>&1 || pgrep -f clash >/dev/null 2>&1 \
                      || pgrep -f Surge >/dev/null 2>&1 ;;
        *)            pgrep -f verge-mihomo >/dev/null 2>&1 ;;
    esac
}

# 国家代码 → 地区格式映射(未收录的国家回退 en_US)
locale_for() {
    case "$1" in
        US) echo en_US ;; JP) echo ja_JP ;; TW) echo zh_TW ;; HK) echo zh_HK ;;
        SG) echo en_SG ;; GB) echo en_GB ;; DE) echo de_DE ;; FR) echo fr_FR ;;
        KR) echo ko_KR ;; AU) echo en_AU ;; CA) echo en_CA ;; *) echo en_US ;;
    esac
}

# 出口记录:统计最近48h内不同IP个数,仅作稳定性提示
iphist_count() {
    [ -z "$1" ] && { echo 0; return; }
    local HIST="$BASE/iphistory.log"
    local now=$(date +%s)
    echo "$1 $now" >>"$HIST"
    # 裁掉48小时(172800秒)以前的记录
    awk -v cutoff=$((now-172800)) '$2>=cutoff' "$HIST" > "$HIST.tmp" && mv "$HIST.tmp" "$HIST"
    # 统计48h内不同IP个数
    awk -v acknowledged="${HISTORY_ACK_BEFORE:-0}" '$2>acknowledged {print $1}' "$HIST" | sort -u | wc -l | tr -d ' '
}

# 人工确认按实际IPv4绑定;STUN策略另从当前控制器读取,不信任人工勾选。
load_check_context() {
    HISTORY_ACK_BEFORE=0; WEB_LOGIN_REVIEW=""; ASN_REVIEW=""; STUN_BLOCK_POLICY=""
    local key value
    while IFS=$'\t' read -r key value; do
        case "$key" in
            history) HISTORY_ACK_BEFORE="$value" ;;
            web) WEB_LOGIN_REVIEW="$value" ;;
            asn) ASN_REVIEW="$value" ;;
            stun) STUN_BLOCK_POLICY="$value" ;;
        esac
    done < <(python3 - "$BASE" "$1" "$PROXY_GROUP" <<'PY_CHECK_CONTEXT'
import datetime
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import sys
import time

base = Path(sys.argv[1])
try:
    ip = str(ipaddress.IPv4Address(sys.argv[2]))
except ValueError:
    raise SystemExit(0)

def clean(value):
    return isinstance(value, str) and 0 < len(value) <= 500 and all(ord(c) >= 32 for c in value)

try:
    record = json.loads((base / 'reviewed-checks.json').read_text())['exits'].get(ip, {})
    ack = record.get('history_ack_before', 0)
    if type(ack) is int and 0 < ack <= time.time():
        print('history\t' + str(ack))
    web = record.get('web_login_confirmed_on', '')
    if clean(web) and datetime.date.fromisoformat(web) <= datetime.date.today():
        print('web\t' + web)
    asn = record.get('ip_type_review', '')
    if clean(asn):
        print('asn\t' + asn)
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    pass

try:
    policy = json.loads((base / 'exit-policy.json').read_text())
    if policy.get('mode') != 'clash-selector' or policy.get('group') != sys.argv[3]:
        raise ValueError('unsupported controller policy')
    class UnixHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(2)
            self.sock.connect(policy['controller_socket'])
    client = UnixHTTP('localhost', timeout=2)
    def query(path):
        client.request('GET', path, headers={'Authorization': 'Bearer ' + policy['controller_secret']})
        response = client.getresponse()
        raw = response.read(2097153)
        if response.status != 200 or len(raw) > 2097152:
            raise ValueError('controller response unavailable')
        return json.loads(raw)
    try:
        config = query('/configs')
        if config.get('mode') != 'rule' or config.get('tun', {}).get('enable') is not True:
            raise ValueError('rule/TUN inactive')
        hosts = ['stun.miwifi.com', 'stun.chat.bilibili.com', 'stun.l.google.com', 'stun.cloudflare.com']
        remaining = {f'((Network,udp) && (Domain,{host}))' for host in hosts}
        ports = set(f'((Network,udp) && (DstPort,{port}))' for port in [3478, 5349, 19302])
        for rule in query('/rules')['rules']:
            kind, payload = rule.get('type'), rule.get('payload', '')
            if kind == 'AND' and rule.get('proxy') == 'REJECT' and payload.startswith('((Network,udp) && ('):
                remaining.discard(payload)
                ports.discard(payload)
            elif kind == 'IPCIDR' and not ipaddress.ip_network(payload).overlaps(ipaddress.ip_network('198.18.0.0/15')):
                continue
            else:
                break  # 不越过可能抢先匹配的其他规则。
            if not remaining and not ports:
                print('stun\t已核验4个STUN域名及3478/5349/19302端口UDP拒绝;未全面验证浏览器路径')
                break
    finally:
        client.close()
except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException):
    pass
PY_CHECK_CONTEXT
    )
}

# 私有固定出口基线,或跟随明确配置的Clash选择组;不自动学习实际探测值。
expected_exit_ip() {
    local pin="$BASE/expected-exit-ip" policy="$BASE/exit-policy.json"
    if [ ! -e "$pin" ] && [ ! -L "$pin" ] && [ ! -e "$policy" ] && [ ! -L "$policy" ]; then
        return 0
    fi
    python3 - "$pin" "$policy" "$PROXY_GROUP" "$COUNTRY_TARGET" "${1:-ip}" <<'PY_EXPECTED_IP'
import http.client
import ipaddress
import json
import pathlib
import re
import socket
import sys
from urllib.parse import quote

try:
    pin, policy = map(pathlib.Path, sys.argv[1:3])
    if policy.exists() or policy.is_symlink():
        data = json.loads(policy.read_text())
        if not isinstance(data, dict) or data.get('mode') != 'clash-selector' or data.get('group') != sys.argv[3]:
            raise ValueError('invalid policy')
        nodes = data['nodes']
        if not isinstance(nodes, dict) or not nodes or not all(isinstance(k, str) for k in nodes):
            raise ValueError('invalid nodes')
        expected = {}
        for name, node in nodes.items():
            ip, country = (node['ip'], node['country']) if isinstance(node, dict) else (node, sys.argv[4])
            if not isinstance(country, str) or not re.fullmatch('[A-Z]{2}', country):
                raise ValueError('invalid country')
            expected[name] = (str(ipaddress.IPv4Address(ip)), country)
        address, secret = data['controller_socket'], data['controller_secret']
        if not isinstance(address, str) or not address.startswith('/') or not isinstance(secret, str):
            raise ValueError('invalid controller')

        class UnixHTTP(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(3)
                self.sock.connect(address)

        client = UnixHTTP('localhost', timeout=3)
        try:
            client.request('GET', '/proxies/' + quote(data['group'], safe=''),
                           headers={'Authorization': 'Bearer ' + secret})
            response = client.getresponse()
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise ValueError('invalid controller response')
            selected = json.loads(raw)
            if not isinstance(selected, dict) or selected.get('type') != 'Selector':
                raise ValueError('invalid selector')
            value = expected[selected['now']]
        finally:
            client.close()
        if (pin.exists() or pin.is_symlink()) and value[0] != str(ipaddress.IPv4Address(pin.read_text().strip())):
            raise ValueError('selected exit differs from fixed pin')
    else:
        value = (str(ipaddress.IPv4Address(pin.read_text().strip())), sys.argv[4])
    print('\t'.join(value) if sys.argv[5] == 'identity' else value[0])
except (OSError, UnicodeError, ValueError, KeyError, TypeError, http.client.HTTPException):
    # Do not print controller credentials, private paths or response contents.
    raise SystemExit(1)
PY_EXPECTED_IP
}

assess_exit() {
    EXIT_STATE="ok"
    EXIT_DETAIL="${1:-无}/${2:-未知}"
    local expected="" identity="" target_country="$COUNTRY_TARGET"
    identity=$(expected_exit_ip identity 2>/dev/null) || {
        EXIT_STATE="fail"; EXIT_DETAIL="固定出口配置无效或选择组查询失败"; return;
    }
    if [ -n "$identity" ]; then
        IFS=$'\t' read -r expected target_country <<< "$identity"
    fi
    if [ "${3:-0}" != "0" ] || [ -z "$1" ] || [ "$2" != "$target_country" ]; then
        EXIT_STATE="fail"
        EXIT_DETAIL="$EXIT_DETAIL(期望国家${target_country};探测退出码${3:-0})"
    elif [ -n "$expected" ] && [ "$1" != "$expected" ]; then
        EXIT_STATE="fail"
        EXIT_DETAIL="$EXIT_DETAIL(与固定出口${expected}不一致)"
    elif [ -n "$expected" ]; then
        EXIT_DETAIL="$EXIT_DETAIL;固定出口匹配"
    fi
}

# 无认证HTTP探测:传输、访问状态与账号权限是不同结论。
assess_access() {
    ACCESS_STATE="ok"
    ACCESS_DETAIL="claude.ai:$1 API:$2;未携带凭据,账号未验证"
    if [ "$3" != "0" ] || [ "$4" != "0" ]; then
        ACCESS_STATE="fail"; ACCESS_DETAIL="传输失败(退出码$3/$4);$ACCESS_DETAIL"
        return
    fi
    case "$1/$2" in
        [1-5][0-9][0-9]/[1-5][0-9][0-9]) ;;
        *) ACCESS_STATE="fail"; ACCESS_DETAIL="未取得有效HTTP响应;$ACCESS_DETAIL"; return ;;
    esac
    case "$1/$2" in
        *429*) ACCESS_STATE="warn"; ACCESS_DETAIL="限流,请查看官方用量并稍后重试;$ACCESS_DETAIL" ;;
        5*|*/5*) ACCESS_STATE="warn"; ACCESS_DETAIL="服务端异常,请核对官方状态;$ACCESS_DETAIL" ;;
        403/401)
            ACCESS_STATE="warn"; ACCESS_DETAIL="访问受限或需要验证,请在官方应用确认;$ACCESS_DETAIL"
            if [ "${5:-}" = "cf-challenge" ]; then
                ACCESS_STATE="info"; ACCESS_DETAIL="网页Cloudflare浏览器验证(403),API匿名未认证(401);HTTP已有响应,账号权限未验证"
            fi ;;
        401/*|403/*|*/403|*/407) ACCESS_STATE="warn"; ACCESS_DETAIL="访问受限或需要验证,请在官方应用确认;$ACCESS_DETAIL" ;;
        [23]*/401|[23]*/[23]*) ;;
        *) ACCESS_STATE="warn"; ACCESS_DETAIL="HTTP访问未确认;$ACCESS_DETAIL" ;;
    esac
    if [ "$1/$2" = "403/401" ] && [ -n "${WEB_LOGIN_REVIEW:-}" ]; then
        ACCESS_DETAIL="$ACCESS_DETAIL;旧IP登录备注${WEB_LOGIN_REVIEW},不代表当前账号状态"
    fi
}

# 用户选择的严格基线;网络修复保留设置,不自动放宽或改写偏好。
preference_rows() {
    local actual state lang
    actual=$(readlink /etc/localtime 2>/dev/null)
    state="fail"; [ "$actual" = "/var/db/timezone/zoneinfo/$TZ_TARGET" ] && state="ok"
    echo "时区=$state:${actual##*/};本地严格基线$TZ_TARGET,非官方封禁判据"
    actual=$(defaults read -g AppleLocale 2>/dev/null)
    state="fail"; [ "$actual" = "$LOCALE_TARGET" ] && state="ok"
    echo "地区=$state:${actual:-未知};本地严格基线$LOCALE_TARGET"
    lang=$(defaults read com.anthropic.claudefordesktop AppleLanguages 2>/dev/null | tr -d '(),"' | awk 'NF {print $1; exit}')
    [ -n "$lang" ] || lang=$(defaults read -g AppleLanguages 2>/dev/null | tr -d '(),"' | awk 'NF {print $1; exit}')
    state="fail"; [[ "$lang" == en* ]] && state="ok"
    echo "客户端语言=$state:${lang:-未知};本地严格基线为英文"
}

# 同一STUN结论供启动检查、界面和修复复用。
assess_webrtc() {
    WEBRTC_STATE="ok"; WEBRTC_DETAIL="探测服务仅返回当前出口;不代表全部浏览器路径"
    local wr="$1" baseline="$2" w leak="" OLDIFS
    case "$wr" in
        RESULT:NONE)
            WEBRTC_STATE="fail"; WEBRTC_DETAIL="STUN无响应且缺少拒绝规则证据;严格策略阻止启动"
            if [ -n "${STUN_BLOCK_POLICY:-}" ]; then
                WEBRTC_STATE="info"; WEBRTC_DETAIL="$STUN_BLOCK_POLICY"
            fi ;;
        RESULT:*)
            if [ -z "${wr#RESULT:}" ] || [ -z "$baseline" ]; then
                WEBRTC_STATE="fail"; WEBRTC_DETAIL="探测结果或出口基线无效"; return
            fi
            OLDIFS=$IFS; IFS=','
            for w in ${wr#RESULT:}; do [ "$w" != "$baseline" ] && leak="$leak $w"; done
            IFS=$OLDIFS
            if [ -n "$leak" ]; then
                WEBRTC_STATE="fail"; WEBRTC_DETAIL="STUN探测发现不同公网地址:${leak# }"
            fi ;;
        *) WEBRTC_STATE="fail"; WEBRTC_DETAIL="STUN检测异常,未取得有效结果" ;;
    esac
}

network_evidence() {
    ROUTE_STATE="fail"; ROUTE_DETAIL="当前客户端实际路由未核验;严格策略阻止启动"
    PROBE_WEB=""; PROBE_API=""; PROBE_WEB_RC=1; PROBE_API_RC=1
    [ "$PROXY_MODE" = "clash-verge" ] || return 0
    local helper="$BASE/network-audit.py" key value detail
    if [ -e "$BASE/exit-policy.json" ] || [ -L "$BASE/exit-policy.json" ]; then ROUTE_STATE="fail"; fi
    [ -f "$helper" ] || helper="$(dirname "$0")/network-audit.py"
    if [ ! -f "$helper" ]; then
        [ ! -e "$BASE/exit-policy.json" ] || ROUTE_STATE="fail"
        ROUTE_DETAIL="网络核验模块缺失,请完整更新安装"; return 0
    fi
    while IFS=$'\t' read -r key value detail; do
        case "$key" in
            route) ROUTE_STATE="$value"; ROUTE_DETAIL="$detail" ;;
            web) PROBE_WEB="$value"; PROBE_WEB_RC="$detail" ;;
            api) PROBE_API="$value"; PROBE_API_RC="$detail" ;;
        esac
    done < <(python3 "$helper" --home "$HOME" --group "$PROXY_GROUP" --country "$COUNTRY_TARGET" --tsv 2>/dev/null)
    if [ "$ROUTE_STATE" = "warn" ]; then
        ROUTE_STATE="fail"; ROUTE_DETAIL="$ROUTE_DETAIL;严格策略阻止启动"
    fi
}

access_probe() {
    local challenge="" headers="" observed="" confirm_rc=1
    if [ -n "$PROBE_WEB" ] && [ -n "$PROBE_API" ]; then
        r1="$PROBE_WEB"; r2="$PROBE_API"; rc1="$PROBE_WEB_RC"; rc2="$PROBE_API_RC"
    else
        r1=$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' https://claude.ai/ 2>/dev/null); rc1=$?
        r2=$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' https://api.anthropic.com/v1/models 2>/dev/null); rc2=$?
    fi
    if [ "$r1/$r2/$rc1/$rc2" = "403/401/0/0" ]; then
        headers=$(mktemp "$BASE/.http-headers.XXXXXX") || headers=""
        if [ -n "$headers" ]; then
            observed=$(curl -q -s --max-time 8 -D "$headers" -o /dev/null -w '%{http_code}' https://claude.ai/ 2>/dev/null); confirm_rc=$?
            if [ "$confirm_rc" = "0" ] && [ "$observed" = "403" ] && grep -Eiq '^cf-mitigated:[[:blank:]]*challenge[[:space:]]*$' "$headers"; then
                challenge="cf-challenge"
            fi
            rm -f "$headers"
        fi
    fi
    assess_access "$r1" "$r2" "$rc1" "$rc2" "$challenge"
}

# 注册不等于实时保护。状态由root所有的保镖模块落在系统安装目录。
guard_status() {
    if ! launchctl print system/local.claude-bodyguard >/dev/null 2>&1; then
        echo '保镖=fail:桌面进程监测服务未注册'; return
    fi
    python3 - '/Library/Application Support/claude-switcher/guard-status.json' <<'PY_GUARD_STATUS'
import json
from pathlib import Path
import sys
import time
try:
    data = json.loads(Path(sys.argv[1]).read_text())
    age = time.time() - data['checked_at']
    if not 0 <= age <= 90:
        raise ValueError('stale')
    if data['state'] == 'idle':
        print('保镖=info:桌面端未运行,监测待命;仅进程级保护,存在检测窗口')
    elif data['state'] == 'info' and data.get('network_verified'):
        print('保镖=info:近期已核对所选出口及API探测链路;仅桌面进程保护,非防火墙')
    else:
        print('保镖=warn:出口监测未确认或出现异常;请查看守护记录;非防火墙保证')
except (OSError, ValueError, KeyError, TypeError):
    print('保镖=warn:服务已注册,但无近期出口监测证据;旧版仅检查内核/TUN')
PY_GUARD_STATUS
}

# ---------- 安全检查 ----------
check() {
    fails=""

    proxy_alive || fails="$fails;代理内核未运行"
    tun_up || fails="$fails;TUN网卡不在线"

    trace=$(curl -s --max-time 8 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null)
    trace_rc=$?
    ip=$(echo "$trace" | grep '^ip=' | cut -d= -f2)
    loc=$(echo "$trace" | grep '^loc=' | cut -d= -f2)
    assess_exit "$ip" "$loc" "$trace_rc"
    [ "$EXIT_STATE" = "ok" ] || fails="$fails;出口IP异常($EXIT_DETAIL)"
    load_check_context "$ip"
    ipwarn=""
    lastip=""; [ -f "$BASE/lastip" ] && lastip=$(cat "$BASE/lastip")
    if [ -n "$ip" ] && [ -n "$lastip" ] && [ "$ip" != "$lastip" ]; then
        ipwarn="注意:出口IP与上次不同($lastip -> $ip)"
    fi
    [ -n "$ip" ] && echo "$ip" > "$BASE/lastip"

    # 不同IP个数不是切换次数,也不是已知的官方封禁阈值。
    ipn=$(iphist_count "$ip")
    if [ "$ipn" -ge 3 ] 2>/dev/null; then
        ipwarn="${ipwarn:+$ipwarn; }48h内出现${ipn}个不同IP,请确认是否为计划内换线"
    fi

    while IFS= read -r preference; do
        case "$preference" in *=fail:*) fails="$fails;$preference" ;; esac
    done < <(preference_rows)
    v6=$(networksetup -getinfo Wi-Fi 2>/dev/null | grep -i '^IPv6:')
    echo "$v6" | grep -qi 'off' || fails="$fails;IPv6未关闭"

    dnsip=$(dig +short +time=3 +tries=1 claude.ai 2>/dev/null | head -1)
    case "$dnsip" in
        198.18.*) ;;
        *) ipwarn="${ipwarn:+$ipwarn; }DNS映射未确认(返回${dnsip:-空});请结合实际链路核验" ;;
    esac

    wr=$(webrtc_test)
    assess_webrtc "$wr" "$ip"
    [ "$WEBRTC_STATE" = "fail" ] && fails="$fails;$WEBRTC_DETAIL"
    [ "$WEBRTC_STATE" = "warn" ] && ipwarn="${ipwarn:+$ipwarn; }$WEBRTC_DETAIL"

    launchctl print system/local.claude-bodyguard >/dev/null 2>&1 || fails="$fails;桌面进程监测服务未注册"
    network_evidence
    [ "$ROUTE_STATE" = "fail" ] && fails="$fails;$ROUTE_DETAIL"
    [ "$ROUTE_STATE" = "warn" ] && ipwarn="${ipwarn:+$ipwarn; }$ROUTE_DETAIL"
    access_probe
    [ "$ACCESS_STATE" = "fail" ] && fails="$fails;$ACCESS_DETAIL"
    [ "$ACCESS_STATE" = "warn" ] && ipwarn="${ipwarn:+$ipwarn; }$ACCESS_DETAIL"

    if [ -n "$fails" ]; then
        echo "FAIL:${fails#;}"
        return 1
    fi
    echo "OK:$ip${ipwarn:+|$ipwarn}"
    return 0
}

# WebRTC/STUN 探测:返回 RESULT:ip,ip 或 RESULT:NONE 或空
webrtc_test() {
    python3 "$BASE/stun-probe.py" 2>/dev/null
}

# 逐项输出检查结果(供UI使用): 名称=ok|fail:细节
checkdetail() {
    if proxy_alive; then
        case "$PROXY_MODE" in
            shadowrocket) echo '代理内核=ok:Shadowrocket 已连接' ;;
            *) echo "代理内核=ok:$(proxy_name) 运行中" ;;
        esac
    else
        echo "代理内核=fail:$(proxy_name) 未运行"
    fi
    if tun_up; then echo 'TUN网卡=ok'; else echo 'TUN网卡=fail:不在线'; fi
    trace=$(curl -s --max-time 8 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null)
    trace_rc=$?
    ip=$(echo "$trace" | grep '^ip=' | cut -d= -f2)
    loc=$(echo "$trace" | grep '^loc=' | cut -d= -f2)
    assess_exit "$ip" "$loc" "$trace_rc"
    echo "出口IP=$EXIT_STATE:$EXIT_DETAIL"
    load_check_context "$ip"
    lastip=""; [ -f "$BASE/lastip" ] && lastip=$(cat "$BASE/lastip")
    ipst=""; ipdt=""
    if [ -z "$ip" ]; then echo 'IP一致=fail:未获取到出口IP'
    elif [ -z "$lastip" ]; then ipst="ok"; ipdt="首次记录"
    elif [ "$ip" = "$lastip" ]; then ipst="ok"
    else ipst="warn"; ipdt="$lastip → $ip"; fi
    [ -n "$ip" ] && echo "$ip" > "$BASE/lastip"
    # 保留历史,仅统计不同IP个数,不推断账号风险。
    if [ -n "$ipst" ]; then
        ipn=$(iphist_count "$ip")
        if [ "$ipn" -ge 3 ] 2>/dev/null; then
            if [ "$ipst" = "ok" ]; then
                ipst="warn"; ipdt="48h内出现${ipn}个不同IP,请确认是否为计划内换线"
            else
                ipdt="$ipdt;48h内出现${ipn}个不同IP,请确认是否为计划内换线"
            fi
        fi
        if [ "$ipst" = "ok" ] && [ "$HISTORY_ACK_BEFORE" -gt 0 ]; then
            ipdt="当前出口与上次一致;旧调试记录已确认;后续历史继续统计"
        fi
        if [ -z "$ipdt" ]; then echo "IP一致=$ipst"; else echo "IP一致=$ipst:$ipdt"; fi
    fi
    preference_rows
    v6=$(networksetup -getinfo Wi-Fi 2>/dev/null | grep -i '^IPv6:')
    if echo "$v6" | grep -qi 'off'; then echo 'IPv6=ok:Wi-Fi已关闭;Clash内核另见探测路由'; else echo 'IPv6=fail:Wi-Fi未关闭'; fi
    dnsip=$(dig +short +time=3 +tries=1 claude.ai 2>/dev/null | head -1)
    case "$dnsip" in
        198.18.*) echo 'DNS=info:claude.ai返回Fake-IP;未单独验证全部上游DNS路径' ;;
        *) echo "DNS=warn:映射返回${dnsip:-空};不能仅凭真实IP或无结果认定泄漏" ;;
    esac
    wr=$(webrtc_test)
    assess_webrtc "$wr" "$ip"
    echo "WebRTC=$WEBRTC_STATE:$WEBRTC_DETAIL"
    guard_status
    network_evidence
    # info 是配套核验模块对成功探测的范围说明;本项只判定本次探测。
    if [ "$ROUTE_STATE" = "info" ]; then
        echo "规则置顶=ok:本次探测通过;$ROUTE_DETAIL"
    else
        echo "规则置顶=$ROUTE_STATE:$ROUTE_DETAIL"
    fi
    # 13. 这里只查询ASN归属名称,不等同于单个IP的hosting/住宅用途分类。
    org=$(curl -s --max-time 6 https://ipinfo.io/json 2>/dev/null | grep '"org"' | cut -d'"' -f4)
    if [ -n "$ASN_REVIEW" ]; then
        echo "ASN属性=info:$ASN_REVIEW;实时归属${org:-未知}"
    else
    case "$org" in
        '') echo 'ASN属性=warn:未获取ASN归属' ;;
        *Comcast*|*AT\&T*|*Verizon*|*Spectrum*|*Charter*|*Cox*|*T-Mobile*|*Cable*|*esidential*|\
        *NTT*|*KDDI*|*SoftBank*|*IIJ*|*OCN*|*So-net*|\
        *HiNet*|*Chunghwa*|*CHT*|*kbro*|*Taiwan*|*FarEasTone*|*Data\ Communication*|\
        *Singtel*|*StarHub*|*M1*|\
        *HKT*|*PCCW*|*HKBN*|*HGC*|\
        *BT*|*Sky*|*Virgin*|*TalkTalk*|*Vodafone*|\
        *Deutsche\ Telekom*|*1\&1*|*O2*) echo "ASN属性=ok:$org(仅名称匹配,接入类型未验证)" ;;
        *) echo "ASN属性=warn:类型待核验($org);未查询IP用途分类" ;;
    esac
    fi
    # 14. Anthropic 生态可达性
    access_probe
    echo "生态可达性=$ACCESS_STATE:$ACCESS_DETAIL"
}

# 兼容命令名;使用订阅末尾脚本,不再把prepend-rules写进普通Merge字段。
write_merge_rules() {
    local helper="$BASE/clash-profile-guard.py"
    [ -f "$helper" ] || helper="$(dirname "$0")/clash-profile-guard.py"
    if [ ! -f "$helper" ]; then
        echo "FAIL:缺少订阅防护模块,请更新配套文件"
        return 1
    fi
    python3 "$helper" --group "$PROXY_GROUP"
}

# 一键修复:按项自动修复,每步输出结果
fix() {
    echo "FIX:开始一键修复"

    # A. 代理内核 + TUN
    if [ "$PROXY_MODE" = "clash-verge" ]; then
        if ! pgrep -f verge-mihomo >/dev/null 2>&1; then
            echo "FIX:正在启动 Clash Verge..."
            open -a "Clash Verge"
        fi
        for i in $(seq 1 40); do
            pgrep -f verge-mihomo >/dev/null 2>&1 && tun_up && break
            sleep 1
        done
        if pgrep -f verge-mihomo >/dev/null 2>&1 && tun_up; then
            echo "FIX:代理内核+TUN ✓"
        else
            V="$CLASH_DIR/verge.yaml"
            if [ -f "$V" ] && grep -q '^enable_tun_mode: false' "$V"; then
                echo "FIX:检测到 TUN 开关被关闭,正在恢复..."
                osascript -e 'tell application "Clash Verge" to quit' >/dev/null 2>&1
                sleep 3
                sed -i '' 's/^enable_tun_mode: false/enable_tun_mode: true/' "$V"
                open -a "Clash Verge"
                for i in $(seq 1 40); do
                    tun_up && break
                    sleep 1
                done
            fi
            if pgrep -f verge-mihomo >/dev/null 2>&1 && tun_up; then
                echo "FIX:代理内核+TUN ✓(已恢复TUN开关)"
            else
                echo "FIX:代理内核/TUN ✗(请打开 Clash Verge 检查节点/线路)"
            fi
        fi
    else
        app=$(proxy_app_name)
        if ! proxy_alive && [ -n "$app" ]; then
            echo "FIX:正在启动 $app..."
            open -a "$app" >/dev/null 2>&1
        fi
        for i in $(seq 1 40); do
            proxy_alive && tun_up && break
            sleep 1
        done
        if proxy_alive && tun_up; then
            echo "FIX:代理内核+TUN ✓"
        else
            echo "FIX:代理内核/TUN ✗(请打开 $(proxy_name) 手动检查节点/线路及TUN模式)"
        fi
    fi

    # B. 网络修复不修改时区、地区格式或客户端语言。
    v6=$(networksetup -getinfo Wi-Fi 2>/dev/null | grep -i '^IPv6:')
    adminCmds=""
    echo "$v6" | grep -qi 'off' || adminCmds="${adminCmds}networksetup -setv6off Wi-Fi; "
    if ! launchctl print system/local.claude-bodyguard >/dev/null 2>&1; then
        adminCmds="${adminCmds}cp $HOME/.local/bin/local.claude-bodyguard.plist /Library/LaunchDaemons/ && chown root:wheel /Library/LaunchDaemons/local.claude-bodyguard.plist && launchctl bootstrap system /Library/LaunchDaemons/local.claude-bodyguard.plist; "
    fi
    if [ -n "$adminCmds" ]; then
        adminCmds="${adminCmds}dscacheutil -flushcache; killall -HUP mDNSResponder"
        echo "FIX:修复IPv6/DNS/进程监测(需要密码)..."
        if osascript <<ASEOF >/dev/null 2>&1
do shell script "$adminCmds" with prompt "一键修复需要管理员权限" with administrator privileges
ASEOF
        then
            echo "FIX:IPv6/DNS/进程监测 ✓"
        else
            echo "FIX:IPv6/进程监测 ✗(取消或失败)"
        fi
    else
        echo "FIX:IPv6/进程监测 无需修复 ✓"
    fi

    if [ "$PROXY_MODE" = "clash-verge" ]; then
        write_merge_rules || echo "FIX:订阅防护未完成,请按提示核对专用脚本配置"
    fi
    echo "FIX:保留现有时区、地区格式与客户端语言;如需调整请使用显式地区设置"
    network_evidence
    echo "FIX:实际路由=$ROUTE_STATE:$ROUTE_DETAIL"

    # C. WebRTC 泄漏专项:在 TUN/IPv6 已处理后复测;UDP 仍绕过隧道时重载 TUN 再测一次
    wrip=$(curl -s --max-time 8 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null | grep '^ip=' | cut -d= -f2)
    wr=$(webrtc_test)
    load_check_context "$wrip"
    assess_webrtc "$wr" "$wrip"
    echo "FIX:WebRTC=$WEBRTC_STATE:$WEBRTC_DETAIL"

    # D. 出口IP最终验证
    sleep 2
    trace=$(curl -s --max-time 8 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null)
    trace_rc=$?
    ip=$(echo "$trace" | grep '^ip=' | cut -d= -f2)
    loc=$(echo "$trace" | grep '^loc=' | cut -d= -f2)
    assess_exit "$ip" "$loc" "$trace_rc"
    echo "FIX:出口IP=$EXIT_STATE:$EXIT_DETAIL"
}

# 地区自适应:按当前出口国家一键重设 国家/时区/地区格式(换了国家节点后运行)
set_region() {
    trace=$(curl -s --max-time 8 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null)
    loc=$(echo "$trace" | grep '^loc=' | cut -d= -f2)
    [ -z "$loc" ] && { echo "FAIL:无法获取出口国家(cloudflare trace 无结果,请先挂代理)"; return 1; }
    info=$(curl -s --max-time 8 https://ipinfo.io/json 2>/dev/null)
    ctry=$(echo "$info" | grep '"country"' | cut -d'"' -f4)
    ntz=$(echo "$info" | grep '"timezone"' | cut -d'"' -f4)
    if [ -z "$ctry" ] || [ -z "$ntz" ]; then
        echo "FAIL:ipinfo 未返回国家或时区"; return 1
    fi
    if [ "$loc" != "$ctry" ]; then
        echo "FAIL:出口国家不一致(cloudflare=$loc ipinfo=$ctry),已中止"; return 1
    fi
    nlocale=$(locale_for "$ctry")

    # 改写脚本自身头部三个配置项
    sed -i '' \
        -e "s|^COUNTRY_TARGET=\".*\"|COUNTRY_TARGET=\"$ctry\"|" \
        -e "s|^TZ_TARGET=\".*\"|TZ_TARGET=\"$ntz\"|" \
        -e "s|^LOCALE_TARGET=\".*\"|LOCALE_TARGET=\"$nlocale\"|" \
        "$0"
    COUNTRY_TARGET="$ctry"; TZ_TARGET="$ntz"; LOCALE_TARGET="$nlocale"

    # 地区格式(用户级,无需密码)
    defaults write -g AppleLocale "$nlocale"

    # 时区(需管理员权限,会弹一次授权框);看门狗脚本在 root 目录下,顺道用同一次授权同步目标值
    WD="/Library/Application Support/claude-switcher/tz-watchdog.sh"
    adminCmds="/usr/sbin/systemsetup -settimezone $ntz"
    wdsync=0
    if [ -f "$WD" ] && [ ! -w "$WD" ]; then
        adminCmds="$adminCmds; /usr/bin/sed -i '' 's|^TARGET=.*|TARGET=$ntz|' '$WD'"
        wdsync=1
    fi
    if ! osascript <<ASEOF >/dev/null 2>&1
do shell script "$adminCmds" with prompt "set-region 需要管理员权限以锁定时区" with administrator privileges
ASEOF
    then
        echo "FAIL:时区设置被取消或失败(国家/地区格式已更新为 $ctry/$nlocale)"
        return 1
    fi
    # 看门狗目标同步兜底(可写的老版本安装直接 sed;失败则提示运行安装器刷新)
    if [ -f "$WD" ] && [ "$wdsync" -eq 0 ]; then
        sed -i '' "s|^TARGET=.*|TARGET=$ntz|" "$WD" 2>/dev/null || echo "WARN:看门狗目标未同步,请运行安装器刷新"
    fi

    echo "OK:region=$loc tz=$ntz locale=$nlocale"
}

# 定制版通过人工审阅合入上游,不下载远端包覆盖本机定制。
self_update() {
    echo "INFO:定制版已禁用远程覆盖更新。请fetch并审阅上游提交、测试后合入自己的分支；本机未改动。"
    return 0
}

# 按需设备信息:不修改设置,不参与启动评分。基于上游4675a35适配。
fingerprint() {
    python3 - "$HOME" <<'PY_DEVICE_INFO'
import json
from pathlib import Path
import re
import subprocess
import sys

def read(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''

def clean(value):
    return ''.join(c for c in str(value) if c.isprintable())[:300]

print('设备信息：仅提供线索，不判定地区、账号风险或封禁原因；不影响启动。')
names = set()
pattern = re.compile(r'simsun|simhei|simkai|simfang|msyh|msjh|dengxian|wqy|fzshu|fzkai|fzhei|fangsong', re.I)
for folder in [Path('/Library/Fonts'), Path(sys.argv[1]) / 'Library/Fonts']:
    try:
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix.lower() in ['.ttf', '.ttc', '.otf'] and pattern.search(path.name):
                names.add(clean(path.name))
    except OSError:
        pass
print('字体线索=info:' + ('、'.join(sorted(names)) if names else '在已扫描目录未匹配所列文件名；不代表只有系统字体'))
try:
    display = json.loads(read(['system_profiler', 'SPDisplaysDataType', '-json']))['SPDisplaysDataType'][0]
    chip = display.get('sppci_model') or display.get('_name') or '未获取'
    monitors = display.get('spdisplays_ndrvs', [])
    resolution = (monitors[0].get('_spdisplays_resolution') or monitors[0].get('spdisplays_resolution') or '未获取') if monitors else '未获取'
except (ValueError, KeyError, TypeError, IndexError, AttributeError):
    chip = resolution = '未获取'
print('GPU=info:' + clean(chip))
print('显示=info:' + clean(resolution))
virtual = read(['sysctl', '-n', 'kern.hv_vmm_present'])
print('虚拟化标记=info:' + {'1': '系统报告虚拟化标记', '0': '系统未报告该标记；不证明物理机'}.get(virtual, '未获取，不能判断'))
print('渲染器=info:本命令不读取Claude/浏览器的Canvas或WebGL，不代表浏览器指纹检查已通过。')
PY_DEVICE_INFO
}

account_observation() {
    python3 - "$BASE/account-observations.json" <<'PY_ACCOUNT_OBSERVATION'
import datetime
import json
from pathlib import Path
import sys
fallback = '账号权限未验证；网络检查不代表登录或模型可用。'
try:
    data = json.loads(Path(sys.argv[1]).read_text())
    records = data['observations']
    if len(records) != 1:
        raise ValueError('unsupported record scope')
    record = records[0]
    if record.get('client') != 'claude_web' or record.get('state') != 'on_hold' or record.get('source') != 'user_report':
        raise ValueError('unverified observation')
    day = datetime.date.fromisoformat(record['reported_on'])
    if day > datetime.date.today():
        raise ValueError('future date')
    print('网页版Proton账号：用户报告on hold（' + day.isoformat() + '）；未关联桌面A/B，非实时验证。')
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    print(fallback)
PY_ACCOUNT_OBSERVATION
}

status() {
    cur="none"; [ -f "$BASE/current" ] && cur=$(cat "$BASE/current")
    hasA=0; [ -d "$BASE/accounts/A" ] && hasA=1
    hasB=0; [ -d "$BASE/accounts/B" ] && hasB=1
    echo "current=$cur hasA=$hasA hasB=$hasB"
}

quit_claude() {
    pgrep -f "/Applications/Claude.app/Contents/MacOS/Claude" >/dev/null 2>&1 || return 0
    osascript -e 'tell application "Claude" to quit' >/dev/null 2>&1
    for i in $(seq 1 15); do
        pgrep -f "/Applications/Claude.app/Contents/MacOS/Claude" >/dev/null 2>&1 || return 0
        sleep 1
    done
    return 1
}

archive_current() {
    cur="$1"
    t0=$(date +%s)
    # 归档=把当前数据目录整体移走(同卷瞬时,跨卷 mv 自动退化为复制),不再全量深拷贝
    rm -rf "$BASE/accounts/$cur.new"
    if mv "$DATA" "$BASE/accounts/$cur.new" 2>/dev/null; then
        rm -rf "$BASE/accounts/$cur"
        mv "$BASE/accounts/$cur.new" "$BASE/accounts/$cur"
    else
        rm -rf "$BASE/accounts/$cur.tmp"
        copy_tree "$DATA" "$BASE/accounts/$cur.tmp" && rm -rf "$BASE/accounts/$cur" && mv "$BASE/accounts/$cur.tmp" "$BASE/accounts/$cur"
    fi
    log "已存档账号$cur ($(( $(date +%s) - t0 ))s)"
}

# 快照复制:APFS 上用 clonefile(COW) 近乎瞬时,不改写已有快照;不支持时回退 ditto 全量复制
copy_tree() {
    src="$1"; dst="$2"
    if [ "${CLAUDE_SWITCHER_NO_CLONE:-0}" != "1" ] && cp -cRp "$src" "$dst" 2>/dev/null; then
        return 0
    fi
    rm -rf "$dst"
    ditto "$src" "$dst"
}

switch_to() {
    target="$1"
    case "$target" in A|B) ;; *) echo "FAIL:账号必须为A或B"; return 2 ;; esac
    check || return 1
    cur="none"; [ -f "$BASE/current" ] && cur=$(cat "$BASE/current")
    just_archived=0

    # 首次运行:把当前登录中的状态收编为账号A
    if [ "$cur" = "none" ] && [ -d "$DATA" ] && [ -n "$(ls -A "$DATA" 2>/dev/null)" ]; then
        quit_claude || { echo "FAIL:Claude 未能退出，请手动退出后重试"; return 1; }
        archive_current A
        just_archived=1
        cur="A"; echo "$cur" > "$BASE/current"
        log "首次运行:当前登录状态已收编为账号A"
        echo "NOTE:已将当前登录收编为账号A"
    fi

    if [ "$cur" = "$target" ]; then
        # 归档是移动语义,首次收编后需把当前账号还原回 DATA
        if [ "$just_archived" = "1" ] && [ ! -d "$DATA" ] && [ -d "$BASE/accounts/$target" ]; then
            copy_tree "$BASE/accounts/$target" "$DATA"
        fi
        open -a "Claude" || { echo "FAIL:未能打开Claude，请检查应用安装后重新扫描重试"; return 1; }
        echo "INFO:当前已是账号$target"
        return 0
    fi

    quit_claude || { echo "FAIL:Claude 未能退出，请手动退出后重试"; return 1; }

    [ "$just_archived" = "0" ] && [ "$cur" != "none" ] && [ -d "$DATA" ] && archive_current "$cur"

    rm -rf "$DATA.new"
    t0=$(date +%s)
    if [ -d "$BASE/accounts/$target" ]; then
        copy_tree "$BASE/accounts/$target" "$DATA.new"
        log "已载入账号$target 存档 ($(( $(date +%s) - t0 ))s)"
    else
        mkdir -p "$DATA.new"
        log "账号$target 无存档，将以全新状态初始化"
    fi
    rm -rf "$DATA" && mv "$DATA.new" "$DATA"
    echo "$target" > "$BASE/current"

    open -a "Claude" || { echo "FAIL:已切换到账号${target}，但未能打开Claude；请重新扫描后打开当前档案"; return 1; }
    log "已切换到账号$target 并启动 ($(( $(date +%s) - t0 ))s)"
    echo "OK:已切换到账号$target ($(( $(date +%s) - t0 ))s)"
    return 0
}

case "${1:-}" in
    network-report)
        helper="$BASE/network-audit.py"
        [ -f "$helper" ] || helper="$(dirname "$0")/network-audit.py"
        exec python3 "$helper" --home "$HOME" --group "$PROXY_GROUP" --country "$COUNTRY_TARGET"
        ;;
    check)  check ;;
    expected-exit)
        expected=$(expected_exit_ip 2>/dev/null) || { echo '固定出口配置无效或选择组查询失败' >&2; exit 1; }
        [ -n "$expected" ] || { echo '未配置固定出口' >&2; exit 2; }
        echo "$expected"
        ;;
    checkdetail)
        OUT_FILE="$BASE/last-check.txt"
        CHECK_OUTPUT=$(mktemp "$BASE/.check-output.XXXXXX") || { echo 'FAIL:无法创建本次扫描输出'; exit 1; }
        {
            echo "# $(date '+%F %T') pid=$$ 开始"
            checkdetail
            echo "# 结束"
        } > "$CHECK_OUTPUT" 2>&1
        cat "$CHECK_OUTPUT"
        mv -f "$CHECK_OUTPUT" "$OUT_FILE"
        ;;
    fix) fix ;;
    account-note) account_observation ;;
    protected-browser|protected-check|provider-audit|support-report)
        helper="$BASE/protected-access.py"
        [ -f "$helper" ] || helper="$(dirname "$0")/protected-access.py"
        case "$1" in protected-browser) action=browser ;; protected-check) action=check ;; support-report) action=report ;; *) action=provider-audit ;; esac
        exec python3 "$helper" "$action"
        ;;
    fingerprint) fingerprint ;;
    status) status ;;
    switch) switch_to "${2:-}" ;;
    set-region) set_region ;;
    update) self_update "${2:-}" ;;
    write-merge-rules) write_merge_rules ;;  # 隐藏入口:供安装器调用,保证两处合并逻辑一致
    *) echo "用法: claude-switch.sh check|checkdetail|expected-exit|network-report|fix|fingerprint|protected-browser|protected-check|provider-audit|support-report|account-note|status|switch A|B|set-region|update [--auto]|diagnose-proxy [--proxy URL|--config FILE]"; exit 2 ;;
esac
