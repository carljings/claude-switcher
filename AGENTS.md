# AGENTS.md —— Agent 交接提示词

> 这份文件写给 AI Agent。用户把本项目交给你时，请按本文档执行安装与配置。
> 用户也可以直接把本文件内容粘贴给任意本地模型（Kimi Code / Cursor / Claude Code 等）作为指令。

---

## 你的任务

帮助用户在 macOS 上安装并配置「Claude 切换器」：一个带环境安检的 Claude 账号启动/切换工具。目标状态是：**14项检查能区分故障、待核验和个人偏好；无启动阻断项，可以正常启动Claude；不追求全部绿标**。

## 2026-10-23 macOS 本地改进版优先规则

2026-10-24增量补强：专用入口必须复用`network-audit.py`核验Claude/API目标实际路由，缺证拒绝；每次打开核对Default偏好及同资料旧进程的必要参数，漂移不覆盖用户资料。HTTP发送/响应失败记为故障，不能因TLS握手成功降为提醒。详见`docs/plans/2026-10-24-entry-and-transport-hardening.md`。

本定制分支补充（2026-10-24）：`update`/`update --auto`只提示采用审阅流程，不会下载远端包覆盖定制；安装器不注册覆盖式更新任务。下文上游历史的自动更新步骤不适用于本分支。单IP锁定文件与选择组策略叠加核验；不一致阻止启动。路由模块必须核对Clash IPv6明确关闭，root模块更新须先准备可审阅构建、验证和可恢复安装脚本。

账号交互为两步：A/B只改内存选择，独立确认按钮才调用核心复检和打开。核心`switch`必须在任何档案修改前校验A/B及重新`check`，打开请求失败返回错误；界面保留目标并读取实际状态，不把未知输出视为成功。使用`scripts/test-account-ui.py`和隔离HOME回归；维护验收不得自动切换本机真实A/B档案。

快照安全补充：归档/复制/提交失败立即停止；保留`.new`、`.previous`和旧`.tmp`恢复现场。资料变动前准备`current.new`，最终原子提交当前档案标记；任何待恢复标记存在时不允许再次切换。不得为重试自动删除暂存或猜测恢复版本。验证只用隔离HOME。

A/B邮箱是本机应用偏好标签，不代表当前登录或权限验证；不得提交真实值或复制到迁移包。编辑期间不触发账号操作。界面的“服务响应”继续使用核心“生态可达性”协议键，保留匿名HTTP探测及提醒门槛。

网络重生成修复补充：用户态需同时安装`clash-profile-guard.py`和同名JS模板，私有策略显式配置`profile_guard_scripts`。不要再把普通Merge里的`prepend-rules`存在当作规则已生效；按真实订阅末尾脚本和控制器前置规则验证。基础IPv6修改需同步Clash内存并复核实际重生成；受管脚本未知改动不得覆盖。明确Cloudflare挑战头的匿名403/API401仅作灰色说明，未知拒绝仍提醒、传输失败仍阻断。

以下规则优先于本文中旧版安装描述：用户后续明确要求严格模式：时区、地区格式和英文语言不符仍阻止启动；这是本地基线，不宣称为官方封禁条件。网络修复不写这些设置。按用户明确要求保留已有严格时区看门狗，并将旧版用户目录入口迁入root所有的系统目录；保留当前已设定的时区。

核心配套文件增加 `core/network-audit.py`，必须与核心一起安装到 `~/.claude-switcher/`，并与保镖一起安装到root所有的 `/Library/Application Support/claude-switcher/`；自动更新只更新用户态副本，root副本仍需显式安装授权。保镖不得执行用户目录内的Python或Shell脚本。

实际路由以无认证TLS探测的源端口、域名和控制器记录核验；Fake-IP/规则文本存在不能替代。仅注册保镖不能代表出口监测正常；查看近期状态及范围。守护仅终止桌面主进程，不终止浏览器和独立CLI。详见 `docs/plans/2026-10-23-checks-and-runtime-guard-design.md` 和 `docs/USAGE-SAFETY.md`。

## 开始之前：必须先确认的前置条件

本机2026-10-24新增`core/protected-access.py`用户态配套模块，需与核心同时安装。它提供专用Edge固定代理入口和Chicago/en-US严格预检，读取私有出口策略；不装入root守护目录、不读取登录态。`status`保持原协议，账号观察单独调用`account-note`；具体范围见`docs/USAGE-SAFETY.md`。迁移时不复制浏览器资料或账号观察文件。

逐项检查，缺哪项就先补哪项：

