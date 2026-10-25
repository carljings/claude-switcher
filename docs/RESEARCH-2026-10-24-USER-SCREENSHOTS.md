# 用户提供的两张风控文章截图核对

日期：2026-10-24。截图1没有明确原始出处；截图2是转发画面，署名`@Abelnadp`，原帖及发布时间尚未独立核验。以下分析只针对截图可见文字，不把作者自述作为已确认的服务端规则；不把手机界面或附件本身提交到仓库。

本文件保留决定发生的先后顺序。下文“不加网页遮罩”是20261024.7阶段的取舍，已被后文20261024.8的明确授权覆盖；系统字体和真实UA始终保留。

## 截图1：技术能力与封禁推断混在一起

| 主张 | 核对结果 | 依据与本轮处理 |
|---|---|---|
| Cloudflare能观察IP/ASN、TLS指纹与TCP RTT | 有这些公开技术能力；不能据此确认Anthropic采用截图的全部五维模型及权重 | [请求字段](https://developers.cloudflare.com/workers/runtime-apis/request/)、[JA3/JA4](https://developers.cloudflare.com/bots/additional-configurations/ja3-ja4-fingerprint/)。继续用真实连接证据，不给本机编造厂商风控分。 |
| 美国IP但160–240ms就标`Suspected_Remote_Proxy` | 本轮未找到该统一标签和阈值的官方依据；不同延迟测量不能混同，固定时延也不能唯一定位中国 | TCP代理建立用户到代理、代理到目标的连接；服务端TCP RTT与端到端TLS/应用响应时间不同。不把延迟阈值写成封禁判据。 |
| 普通代理必然改变ClientHello/JA3/JA4 | 不准确。标准CONNECT隧道可以双向透传原始字节；TLS终止/重签、另建TLS会话是另一种机制 | [RFC 9110 §9.3.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.3.6)。保持官方客户端和TLS校验，不加中间人证书或伪造TLS栈。 |
| 检出微软雅黑、宋体、苹方就证明人在中国 | 字体可参与指纹，但不能单独证明所在地；macOS官方字体清单本身就有PingFang SC | [Apple字体清单](https://support.apple.com/en-euro/127491)、[MDN指纹说明](https://developer.mozilla.org/en-US/docs/Glossary/Fingerprinting)。拒绝专用浏览器Local Fonts API，保留系统字体；CSS测量仍有边界。 |
| 中文语言/时区可被读取 | 可以。被读取、实际发送、用于具体账号处理是不同结论 | 保留用户选择的Chicago/en-US严格基线，实测请求语言、navigator和Intl，不凭文章推断因果。 |
| 换时区可以掩盖NTP或毫秒时钟差 | 时区只改变本地显示/解释偏移，不改变UTC绝对时间；时钟误差与时区是不同变量 | 不改变真实系统时钟或关闭时间同步来追求伪装，避免破坏TLS、认证和日志时序。 |
| AVS核对账单地址与IP | 解释错误。AVS主要核对账单街道/邮编与发卡行记录；IP一致性是另一信号 | [Stripe验证说明](https://docs.stripe.com/disputes/prevention/verification)。不根据截图编造支付资料。 |
| 中国BIN、虚拟卡、IP国不一致会默认整段封禁 | Stripe存在相关字段及商户可选规则，不能推出Anthropic采用了同一策略，也不能把所有虚拟卡等同预付卡 | [Stripe规则参考](https://docs.stripe.com/radar/rules/reference)。支付资格和本地网络分别处理，不添加伪造支付或身份逻辑。 |
| 中文问题、中文专业术语和北京时间作息会直接认定地区 | 服务端可看到提交的内容与请求时间；截图未提供其对应封禁阈值或用途证据 | 不改写用户业务代码、强制翻译全部内容或模拟上下班行为。专用网络、配置与权限层继续严格。 |

## 截图2：一致性有用，具体门槛仍是经验

- 固定出口、检查不同入口是否串线、保护账号和凭据控制权，都是可以落实并验证的维护措施。
- “邮箱使用一周、Google优先、当天注册当天订阅是红线、礼品卡更稳”在截图里没有官方规则、对照实验或完整样本记录。
- “12个被封、近30个短期存活”是作者自述，不能区分IP、支付、验证、共享行为及其他变量，也不能推算长期保号概率。
- “时区完全没用”同样超出该经验能证明的范围。它不能推翻用户偏好，也不能反证客户端不读取时区；本机继续保留Chicago严格基线。
- “100%质保都是骗子”是作者判断；平台账号绝不被限制的保证缺少依据，卖方合同中承诺退款则是另一件事，不能混为同一结论。

## 对本次实现的影响

保留固定具体出口、专用端口、权限默认拒绝、Chicago/en-US一致信号和失败阻断。新增严格项要有本机证据，不将截图里的延迟数字、邮箱天数、中文字体或作者存活样本直接写成核心通过/失败条件。

## 后续专用浏览器检测截图

用户后续提供的检测图显示：Chicago、浏览器英文、en-US区域格式和UTC−5均为零加分；Canvas字宽仍检测到PingFang、Hiragino Sans GB、STHeiti、STSong等字体，被该站自定加20分；依据UA推断的Apple风格加2分。该权重来自检测站，不是已确认的Claude评分。

拒绝Local Fonts API不能阻止所有CSS／Canvas字宽推断，两者不能混称。本机实际权限查询为denied，但没有声称测量层字体不可见。Apple风格与中文字体本身也不能证明中国所在地。

已向用户说明自有脚本遮罩的PDF／图表兼容风险、修改痕迹及Worker／iframe覆盖边界。用户明确选择：**保留真实Mac字体，维持已验证的权限防护**。因此本轮不加站点字体遮罩，不修改UA为其他系统，不删除系统字体；该项是明确取舍，不是遗漏或伪报通过。

以上为当时的阶段性决定，不代表随后版本一直禁止字体测量过滤。

追加核对没有找到受支持的Edge按Profile字体白名单或`measureText()`禁用选项。[Chromium开关](https://github.com/chromium/chromium/blob/main/content/public/common/content_switches.cc)里的`--disable-reading-from-canvas`限制像素读取，不能据此宣称封锁字宽；`--disable-remote-fonts`限制远程字体，不能当作本地字体隐藏。[Canvas实现](https://github.com/chromium/chromium/blob/main/third_party/blink/renderer/modules/canvas/canvas2d/base_rendering_context_2d.cc)与[内容脚本覆盖范围](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts)分别说明了这些边界。

本机Edge156隔离试验能通过侧载参数注入无权限localhost测试标记扩展，与通用工具文档的限制描述存在差异；但没有实现或在真实Profile加载字体遮罩。所有该试验临时进程与资料已清理，不能把“能加载测试扩展”写成字体防护已完成。

## 20261024.8：后续授权与生产验收

用户随后比较普通Edge与专用Edge：普通Edge通过此前的Site Locale Control取得总分2、字体项0，专用Edge禁扩展且保留原生测量，字体项加20。两种配置的字体测量策略并不相同，不能用专用出口的强度来否认这一实在差分。

用户继而明确要求给专用浏览器“加上这个插件或者插件的能力”。新授权覆盖先前不加网页遮罩的选择。本轮只复用[最小字体过滤能力](PLUGIN-FONT-GUARD.md)，没有完整移植原插件的日期、语言、UA或WebRTC覆盖；真实系统字体、Mac UA、原生Chicago/en-US与固定代理仍保留。

本次证据分开记录：

| 证据 | 结果与范围 |
|---|---|
| 自动回归 | 175项Python测试、14个隔离Swift UI场景通过。包括字体算法、三文件完整性、额外loader拒绝、旧进程参数拒绝和组件安装竞态等。 |
| 真实Edge隔离实验 | headless／headed中预置4种字体从可测变为0；正常字体测量、font恢复及给定固定绘制场景像素哈希不变；非白名单localhost仍可测4种。测试manifest的localhost匹配不进入生产配置。 |
| 用户手工生产验收 | 用户确认切换器底部版本为`20261024.8`，生产专用Edge访问IPPure后字体0分、总分2分。这不是自动截图或自动扫描结果。 |

生产组件仅匹配六个Claude／IPPure HTTPS模式，静态MAIN脚本不读正文、Cookie、token或认证信息、不联网。它仍是可被站点识别或干扰的页面层测量补丁，不覆盖全部Worker、DOM/CSS或iframe时序；测量与真实字形不一致仍可能影响PDF／图表布局。源码沿用MIT声明，范围和维护要求见组件说明。

本次未新增外部检测入口或自动扫描按钮；这些属于后续设计，不能计入20261024.8已实现能力。该站分数也不等于Claude账号权限或服务端风控结论。
