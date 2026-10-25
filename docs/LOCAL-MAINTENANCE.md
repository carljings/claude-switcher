# 资料扫描与维护

20261025.2在主窗口增加“资料维护”。它先扫描固定范围，列出可处理项目与影响，再由用户确认执行。扫描不代表已经清理，也不证明所有设备指纹已消失。

## 可以处理什么

| 操作 | 范围 | 影响 |
|---|---|---|
| 专用浏览器缓存 | 专用Edge中的Cache、Code/GPU/Dawn、着色器与Service Worker缓存白名单 | 保留Cookie、密码和书签文件；缓存会重新生成。缓存移入备份后暂不释放对应磁盘空间。 |
| 重建专用浏览器资料 | 独立`Claude Protected Edge`整个资料目录 | 旧资料保存为私有备份，新资料需重新登录；原有固定代理、权限基线和字体组件继续由专用入口应用。 |
| Claude桌面本地ID | 当前桌面资料中的`ant-did`、`ant-device-registry.json` | 仅处理列出的应用标识，客户端可能要求重新验证；旧A/B存档不改，切回档案可能重新带回其中的旧标识。 |
| 独立原生CLI本地ID | 预置`.claude-native-greencloud`目录中的`.user-id`、`.machine-id`及`.claude.json`三个顶层ID字段 | 不自动搜索其他`CLAUDE_CONFIG_DIR`；候选不存在时显示未发现，不回退到默认GLM目录。 |

桌面ID预览与备份绑定当前A/B档案槽位，切换槽位后不能直接套用另一槽位的备份。它不核验服务端登录身份，也不读取账号状态备注。原生CLI维护会保守要求已识别的Claude Code实例退出；未修改其他实例资料。

三个JSON字段是`userID`、`machineID`、`anonymousId`。其他字段保留，不删除OAuth、API密钥、MCP或项目配置。它们是从参考工具借鉴的候选，不代表当前所有Claude版本一定生成或使用这些文件/字段。

本功能不处理硬件UUID、系统字体、真实UA、系统钥匙串、普通Edge资料、默认`.claude`及桌面A/B归档。服务端身份、历史记录与账号权限不会因本地维护自动改变。

## 使用流程

1. 保存工作并正常退出对应客户端，打开“资料维护”，选择范围并预览。
2. 检查项目、大小和影响。没有项目时会明确说明，不能据此推断其他位置不存在标识。
3. 勾选已退出客户端并理解影响，再确认执行。改变模式、资料变化或预览过期后必须重新扫描。
4. 执行完成后查看备份记录。需要撤销时先生成恢复预览，再确认恢复；中断记录使用对应恢复入口。

清理和恢复不会自动启动浏览器或Claude。重新打开时仍执行原有网络、固定IP、权限和组件完整性检查。客户端运行或文件状态不明时停止，不自动强杀来继续。

## 备份与恢复

备份保存在`~/.claude-switcher/maintenance/`的私有目录中，可能包含登录资料、网站数据和配置。不要提交到GitHub、复制进公开安装包或上传日志。这里是本机私有备份，不是另一个加密保险库，也不承诺同用户隔离；它供当前本机恢复，不是跨设备迁移格式。

只允许同卷移动。正常恢复前先保存当前对应资料，避免覆盖清理后新产生的内容；原生CLI JSON只恢复三个ID键，保留当前其他字段。已被恢复消费的旧记录不再作为可恢复备份展示；恢复前保存的新备份可用于撤销该次恢复。

中断恢复是回滚未完成事务；有新资料或状态无法确认时停止，不把它说成已经生成另一份完整备份。发生中断或并发变化时，恢复现场保留并阻止该作用域继续启动。无法确认文件归属时不猜测、不覆盖，按界面提示先核对。通过外部入口直接启动客户端不参与本工具的锁，执行期间应保持客户端关闭。

“升级后只保留最新版App”的清理原则不适用于维护备份与账号资料；卸载也保留这些资料供恢复。

## 命令入口

```bash
claude-switch.sh maintenance-preview cache
claude-switch.sh maintenance-preview browser-reset
claude-switch.sh maintenance-preview desktop-ids
claude-switch.sh maintenance-preview native-ids
claude-switch.sh maintenance-apply TOKEN
claude-switch.sh maintenance-backups
claude-switch.sh maintenance-restore-preview BACKUP_ID
claude-switch.sh maintenance-recover-preview BACKUP_ID
```

`TOKEN`和`BACKUP_ID`由工具返回，不使用任意路径。预览和恢复预览返回新计划，真正执行只有`maintenance-apply`；界面将令牌交给后端前要求用户确认。令牌与备份清单不进入公开日志。备份记录绑定格式版本及固定目标列表；不兼容的范围变化明确拒绝，不猜测旧备份应恢复到哪里。

扫描完整遍历目标，不截断后冒充完整清单。若元数据记录超过当前安全上限，会明确停止；这不会执行清理。

## 来源与本版取舍

参考[CCBaga](https://github.com/liseami/CCBaga/tree/bdfb90ceadfc5fae6772ffff597bddecb0b73cc3)的缓存白名单、应用ID候选和分级预览思路，使用本项目Python/SwiftUI实现。没有引入其第三方UI、Chromium二进制或钥匙串身份管理。

CCBaga的种子轮换依赖Fingerprint Chromium且会清空显式代理字段；本版继续使用原专用Edge和17897固定入口，不把清理资料写成种子轮换或硬件指纹重置。具体合同与验证项见[设计记录](plans/2026-10-25-local-maintenance.md)。
