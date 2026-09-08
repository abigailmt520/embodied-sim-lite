# ITERATION.md — 平台迭代纪律（CSO-028 平台保护令·任务4）

适用：`embodied-sim-lite` 全仓，自 2026-09-08 起先于一切功能开发生效。与本文件冲突的提交由 CI 三门拦下，不靠人记。
主理人规则（TA-049 入账）：平台与工具可持续迭代；每次迭代在主理人确认前不得影响课程对已钉版本的使用，不得影响已录用论文的复现；课件升级只在主理人单独下令后进行，此前只做平台与工具。

## 1. 三个不可变面

| 面 | 载体 | 守卫 |
|---|---|---|
| 课程冻结面 | tag `course-2026A`（＝`paper-sync-v1.1` HEAD `bc8fa50`）＋ `course_manifest.yaml` ＋ `golden/course-2026A/` | 门2 `ready_check --course` |
| 论文复现面 | tag `paper-jsjjy-2026`（＝`bc8fa50`）、`paper-p4-v1`（＝`b83ec8c`，Paper 87 提交日末 commit＝`paper87-artifacts-r3.1`）＋ `artifacts/` 只增不改（`artifacts/HASHES.lock`）＋ `artifacts/eval/ci_frozen_subset.json` | 门3 `ready_check --paper` |
| 教学接口契约面 | `docs/teaching_api.md`（语义化版本，现 v1.0.0＝现状快照） | 门2 版本一致 ＋ 人审 |

## 2. 加法 ＋ 开关

- 新功能一律**加法**：不删、不改现有入口/参数默认值/产物文件名与列/stdout 判定行/WS 字段语义/种子与阈值常量。
- 新行为以**开关**启用（CLI 参数或环境变量），**默认关闭**；开关关闭态下旧入口产物与 course tag **逐字节一致**（门2 A/B 同机复跑强制；golden 在基准机强制）。
- 需要打破上述任一条＝契约 MAJOR（§5）＋ 新 course tag（仅主理人令）＋ 课程迁移检查；在此之前不得合并。

## 3. 三道门

- 门1 三门自检（旧）：`audit/run_action1.py` 三行 ✅（审计抓假·红 / 放行健康·绿 / PPO 评测）。
- 门2 课程一致性：manifest↔tag↔commit 三点一致；契约版本一致；golden 清单完整；旧入口 A/B 同机复跑逐字节；golden 对照（目标跨平台 15/15：CI 依赖钉版 `requirements-ci.txt` ＋ session JSON 定点化归一；收不掉的逐件在 FROZEN-CI 列明豁免理由）。
- 门3 论文复现：`HASHES.lock` 只增不改（冻结路径哈希不变；台账/索引类 append-only 以锚点内容为前缀；`benchmark/` 新增须 v2+ 新目录）；冻结基准子集派生复跑（字段等价＋数值逐位）；S5 派生脚本与 D4 计数逐字节；平台论文数字。**门3 守护的是「冻结证据→论文数字」推导链，LLM 真推理不入 CI（设计，非妥协）。**
- 本地：`python3 tools/ready_check.py --all`（推送前必跑）；CI：`.github/workflows/gates.yml`，push 任意分支与 PR 均触发。
- master 分支保护：required checks＝`gate1-selfcheck` / `gate2-course` / `gate3-paper`，strict，`enforce_admins` 开启——**三门全绿方可合并**。紧急绕行（关 enforce_admins）只在主理人明示下执行并记 DECISIONS，事后即恢复。
- 定义、子集与容差：`FROZEN-CI.md`。

## 4. tag only

- 课程与论文**只认 tag**，不认分支。三面 tag 均为附注 tag，**永不移动/删除**；GitHub tag ruleset 对 `course-*`、`paper*-*` 禁删禁改（含管理员）。
- 新版本＝新 tag（`course-2026B`、`paper-p4-v2`…），旧 tag 保留；`tools/publish.sh` 只推显式指定且匹配前缀白名单（`paper*-*`、`p5-*`、`course-*`）的 tag。
- **镜像纪律的秤**：Gitee 无 ruleset/Actions，接受为残余风险；对冲＝`tools/mirror_check.sh` 双远端受保护 tag/关键分支哈希比对（`publish.sh` 双推后自动跑、`.github/workflows/mirror.yml` 每日巡检），漂移即红。所有者经「停用 ruleset→删→恢复」两步可绕过 GitHub 侧保护（平台固有），演练已验拒（FROZEN-CI §6）。
- 分支模型：`master`＝开发主线（TA-049 所称 `main`；默认分支名沿用 `master`，改名属破坏性动作，不在本令内）；`release/vX.Y`＝发布线；**`release/v1.1`＝现钉版**（`bc8fa50`，与 `course-2026A` 同点）：热修只入此线并打新 tag，课程不自动跟随；`paper-sync-v1.1`、`paper2-embodied-simlite` 为冻结分支，不再提交（publish.sh 默认拒推）。

