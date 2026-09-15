# CHANGELOG — Embodied-SimLite 版本变更日志

> **格式**：每个版本一节，按「新增／变更／修复」分组；**每条必须带「教学影响」字段**——课程侧据此决定是否迁移（无影响写「无」并给理由）。
> **锚点**：课程与论文只认冻结 tag（`course-2026A`、`course-2026B-pre1`、`paper-jsjjy-2026`、`paper-p4-v1`）；版本 tag（`v*`）不改冻结面。
> **维护态**：自 `v1.1.1` 起本仓为冻结基线维护态，此后的版本只会是 hotfix 补丁版（流程见 `FROZEN-CI.md` §7）。教学接口契约另有独立版本号（`docs/teaching_api.md` 头部）。

## [v1.1.1] — 2026-09-15（冻结基线补丁版）

涵盖自 `course-2026A`（`bc8fa50`，2026-09-05）以来的保护面、审计工具链、冻结声明与实验模式入口。本版之后公开仓只收 hotfix。

### 新增

| 变更 | 说明 | 教学影响 |
|---|---|---|
| 实验模式入口（FORGE-004 任务六卡 B） | `experiment_mode.py`＋`inference_server.py` 开关挂钩：`--audit-exp`／`AUDIT_EXP=1` 开启后，`?exp=1` 会话双盲注入 C1/C2/C3 或健康、证伪动作只作用于本会话并留痕、平台截图烧水印、导出哈希链审计包；截图与导出凭会话票据；上传、截图张数与上行消息均限额；教师定向注入须请求头口令（只认环境变量）。合入前经独立只读复核并修复。规范见 `docs/audit_pack_spec.md` §9 | **无**：默认关闭，关闭态 `/`、`/health`、`/openapi.json`、启动 stdout、WS 下行与 `course-2026A` 逐字节一致；课程 manifest 与教学接口契约不动。开启属研究采集，需另行安排 |
| 教师自测与产生侧红测 | `tools/audit_tools/simulate_sessions.py`（端到端 5 会话，含起爆前导出、起爆前判定两个边界场景，`--verify` 自动核对）、`tools/audit_tools/exp_selftest.py`（离线：注入语义、会话隔离、票据、限额、边界口径、导出包判绿与篡改判红） | 无：教师与维护者工具，不进学生流程 |
| 审计链与审计包工具链（FORGE-003 任务六卡 A） | `audit_chain.py`、`tools/audit_tools/{verify_pack,analyze_packs,make_fixture_pack,selftest}.py`、`docs/audit_pack_spec.md`、`make_paper_figures.py --audit-json` | 无：独立离线工具，不碰课程入口 |
| `--slip`／`SLIP` 开关与桥接日志（FORGE-002） | `inference_server.py` 里程计打滑系数显式覆盖（默认关闭）；`ros_bridge.py` 启动打印桥接契约声明与连接生命周期日志；教学接口契约 v1.0.0 → **v1.1.0（MINOR）** | **有、可选**：课程可用 `--slip 0` 做「退化检验」对照档；不指定时与 v1.0.0 逐字节一致；话题、QoS、frame 不变 |
| 平台保护面与 CI 三道门（CSO-028／-R1） | `course_manifest.yaml`、`golden/course-2026A/`（15 件）、`artifacts/HASHES.lock`、冻结子集、`tools/ready_check.py`、`.github/workflows/{gates,mirror}.yml`、`ITERATION.md`、`FROZEN-CI.md`、`docs/teaching_api.md`、`tools/bench/` | 无：守卫面，保证课程冻结 tag 与论文复现不被后续改动破坏 |
| 发布与巡检工具 | `tools/publish.sh`（自测→全树审计→推送→双远端巡检）、`tools/mirror_check.sh`、`tools/audit_secrets.py` 与钩子 | 无 |
| 开源协作文档 | `CONTRIBUTING.md`（维护态流程与 AI 辅助生成内容声明）、`CODE_OF_CONDUCT.md`、本文件 | 无 |

### 变更

| 变更 | 说明 | 教学影响 |
|---|---|---|
| 冻结基线声明与周检 | `README.md` 顶部冻结声明；`gates.yml` 每周一定时运行三门；`FROZEN-CI.md` §7 冻结基线与 hotfix 流程；综 II 预冻结点 tag `course-2026B-pre1`（位于冻结提交 `41858c2`） | 无：不改课程入口；为综 II 学期冻结预留锚点 |
| `docs/audit_pack_spec.md` v1.0.0 → v1.0.1（PATCH） | 产生侧入仓并成文 §9；补定两处边界口径（起爆前即结束会话标 `incomplete` 并在汇总剔除；判定早于起爆不计命中），发生在任何数据采集之前；`verify_pack.CHECK_FIELDS` 与 `analyze_packs` 同步 | 无 |
| `ITERATION.md` §4 | tag 白名单增 `v*` 版本 tag | 无：治理文档 |
| `tools/publish.sh`、`tools/mirror_check.sh` | 允许推送 `v<主>.<次>.<修>[-预发布]` 版本 tag；巡检纳入 `v*` tag（历史 tag `v1.0.0` 仅在 Gitee，挂账豁免、只报不红） | 无 |
| `README.md` | 增 ⑩ 实验模式用法；许可证节指向贡献指南、行为准则与本文件；保护面横幅契约版本更正为 v1.1.0；Paper 87 状态更新为 Accepted to ICCWAMTIP 2026 | 无 |
| 维护者协作说明 | `CLAUDE.md` 开场说明、用量约束与维护态状态 | 无 |

### 修复

| 变更 | 说明 | 教学影响 |
|---|---|---|
| 论文复现工件勘误与同步（2026-09-05） | 3B S5 原因标签勘误；`s4_datapack.md` 同步 3B 节（tag `paper87-artifacts-r3`／`-r3.1`）；`artifacts/ERRATA.md` 记录 | 无：论文复现面按 `paper-p4-v1` 锚定，只增不改 |

### 与冻结面的关系

- `course-2026A`、`paper-jsjjy-2026`（均 `bc8fa50`）与 `paper-p4-v1`（`b83ec8c`）三 tag **哈希不变**；门2 A/B 与 golden **15/15** 在本版本提交上复验。
- 教学接口契约现为 **v1.1.0**；本版本**不升契约版本**：实验模式属研究采集面，未入教学契约。
- `course-2026B-pre1` 位于冻结提交 `41858c2`，与 v1.1.1 的差异只含默认关闭的新增与文档。

## [course-2026A] — 2026-09-05（冻结锚，非版本 tag）

课程 2026-2027-1 学期冻结点（`paper-sync-v1.1` HEAD `bc8fa50`，与 `release/v1.1` 同点）；教学接口契约 v1.0.0 为其现状快照。更早历史见 git log 与 tag `v1.0.0`（2026-05-03）。
