#!/bin/bash
clear
echo "=============================="
echo "  Claude 账号切换器 - 卸载"
echo "=============================="
echo ""
sudo launchctl bootout system/local.claude-bodyguard 2>/dev/null
sudo launchctl bootout system/local.tz-watchdog 2>/dev/null
sudo launchctl bootout system/local.claude-update 2>/dev/null
sudo rm -f /Library/LaunchDaemons/local.claude-bodyguard.plist /Library/LaunchDaemons/local.tz-watchdog.plist /Library/LaunchDaemons/local.claude-update.plist
sudo rm -rf "/Library/Application Support/claude-switcher"
launchctl bootout "gui/$(id -u)/local.claude-update" 2>/dev/null
rm -f "$HOME/Library/LaunchAgents/local.claude-update.plist"
# ---- App 与桌面入口 ----
APP="$HOME/Applications/Claude切换器.app"
DESKTOP_APP="$HOME/Desktop/Claude切换器.app"
is_switcher_app() {
    [ -d "$1" ] && [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$1/Contents/Info.plist" 2>/dev/null)" = "local.claude-switcher" ]
}
if [ -e "$DESKTOP_APP" ] || [ -L "$DESKTOP_APP" ]; then
    if is_switcher_app "$DESKTOP_APP" \
        || { [ -L "$DESKTOP_APP" ] && [ "$(readlink "$DESKTOP_APP")" = "$APP" ] && [ ! -e "$APP" ] && [ ! -L "$APP" ]; }; then
        rm -rf "$DESKTOP_APP"
    else
        echo "保留未知的桌面同名入口,请人工核对。"
    fi
fi
if [ -e "$APP" ] || [ -L "$APP" ]; then
    if is_switcher_app "$APP"; then
        rm -rf "$APP"
    else
        echo "保留未知的 Applications 同名目标,请人工核对。"
    fi
fi
# ---- 用户态脚本 ----
rm -f "$HOME/.local/bin/claude-switch.sh" "$HOME/.local/bin/claude-bodyguard.sh" "$HOME/.local/bin/tz-watchdog.sh" "$HOME/.local/bin/local.claude-bodyguard.plist" "$HOME/.local/bin/local.tz-watchdog.plist" "$HOME/.local/bin/local.claude-update.plist" "$HOME/.local/bin/claude-switch.sh.bak" "$HOME/.local/bin/claude-bodyguard.sh.bak" "$HOME/.local/bin/tz-watchdog.sh.bak"
echo ""
echo "✅ 已卸载。"
echo "注意: 账号存档保留在 ~/.claude-switcher/(含你的登录态),要删干净可手动: rm -rf ~/.claude-switcher"
echo "置顶规则提示: 如曾在 Clash Verge 配置过置顶规则,可手动清空 全局扩展配置(Merge.yaml);其他客户端的规则请自行检查。"
echo ""
read -n 1 -s -r -p "按任意键关闭窗口..."
