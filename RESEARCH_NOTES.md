# 公众号结构化接口研究

当前状态：已通过当前登录微信的 CDP 页面会话调用真实接口，读到 236 条账号记录。全选、持久化白名单、清单预览和串行取关队列已接入；真实取关已验证：用户选择的北京森马、比尔盖茨均收到 UnSubscribe:ok，随后查询 IsSubscribed=false。

## 全选、白名单与执行队列

- “全选可取关账号”覆盖全部记录，自动排除白名单及已确认未关注、仅手机端支持的账号；“全选当前结果”只选择筛选结果。
- 白名单默认包含 AI白牙、每天晒白牙，按稳定账号 ID 存储在 `.runtime/whitelist.json`。可单独或批量添加，默认隐藏，也可在白名单筛选中查看和移出。前端禁选、后端清单校验、执行前再校验。
- “生成取关清单”现在显示具体账号和独立的“开始取关”按钮。旧版本只保存文件、在页脚显示一行提示，没有实际执行端点；已修复该流程缺口。
- `wechat_action.mjs` 通过 flat CDP 调用微信页面自身的 `H5ExtTransfer` 5814 / `bizprofilev2h5`，核对返回账号 ID 与 `BaseInfo.IsSubscribed`。查询使用正常页面请求参数及 BaseRequest 占位，由微信补充身份；未导出登录凭据。执行前已实测 AI白牙、北京森马、比尔盖茨处于关注状态。预加载模式下观察到错误的未关注结果，已改成正式页面参数，不能沿用该早期结果。
- 点击开始后逐个调用 `Unsubscribe({userName: ID})`，要求成功回调并重新查询未关注状态。超时、拒绝、状态不一致均暂停；不自动重试不确定的取关动作；用户点击“继续未完成项”后，会重新查询状态，跳过已未关注的账号。后台执行状态保存到 `.runtime/unfollow-job.json`；服务重启不会自动继续队列。
- 点击执行绑定生成时的 `plan_id`；重复执行、失效清单、未知 ID、白名单命中均拒绝。执行期间不可修改白名单；可请求在当前账号处理后停止。

验证：`python3 test_selection.py` 的五个隔离集成测试通过，覆盖来源验证、白名单与失效清单、串行执行、防重复、异常暂停和私有存储；使用模拟执行器，不会修改微信。真实浏览器验证全选 234 项、白名单禁选、原始两个账号清单成功生成并显示执行按钮。真实队列已完成 2/2，两次成功回调与关注状态复核均通过。

## 断线与继续

页面每 3 秒检测本机调试连接。断线时禁用执行，服务端也在消费清单前检查，清单不会因断线作废。恢复小程序连接后可继续原队列，已完成项不会重做。执行日志区分请求尚未发送与发送后状态未知，并记录失败阶段。当前仍需保留腾讯文档小程序窗口；这个版本尚未消除该依赖。

以下为研究过程记录，后文的阶段性“未完成”状态以本文顶部实测结果为准。

## 真实接入成功（2026-09-07 17:24）

- 用户授权后，终端 App 管理权限已开启；受保护脚本应用 helper 临时签名改动，微信重启正常。
- WMPFDebugger 成功附加 build 269136。借已打开的腾讯文档小程序建立调试会话，CDP 找到 SubscriptionDisorder 页面。
- 当前通道需要 flat session；探针已修正为带顶层 sessionId 的 CDP 消息。
- `H5ExtTransfer` 29175 返回 `BaseResponse.Ret=0`，两次均为 236 条记录、236 个唯一 ID，含 10 个名称显示已注销、2 个未返回名称的账号。旧 `GetSubscriptionList` 返回 `system:function_not_implement`。不要据此声称已与通讯录数量完全对齐。
- 数据存于 `.runtime/live-accounts-probe.json`（0600）。`selection_server.py` 在 `http://127.0.0.1:8876/` 提供搜索、勾选及清单保存；没有取关端点。星标可选；两个个人账号默认不参与批量选择。
- 真实页面测试后恢复 236 项、0 已选。后端在隔离的模拟目录验证来源校验、未知/重复账号拒绝和私有保存。没有发送取关调用。

调试过程中需要保留小程序窗口。helper 目前仍为临时签名，原始文件和精确恢复脚本保持可用；详见 `.runtime/helper-signing-change/manifest.json` 与 `../work/wechat-unfollow-feasibility/evidence/live-cdp-verification.json`。

## 已确认

