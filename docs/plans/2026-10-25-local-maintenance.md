# 本地资料扫描与维护设计

用户明确选择新版本同时加入专用Edge清缓存、资料重建与Claude本地ID重置。借鉴CCBaga的固定目标、预览与影响说明，保留本分支的私有备份、固定网络入口和故障恢复要求。开发与验收不执行真实资料清理。

## 固定范围

| 模式 | 唯一目标 |
|---|---|
| `cache` | `Claude Protected Edge`内固定缓存白名单；不处理Cookie、密码与书签文件。 |
| `browser-reset` | 整个专用Edge资料目录；先移入私有备份，再建立现有权限基线的新资料。 |
| `desktop-ids` | 当前Claude桌面资料的`ant-did`、`ant-device-registry.json`。 |
| `native-ids` | 预置独立CLI目录`.claude-native-greencloud`内`.user-id`、`.machine-id`与`.claude.json`顶层`userID/machineID/anonymousId`。 |

不存在的候选明确显示未发现，不回退默认`.claude`或其他配置目录。设备ID候选来自参考工具，不保证所有Claude版本都使用这些字段。硬件UUID、钥匙串、OAuth字段、默认GLM与桌面A/B存档不在此功能范围。

## 协议

统一JSON使用`schema_version:1`。预览包含`token/mode/operation/scope/items/item_count/total_bytes/impact/expires_at/can_apply`；时间为Unix秒数，项目仅显示固定相对路径、大小与操作，不显示ID或凭据值。

命令为`preview MODE`、`apply TOKEN`、`backups`、`preview-restore ID`和`preview-recover ID`。恢复与中断恢复也先生成新预览，再由用户确认。执行只接收一次性令牌，不接收任意目标路径。`operation`区分`clean/restore/recover`，`mode`始终为原固定模式。

没有目标时不创建空备份，返回`can_apply:false`。令牌绑定完整文件状态、作用域和有效期；过期、重复使用、预览后变化均需重新扫描。

## 事务与边界

- 所有资料操作要求相关客户端退出，不自动强杀。每次变动前重查进程与文件状态。
- 计划和备份位于用户态私有目录，目录700、私密清单600。仅同卷改名，跨卷拒绝；不引入大目录迁移引擎。
- 拒绝链接、硬链接、特殊文件、不明所有者及并发变化。完整扫描目标树；ID/JSON额外校验内容哈希，不输出内容。
- 修改前准备替换文件/新资料和持久化journal。失败仅在身份与目标位置可确认时回滚，否则保留现场并阻止同作用域启动。
- 恢复先保存当前对应资料为新备份，不覆盖新产生的数据。原生CLI的JSON恢复仅合并三个ID键，保留当前其余配置。
- 专用浏览器/CLI启动、偏好加固与桌面切号参与对应作用域锁。外部直接启动客户端不参与该锁，不能声称彻底消除所有外部竞态。

## 界面

主窗口增加“资料维护”，保留当前大小、底部版本和首屏外部检测。维护页显示范围、影响、预览清单、确认勾选与执行结果；恢复入口采用同样的预览确认。维护期间阻止切号、启动与重复请求；改变模式或备份选择立即废弃旧预览。空、畸形或未知输出不能显示成功。

## 验证标准

用临时HOME与伪进程测试四模式、无目标、过期/重放、文件增改/链接/所有权异常、运行进程、并发执行、每步故障与中断、恢复新数据保存、JSON非ID字段保持，以及备份隐私。UI测试预览不执行、必须确认、状态失效、互斥与错误恢复。原有专用入口、快照事务与14项协议回归继续通过。

参考：[CCBaga固定提交](https://github.com/liseami/CCBaga/tree/bdfb90ceadfc5fae6772ffff597bddecb0b73cc3)。本版不引入其Chromium二进制、UI依赖、钥匙串身份保险库或网络部署Skill。
