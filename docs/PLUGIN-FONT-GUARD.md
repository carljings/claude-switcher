# 专用浏览器字体过滤组件

版本**20261024.8**（2026-10-24，America/Chicago）起，按用户最新授权，将普通Edge中Site Locale Control的**字体过滤能力**接入专用浏览器。系统字体、真实UA、原生Chicago/en-US、WebRTC限制及固定代理保留；没有完整移植原插件的日期、语言、UA或WebRTC覆盖。

用户已在本机手工确认：切换器底部显示`20261024.8`，从生产专用Edge访问IPPure后，**字体项0分、总分2分**。这是用户手工验收结果，区别于下文自动回归与隔离实验；它不证明所有字体指纹消失或账号权限已验证。

## 能力与范围

- 在Canvas与同一window内OffscreenCanvas的`measureText()`调用期间临时移除名单中的字体family，调用原生方法后恢复`ctx.font`。
- `FontFaceSet.check()`对名单中的字体返回false。字体文件不被删除，也不包装`fillText()`／`strokeText()`；测量值与实际字形可能不一致，因此依赖测量值的PDF／图表排版仍可能受影响。
- Manifest V3静态MAIN脚本，在document_start执行，仅匹配下表六个HTTPS模式；相关about/blob/data iframe按浏览器匹配规则处理。
- 无后台、storage、DNR、privacy或额外API权限。静态内容脚本仍能在所列页面执行，不能把“无额外API权限”说成“没有页面访问能力”。本脚本不读DOM正文、Cookie、token或认证信息，不联网。
- 不覆盖Worker里的独立OffscreenCanvas、所有DOM/CSS测量或所有iframe时序。方法包装和MAIN世界脚本也可能被网页识别或干扰，不是系统级字体隐藏。

| 生产匹配模式 | 范围 |
|---|---|
| `https://claude.ai/*` | Claude主域 |
| `https://*.claude.ai/*` | Claude子域 |
| `https://claude.com/*` | Claude主域 |
| `https://*.claude.com/*` | Claude子域 |
| `https://ippure.com/*` | IPPure主域 |
| `https://www.ippure.com/*` | IPPure的www域 |

生产manifest不含localhost或任意HTTPS通配权限，不向普通Edge复制插件、偏好或登录资料。

## 启动与完整性

组件位于用户态`font-guard`目录。启动器校验manifest、脚本、MIT声明的固定SHA256，只允许该目录的`--load-extension`及`--disable-extensions-except`，拒绝额外加载路径或普通全禁参数混用。缺失、修改或符号链接会拒绝浏览器启动；CLI网络入口不依赖字体扩展。

这是网页测量过滤，不修改代理，也不让检测站分数代表账号权限。每次更新Edge或组件后，应重新检查指定站点的字体项及实际网页功能。旧专用进程不会可靠采用新增启动参数，必须保存页面并退出后重开；仅关窗口但后台仍在时需正常退出该实例。

更改`core/font-guard`文件时，同步`core/protected-access.py`中的`FONT_GUARD_HASHES`，运行相关测试和`scripts/gen-sums.sh`。组件不安装到root守护目录。安装器保存旧组件，最终移动前确认目标仍不存在；移动失败仅在目标仍为空时恢复，遇已检测到的并发未知目标时保留目标和原备份。卸载将组件移至本机备份，不清理浏览器登录资料。

## 验证范围

| 证据类型 | 本轮结果 |
|---|---|
| 自动回归 | 175项Python测试全部通过；14个隔离Swift UI场景通过。App底部版本号来自实际`CFBundleVersion`，未恢复账号状态备注。 |
| 字体算法 | 8项Node VM测试覆盖名单过滤、正常字体、原生异常后的恢复、同realm Offscreen及重复安装等。 |
| 真实Edge隔离对照 | headless和headed都将预置4种Mac字体从可测变为0；Arial测量、`ctx.font`及给定固定绘制场景的像素哈希保持一致；非白名单localhost仍可测4种。 |
| 组件安装故障 | 4项临时HOME测试覆盖正常备份安装、并发目标不被当容器、移动失败后目标变化不向其恢复、目标为空时恢复旧组件。未执行完整安装器或改动真实安装态来制造这些故障。 |
| 用户生产验收 | 用户确认已安装App底部版本`20261024.8`；生产专用Edge的IPPure字体项0分、总分2分。未将此结果称为自动扫描。 |

隔离实验仅对测试manifest增加本机HTTP匹配，生产JS与许可证字节完全一致。这证明相应算法和加载机制，不代替生产HTTPS验收；本轮生产站点结果由用户手工确认。系统字体和普通Edge配置没有改动，实际App继续放在用户Applications，桌面同名入口保留为链接。

本次**没有新增外部检测入口或自动扫描按钮**。这些仍是后续设计，不能因为已有手工IPPure结果就记作20261024.8已经实现。

## 来源

字体名单和实现复用自[LinXiaoTao/FuckClaude](https://github.com/LinXiaoTao/FuckClaude)，原本地包记录提交`bb0015805a4a92a7ed9221693219a69315123aee`。已保留[MIT声明](../core/font-guard/LICENSE)和脚本内来源。生产manifest及脚本见[组件目录](../core/font-guard/)。
