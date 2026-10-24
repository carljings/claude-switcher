<div align="center">

# Claude 切换器

**本地环境检查与桌面账号切换 —— 在启动前发现配置与连接问题**

> 🛠️ **本项目持续活跃更新中**——防护项随目标平台风控演进不断增加，见下方[路线图](#路线图)。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS-blue.svg)]()
[![Windows](https://img.shields.io/badge/Windows-Beta-lightgrey.svg)](windows/)
[![Linux](https://img.shields.io/badge/Linux-Beta-lightgrey.svg)](linux/)
[![UI](https://img.shields.io/badge/UI-SwiftUI-orange.svg)]()
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero-brightgreen.svg)]()

<img src="assets/icon-2048.png" width="128">

</div>

---

## 本定制分支

面向macOS的本地严格配置：固定出口与所选节点叠加核验、时区/地区/英文基线、实际TLS探测路由、有限范围桌面守护、重新扫描、全文详情、黑白直切、专用Edge入口。专用入口以Chicago/en-US为本地基线，保留真实设备信息，不提供“防封号”承诺。匿名HTTP响应和旧登录备注不验证当前账号。

远程覆盖式自动更新已禁用；在自己的分支审阅、合入和测试上游修复。私有配置、代理凭据和账号数据不得提交。新增命令和验证边界见[使用说明](docs/USAGE-SAFETY.md)。

获取此定制分支：

```bash
git clone --branch custom/strict-macos https://github.com/carljings/claude-switcher.git
```

本节与使用说明优先于下文继承的上游安装、自动更新示例。本分支的严格定制针对macOS；Windows/Linux未做同等实机验证。

## 为什么做这个

代理未运行、规则漏配和出口漂移都可能造成连接问题。本项目在启动前检查当前配置与探测信号，并管理Claude桌面端的本地会话快照。

检查通过不等于账号获得访问许可或不会被停用。账号使用应遵守官方服务条款、使用政策及适用地区要求，详见[使用建议与检查边界](docs/USAGE-SAFETY.md)。

> 本地改进版在桌面端运行时核验所选出口及API探测链路，连续两次异常后终止桌面主进程。它不保护浏览器或独立CLI，存在巡检窗口，属于进程级保护，不是防火墙级保证。

## 核心创新

### 1. Block-on-Fail 环境审计引擎

macOS版显示14项检查。故障项阻止启动；提醒项表示存在限制或需要核实，不等同于故障：

| # | 检查项 | 防什么 |
|---|---|---|
| 01 | 代理内核 | 代理根本没在跑就启动 |
| 02 | TUN 网卡 | 系统代理开着但流量没被接管 |
| 03 | 出口 IP | 核对目标国家；配置了固定IPv4时同时校验该值 |
| 04 | IP 一致性 | 与上次探测比对，显示48小时内不同IP个数 |
| 05 | 时区（严格） | 按本地基线核对，不符阻止启动；非官方封禁判据 |
| 06 | 地区格式（严格） | 按本地基线核对，不符阻止启动 |
| 07 | IPv6 | 双栈旁路直连（最隐蔽的泄漏通道之一） |
| 08 | DNS 映射 | 只报告指定域名映射；不覆盖全部DNS路径 |
| 09 | WebRTC | 多节点 STUN 交叉探测（详见第 2 节） |
| 10 | 桌面进程监测 | 近期出口与API链路监测证据；非防火墙保证 |
| 11 | 探测路由 | 按探测连接源端口核对控制器规则、代理链与所选出口 |
| 12 | 客户端语言 | 本地严格策略要求英文，不符阻止启动 |
| 13 | ASN 属性 | 归属名称匹配或待核验；不判定具体IP的住宅/托管用途 |
| 14 | 生态可达性 | 区分传输故障、访问限制、限流和服务端异常；不验证账号 |

> 「IP 与上次一致」保留48小时出口历史，出现至少3个不同IP时显示提醒。这是本地稳定性提示，不是切换次数或已知的官方封禁阈值。可选私有文件`~/.claude-switcher/expected-exit-ip`指定固定IPv4；不匹配或文件无效时检查失败，详见[配置说明](docs/USAGE-SAFETY.md#可选固定出口校验)。

主界面常驻“重新扫描”（Command-R）与最近扫描时间；每次读取当前网络，空结果或缺项不复用旧扫描，不切换账号。单击右上角月亮/太阳按钮即可直接切换黑色或白色皮肤，自动记住选择，说明页同步切换；皮肤切换不触发扫描或账号操作。点击任意检查项可查看完整结果与对应处理建议，并选中文字复制。

红色故障阻止启动，黄色表示需要核实，灰色表示确认记录或范围说明。旧调试历史已确认且当前出口与上次一致时正常通过；探测路由通过仅代表本次受控探测及已观察连接，未观察的应用连接仍未核验。

### 2. 纯标准库手写 STUN 协议栈的 WebRTC 泄漏探针

不依赖浏览器内核（headless Chrome 的 ICE 子系统在无人值守场景下根本不工作——我们踩过这个坑），直接用 `socket` + `struct` 手工构造 RFC 5389 Binding Request，解析 XOR-MAPPED-ADDRESS。

探测列表包含Google、Cloudflare和国内服务。收到的公网地址与出口探测值不同会报告失败；所有服务无响应通常显示提醒。若实时核验到四个探测域名的优先UDP拒绝规则，则显示灰色的策略说明；这不能证明全部UDP或浏览器WebRTC路径均已覆盖。用户已确认的历史与第三方标签可按具体IPv4记录，详见[范围说明](docs/USAGE-SAFETY.md#已确认记录与灰色说明)。

### 3. Fail-Closed Kill-Switch

常驻守护进程以 10s 周期巡检隧道健康度（内核进程 × 虚拟网卡双因子），隧道中断即刻终止受保护进程。区别于客户端自带的 Fail-Open 容错重试——那种机制会把含真实 IP 的握手包送到对方网关日志里，哪怕最终"超时失败"。

### 4. Session Snapshot 快照隔离

切换前退出Claude桌面端，再封存和载入对应的数据目录。此操作不等同于完整设备、系统钥匙串或原生CLI账号隔离，也不保证服务端把账号视为固定设备。CLI多账号应采用官方支持的独立`CLAUDE_CONFIG_DIR`和认证流程。

切换开销被压到"零拷贝"级别：归档是**同卷移动**（rename，瞬时完成），载入走 **APFS clonefile / reflink 的写时复制（COW）**——只有日后被修改的数据块才会真正复制。macOS 不支持 clonefile 时自动回退 `ditto` 全量复制，Linux 回退普通 `cp -a`（可用 `CLAUDE_SWITCHER_NO_CLONE=1` 强制走回退路径）。

### 5. 配置漂移自愈（Watchdog）

用户选择了严格模式：时区、地区格式与英文语言按本地基线核对，不符仍阻止启动；这些要求不代表官方封禁规则。网络修复不修改或放宽它们，设置仅通过显式入口调整。

### 6. Pinned Routing 置顶路由

导入规则只是配置意图。新版探测路由项通过无认证TLS连接并按源端口核对控制器记录，不再用Fake-IP或文本存在代替实际匹配；应用真实连接未出现时明确标注尚未观察。详细证据可运行 `claude-switch.sh network-report`。

## 实战战绩

这不是玩具项目，每个机制都有生产环境实战记录：

```
2026-10-07 00:31:12  代理离线(内核或TUN丢失),已自动关闭 Claude   ← Kill-Switch 真实拦截
2026-10-04 12:55:26  时区异常: [Asia/Shanghai] 已自动恢复        ← Watchdog 第 8 次拦截漂移
```

## 界面

![Screenshot](docs/screenshot.png)

原生 SwiftUI 单文件应用（无 Xcode 工程、无第三方依赖，`swiftc` 一条命令出可执行文件），图标由 Swift 代码程序生成——整个仓库不含一张设计素材。

## 安装

**系统要求**：macOS · Clash Verge / Shadowrocket / sing-box / ClashX / Surge 任一（TUN 可用）· Claude 桌面版 · python3

> **Windows 用户**：[`windows/`](windows/) 目录提供 Windows 版（PowerShell + WPF，Beta），安装与注意事项见 [windows/README.md](windows/README.md)。
> **Linux 用户**：[`linux/`](linux/) 目录提供 Linux 版（bash + systemd，Beta），设计取舍（无官方桌面版→切换浏览器登录态）见 [linux/README.md](linux/README.md)。

```bash
# 克隆后双击 installer/安装.command 即可,自动识别代理客户端、代理组名与地区目标
git clone https://github.com/YOURSJEYO/claude-switcher.git
```

## 地区自适应

安装程序记录当前出口的目标国家及参考时区/地区格式，默认保留系统偏好。固定出口策略可核对所选节点的IP与国家；这些检查不能代表账号符合服务地区要求。之后换了其他国家的节点，不用重装，一条命令重新适配：

```bash
~/.local/bin/claude-switch.sh set-region
# 自动探测出口国家 → 改写自身配置 → 设地区格式 → 弹一次授权锁时区 → 同步看门狗
# 输出: OK:region=JP tz=Asia/Tokyo locale=ja_JP
```

出口按明确配置的国家/节点核对；时区、地区和语言按本地严格基线检查。

## 不会配置？交给你的 AI

仓库根目录的 [`AGENTS.md`](AGENTS.md) 是一份完整的 **Agent 交接提示词**：把它直接粘贴给你的本地模型（Kimi Code / Cursor / Claude Code 等），它会按文档自动完成环境检查、安装、配置与验收。里面还附了我们实战踩过的全部坑的排障手册。

## 使用

1. 双击桌面「Claude切换器」→ 等待 14 项检查
2. 全绿 → 选账号启动；有红项 → 「一键修复」自动处理
3. B 账号首次使用登录一次，以后 A/B 随切随用、互不干扰
4. 换了其他国家的节点 → 跑一次 `~/.local/bin/claude-switch.sh set-region`，国家/时区/地区格式一键重新锁定

## Web 版环境检测（零安装）

手机 / 平板浏览器打开即测，无需安装：[https://yoursjeyo.github.io/claude-switcher/](https://yoursjeyo.github.io/claude-switcher/)

页面逐项评估 6 类浏览器侧信号，并给出总评与失败项：

- **出口 IP / 归属**：ipinfo.io 优先，Cloudflare trace 兜底
- **地区一致性**：浏览器时区、UTC 偏移与语言是否和出口国家矛盾
- **WebRTC 泄漏**：STUN 候选地址与出口 IP 比对，识别 mDNS 混淆与 fake-IP
- **IPv6 暴露**：IPv6 是否可直连、归属国家是否与 IPv4 出口一致
- **DNS 泄漏（近似）**：1.1.1.1 / Google DoH 公共加密解析可达性
- **浏览器指纹展示**：Canvas 哈希、WebGL vendor/renderer、屏幕与设备参数（只展示，不阻断）

纯前端、无追踪、无 localStorage；检测请求只发往公共 API，结果不上传。它只评估浏览器侧信号，**不替代桌面版 14 项审计**，也不检测 TUN / 保镖 / 进程级泄漏。部署方式与完整隐私说明见 [docs/WEB-README.md](docs/WEB-README.md)。

## 已有代理的独立诊断（macOS CLI）

已有 HTTP/SOCKS 入口、由其他工具管理账号时，可以先单独检查 Claude 的网络传输，无需运行安装器或启动 Claude：

```bash
bash core/claude-switch.sh diagnose-proxy --proxy http://127.0.0.1:18080
# 已安装版本:
~/.local/bin/claude-switch.sh diagnose-proxy --config /path/to/private-proxy.json
```

私有配置文件只需包含 `{"proxy_url":"http://127.0.0.1:18080"}`。也可明确设置 `CLAUDE_SWITCHER_PROXY_URL`；命令行/配置文件优先于该变量。需要代理认证时优先使用私有配置或变量，避免凭据出现在本命令的参数中。支持 `http`、`https`、`socks5`、`socks5h`，地址必须包含端口；不会自动扫描代理或回退直连。

命令只向固定的 Claude 网页/API 地址发送无账号认证的请求，输出 JSON，不读取账号存档、不创建状态目录、不更改系统设置、不启动/关闭应用。代理地址和凭据不进入报告；代理凭据通过 curl 标准输入传递。它随现有核心脚本分发和更新，无需额外服务。

- 退出码 `0`：两个目标均收到经过 TLS 验证的 HTTP 响应。API 的 `401` 单独标为 `unauthenticated`，网页的 `403` 标为 `access_restricted`，均不等于账号或业务可用。
- 退出码 `1`：至少一项传输失败、超时或输出异常；未完成的检查保持未知。
- 退出码 `2`：代理或参数配置无效。普通 `HTTP_PROXY` / `NO_PROXY` 等继承值不会代替明确选择的入口。

该命令仅诊断上述官方域名的传输，不验证自定义 API Base URL/第三方供应商、DNS/WebRTC/IPv6 泄漏，不产生启动许可，也不绕过或修改原有的 TUN 启动审计。可用 `CLAUDE_SWITCHER_PYTHON` 选择已有 Python 解释器；默认 `python3`。

隔离回归测试（不连接真实代理或账号）：`python3 -m unittest discover -s tests -v`。

## 使用卫生与被封急救

以下以官方资料为依据，完整来源见[使用建议](docs/USAGE-SAFETY.md)：

- 使用自己的账号与官方认证流程，不共享凭据；订阅OAuth与开发者API密钥有不同用途，不应替其他用户代转发订阅额度。
- 服务条款、使用政策及适用地区要求仍需遵守。住宅评分、固定IP或改时区不能证明合规，也不能保证不会停用。
- 无认证API401不等于账号可用，网页403不单独证明账号停用；429和5xx应先查看用量、服务状态及官方排障资料。
- 对多账号采用官方支持的配置隔离方式，不自动轮换账号绕过限制。本工具不新增或改写CLI登录凭据。
- 如果官方页面确实显示账号停用，通过[官方申诉入口说明](https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals)处理，不依靠未经核实的“养号阈值”或申诉成功率传言。

## 项目结构

```
├── app/main.swift          # SwiftUI 界面(单文件)
├── core/
│   ├── claude-switch.sh    # 核心逻辑:审计/切换/修复
│   └── stun-probe.py       # STUN 探针(手工协议实现)
├── windows/                # Windows 版(PowerShell 核心 + WPF 界面, Beta)
├── linux/                  # Linux 版(bash 核心 + systemd 保镖 + 终端菜单, Beta)
├── docs/                   # Web 版环境检测页(index.html 等, GitHub Pages 从这里发布) + 项目文档
├── daemons/                # Kill-Switch / Watchdog / 自动更新 launchd 模板
├── installer/              # 双击安装/卸载
├── scripts/gen-sums.sh     # 重新生成 SHA256SUMS(改动 core/daemons/installer 后必跑)
├── SHA256SUMS              # 发布工件完整性校验清单(自动更新逐项比对)
└── assets/                 # 程序生成图标
```

## 二改指南

- **改界面**：编辑 `app/main.swift`，`swiftc -O -parse-as-library` 重编译即可
- **加检查项**：`core/claude-switch.sh` 的 `checkdetail()` + UI 的 `keyMap` 各加一行
- **改防护策略**：`daemons/` 里的模板即全部守护逻辑

欢迎 Fork / PR。Issue 区接受场景补充——你遇到的每一个真实泄漏场景，都可能成为下一个检查项。

## 问题反馈

- 提交 [Issue](https://github.com/YOURSJEYO/claude-switcher/issues)
- 在 [Linux.do](https://linux.do) 论坛发帖讨论
- **安全问题请走非公开渠道**：见 [SECURITY.md](SECURITY.md)（GitHub Private Vulnerability Reporting 优先）

反馈掉登录、弹盾类问题时，请附上「应用设置 → 日志」导出的日志，里面不含密码和 Cookie 原文；如果可以，也请附上可复现步骤。

## 路线图

本项目按"实战驱动"迭代——风控怎么进化，防护就怎么跟上：

- [x] macOS 版：14 项环境审计 + Kill-Switch + 快照切换 + 漂移自愈（已稳定）
- [x] Windows 版（Beta）：核心逻辑全移植
- [x] Linux 版（Beta）：bash 核心 + systemd 保镖 + 终端菜单
- [ ] Windows 版稳定化：多客户端/地区自适应/TUN 通用判定已落地（静态验证通过），真机回归持续进行
- [ ] Linux 版稳定化：多客户端/地区自适应/COW 快照已落地（桩测试通过），多发行版真机回归持续进行
- [x] Web 版环境检测页：手机/平板浏览器打开即测，零安装
- [ ] 更多指纹维度：字体地区特征、Canvas/WebGL 渲染特征（Web 版已覆盖 Canvas/WebGL 展示，桌面版后续）
- [x] 更多代理客户端适配：已支持 Clash Verge / Shadowrocket / sing-box / ClashX / Surge（含 auto 自动识别）
- [x] 快照切换提速：归档改为同卷移动 + 载入走 COW 克隆（APFS clonefile / Linux reflink），不再产生全量复制
- [x] 应用内自动更新：launchd 每 12 小时自动检查更新，自检失败自动回滚，也可手动 `claude-switch.sh update` 保底

> 有想优先看到的功能，去 [Issues](https://github.com/YOURSJEYO/claude-switcher/issues) 投票或提需求，热度高的先做。

## 帮忙吆喝一声

如果这个工具让你少被封了一个号，希望有条件的佬哥能帮我们在 [Linux.do](https://linux.do) 论坛发个帖子推荐一下——仓库地址 <https://github.com/YOURSJEYO/claude-switcher>，一句话定位：**"Claude 账号的 Fail-Closed 环境保护罩：14 项环境审计不过就物理上不让启动"**。让更多被风控折磨的兄弟少走弯路。

## License

MIT © Claude Switcher Contributors

## 2026-10-23 上游适配合入

参考 a04db61 的端口保护：本地固定HTTP出口采用 UDP 3478/5349/19302 和四个探测域名置顶拒绝，保持TCP分流。无响应时必须核验完整优先规则，不能把无响应视为零泄漏。相关端口的实时通话可能受影响，其他端口与全部浏览器路径未由此覆盖。

参考4675a35新增按需 `fingerprint` /「设备信息」，只列字体文件名线索、GPU/显示和虚拟化标记，不评分、不阻断启动，不更改字体；未获取数据明确标注。黑白直切、全文详情和原严格基线保留。
