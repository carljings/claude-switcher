# 配置重生成后的严格网络修复

发现两个持久化缺口：Clash Verge Rev 2.4.3的普通Merge只进行深度合并，不展开`prepend-rules`；末尾还会使用应用内存中的基础设置覆盖ipv6，并据此覆盖TUN的DNS IPv6。仅改运行态、基础文件或Merge字段不能证明下一次生成仍生效。

将已授权的订阅末尾脚本配置为工具防护脚本：在每个订阅的规则/节点/组扩展之后，将3个UDP端口与4个STUN域名拒绝规则及已有Claude生态域名置顶；保留其他规则、节点和手动选择。私有策略以`profile_guard_scripts`列出受管脚本文件名。只接管默认空脚本、当前模板或已有所有权哈希匹配的脚本；未知自定义脚本拒绝覆盖。

用户态修复模块保存备份、写入基础IPv6关闭设置并核验当前内核标志；不运行root，不自动切节点或重启网络。提示订阅重生成/Clash重开要求。普通Merge的旧置顶写法不再作为修复成功证据。

本机维修先回放两个真实订阅生成步骤，并通过Mihomo配置检查；再安排独立、有限时的用户态恢复任务，重启Clash读取正确基础设置。实际重生成后核对7条最前置拒绝、IPv6/TUN/模式、固定出口和原有Google/国内网络；完成后撤销恢复任务。失败保留原错误并验证回滚，不能只凭进程启动或文件生成报成功。

服务响应只有在匿名网页403带有明确`cf-mitigated: challenge`标记且匿名API401、传输成功时显示灰色范围说明；未知403、API403、限流和服务端异常仍提醒，传输失败仍阻断。HTTP与账号权限继续分开。Wi-Fi IPv6标签明确本项接口范围，内核IPv6仍由实际路由严格检查。

依据：[Clash Verge合并实现](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.4.3/src-tauri/src/enhance/merge.rs)、[生成顺序](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.4.3/src-tauri/src/enhance/mod.rs)、[TUN DNS设置](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.4.3/src-tauri/src/enhance/tun.rs)、[Cloudflare挑战标记](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)。