1. **macOS**（Apple Silicon 或 Intel 均可）
2. **代理客户端**已安装且代理可用，支持 Clash Verge / Shadowrocket / sing-box / ClashX / Surge 任一（TUN 可用）。Clash Verge 的配置目录应存在于 `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/`；Shadowrocket 以 VPN 配置形式存在（`scutil --nc list` 可见）
3. **Claude 桌面版** 在 `/Applications/Claude.app`
4. **python3** 可用（`python3 --version` 能输出版本号；没有则引导用户运行 `xcode-select --install`）
5. **当前出口 IP 所在国家不能是 CN**——先跑 `curl -s https://www.cloudflare.com/cdn-cgi/trace | grep loc=`，返回的 `loc` 不是 `CN` 才能继续。是 CN 就停下，让用户先把代理调好（安装程序会按出口 IP 自动锁定地区目标：国家/时区/地区格式三件套，裸连时装机会把它们锁错）

## 安装步骤

首选引导用户运行安装器（双击 `installer/安装.command`，或终端执行它）。如果安装器环境受限，按下面的手动等效步骤执行：

1. 把 `core/claude-switch.sh` 复制为 `~/.local/bin/claude-switch.sh`（可执行），把 `core/stun-probe.py` 放到 `~/.claude-switcher/`
2. 探测代理客户端并写进脚本顶部 `PROXY_MODE="..."`：存在 Clash Verge 配置目录 → `clash-verge`；否则 `scutil --nc list` 有 Shadowrocket VPN 配置 → `shadowrocket`；都没有则让用户在 clash-verge/shadowrocket/sing-box/clashx/surge/auto 中选择
3. Clash Verge 模式下，从 `clash-verge.yaml` 的 `proxy-groups:` 找第一个 `type: select` 的组名写进 `PROXY_GROUP="..."`（其他客户端跳过）
4. 按出口 IP 自动锁定地区目标：`curl -s ipinfo.io/json` 的 country → `COUNTRY_TARGET`，timezone → `TZ_TARGET`，country 经映射表（US→en_US、JP→ja_JP、TW→zh_TW、HK→zh_HK、SG→en_SG、GB→en_GB、DE→de_DE、FR→fr_FR、KR→ko_KR、AU→en_AU、CA→en_CA，其余→en_US）→ `LOCALE_TARGET`，三项都写进脚本头部
5. 参照 `daemons/` 目录的模板，物化保镖与时区看门狗脚本（把 `__HOME__` / `__TZ_TARGET__` / `__PROXY_MODE__` 替换为实际值），用 sudo 装入 **root 所有的** `/Library/Application Support/claude-switcher/`（chown root:wheel、chmod 755，用户态不可写防提权）；`local.claude-bodyguard` / `local.tz-watchdog` 两个 LaunchDaemon 安装到 `/Library/LaunchDaemons/`（plist 的 ProgramArguments 已写死指向系统目录，直接 cp 即可）。自动更新 `local.claude-update` 是**用户态 LaunchAgent**：plist 放 `~/Library/LaunchAgents/`，用 `launchctl bootstrap gui/$(id -u)` 注册，不走 root（模板 `daemons/local.claude-update.plist`，每 12 小时跑一次 `update --auto`）
6. 现场编译界面 App（需要 Xcode 命令行工具，必须带 `-target` 否则新 SDK 产物在老系统拒启动）：
   ```bash
   swiftc -O -parse-as-library -target "$(uname -m)-apple-macos13.0" app/main.swift -o Claude切换器.app/Contents/MacOS/ClaudeSwitcher -framework SwiftUI -framework AppKit
   ```
   图标用 `assets/icon-2048.png` 经 sips 生成 iconset 再 `iconutil -c icns` 打进 `Contents/Resources/AppIcon.icns`，`Info.plist` 声明 `CFBundleIconFile`，最后 `codesign --force --deep -s -`
7. Clash Verge 模式下把置顶规则写入「全局扩展配置」(Merge.yaml) 并重启 Clash Verge；其他客户端提示用户自行添加 DOMAIN-SUFFIX 置顶规则
8. 时区与 IPv6（已是目标值则跳过对应命令）：`systemsetup -settimezone <TZ_TARGET>`、`networksetup -setv6off Wi-Fi`（需管理员）
9. 收尾自检：运行 `~/.local/bin/claude-switch.sh checkdetail` 确认故障项已排除，信息与待核验项范围明确

日常维护命令：`check`（静默总检）/ `checkdetail`（14 项逐项）/ `fix`（一键修复）/ `switch A|B`（切换账号）/ `set-region`（换国家节点后重锁地区目标）/ `update [--auto]`（自动更新：`--auto` 由用户态 LaunchAgent 每 12 小时调用、输出落 `~/.claude-switcher/update.log`；手动跑则直接打印。流程：拉取 main → 逐项 SHA256 校验工件（对照仓库 SHA256SUMS，不符即中止）→ 剔除 5 个配置行比对去重 → 备份 .bak → 注入配置 → 守护脚本仅比对并提示 → 自检，含任何 `=fail` 自动回滚）

