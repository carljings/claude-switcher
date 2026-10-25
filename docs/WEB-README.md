# Web 版环境检测

零安装的浏览器侧环境自检页：手机 / 平板浏览器打开即测。纯静态、无构建、无第三方 JS/CSS 依赖，可直接由 GitHub Pages 托管。

页面源码入口：[index.html](index.html)。以下说明如何部署，不表示本分支已启用 GitHub Pages；实际地址以当前仓库的 Pages 设置为准。

## 检测项

| # | 检测项 | 内容 | 判定 |
|---|---|---|---|
| 01 | 出口 IP / 归属 | `ipinfo.io/json` 优先；失败回退 `www.cloudflare.com/cdn-cgi/trace` | 成功 `ok`；仅兜底成功 `warn`；全部失败 `fail` |
| 02 | 地区一致性 | 比对浏览器与出口时区，按出口国家映射比对 `navigator.language(s)`；UTC 偏移仅展示 | 时区不符、语言不符或缺少出口时区 `warn`；国家无语言映射时语言仅展示 |
| 03 | WebRTC 泄漏 | 通过 Google / Cloudflare STUN 收集 ICE 候选，提取公网地址并与出口 IP 比对 | 额外公网 IP `fail`；不支持、无候选或公网候选缺少出口对照时 `warn`；仅出口 IP、mDNS 或仅内网/本地候选时源码标为 `ok` |
| 04 | IPv6 暴露 | `api6.ipify.org` 3 秒超时探测，必要时用 ipinfo 查询 IPv6 归属 | 未取到地址或与出口相同 `ok`；异于出口且国家不同，或有出口对照且非空机构名未匹配代理关键词时 `fail`；其余可达但证据不足的情况 `warn` |
| 05 | DNS 泄漏（近似） | 并行请求 HTTPS trace `1.1.1.1/cdn-cgi/trace` 与 Google DoH `dns.google/resolve`，不追踪实际 DNS 路径 | 两请求成功 `ok`（DoH 无 A 记录也可）；否则 `warn`；不是完整 DNS 泄漏检测 |
| 06 | 浏览器指纹展示 | Canvas 哈希、WebGL vendor/renderer、屏幕、DPR、色彩深度、platform、CPU 核心、设备内存 | 仅展示，源码固定 `ok`，字段不可用也不自动失败 |
| 07 | 检测结论 | 汇总前 6 项的 `fail` / `warn` 并列出明细 | 页面文案：0 fail 为“环境基本合规”，有 `fail` 为“高风险”；无 `fail` 但有 `warn` 时总状态为 `warn` |

评分仅为页面内的粗略参考：`100 - fail×25 - warn×6`，最低 0 分；这些标签不代表官方规则、账号可用或零泄漏。IPv6 的机构关键词判断也不能证明实际路由或物理接入类型。

打开页面或点击“重新检测”会执行 6 项检查；出口 IP 结果供地区、WebRTC 和 IPv6 对照，完成后汇总结论。页面不调用本机核心、不读取 A/B 档案，也不更改代理或系统设置。

## 本地预览

请通过 HTTP / HTTPS 访问。`file://` 可能受跨域与浏览器安全策略限制，页面也会显示提示，不宜用其结果验收。在仓库根目录执行：

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory docs
# 打开 http://127.0.0.1:8000
```

## 部署到 GitHub Pages

推荐直接从 `docs/` 目录发布，不需要 Actions：

1. 将仓库推送到 GitHub。
2. 仓库 **Settings → Pages → Build and deployment**。
3. Source 选择 **Deploy from a branch**。
4. Branch 选择实际发布分支（如 `main`），Folder 选择 **`/docs`**，保存。
5. 等待 Pages 部署成功，使用 Settings → Pages 显示的站点地址。`docs/` 是发布源目录，不是需要附加到站点 URL 的路径。

如果使用自定义 Actions 发布，也只需要把 `docs/` 作为站点根目录发布，无需构建步骤。

## 隐私说明

- 当前页面脚本不设置 Cookie、不写 `localStorage`/`sessionStorage`、不引入分析或追踪脚本，检测状态保存在页面内存中。
- 源码中的 HTTP 检测请求发往以下公共 API：`ipinfo.io`、`www.cloudflare.com`、`1.1.1.1`、`dns.google`、`api6.ipify.org`，使用 `credentials: "omit"` 和 `referrerPolicy: "no-referrer"`。
- WebRTC 检测使用 `stun:stun.l.google.com:19302` 与 `stun:stun.cloudflare.com:3478` 收集候选地址。
- 公共服务会看到请求源 IP；IPv6 归属查询还会把所探测地址放入 ipinfo 请求路径，Google DoH 会收到 `claude.ai` 查询。源码未向项目后台提交检测结果，不能据此保证托管方或公共服务没有请求日志。
- 外部文本（IP、org、DoH 结果等）通过 `textContent` 写入 DOM；CSP 将 `script-src` 限制为 `'self'`，但 `connect-src` 允许 HTTPS / WSS，并非上述域名的白名单。

## 能力边界

- 只评估**浏览器侧**信号，不替代桌面版的 14 项审计。
- 不检测 TUN 网卡、桌面进程守护、进程级泄漏、系统路由表、系统 DNS 配置或代理内核，也不提供断网保护。
- 地区一致性只读浏览器时区与语言，不代表系统全部区域设置。
- DNS 项只覆盖列出的公共请求；DoH 可达不能证明所有 DNS 查询都走代理。桌面核心的 Fake-IP / 路由审计也有各自范围，不能由本页替代。
- WebRTC / IPv6 结果会受浏览器策略、代理是否接管 UDP、节点是否支持 IPv6 影响；没有候选或未取到 IPv6 地址都不证明系统不存在其他暴露路径。
- 页面不做任何自动修复，也不绕过任何服务条款。

## 文件结构

Web 页面相关文件（不列其他项目文档）：

```
docs/
├── index.html   # 页面结构、CSP、静态文案
├── style.css    # 暗色 + 紫色品牌样式，移动端优先
├── app.js       # 全部检测逻辑与安全 DOM 渲染
├── favicon.svg  # 品牌图标
└── WEB-README.md # 本文件
```

修改后无需构建，本地刷新页面即可；线上需重新部署后再核对。检测依赖 `fetch`、`AbortController` 等浏览器 API；WebRTC、Canvas、WebGL、`Intl.DisplayNames` 或设备内存信息不可用时，相关结果会提示或降级显示。本次仅核对源码，未验证线上 Pages 状态或各浏览器的实测兼容性。
