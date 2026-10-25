# Claude专用链路：资料、采用理由与本机实验

日期：2026-10-24，America/Chicago。用户本轮选择“Claude专用链路最严，保留普通浏览器、公司内网和其他开发工具”。前一轮四个平台的检索记录及YouTube/X访问限制见[增量调研](RESEARCH-2026-10-24-HARDENING.md)，本轮新增公众号文章与实际阅读范围见[微信资料核对](RESEARCH-2026-10-24-WECHAT.md)。

追加调研的8组GitHub、8项Google来源与主题比较见[多来源总结](RESEARCH-2026-10-24-SOURCE-COMPARISON.md)。

## 来源与决策

| 原始资料 | 能确认的结论 | 本轮决策 |
|---|---|---|
| [Mihomo listener文档](https://github.com/MetaCubeX/Meta-Docs/blob/main/docs/config/inbound/listeners/index.en.md) | 独立HTTP入口可以指定代理，避开通用规则 | 增加仅loopback监听的专用端口，直接绑定具体锁定节点；需隔离实例与实际入站证据验证 |
| [Edge默认定位权限](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/DefaultGeolocationSetting) | 可拒绝网站定位请求 | 专用Profile拒绝并检查既有允许例外；不伪造GPS坐标 |
| [Edge Local Fonts权限](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/DefaultLocalFontsSetting) | 可拒绝Local Fonts API，URL例外可能覆盖默认 | 专用Profile拒绝该API；不能据此宣称CSS字体测量全部消失 |
| [Chromium权限键生成](https://raw.githubusercontent.com/chromium/chromium/main/components/content_settings/core/browser/website_settings_info.cc) | 默认项和站点例外使用不同存储前缀，名称连字符转换成下划线 | 同时检查默认拒绝和相关普通/partitioned例外，不只写默认键 |
| [Chromium语言定义](https://raw.githubusercontent.com/chromium/chromium/main/components/language/core/browser/pref_names.h)、[开关定义](https://raw.githubusercontent.com/chromium/chromium/main/chrome/common/chrome_switches.h) | Accept-Language由selected/forced语言派生；命令行有accept-lang | 设置专用英文语言，核对强制语言，真实页面同时看请求头、navigator和Intl |
| [Edge网络预测](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-browser-policies/networkpredictionoptions)、[Chromium枚举](https://chromium.googlesource.com/chromium/src/+/HEAD/chrome/browser/preloading/preloading_prefs.h) | 可关闭预测/预加载 | 专用Profile关闭；不是所有后台网络的总开关 |
| [Edge URL级WebRTC](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/WebRtcIPHandlingUrl)、[全局策略](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/WebRtcLocalhostIpHandling) | URL首个匹配可能覆盖全局IP处理策略；disable_non_proxied_udp不是完全关闭RTCDataChannel | 检查已知受管策略冲突，保留代理UDP限制与QUIC关闭；不宣称彻底关闭WebRTC |
| [Edge后台模式](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/BackgroundModeEnabled) | 该策略在macOS不支持 | 不写无效键来充当已验证防护 |
| [Microsoft MXC Seatbelt实现](https://github.com/microsoft/mxc/blob/main/docs/backends/seatbelt/seatbelt-backend.md)、[Anthropic Sandbox Runtime](https://raw.githubusercontent.com/anthropics/sandbox-runtime/main/README.md) | 进程网络可约束为本机代理端口，子进程有继承范围 | CLI增加经本机实验验证的TCP-only限制；系统接口已弃用，不能当长期支持承诺 |
| [Apple DTS说明](https://developer.apple.com/forums/thread/661939)、本机sandbox-exec手册 | sandbox-exec与SBPL不是第三方长期受支持的接口 | 缺失/失败拒绝，不静默退回无沙箱 |
| [Chromium macOS沙箱边界](https://chromium.googlesource.com/chromium/src/+/main/sandbox/mac/README.md) | 子进程、继承FD与系统broker有不同边界 | 不把网络沙箱说成所有IPC或所有应用的全面隔离 |
| [LuLu官方](https://objective-see.org/products/lulu.html)、[过滤源码](https://raw.githubusercontent.com/objective-see/LuLu/v4.5.3/LuLu/Extension/FilterDataProvider.m) | 免费开源出站过滤，需要系统扩展/网络过滤器授权，存在明确范围和允许路径 | 不在本轮直接给共用Edge二进制加全局封锁；需先设计可靠进程树区分与故障验收 |
| [Little Snitch兼容性](https://www.obdev.at/products/littlesnitch/releasenotes.html)、[规则](https://help.obdev.at/littlesnitch6/lsc-edit-rules)、[demo限制](https://help.obdev.at/littlesnitch6/intro-whatis) | 稳定6.5支持macOS27；demo会定期停用过滤 | 不把试用当持续断网保护；本轮不购买或安装 |

## 本机已完成的隔离可行性实验

- 无沙箱时两个临时HTTP端口均可达；Seatbelt只放行指定localhost TCP端口时，另一端口被PermissionError拒绝。
- 经Shell执行的子进程同样受限制；TCP-only策略拒绝UDP。通过允许的HTTP代理访问HTTPS成功，保留TLS校验；绕过代理直接访问同目标失败。
- 模拟OAuth本机HTTP回调可监听并响应；原生CLI在隔离HOME下执行`--version`正常，未调用已认证账号。
- 独立Edge加普通代理可用，但套外层Seatbelt后退出-5，报告自身沙箱初始化失败。因此不给Edge套外层sandbox-exec，不用`--no-sandbox`强行启动。
- `remote ip`在本机只接受localhost或通配地址，不能写任意127文字；且它可能允许同端口UDP，本轮选择更窄的`remote tcp`。

这些是功能与故障实验，不证明完整认证、MCP工具、全部DNS/WebRTC、休眠和切网都通过。专用链路部署后的最终结果另行记录；尚未完成的步骤不能用资料中的能力描述冒充本机验收。

## 与“芝加哥使用者”的关系

可控的系统时区、地区、语言和专用请求出口会统一核验；定位权限拒绝减少精确位置暴露。本地这些信号不能证明实际所在地，也不代表账号地区资格或解除服务端限制。设备硬件和UA保持真实，保留普通软件与内网用途。