## 独立代理诊断

`bash core/claude-switch.sh diagnose-proxy --config /path/to/private-proxy.json` 只验证明确指定代理到 Claude 网页/API 的无认证传输，详见 README。它可直接从仓库运行，不适用上述安装/启动前置条件，不启动或关闭应用，不创建账号状态、不修改系统设置。输出 JSON；401/403 分别标注认证或访问状态，传输到达不等于账号可用、启动许可或防泄漏通过。不要为运行诊断先安装后台或改 TUN/时区。

隔离回归：`python3 -m unittest discover -s tests -v`。测试使用本机假 curl 和隔离 HOME，不使用真实登录资料或代理。

## 验收标准（全部满足才算装完）

- 终端执行 `~/.local/bin/claude-switch.sh checkdetail` 输出14项，无未解决的 `=fail`；严格基线不符为 `=fail`；信息与待核验项不能当作独立验证通过
- 双击桌面 App，界面无启动阻断项，能正常启动Claude；灰色范围说明不代表零风险
- `launchctl print system/local.claude-bodyguard`、`system/local.tz-watchdog` 与 `gui/$(id -u)/local.claude-update` 均能查到（服务已注册）
- `/Library/Application Support/claude-switcher/` 下两个守护脚本属 root:wheel、权限 755，当前用户不可写
- 切换一次账号 B 再切回 A，A 的登录态完好

## 排障手册（以下全是实战中踩过的坑，按症状直接查）

| 症状 | 根因 | 处理 |
|---|---|---|
| TUN 网卡消失、出口变回国内 | **Clash Verge 更新/异常重启会把 `enable_tun_mode` 重置为 false**（生产环境已发生 4 次） | 退出 App → 改 `verge.yaml` 为 true → 重启 App。切换器的一键修复已内置此逻辑 |
| 时区总是自己变回去 | macOS 自动时区或未知程序改动（生产环境已抓 8 次） | 看门狗会自动回滚；查 `~/Library/Logs/tz-watchdog.log` 留痕 |
| 检查结果显示 0/11、数据为空 | 中文日志被 `cut -c` 按字节截断产生非法 UTF-8，Swift 严格解码整体失败 | 脚本必须 `export LC_ALL=en_US.UTF-8`；界面端用容错解码 `String(decoding:as:)` |
| 修改 App 后界面没变化 | 旧进程没死：App 关窗不退 + `pkill` 匹配中文路径会因 Unicode NFD 编码失配而静默失败 | 用 `pkill -x ClaudeSwitcher`（按进程名）；App 必须实现 `applicationShouldTerminateAfterLastWindowClosed` |
| headless Chrome 做 WebRTC 检测无结果 | headless 模式 ICE 子系统不产出候选 | 不要走浏览器路线，用本项目的纯 Python STUN 探针 |
| 代理节点报错但流量没泄漏 | 节点被重置时隧道内请求失败≠泄漏；Fail-Closed 下流量只断不绕 | 换线路即可 |
| 切换账号后对方看到"新设备" | 正常：快照隔离意味着每个账号有独立设备指纹，这正是设计目标 | 无需处理 |

## 安全红线（Agent 必须遵守）

1. **绝不在出口国家与目标不一致时启动 Claude**——任何时候先验 cloudflare trace 的 `loc` 与脚本头部 `COUNTRY_TARGET` 一致；换了国家节点先跑 `claude-switch.sh set-region` 再启动
2. 切换账号前必须先完全退出 Claude 进程，再交换数据目录
3. 不要在日志、文档、Issue 里暴露用户的住宅/代理 IP 与任何凭据
4. 不要改动 `~/.claude-switcher/accounts/` 下的存档结构
5. **维护纪律**：`core/`、`daemons/`、`installer/` 下任何文件改动后，提交前必须运行 `scripts/gen-sums.sh` 重新生成根目录 `SHA256SUMS` 并同提交——自动更新靠它校验工件完整性，清单与代码不一致会导致所有用户更新失败
6. **守护进程脚本只在 root 目录**：`/Library/Application Support/claude-switcher/` 下的保镖/看门狗属 root:wheel，任何功能都不要改回写 `~/.local/bin/` 下的同名脚本（用户可写=提权面）；需要变更时引导用户重跑安装器

## Windows 版（windows/ 目录, Beta）

Windows 用户请使用 `windows/` 下的 PowerShell 版本。关键差异与注意事项：

