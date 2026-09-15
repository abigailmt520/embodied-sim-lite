# docs/audit_pack_spec.md — 审计包格式与哈希链规范（Audit Pack Spec）

规范版本：v1.0.1 ｜ 2026-09-15（v1.0.0＝2026-09-08 FORGE-003 任务六卡 A：校验与汇总侧；**v1.0.1＝FORGE-004 任务六卡 B，PATCH：产生侧入仓并成文 §9，包格式与哈希链零变化；补定两处边界口径（§4 `incomplete`、判定早于起爆），发生在任何数据采集之前**）
本文件 **= 现状快照**：只成文本仓已实现的格式与口径，不含计划与愿望。与代码不符处以代码为准，并以 PATCH 修订本文件。

> **实现状态**：校验与汇总侧＝`audit_chain.py`、`tools/audit_tools/`（v1.0.0 起）；
> **产生侧＝`experiment_mode.py`（v1.0.1 起，FORGE-004）**，经 `inference_server.py` 的实验模式开关接入，**默认关闭**，
> 关闭态与接入前逐字节一致（§9）。两侧共用 `audit_chain.py` 同一套字节级口径，杜绝漂移。
>
> 本文件**不是**教学实验设计文件。课程执行脚本、评分、伦理告知与研究设计属课程与论文线材料，不在公开仓。

---

## 1 审计包结构

一个审计包 = `{uid}_{session_id}.zip`，含四项：

| 条目 | 内容 |
|---|---|
| `audit_log.jsonl` | 事件日志，一行一事件，**带链式哈希**（§2） |
| `summary.json` | 机器可读的会话结论（判定/真值/时延等，§4） |
| `MANIFEST.json` | 总哈希、行数、平台版本、时钟基准、生成时刻（§3） |
| `screenshots/` | 截图，文件名须与日志中的 `SCREENSHOT` 事件**逐一对应** |

时间一律用**平台单一时钟**，毫秒级 ISO 8601；不采用客户端时间。

## 2 事件日志与哈希链（`audit_chain.py` 即规范的唯一实现）

```
core       = {ts, session_id, uid, event, payload}          # 五字段，缺一不可
core_json  = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
line_hash  = SHA256(prev_hash + core_json) 的十六进制
存盘行     = core 五字段 + prev_hash + line_hash（同一规范化序列化）
创世 prev_hash = 64 个 '0'
```

**规范化序列化是哈希的唯一输入形式**——`sort_keys=True` 与紧凑分隔符缺一不可，否则同一内容会算出不同哈希。
写入侧与校验侧**必须**共用 `audit_chain.py`，不得各自实现。

事件类型（`event` 取值）：`SESSION_START`｜`INJECT`（注入真值，学生端不可见）｜`TELEMETRY`｜`SELF_TEST`｜`STUDENT_VERDICT`｜`SCREENSHOT`｜`SESSION_END`。

**两侧必录**：注入真值与学生行为都必须在同一条链上——检出率与时延**由日志重算，不采信自报**。

## 3 MANIFEST 字段

`total_hash`（末行 `line_hash`）｜`lines`（有效行数）｜`chain_ok_at_export`｜`platform_version`｜`clock_basis`｜`generated_at`。

## 4 summary 复算口径（`audit_chain.derive_summary`）

| 字段 | 口径 |
|---|---|
| `condition` | 日志中有 `INJECT` 即为该注入类型；无 `INJECT` 视为健康轮 |
| `final_verdict` | 以**最后一次** `STUDENT_VERDICT` 为准 |
| `hit` | 注入轮、最终判定为 `abnormal`，且判定时刻**不早于** `INJECT` |
| `localization_correct` | `hit` 且判定的 `checkpoint` 与注入类型一致 |
| `false_alarm` | 健康轮（非 `incomplete`）且最终判定为 `abnormal` |
| `detect_latency_ms` | 判定时刻 − `INJECT` 时刻，**仅命中轮** |
| `incomplete` | 日志无 `INJECT`，但 `SESSION_END.payload.assigned_condition` 为注入类型（会话在起爆前被导出或结束）：`condition` 取分配条件，`hit`／`false_alarm` 均为假，**汇总时剔除**（v1.0.1） |
| `verdict_before_onset` | 注入轮的最终判定早于 `INJECT`：不计命中、不算时延，仍计入该类发现率分母（v1.0.1） |

