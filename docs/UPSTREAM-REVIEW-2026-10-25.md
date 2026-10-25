# 上游与分支内容核对（2026-10-25）

## 发布到哪里

- 用户仓库：[carljings/claude-switcher](https://github.com/carljings/claude-switcher)。
- 本机定制开发与推送分支：[custom/strict-macos](https://github.com/carljings/claude-switcher/tree/custom/strict-macos)。本次检查开始时本地与远端均为`a6fc33edabfcf7b0040759ed207d0175d8a05cc8`。
- 仓库默认分支仍是`main`，指向`179a38bfdb61c834e4e6d044c82308ecf9bf29a6`；打开仓库首页看到的不是定制分支最新代码。此次没有修改默认分支或覆盖`main`。
- 原始上游为[YOURSJEYO/claude-switcher](https://github.com/YOURSJEYO/claude-switcher)，与用户fork分别审阅。

## 上游是否有新提交

本次以Git直接fetch上游`main`，并用GitHub提交比较接口交叉核对。上游HEAD为[`e2da42956bccd39f5e8e2e052c5002b96137f146`](https://github.com/YOURSJEYO/claude-switcher/commit/e2da42956bccd39f5e8e2e052c5002b96137f146)，与上次记录的已审阅HEAD相同，比较结果为`identical`，新增提交数为0。[比较入口](https://github.com/YOURSJEYO/claude-switcher/compare/e2da42956bccd39f5e8e2e052c5002b96137f146...main)。本次开放PR查询没有返回候选。

这是一份检查时点的记录，不是上游以后不再更新的保证。没有为凑更新重复cherry-pick或整包覆盖定制代码。

## 已借鉴的内容

| 上游提交 | macOS定制版状态 | 实现与核对 |
|---|---|---|
| [`c78939b`](https://github.com/YOURSJEYO/claude-switcher/commit/c78939b)：归档失败保护 | 已手工适配，非本轮新增 | [核心归档与切换事务](../core/claude-switch.sh)、[快照测试](../tests/test_snapshot_safety.py)。失败保留现场，且增加`current.new`和跨档案恢复标记检查；本次23项快照隔离测试通过。 |
| [`e2da429`](https://github.com/YOURSJEYO/claude-switcher/commit/e2da429)：归档中断恢复排障说明 | 已有对应、更谨慎的恢复边界 | [AGENTS](../AGENTS.md)与[使用说明](USAGE-SAFETY.md)要求先核对副本，不为重试自动删除暂存或猜测哪份更新。此提交是恢复说明，不是新增运行时代码。 |
| [`a04db61`](https://github.com/YOURSJEYO/claude-switcher/commit/a04db61)：STUN/TURN端口规则 | macOS已适配 | [受管规则脚本](../core/clash-profile-guard.js)前置三端口与四域名UDP拒绝；核心核对真实控制器规则与顺序，不把无响应当零泄漏。 |
| [`4675a35`](https://github.com/YOURSJEYO/claude-switcher/commit/4675a35)：设备信息 | 已适配 | `fingerprint`与界面“设备信息”按需读取字体、GPU和虚拟化线索，不评分、不作为启动门槛。 |
| [`179a38b`](https://github.com/YOURSJEYO/claude-switcher/commit/179a38b)：过期文案清理 | 本轮消除README残留冲突 | README原来仍有“桌面版后续”、覆盖更新及旧界面等说法，按当前实现修正。 |

另针对STUN、规则生成和设备信息，本次5项相关隔离用例通过。以上不是本次全量回归数量，也不等于本机真实账号验收。

Windows/Linux为继承的Beta实现，未同步全部macOS定制及上述三端口加固；不能由“macOS已适配”推断所有平台均已实现。本轮没有扩大跨平台代码修改。

## README与图片核对结果

检查前README上半段已说明定制行为，但下半段仍有旧截图、原始上游安装地址、“全绿才启动”、即时断网保证和每12小时覆盖更新等冲突。本轮修正文案、安装器收尾提示，更新当前布局预览及图片说明，并澄清静态Web页面的第三方请求与隐私文案。

当前界面图基于20261025.1生产视图和隔离示例数据，不能当作实时网络、真实账号或模型权限证明。旧发布记录中的截图保留各自版本含义，不替换成新图后冒充旧版本。

[网络架构图](NETWORK-ARCHITECTURE.md)为本机策略的脱敏示例，三节点、VPS及DNS选择不是源码自带服务，也不是每台机器的安装默认值。VPS双账号仍为历史结构示意，当前运行状态没有远程核验。新图不包含真实出口IP、代理服务器地址、凭据或真实邮箱。

## 本轮验证

- 上游Git fetch与GitHub比较接口结果一致；检查开始时用户远端定制分支与本地HEAD一致。
- 23项快照、5项STUN／规则／设备信息相关隔离用例通过；安装布局11项通过。分别执行，不拼成一次全量回归。
- 16项工件校验和匹配，安装器Shell语法及Git差异检查通过。
- 当前黑白界面图与20261025.1隔离渲染原件哈希一致；两张网络图已目视核对且SVG结构检查通过。
- README及本轮说明的相对链接、示例数据和敏感值检查已执行；没有把历史截图替换后冒充旧版本。
- 未验证此fork的Pages发布状态或Windows/Linux真机行为；不将源码说明当作部署证明。

## 本轮修改范围

本轮是仓库文档、图片、静态Web隐私文案和安装器提示修正，没有新的上游运行时功能待合入。不改本机已安装App、用户态模块、root守护、代理/网络策略、账号或浏览器资料；GitHub分支更新不等于本机重新部署。
