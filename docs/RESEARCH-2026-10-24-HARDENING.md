# Claude严格使用环境：增量调研与修复依据

核对日期：2026-10-24（America/Chicago）。本轮用户授权调研、改进和本机部署。这里只记录可验证的技术行为；不把IP评分、语言、时区、字体或个案升级为免封规则。

## 四个平台的检索与访问范围

| 渠道 | 实际读到的内容 | 采用方式 |
|---|---|---|
| Google | 实际搜索结果页，包含官方申诉说明、代理商指南及相互矛盾的使用个案 | 找原始资料；排名、商业推荐和数字不作为风控阈值 |
| GitHub | 只读fetch上游至`e2da429`，审阅新增`c78939b`归档失败修复及测试；Chromium代理/开关源码 | 适配安全修复，保留本地严格检查、双步确认及错误处理 |
| YouTube | 视频介绍的搜索索引，以及原作者伴随仓库README；视频直开受限，未完整观看 | 认证串线作为排障线索，回官方文档核实 |
| X | Google精确索引、公开讨论中的原帖链接；原帖403、空页或超时 | 仅作线索，不据此确认封号原因或自动安装插件 |

可复查的社区来源：

- [IndyDevDan的视频](https://www.youtube.com/watch?v=8IDzBRRFnQU)与[原作者伴随仓库](https://github.com/disler/max-your-cc-sub)：提示API key可能改变认证来源；其订阅用途建议仍以当前官方要求为准。
- [个人防封经验视频](https://www.youtube.com/watch?v=5tfLMuUpij4)：索引以机房IP、非当地时区的个案反对固定配方，不能由此推出普遍安全性。
- [WebRTC提醒原帖](https://x.com/binghe/status/2095195633519145140)：索引建议WebRTC Control；原帖未成功读取，泄漏与封号的因果未验证。
- [第三方客户端讨论](https://x.com/trq212/status/2009689809875591565)、[SDK/Max历史澄清](https://x.com/trq212/status/2024212378402095389)、[第三方用量说明](https://x.com/bcherny/status/2040206440556826908)：仅索引/外部引文可用，不作为当前认证授权依据。

## 一手依据与实际决策

### 目标路由需要独立核验

[Chromium代理文档](https://chromium.googlesource.com/chromium/src/+/HEAD/net/docs/proxy.md)说明HTTP代理支持HTTPS CONNECT，目标名称由代理解析，DIRECT后备由代理列表决定。Cloudflare出口正确不能代替Claude目标路由证据。

专用入口现在复用路由模块，对`claude.ai`和`api.anthropic.com`的TLS连接按源端口、域名和控制器代理链核验。证据不全也拒绝启动。保留单一HTTP代理；不添加DIRECT后备，也不机械取消localhost隐式绕过（本地认证回调需要单独考虑）。

### Edge偏好与启动参数不能只初始化一次

[Chromium开关定义](https://github.com/chromium/chromium/blob/main/chrome/common/chrome_switches.h)和[命令行偏好映射](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/chrome/browser/prefs/chrome_command_line_pref_store.cc)使用`--webrtc-ip-handling-policy`。保留旧参数兼容，补当前参数；不根据上游源码就断言本机Edge曾忽略旧参数。

每次专用浏览器启动前核对Default资料中的WebRTC、DoH及英文偏好；已有同资料进程还需符合当前参数，避免新的打开请求沿用旧进程。偏好漂移只拒绝并说明，既有资料不被覆盖。普通Edge不参与检查。

[Microsoft的DoH说明](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/DnsOverHttpsMode)中的`off`仅表示关闭DoH，不能单独证明所有DNS路径；[WebRTC策略说明](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/WebRtcLocalhostIpHandling)也不能代替实际浏览器候选验证。

### HTTP黑洞必须是传输故障

本地反例已复现：TLS成功后HTTP请求发送或响应超时，被旧探针降为warn，桌面守护因此清零连续失败。修复后HTTP完成才设置`transport_ok`，失败为fail；控制器缺证独立为warn。匿名401/403仍只说明收到响应，不确认账号权限。

### 认证配置应避免串线

[官方网络配置](https://code.claude.com/docs/en/network-config)明确大小写代理优先级及`NO_PROXY`绕过；本机独立原生CLI入口已显式设置大小写代理、仅保留loopback绕过，并清理意外供应商环境变量。本轮核对未发现该项缺口，不改变默认第三方供应商配置。

[官方认证优先级](https://code.claude.com/docs/en/authentication#authentication-precedence)还涉及provider、token、API key和`apiKeyHelper`。本工具的配置存在性审计不代表实际认证成功；应在未经修改的官方CLI中由用户核对`/status`。当前[凭据用途规则](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)和[登录说明](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account)优先于历史社交帖子，不收集凭据供第三方代转发。

### GitHub新增修复需要适配

上游[归档失败保护](https://github.com/YOURSJEYO/claude-switcher/commit/c78939b8485c8e3413b81c85b3046c207c33fb5f)保留中断暂存及旧快照，失败停止切换。本地同时检查目标复制和最终提交失败，保留恢复现场；不运行真实A/B切换验收。

## 本轮实测范围

真实Edge（隔离临时资料、headless、无登录）经独立临时CONNECT中转加载公开HTTPS页面成功。停止临时代理后目标返回`ERR_PROXY_CONNECTION_FAILED`，拒绝CONNECT后返回`ERR_TUNNEL_CONNECTION_FAILED`；按目标请求源ID核对NetLog，均无DIRECT后备。同站点不指定临时代理的curl对照可用，沿用原有网络/TUN，不能称为物理直连证明。TLS证书验证保持启用；临时进程与服务已清理，真实Clash和普通浏览器未改动。

未验证全部DNS/WebRTC、WSS、休眠唤醒、切网及已认证会话的全部运行路径。桌面守护仍有巡检窗口，不能称为系统防火墙。

[官方账号复核说明](https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals)区分账号停用与组织on hold；本地配置不能解除服务端限制。[官方位置说明](https://privacy.claude.com/en/articles/11186740-does-claude-use-my-location)也不支持把IP显示国家当成实际所在地资格证明。