`verify_pack.py` 用同一函数从日志独立复算，与包内 `summary.json` **逐字段比对**；
`platform_version` 等附注字段不参与比对（`CHECK_FIELDS` 为准；v1.0.1 起含 `incomplete`、`verdict_before_onset`）。

## 5 汇总指标口径（`tools/audit_tools/analyze_packs.py`）

- **发现率** = 注入轮中报告异常的比例
- **定位准确率** = 报异常的注入轮中检查点点名正确的比例
- **误报率** = 健康轮中报告异常的比例
- **检出时延** = 判定时刻 − 注入 onset，只对命中轮计算，报**中位数[四分位距]**（分布右偏，不用均值）
- 比例的 95% 置信区间一律 **Clopper–Pearson 精确区间**（纯 Python 实现，无 scipy 依赖）
- **`incomplete` 会话**（§4）不进任何比例与时延，单列 `n_incomplete_excluded`；判定早于起爆的会话单列 `n_verdict_before_onset`（v1.0.1）

**指标先于数据定稿**：本规范连同公式入仓，日期即存证——从根上免疫「事后挑数据」。

## 6 三个标准自检动作（`SELF_TEST.payload.action`）

| action | 含义 |
|---|---|
| `slip_zero` / `slip_restore` | **退化检验**：把 slip 归零，验证里程计是否退化为真值 |
| `feed_cut` | **报警器自检**：主动断流，验证告警是否真的响——审计报警器自身也要被审计，「绿灯常亮」可能只是灯坏了 |
| `seq_probe` | **残差交叉**：核对残差走势与帧序号单调性，不依赖面板结论 |

## 7 校验与汇总用法

```bash
python tools/audit_tools/verify_pack.py <审计包.zip 或目录>   # 逐包：哈希链 + MANIFEST + summary 复算 + 截图对账
python tools/audit_tools/analyze_packs.py <包目录>            # 汇总 → audit_summary.json + receipts.csv
python tools/audit_tools/selftest.py                          # 红测：合法包判绿、篡改包判红（离线，不需服务端）
python tools/audit_tools/exp_selftest.py                      # 产生侧离线红测：注入语义、会话隔离、密钥纪律、导出包判绿
python tools/audit_tools/simulate_sessions.py --verify        # 端到端：对开启实验模式的服务端跑 3 个定向会话并核对复算结论
python tools/paper_figures/make_paper_figures.py --audit-json audit_summary.json
```

`verify_pack.py` 退出码：全部通过 `0`，任一失败 `1`。

## 8 红测纪律

校验器**必须能红**。`selftest.py` 用 `make_fixture_pack.py` 离线造包，覆盖五种篡改面：
改事件内容、改 `line_hash`、断 `prev_hash`、改 `MANIFEST.lines`、改 `summary` 自报值。
**任一篡改未被判红即为校验器失效**——一个永远显绿的审计，正是它自己反对的东西。

## 9 产生侧：实验模式（`experiment_mode.py`，v1.0.1 起）

### 9.1 开关与隔离

| 层 | 口径 |
|---|---|
| 服务端总开关 | `python inference_server.py --audit-exp` 或环境变量 `AUDIT_EXP=1`；**默认关闭**。关闭时不导入 `experiment_mode`、不注册 §9.3 端点、首页与 `/health` 原样 |
| 会话开关 | 总开关打开后，WebSocket URL 带 `?exp=1&uid=<匿名代号>` 的连接才建实验会话；普通观测窗与 ROS 2 桥接收统一广播，字节不变 |
| 隔离 | 注入、证伪动作与里程计只改写**该连接的下发文本**，不写全局孪生；每会话里程计与 `embodied_env._integrate_odom` 同一模型（相邻真值帧反解 (v,w)，会话自有 RNG，回合复位时对齐真值） |

### 9.2 环境变量

