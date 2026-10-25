# 原生CLI专用入口模板与本机改动范围

本机已有原生启动器继续使用原来的官方可执行文件与独立配置目录。本轮仅精简重复探测、清理意外继承的provider/凭据库覆盖，并委托核心`protected-cli`执行专用入口预检和网络约束；默认第三方供应商配置不变。

下面是脱敏逻辑模板，**不是可直接运行的安装脚本**。占位符应填现有已验证路径，不要为了套模板改动已工作的配置目录或末尾斜杠；未填时前置检查会停止。

```bash
#!/bin/bash
set -euo pipefail
NATIVE_CLI="__ABSOLUTE_OFFICIAL_CLI_PATH__"
export CLAUDE_CONFIG_DIR="__EXISTING_NATIVE_CONFIG_DIR__"
[ -x "$NATIVE_CLI" ] && [ -f "$CLAUDE_CONFIG_DIR/settings.json" ] || exit 1
while IFS= read -r provider_env_name; do
    case "$provider_env_name" in
        ANTHROPIC_*|CLAUDE_CODE_USE_BEDROCK|CLAUDE_CODE_USE_VERTEX|CLAUDE_CODE_USE_FOUNDRY|CLAUDE_CODE_OAUTH_TOKEN|CLAUDE_CODE_OAUTH_REFRESH_TOKEN|CLAUDE_CODE_OAUTH_SCOPES|CLAUDE_SECURESTORAGE_CONFIG_DIR)
            unset "$provider_env_name" ;;
    esac
done < <(compgen -e)
exec "$HOME/.local/bin/claude-switch.sh" protected-cli "$NATIVE_CLI" \
    --settings "$CLAUDE_CONFIG_DIR/settings.json" "$@"
```

核心在启动时读取私有`protected_listener`端口，强制大小写HTTP(S)/ALL代理和loopback绕过，设置Chicago与英文UTF-8环境，并应用TCP单端口沙箱。模板不读取登录凭据或钥匙串，不能证明实际账号权限。`lsopen/appleevent-send`拒绝会限制自动打开浏览器，用户可手动将官方登录URL放到专用浏览器。

CLI设置文件中的`env`也需要与该端口一致，避免设置覆盖启动环境。下列仅是网络字段示例，应**合并到原env而不是覆盖整个设置文件**；17897为本机约定示例，应与私有listener一致。

```json
{
  "HTTP_PROXY": "http://127.0.0.1:17897",
  "HTTPS_PROXY": "http://127.0.0.1:17897",
  "ALL_PROXY": "http://127.0.0.1:17897",
  "http_proxy": "http://127.0.0.1:17897",
  "https_proxy": "http://127.0.0.1:17897",
  "all_proxy": "http://127.0.0.1:17897",
  "NO_PROXY": "localhost,127.0.0.1,::1",
  "no_proxy": "localhost,127.0.0.1,::1",
  "TZ": "America/Chicago",
  "LANG": "en_US.UTF-8",
  "LC_ALL": "en_US.UTF-8"
}
```

本机真实可执行路径、配置中的凭据和完整设置不进入仓库；本地保留权限受限的恢复副本。API端点与原登录方式不由此模板替用户重新选择，实际认证仍需在官方CLI核对。其他终端、默认供应商入口和服务器不套用这层限制。
