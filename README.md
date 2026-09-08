# 公众号整理

一个在 Mac 本机整理微信公众号关注列表的自由软件。它可以读取当前微信账号的公众号列表，按名称或账号 ID 搜索，批量选择、维护白名单、生成取关清单，并在再次确认后逐个执行和复核。最近 30 天的取关记录可以用来恢复关注。

> 当前版本仅支持 **Apple Silicon**（M1、M2、M3、M4 及后续同架构芯片），**不支持 Intel Mac**。目前只验证了 macOS 26.6.2、微信 4.1.11 与 WMPF build 269136 的组合。

这是非官方实验性工具，与腾讯、微信没有关联，也没有得到其认可。它依赖调试接入和微信辅助程序签名调整，可能因微信升级失效，也无法保证平台账号零风险。请只处理你自己的账号，并先少量测试。

## 为什么列表还在，却提示打开小程序

应用会把上次成功读取的公众号列表保存在本机，所以实时连接断开后，你仍然可以搜索、筛选、维护白名单和生成清单。真正执行取关或恢复关注时，需要重新打开一个微信小程序来恢复实时连接。界面会把这两种状态分别标为“本机缓存列表”和“实时连接已建立”。

## 使用流程

1. 登录微信并打开公众号页面，启动应用并查看兼容性检查。
2. 点击“开始连接”，在微信左侧进入小程序列表，再打开任意一个小程序的内容页。只停在小程序列表不够；使用期间请保持该窗口打开。
3. 搜索或选择账号，把重要账号加入白名单，然后生成取关清单。
4. 核对清单后点击“开始取关”。应用串行处理，每完成一个账号都会立即查询并复核结果；不确定时会暂停，不会继续盲目执行。
5. 在“取关记录 / 恢复关注”中查看最近 30 天的记录。恢复关注后默认加入白名单。

退出应用会停止后续队列，并等待当前账号完成复核。不会退出微信。

## 数据与安全边界

- 不读取聊天数据库内容。应用通过微信当前打开的数据目录识别本机账号，并用哈希作为隔离目录。
- 白名单、选择、清单和日志按账号与微信进程会话隔离；切换账号或重启微信后，旧清单不能直接执行。
- 本地网页服务和 CDP 控制连接只监听回环地址，CDP 客户端需要每次启动生成的随机令牌。
- 数据保存在 `~/Library/Application Support/com.baiya.WeChatOrganizer`，不会写入仓库或安装包。
- 环境准备和恢复都需要你明确点击并接受 macOS 管理员授权；版本或文件指纹不匹配时拒绝修改。

## 从源码构建

需要 Apple Silicon Mac、Swift 5.9+、Python 3.13.1、Node.js 23.6.0 和 npm。首次构建先安装固定依赖：

```sh
python3 -m venv .build-env
.build-env/bin/pip install pyinstaller==6.22.2
npm ci --prefix third_party/WMPFDebugger
```

然后构建应用或运行测试：

```sh
./script/build_and_run.sh --build-only
python3 -m unittest -v test_guards.py test_selection.py
```

构建结果位于 `dist/公众号整理.app`。当前使用 ad-hoc 签名，尚未完成 Developer ID 签名与 Apple 公证。应用包内的 `Contents/Resources/Source` 保存与该二进制对应的完整源码，`Contents/Resources/Licenses` 保存第三方许可证。

## 支持范围与升级策略

支持矩阵和微信组件 SHA-256 位于 [`compatibility.json`](compatibility.json)。未知版本不会尝试接入，也不会自动降级微信或关闭系统保护。每次新增兼容版本都应重新验证列表读取、账号隔离、白名单、取关回执、结果复核、恢复关注和中断恢复。

WMPFDebugger 固定在提交 `1d9f6e03a24dcd39baa223e25a883a85b84bd303`，源码位于 [`third_party/WMPFDebugger`](third_party/WMPFDebugger)。本项目对它所做的修改记录在 [`MODIFICATIONS.md`](third_party/WMPFDebugger/MODIFICATIONS.md)。

## 许可证

本项目按 [GNU GPL v2.0 only](LICENSE) 发布。你可以使用、研究、修改、再分发，也可以收费分发，但分发受 GPL 约束的二进制或修改版本时，必须继续向接收者提供相应源码和同等自由；不要把“收费”误写成“闭源授权”。

第三方组件、版本、版权与许可说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。其中：

- [WMPFDebugger](https://github.com/evi0s/WMPFDebugger) 使用 `GPL-2.0-only`；
- 上游 README 声明 `src/third-party` 中的代码来自微信开发者工具、版权归腾讯控股有限公司；该声明在本仓库中原样保留；
- Frida、Node.js、Python、PyInstaller、protobufjs 和 ws 仍分别受各自许可证约束。

GPL 允许商业分发，但这不等于获得腾讯或微信的商标、平台接口或相关代码授权。若准备收费、投放广告或大规模公开分发，建议先让熟悉开源软件和平台条款的律师审阅。

## 致谢

核心调试通道基于 evi0s 及贡献者维护的 [WMPFDebugger](https://github.com/evi0s/WMPFDebugger)。感谢上游作者公开研究成果。

历史探索记录见 [`RESEARCH_NOTES.md`](RESEARCH_NOTES.md)。
