# 专用浏览器字体过滤交付记录

版本：**20261024.8**。发布日期：2026-10-24（America/Chicago）。本轮按用户后续明确授权，将原Site Locale Control的字体过滤能力接入专用Edge，覆盖20261024.7阶段“不加网页遮罩”的选择；旧决定保留在[截图核对历史](RESEARCH-2026-10-24-USER-SCREENSHOTS.md)，不回写成从未发生。

## 本轮实现

- 只复用字体名单、Canvas／同realm OffscreenCanvas的`measureText()`过滤及`FontFaceSet.check()`处理，没有移植原插件的时区、语言、UA或WebRTC覆盖。
- 生产manifest静态匹配六个HTTPS模式：`claude.ai`、其子域、`claude.com`、其子域、`ippure.com`、`www.ippure.com`。不含localhost或任意HTTPS通配权限，无后台、storage、DNR、privacy或额外API权限。
- 页面脚本仍有在白名单页面执行的能力；已审代码不读取DOM正文、Cookie、token或认证信息，不联网。
- 启动器固定校验manifest、脚本和MIT文件的SHA256，仅允许该目录的两个extension loader参数；缺失、修改、链接或额外加载参数均拒绝。旧专用进程需退出重开，不把新参数视为已自动应用。
- 真实系统字体和Mac UA保留，原生Chicago/en-US、固定专用代理、权限限制及CLI约束沿用。实际App仍位于用户Applications，桌面同名入口为链接，普通Edge和其他工具不安装本组件。
- App底部新增实际`CFBundleVersion`显示。账号状态备注及读取没有恢复。
- 安装器暂存新组件、保留旧备份；最终移动前拒绝已出现的并发目标，移动失败只在目标仍为空时恢复。未知目录不被当作容器。卸载把组件移到备份，不清登录资料。

## 来源与许可

字体名单和实现来自[LinXiaoTao/FuckClaude](https://github.com/LinXiaoTao/FuckClaude)，原本地包记录提交`bb0015805a4a92a7ed9221693219a69315123aee`。已保留[MIT声明](../core/font-guard/LICENSE)及[脚本来源注释](../core/font-guard/font-guard.js)。完整范围与维护方式见[组件说明](PLUGIN-FONT-GUARD.md)。

## 验证证据

| 类型 | 本轮结果 | 不应外推为 |
|---|---|---|
| 自动Python回归 | 175项全部通过；包括8项字体专项和4项组件安装专项，这些已包含在总数内 | 所有网站或所有账号功能均通过 |
| 自动Swift交互 | 14个隔离UI场景通过，未操作真实A/B | 真实账号登录和模型权限已验收 |
| 真实Edge隔离实验 | headless和headed均将预置4种字体从可测变为0；Arial测量、`ctx.font`恢复及给定固定绘制场景像素哈希一致；非白名单localhost仍可测4种 | 全部字体指纹隐藏、所有PDF／图表排版完全不变 |
| 组件安装故障 | 临时HOME／fake命令覆盖正常备份、并发目标、移动失败及安全恢复；没有为测试破坏真实安装态 | 所有可能并发时序都已穷尽 |
| 用户手工版本验收 | 用户确认本机App底部显示`20261024.8` | 自动截图工具已成功抓取真实窗口 |
| 用户手工生产检测 | 用户确认生产专用Edge的IPPure字体项0分、总分2分 | 自动扫描已实现、账号权限已验证或站点分数等于官方风险 |

## 边界与未实现项

字体过滤不删除字体，也不包装实际绘制函数；依赖被修改测量值的布局仍可能改变。Worker里的独立OffscreenCanvas、所有DOM/CSS测量及全部iframe时序未覆盖，MAIN世界脚本可被网页识别或干扰。保持真实Mac UA，不能通过伪装其他系统强行清除剩余分数。

外部检测入口／自动扫描按钮目前仅属后续设计，**20261024.8未实现**。本轮生产IPPure结果来自用户手工访问。账号权限、全部DNS/WebRTC/WSS、已认证CLI全部工具和睡眠／切网等旧有未验范围仍保留，不用本次字体实验替代。

此版本的源码随[20261024.9交付](RELEASE-2026-10-24-EXTERNAL-CHECKS.md)统一提交与打包；不将.9新增入口倒记到.8。整体注意事项及用户操作见[总清单](CLAUDE-SAFETY-CHECKLIST.md)。