- 微信 4.1.11 内 `wmpf_resources.pak` 可按 Chromium DataPack v5 解析。资源 48266/48268 等含公众号页面。
- 安装包旧页面通过 `WeixinJSBridge.invoke("GetSubscriptionList", {}, callback)` 读取 `subscriptionUserList`；不能把安装包内演示数据当成用户数据。
- 当前用户目录更新包 `udr/subscription/629/main` 为 ZIP。`SubscriptionProfile/home.html` 的 `getAllAccounts` 使用 `H5ExtTransfer`：命令 29175，路径 `/cgi-bin/mmbiz-bin/bizattr/getbizlatestitemlisth5`，scope `subscriptions`，请求 scene 16。身份字段由客户端补充，不需要导出凭据。
- 返回代码使用 `list`，账号字段为 `biz_name`、`nick_name`、`brandiconurl`、`top_flag`。实际覆盖范围仍需实时核验。
- 页面按 `Unsubscribe` / `{userName: 账号ID}` 调用客户端取关；本目录探针不含该调用。
- 最新页面把列表写入 `SavePermanentData` 的 `home_local_data`，对应存储位置已定位，但本机该页面缓存目前未包含此键。

## 无截图读取的实测结果（2026-09-07）

- `inspect_runtime_config.py` 成功校验、解码四份 XWeb MMKV 配置（9、59、17、81 个有效条目）。配置确认当前公众号资源项目是 `ilinkres_9c139286`，对应 `subscription/629/main`。配置中没有 `home_local_data`。
- `inspect_subscription_cache.py` 沿原生 `SavePermanentData` 实现找到按页面项目隔离的缓存。`SubscriptionProfile` 的缓存目前只有版本标记；`SubscriptionDisorder` 的缓存含公众号信息流数据。
- 实测从信息流的 59 组消息中去重得到 **31 个真实缓存账号 ID 和名称**。消息分组数量会随客户端更新；这不是全量关注列表，无法证明当前关注状态，也不能据此直接取关。
- 提取结果仅写入权限 `0600` 的 `.runtime/cached-accounts.json`。不输出缓存密钥、原始文章内容或登录凭据；不写微信缓存，不操作界面，不调用取关接口。
- `inspect_runtime_config.py` 对当前 ARM64 framework 有精确哈希保护。缓存读取脚本仅在找到唯一有效解码结果、CRC 与结构校验通过时输出，版本变化可能使其不可用。

运行缓存检查需 Python 与 `cryptography`：

```sh
python inspect_subscription_cache.py --output .runtime/cached-accounts.json
```

多个本地微信用户目录存在时必须显式传入 `--profile`，避免混合账号数据。当前验证包含：真实缓存读取、CRC 损坏拒绝、截断条目拒绝、账号 ID 去重、私有文件权限及“不完整/不可直接取关”标记。

## 验证与撤回

临时只读探针曾写入上述更新包，原包已备份。因为未确认探针在真实页面中加载，未得到任何接口返回。更新包已恢复并校验 SHA-256 与修改前一致：
`72fcaae304a2088fb36ae1471780d85d7dbded69af5871261f062562a3bc30df`。
本地收集服务已停止，截图验证 App 已关闭。

确认配置映射后再次进行了只读探针试验，仅激活微信并发送一次 Command-R，没有截图或鼠标操作。收集服务仍未收到任何事件；无法区分目标页面未刷新、资源未重读或页面回报被拦截。随后原包再次恢复，SHA-256 核对一致，收集服务已停止。不得把此次尝试记为注入成功。

用户已要求放弃截图扫描作为产品数据来源，后续不得继续借助账号列表截图推进此方案。后续研究应限于页面加载机制、结构化缓存、只读接口与可恢复的脚本接入方式。

## 未完成的关键验证

1. 找到能在正常微信登录会话中运行探针的入口，不依赖截图与坐标点击。
2. 用真实返回核对当前关注数量及完整性，处理公众号与服务号的范围差异。
3. 只有用户明确勾选的稳定账号 ID 才能执行取关，星标不影响可选性。
4. 在测试账号或用户明确选择的账号上验证成功回调和实际关注状态；不可用构建成功或静态调用代码冒充实测。

`patch_probe.py` 是当前机器、当前版本的研究脚本，带精确原包哈希检查和备份；不可直接作为分发产品。再次运行前必须先核对已恢复的记录，不能盲目重复修改。

## GitHub 调研后的新入口

WMPFDebugger 的 macOS ARM64 配置明确支持本机 build 269136，且文档记录了接入微信内嵌网页的方式。已完成代码检查、回环地址限制，以及只读 CDP 账号探针的模拟测试；尚未连接真实微信页面。

`helper_signing_change.py` 默认输出只读计划。必要的 helper 签名变化已在本地副本验证，备份和恢复流程已准备；已安装微信仍保持原样。`cdp_accounts_probe.mjs` 仅供后续只读验证，当前不具备完整列表或取关能力。

详见 `../work/wechat-unfollow-feasibility/report/github-breakthrough.md`。此方案仍有真实调试接入、小程序会话建立、公众号范围与列表完整性待验证，不能将版本匹配当作可用工具。