## 5. 契约 semver

- `docs/teaching_api.md` 头部「契约版本」为唯一版本源；`course_manifest.yaml` `course.contract.version` 须一致（门2）。
- MAJOR：任一契约面不兼容变更，须附迁移说明＋兼容垫片＋课程迁移令（TA-047 一致性检查，只改红项）；MINOR：向后兼容新增，默认关闭或不改旧输出；PATCH：文档对齐，零行为变化。
- 契约＝现状快照：只写代码已有的行为；愿望进路线图，不进契约。

## 6. 冻结物变更程序 与 CSO 四加固（正式定义，CSO-028-R1 转正）

**冻结物变更程序**：冻结物＝`golden/`、`artifacts/HASHES.lock`、`artifacts/eval/ci_frozen_subset.json`、`course_manifest.yaml`、`docs/teaching_api.md` 版本号、`FROZEN-CI.md` 既有条目。改动须同时具备：①机械锁——`ready_check` 维护子命令默认拒绝覆盖，须显式 `--force`/`--append`（golden 重录另须 `GOLDEN_RERECORD_REASON` 环境变量，原因写入 `RECORD.json` history）且产物走新版本路径或追加条目；②人审记录——`FROZEN-CI.md` 追加条目 ＋ dream-os `DECISIONS` 登记，由主理人令启动。缺任一把即不合并。

**CSO 四加固（正式定义，摘自《平台迭代线立项书＋五层裁定》CSO 正式件）**：
- **A1 插件契约 golden 测试**：四类插件接口（传感器/世界/智能体/评测器）各配 golden 测试，防架构自身漂移。→ T0 施工项；本保护令的 golden 基准输出集是其前身。
- **A2 双钥匙**：**隐藏真值对学生、可审计对教师裁判**；预注册工作流与 FROZEN 家规同构。→ T3 施工项；与上段「冻结物变更程序」是两回事（后者是仓库治理，A2 是评测抗投机机制）。
- **A3 雷达模型锚定实机 RPLIDAR C1**（LD19 级降为兼容预设）＋ Sim-to-Real 检定数据**只用聚合分布**（PII 红线延伸）＋ 语义相机可选置 T1 末。→ T1 施工项。
- **A4 挑战赛种子赛前封存、赛后公布** ＋ T4 **密钥不入平台代码，只认 env 注入**。→ T2/T4 施工项。

> **勘误（CSO-028-R1）**：CSO-028 令文所列「C1 对齐」中的 C1 指**实机雷达 RPLIDAR C1**（A3），并非本平台完整性审计的 C1 检查器；本文件 v1 与 DECISIONS 09-08 条目按后者作的推定作废。「种子封存」在正式件中特指**挑战赛种子**（A4），与 `course_manifest.yaml seeds`（旧入口内置常量登记）不是同一物，后者保留但不再冒名。

## 7. 性能预算（CSO-028-R1 裁定④定案）

- **主口径＝整机占比 ≤ 10%**（绝对门，与论文图 5 自洽）；**单核值并行登记**（负载本身的可移植度量）；**相对回归预算＝任一层合并后单核占用对 `baseline_course-2026A` 劣化 ≤ 20%（相对值）**。
- 秤＝`tools/bench/cpu_usage.py` → `tools/bench/compare_baseline.py`（指纹不同即不可比）；基准机与基线＝`tools/bench/BENCH-MACHINE.md`；学生代表机待器材盘点后补一台入秤。
- 开关关闭态同机复测须过两门；开关打开态另测另记。

## 8. 攻击语料隔离

- S5 样本只以 benchmark id 引用；任何脚本输出、文档、commit message、CI 日志不得复述 instruction 文本。

## 9. 本地流程（每次迭代）

1. 自 `master` 切分支开发（加法＋开关）。
2. `python3 tools/ready_check.py --all` 三绿。
3. `tools/publish.sh <branch> github` 推分支（经凭证审计），CI 三门跑。
4. 三绿后合并 `master`（fast-forward 或 PR）；`tools/publish.sh master` 双远端同步；需要发 tag 时 `--tag NAME`。
5. 触及冻结物走 §6；触及契约走 §5。
