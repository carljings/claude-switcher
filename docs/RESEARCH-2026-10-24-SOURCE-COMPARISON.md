# 微信、Google与GitHub资料交叉总结

日期：2026-10-24，America/Chicago。资料池包括[9篇公众号文章及公开同步稿](RESEARCH-2026-10-24-WECHAT.md)、本页8组新增GitHub一手材料和8项新增Google可追原始来源。之前的YouTube/X线索与访问限制另见[上一轮调研](RESEARCH-2026-10-24-HARDENING.md)。

用户后续提供的两张风控文章截图，另有[逐条核对](RESEARCH-2026-10-24-USER-SCREENSHOTS.md)。

## GitHub新增8组

| 来源 | 具体证据与版本 | 对本轮方案的影响 |
|---|---|---|
| [Claude Code #79223](https://github.com/anthropics/claude-code/issues/79223) | 用户报告`CLAUDE_SECURESTORAGE_CONFIG_DIR`可独立选择Keychain命名空间；2.1.257有复现，作者称2.1.301仍含该变量。本轮未证明2.1.310同样受影响。 | 专用入口移除意外继承的该变量，不设为空、不读取或删除钥匙串；固定现有专用配置目录。 |
| [#92252](https://github.com/anthropics/claude-code/issues/92252)、[维护者说明#27359](https://github.com/anthropics/claude-code/issues/27359) | 2.1.261报告未设/显式设同一默认目录的登录差异；维护者后续明确推荐独立配置目录。两者时间和环境不同。 | 保留现有已工作的专用路径，不为格式统一改路径字符串或尾斜杠。不把旧问题泛化为当前完全没有隔离。 |
| [Sandbox Runtime #188](https://github.com/anthropics/sandbox-runtime/issues/188)、[PR #530](https://github.com/anthropics/sandbox-runtime/pull/530) | `allowLocalBinding`曾同时放开广泛loopback出站；提案改成按端口。开放PR不等于已经发布。 | 本轮仅允许一个TCP代理端口，不使用localhost任意端口；子进程和UDP另测。 |
| [Sandbox Runtime #599](https://github.com/anthropics/sandbox-runtime/issues/599) | macOS 26.6.2、srt 0.0.67/77报告本地`com.apple.netsrc`kernel-control被记作network-outbound拒绝；有最小复现，不是公网连接。 | 拒绝日志不自动等于泄漏。没有该故障时不追加宽泛放行；有故障须隔离复现精确规则。 |
| [Sandbox Runtime #606](https://github.com/anthropics/sandbox-runtime/issues/606) | 0.0.75/77报告CONNECT中转关闭时丢失未刷完的数据，有大响应对照和补丁。 | 本轮使用Mihomo而非该中转实现，不搬无关补丁。提醒HTTP状态、完整响应和业务成功分开，大响应可增加哈希验证。 |
| [Claude Code #81611](https://github.com/anthropics/claude-code/issues/81611) | 2.1.220启动预检不认代理而API可通；维护者说明2.1.222修复为proxy-aware transport。 | 当前2.1.310高于修复版本，不关闭预检或降级；仍分别测CLI、浏览器和匿名探针。 |
| [Mihomo #2293](https://github.com/MetaCubeX/mihomo/issues/2293) | macOS案例中网关DNS未接管，贡献者说明不透明代理LAN是预期行为。 | TUN/Fake-IP不代表全部DNS已验证；保持用户公司内网，改用专用HTTP入口约束专用请求。 |
| [Mihomo #3281](https://github.com/MetaCubeX/mihomo/issues/3281) | macOS 27、v1.19.32/Alpha报告重载204后fake-IP映射变化，有独立复现。 | 不证明本机v1.19.15同样有问题；真实重生成后仍需检查DNS、普通联网与路径，不能只看toast。 |

[Sandbox Runtime官方说明](https://github.com/anthropics/sandbox-runtime#readme)还指出Apple Events/LaunchServices可能启动沙箱外应用。本轮CLI追加拒绝`appleevent-send`和`lsopen`；本机内核检查两操作均拒绝，未为了测试去打开用户应用。OAuth自动开浏览器将受限，用户需要把官方登录URL手动放进专用浏览器。本层仍不宣称隔离全部Mach broker、继承文件描述符或文件持久化。

## Google追到的8项原始材料

| 来源与日期依据 | 核对到的内容 | 采用或保留的边界 |
|---|---|---|
| [Claude身份验证](https://support.claude.com/en/articles/14328960-identity-verification-on-claude)，页面标2026-08-11 | Persona身份/企业验证可能需要实体证件及手机自拍，验证完成后仍适用账号政策。 | 与网络检查分开。默认拒绝摄像头会阻止部分正常验证流程，不能声称极严权限下所有功能仍可用。 |
| [Claude年龄验证](https://support.claude.com/en/articles/15171100-age-assurance-on-claude)，页面标2026-05-18 | Yoti年龄核验与Persona身份核验不同，部分年龄问题有对应恢复流程。 | 区分身份验证、年龄验证、组织on hold、账号停用和网络错误。 |
| [Tor官方指纹防护说明](https://support.torproject.org/tor-browser/features/fingerprinting-protections/)，本轮读取 | HTTP/JS UA不一致可能触发检测；任意伪装系统会增加独特性，不能覆盖所有上下文。 | 保留默认UA/真实硬件，限制权限和额外请求，实际核对语言与Intl。 |
| [Ethan Zhao使用经历](https://www.yizhe.me/blog/202604/my-experience-using-claude/)，页面April 2026 | 自述不使用住宅IP/指纹浏览器也有活跃账号；支付变化后的封禁归因仍是个人推测。 | 是“某配置必封/必稳”的反例线索，不是机房IP普遍安全的证明，不采用其跳权限或地区付款做法。 |
| [Anthropic透明度报告](https://www.anthropic.com/transparency/system-trust-reporting)，页面标2026-07-23 | 提供平台封禁、申诉与推翻决定的汇总数。 | 平台总量不是单个用户封号概率，不能给本机生成保号分。 |
| [Apple Private Relay技术说明](https://developer.apple.com/icloud/prepare-your-network-for-icloud-private-relay/)，本轮读取 | 覆盖Safari、DNS及部分HTTP流量，粗位置与会话稳定性有自身规则。 | 不等于全机固定美国代理；不为Claude专项加固全局关闭其他浏览器的隐私功能。 |
| [Sign in with Apple邮箱域通知](https://developer.apple.com/news/?id=1ptvdtcm)，2026-08-24 | 新隐藏邮箱域与旧域可并存。隐藏邮箱与网络Private Relay是两种机制。 | 邮件/登录匹配故障不自动判定为IP泄漏；本机邮箱标签不应限制为旧域。 |
| [EFF测试方法](https://coveryourtracks.eff.org/about)，本轮读取 | 指纹唯一性比较其测试样本，模拟跟踪行为；删除Cookie不能清除所有指纹。 | 测试站分数不是Claude阈值，不能为降分删除用户资料。 |

另有[Private Relay受限个案](https://www.reddit.com/r/claude/comments/1txvjqu/claude_account_revoked_after_using_icloud_private/)与[隐藏邮箱登录循环#66123](https://github.com/anthropics/claude-code/issues/66123)。前者没有平台确认归因，后者是登录路径问题，都不能直接变成本地网络故障条件。

## 横向总结：哪些最值得做

1. **固定出口与进程约束是两层**：专用Mihomo入口避免第三方目标走通用DIRECT；CLI单端口TCP限制再阻止自身或子进程绕过代理。Edge外层系统沙箱已实测冲突，保留其原有沙箱。
2. **一致信号比零散覆盖更可核对**：系统Chicago/en_US、专用请求语言、navigator/Intl和固定出口分别测。默认拒绝定位、音视频、传感器、字体API与预加载减少暴露；不伪造精确坐标或硬件。
3. **认证来源有独立风险**：继承环境、配置目录和凭据库命名空间可影响实际身份。仅在专用入口清理意外覆盖，保留普通入口，不读取登录态来做匿名“保号检测”。
4. **历史代码、实际传输与服务端决策不能混同**：多篇微信文章追到同一旧版研究，不能累计当成独立证据，更不能直接推断当前2.1.310。
5. **缺证和已证实故障都能严格阻止，但理由要分别记录**：本轮用户选择两次warn也停止桌面进程；普通信息项仍明确范围，不把人工备注或住宅标签当独立验证。
6. **功能代价要公开**：专用音视频/定位、部分官方验证、CLI自动开浏览器及子进程直连会受限。普通浏览器、内网和普通开发入口保留。

本页记录调研结论及代码选择，真机部署结果需要另行核对，不用来源描述替代运行验收。
