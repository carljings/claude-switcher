#!/bin/bash
# Claude 保镖 (参考模板) —— 安装程序会把 __HOME__ / __PROXY_MODE__ 替换为实际值后安装
# 仅保护Claude桌面主进程;周期检测有窗口,不是防火墙级断网保护。
MODE="__PROXY_MODE__"
APPDIR="/Library/Application Support/claude-switcher"
HELPER="$APPDIR/network-audit.py"
STATE="$APPDIR/guard-status.json"

# 不运行任何用户可写脚本;待命时清除上次失败计数。
if ! pgrep -f '^/Applications/Claude.app/Contents/MacOS/Claude([[:space:]]|$)' >/dev/null 2>&1; then
    /usr/bin/python3 "$HELPER" --idle --state-file "$STATE" >/dev/null 2>&1
    exit 0
fi

# Clash专用策略核验所选出口及API连接,连续两次失败才终止桌面端。
if [ "$MODE" = "clash-verge" ]; then
    decision=$(/usr/bin/python3 "$HELPER" --home "__HOME__" --guard --state-file "$STATE" 2>/dev/null)
    if [ "$decision" = "stop" ]; then
        pkill -f '^/Applications/Claude.app/Contents/MacOS/Claude([[:space:]]|$)'
        /usr/bin/logger -t claude-switcher '固定出口或API路由连续两次核验失败,已终止Claude桌面主进程;仅进程级保护'
    fi
    exit 0
fi

ok=1

# TUN 在线判定:存在 fake-ip 网段地址即视为 TUN 已接管
ifconfig 2>/dev/null | grep -q 'inet 198\.18\.' || ok=0

# 内核在线判定:按安装时识别的客户端分派
case "$MODE" in
    shadowrocket)
        # launchd 环境下 scutil 可能查不到 VPN 行,查不到时以 TUN 判定为准(避免误杀)
        nc=$(scutil --nc list 2>/dev/null)
        if echo "$nc" | grep -q 'com.liguangming.Shadowrocket'; then
            echo "$nc" | grep 'com.liguangming.Shadowrocket' | grep -q '(Connected)' || ok=0
        fi ;;
    sing-box)
        pgrep -f sing-box >/dev/null 2>&1 || ok=0 ;;
    clashx)
        { pgrep -x ClashX >/dev/null 2>&1 || pgrep -f clash >/dev/null 2>&1; } || ok=0 ;;
    surge)
        pgrep -f Surge >/dev/null 2>&1 || ok=0 ;;
    auto)
        : ;;  # auto 模式只查 TUN
    *)
        pgrep -f verge-mihomo >/dev/null 2>&1 || ok=0 ;;
esac

if [ "$ok" -eq 0 ]; then
    if pgrep -f '^/Applications/Claude.app/Contents/MacOS/Claude([[:space:]]|$)' >/dev/null 2>&1; then
        pkill -f '^/Applications/Claude.app/Contents/MacOS/Claude([[:space:]]|$)'
        /usr/bin/logger -t claude-switcher '代理内核或TUN离线,已终止Claude桌面主进程;未核验指定出口'
    fi
fi
