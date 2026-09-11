# CLAUDE.md — FORGE 平台线（embodied-sim-lite）开场说明

## ① 本仓属哪条线与航道
- **FORGE 平台线，航道 A**（一人公司/IP/资产）。本仓＝Embodied-SimLite 公开仓（gitee 主 ＋ GitHub 镜像）；治理与决策记录在私有仓 dream-os（`50_product/platform/`）。

## ② 编号与回报
- 令号前缀 **FORGE-###**（自 FORGE-001 起；旧号 CSO-026/028 存档不改）。执行摘要末尾注明「本轮执行：FORGE-0XX」。


## ③ 真源与纪律（以仓内既有文件为准）
- `ITERATION.md`：加法＋开关（默认关，旧入口逐字节一致）／三道门／tag only／契约 semver／双钥匙／性能预算／攻击语料隔离。
- **三道门全绿方可合并 master**（gate1-selfcheck / gate2-course / gate3-paper，required checks + enforce_admins）；定义与容差 `FROZEN-CI.md`；本地 `python3 tools/ready_check.py --all`。
- **课程与论文只认 tag**：`course-2026A`、`paper-jsjjy-2026`、`paper-p4-v1` 永不移动/删除（tag ruleset）；`release/v1.1`＝现钉版；冻结分支 `paper-sync-v1.1`、`paper2-embodied-simlite` 不再提交。
- 推送只走 `tools/publish.sh`（审计 → 推送 → 双远端巡检）；契约 `docs/teaching_api.md`（改契约＝升主版本＋迁移说明＋垫片）。
- `artifacts/` 只增不改（`HASHES.lock`）；S5 样本只引 benchmark id。

## ④ 当前状态与 INDEX
- 状态：**活跃**——保护令三绿（CSO-028/-R1），golden 15/15，候 T0 施工令（FORGE-002 位）。
- INDEX：dream-os `00_portfolio/index/FORGE-INDEX.md`；护照：`00_portfolio/passports/FORGE.md`。

## 协作提示词落地件（LAB-005，源＝手册 T25／T32；勿手改，改源在手册后重新发放）

> **钩子管硬红线，本段管灰区。** `.claude/hooks/` 的护栏拦的是冻结物/密钥这类**明确禁止**；
> 下面两段管的是**规则没写死、要靠判断**的那一片——可逆性、爆炸半径、默认动不动。

```text
Weigh reversibility and blast radius before acting. Local, reversible steps — editing files, running tests — are yours to take. Ask first for anything hard to undo, visible to others, or destructive: deleting files or branches, dropping tables, rm -rf, force pushes, hard resets, amending published commits, pushing code, commenting on PRs or issues, sending messages, changing shared infrastructure. Never take a destructive shortcut around an obstacle: no bypassing safety checks (--no-verify), no discarding unfamiliar files that may be someone's in-progress work.
```

```text
<default_to_action>
By default, make the change rather than only suggesting it. If the intent is unclear, infer the most useful action and proceed, using tools to discover missing details instead of guessing; judge from context whether a tool call (a file read or edit) is what the user wants, and act accordingly.
</default_to_action>
```

（对话席用的是另一半 `do_not_act_before_instructions`，见 dream-os `00_portfolio/PROTOCOL.md` §5。）