| 变量 | 默认 | 含义 |
|---|---|---|
| `AUDIT_DIR` | `audit_sessions` | 会话目录根（运行产物，已 gitignore） |
| `AUDIT_INJECT` | `1` | `0`＝只留痕不注入（全部为健康轮） |
| `AUDIT_HEALTHY_WEIGHT` | `0.25` | 健康轮权重，取值 [0, 1] |
| `AUDIT_ONSET_MIN_S` / `AUDIT_ONSET_MAX_S` | `30` / `180` | 起爆时刻均匀分布区间（秒） |
| `AUDIT_TEACHER_KEY` | 无 | 教师自测口令；**只认环境变量**，不打印、不落盘 |
| `AUDIT_PLATFORM_VERSION` | `git describe` | 写入 MANIFEST 与 summary 的附注字段，不参与复算比对 |

### 9.3 端点与消息（仅总开关打开时存在）

- WS 握手：会话建立后先下发一条 `{"exp_session":{"session_id","uid","ticket","platform_version"}}`，此后为按注入调度改写的孪生状态。`ticket`＝会话票据，页面不显示、不落盘，只用于下列端点授权。
- WS 上行（会话内）：`{"self_test":{"action":"slip_zero|slip_restore|feed_cut|seq_probe"}}`、`{"student_verdict":{"choice":"healthy|C1|C2|C3","note":"…"}}`。
- `POST /screenshot`：`{"session_id","ticket","image":"data:image/png;base64,…","panel":{"seq","feed_age_s"}}`；凭票据；请求体按流读取封顶；只收 PNG，解码后 ≤8 MiB、单边 ≤4096、像素 ≤16,777,216（先查尺寸再解码），每会话 ≤60 张；服务端烧两行水印（uid｜session_id｜平台时钟｜平台版本；页面面板读数），缺 Pillow 返回 503、不存无水印的图；水印计算在工作线程执行，不阻塞心跳。
- `POST /export_pack/{session_id}`，请求体 `{"ticket"}`：返回 §1 的 zip；**导出即结束会话**（补记 `SESSION_END`，此后不再下发、不再接受判定）；打包在工作线程执行。只知道会话号不能导出或结束会话（票据不符与会话不存在同返回 404；请求体超限 413、不是 JSON 对象 400，均先于授权判定）。
- 上行消息令牌桶：每会话 10 条/秒、突发 20 条，超出丢弃，丢弃数记入 `SESSION_END.payload.dropped_messages`。

### 9.4 注入与定向

- 会话种子由系统密码学随机源（`os.urandom`）生成并记入 `SESSION_START.payload.seed`；抽签顺序固定为「健康判定 u → 类型序号 k → 起爆时刻」，凭种子可独立复算非定向会话的条件与起爆时刻。
- 注入语义：`C1` 下发的 `odom` 接回真值；`C2` 下发的 `seq` 冻结于起爆帧；`C3` 停发（连接保持）。`INJECT` 只落盘、不下发。
- 定向（教师自测）：URL 参数 `force`／`onset` 仅在请求头 `X-Audit-Teacher-Key` 与 `AUDIT_TEACHER_KEY` 一致时生效；否则忽略，并在 `SESSION_START.payload` 记 `override_requested=true, forced=false`。

### 9.5 产生侧附注字段（加法，均不在 `verify_pack.CHECK_FIELDS` 内）

`SESSION_START.payload`：`mode`、`inject_enabled`、`healthy_weight`、`onset_window_s`、`slip`、`platform_version`、`override_requested`、`forced`｜
`INJECT.payload`：`scheduled_onset_ms`、`params`｜`SELF_TEST.payload`：`scope="session"` 及动作参数｜
`SCREENSHOT.payload`：`bytes`、`sha256`、`watermark`、`page_panel`（页面自述读数）｜`TELEMETRY.payload`（1 Hz）：`truth_xy`、`odom_xy`、`seq`、`feed_age_ms`、`slip`｜
`SESSION_END.payload`：`reason`（`export`／`shutdown`）、`assigned_condition`、`scheduled_onset_ms`、`injected`、`dropped_messages`（v1.0.1，支撑 §4 `incomplete`）。

### 9.6 部署前提（双盲的边界）

服务端运行在教师机，学生只经浏览器连入，`AUDIT_DIR` 对学生不可读。学生本机自跑服务端时可直接读到 `INJECT` 落盘，**双盲不成立**，此类数据不得作盲测结论使用。
