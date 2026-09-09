# CLAUDE.md — FORGE 平台线（embodied-sim-lite）开场说明

## ① 本仓属哪条线与航道
- **FORGE 平台线，航道 A**（一人公司/IP/资产）。本仓＝Embodied-SimLite 公开仓（gitee 主 ＋ GitHub 镜像）；治理与决策记录在私有仓 dream-os（`50_product/platform/`）。

## ② 编号与回报
- 令号前缀 **FORGE-###**（自 FORGE-001 起；旧号 CSO-026/028 存档不改）。执行摘要末尾注明「本轮执行：FORGE-0XX」。

- **本仓 CSO 件以 dream-os 的信箱为准**：`00_portfolio/inbox/CSO-inbox.md`（唯一账，已办全文在 `inbox/done/`）；**跨仓件在信箱条目里注明目标仓**。CC 每次开工先读信箱、报未办项。

## ③ 真源与纪律（以仓内既有文件为准）
- `ITERATION.md`：加法＋开关（默认关，旧入口逐字节一致）／三道门／tag only／契约 semver／双钥匙／性能预算／攻击语料隔离。
- **三道门全绿方可合并 master**（gate1-selfcheck / gate2-course / gate3-paper，required checks + enforce_admins）；定义与容差 `FROZEN-CI.md`；本地 `python3 tools/ready_check.py --all`。
- **课程与论文只认 tag**：`course-2026A`、`paper-jsjjy-2026`、`paper-p4-v1` 永不移动/删除（tag ruleset）；`release/v1.1`＝现钉版；冻结分支 `paper-sync-v1.1`、`paper2-embodied-simlite` 不再提交。
- 推送只走 `tools/publish.sh`（审计 → 推送 → 双远端巡检）；契约 `docs/teaching_api.md`（改契约＝升主版本＋迁移说明＋垫片）。
- `artifacts/` 只增不改（`HASHES.lock`）；S5 样本只引 benchmark id。

## ④ 当前状态与 INDEX
- 状态：**活跃**——保护令三绿（CSO-028/-R1），golden 15/15，候 T0 施工令（FORGE-002 位）。
- INDEX：dream-os `00_portfolio/index/FORGE-INDEX.md`；护照：`00_portfolio/passports/FORGE.md`。
