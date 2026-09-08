# docs/audit_pack_spec.md — 审计包格式与哈希链规范（Audit Pack Spec）

规范版本：v1.0.0 ｜ 2026-09-08（FORGE-003 任务六卡 A）
本文件 **= 现状快照**：只成文本仓已实现的格式与口径，不含计划与愿望。与代码不符处以代码为准，并以 PATCH 修订本文件。

> **实现状态**：本仓当前实现的是**审计包的校验与汇总侧**（`audit_chain.py`、`tools/audit_tools/`）。
> 产生审计包的**平台实验模式入口**（`?exp=1` 会话、注入调度、截图水印、`/export_pack`）尚未进入本仓，
> 其接线属课程冻结面改动，另行评审。本规范先落地，使**校验器与产生器两侧共用同一套字节级口径**，杜绝日后漂移。
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
| `hit` | 注入轮且最终判定为 `abnormal` |
| `localization_correct` | `hit` 且判定的 `checkpoint` 与注入类型一致 |
| `false_alarm` | 健康轮且最终判定为 `abnormal` |
| `detect_latency_ms` | 判定时刻 − `INJECT` 时刻，**仅命中轮** |

`verify_pack.py` 用同一函数从日志独立复算，与包内 `summary.json` **逐字段比对**；
`platform_version` 等附注字段不参与比对（`CHECK_FIELDS` 为准）。

## 5 汇总指标口径（`tools/audit_tools/analyze_packs.py`）

- **发现率** = 注入轮中报告异常的比例
- **定位准确率** = 报异常的注入轮中检查点点名正确的比例
- **误报率** = 健康轮中报告异常的比例
- **检出时延** = 判定时刻 − 注入 onset，只对命中轮计算，报**中位数[四分位距]**（分布右偏，不用均值）
- 比例的 95% 置信区间一律 **Clopper–Pearson 精确区间**（纯 Python 实现，无 scipy 依赖）

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
python tools/paper_figures/make_paper_figures.py --audit-json audit_summary.json
```

`verify_pack.py` 退出码：全部通过 `0`，任一失败 `1`。

## 8 红测纪律

校验器**必须能红**。`selftest.py` 用 `make_fixture_pack.py` 离线造包，覆盖五种篡改面：
改事件内容、改 `line_hash`、断 `prev_hash`、改 `MANIFEST.lines`、改 `summary` 自报值。
**任一篡改未被判红即为校验器失效**——一个永远显绿的审计，正是它自己反对的东西。