- **文件编码**：所有 `.ps1` 文件必须保持 **UTF-8 with BOM**（Windows PowerShell 5.1 无 BOM 会把中文读成乱码）。编辑后若中文变乱码，重新加 BOM。
- **时区 ID 体系不同**：Windows 用 `Eastern Standard Time` 这类 ID，安装器负责把 IANA 时区（America/New_York）映射过去，见 `install.ps1` 的 `$tzMap`。
- **权限模型**：`install.ps1` 需要管理员运行（注册计划任务/锁时区/关 IPv6）；日常使用中「一键修复」通过 `Start-Process -Verb RunAs` 触发 UAC 弹窗。
- **保镖实现**：用计划任务（AtLogOn 触发）启动隐藏 PowerShell 常驻进程，10 秒巡检，与 Mac 版行为一致。
- **robocopy 退出码**：0-7 都是成功，8+ 才是失败——判断切换成败时不要按常规退出码判断。
- **账号数据目录**：`%APPDATA%\Claude`（不是 macOS 的 `~/Library/Application Support/Claude`）。
- **已知限制**：WPF 界面为第一版重写，未经大规模真机测试；Clash Verge 的 TUN 开关被更新重置后在 Windows 端需手动重开。
- SmartScreen 首次运行拦截属正常现象（未签名脚本），引导用户「更多信息 → 仍要运行」。

## Linux 版（linux/ 目录, Beta）

Linux 用户使用 `linux/` 下的 bash 版本。**开始之前必须先理解最大的前提差异**：

- **Claude 官方没有 Linux 桌面版**——使用形态是「网页版(浏览器) + Claude Code CLI」。因此：
  - 账号切换切换的是**浏览器配置目录**（`~/.config/google-chrome` 或 `~/.config/chromium`），即切换 Web 登录态；切换前必须完全退出浏览器
  - 保镖只终止 `claude` CLI 进程，**不要让它去杀浏览器**（网页端保护交给 TUN + 置顶规则）
- **多客户端**：`PROXY_MODE` 支持 clash-verge / mihomo / sing-box / v2raya / nekobox / hiddify / wireguard / other / auto；非 Clash 客户端不做配置改写，只做 fake-ip 行为检测并提示用户自行加 DOMAIN-SUFFIX 规则；`wireguard` / `other` 为通用虚拟网卡启发式判定
- **地区自适应**：`COUNTRY_TARGET` / `TZ_TARGET` / `LOCALE_TARGET` 由安装器按出口自动写入；`CN` 出口拒绝安装；换国家节点后手动改这三个值（Linux 版暂无 `set-region` 命令）
- **常驻服务**：systemd 用户单元（`~/.config/systemd/user/`，免 sudo、登录自启）
- **系统设置**：时区用 `timedatectl set-timezone`（sudo）；IPv6 用 `sysctl -w net.ipv6.conf.all.disable_ipv6=1` + `/etc/sysctl.d/` 持久化
- **DNS 查询工具**：`dig` → `nslookup` → `getent` 逐级回退（部分发行版默认无 dig，脚本已内置回退，勿改成 dig 硬依赖）
- **界面**：无 GUI，终端菜单（`claude-switch menu`）+ CLI 参数
- **发行版差异**：安装器不区分发行版，但依赖 systemd；非 systemd 发行版（如 Alpine/void 部分配置）需要手工替代保镖常驻方式
- 配置目录路径：Clash Verge Linux 版配置在 `~/.config/io.github.clash-verge-rev.clash-verge-rev/`（脚本已兼容两种常见路径）

## 文件索引

- 核心逻辑：`core/claude-switch.sh`（安检/切换/修复全在这一个文件）
- 泄漏探针：`core/stun-probe.py`
- 界面：`app/main.swift`（单文件 SwiftUI）
- 守护进程模板：`daemons/`
- 安装器：`installer/`
- Windows 版：`windows/`（核心 `claude-switch.ps1` / 界面 `SwitcherUI.ps1` / 安装器 `install.ps1` / 保镖 `claude-bodyguard.ps1`）
- Linux 版：`linux/`（核心 `claude-switch.sh` / 保镖 `claude-bodyguard.sh` / 安装器 `install.sh`）
- Web 版：`docs/` 下的 index.html/app.js/style.css（纯静态环境检测页，GitHub Pages 从 docs/ 发布）

## 维护者本机纪律（Agent 必须遵守）

**除非维护者在当次对话中明确要求，否则不得更新/部署维护者本机的已安装版本。** 具体包括：

- 不得覆盖 `~/.local/bin/claude-switch.sh`、`~/.local/bin/local.claude-*.plist`
- 不得重新编译或替换桌面 App（`~/Desktop/Claude切换器.app`）
- 不得改动 `/Library/Application Support/claude-switcher/`、`/Library/LaunchDaemons/local.claude-*`、`~/Library/LaunchAgents/local.claude-*`
- 不得触发本机 `update`、不得执行安装器/卸载器

日常开发默认流程：**只修改仓库文件 → 验证（本地只跑不影响安装态的测试/静态检查）→ 提交推送**。需要真机验证时，先询问维护者是否允许在本机部署。
