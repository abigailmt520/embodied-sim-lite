# FROZEN-CI.md — CI 三道门：定义、子集选取与容差（CSO-028 平台保护令·任务2；只增不删）

## 0. 总则

- 三门＝`.github/workflows/gates.yml` 的三个 job：`gate1-selfcheck` / `gate2-course` / `gate3-paper`；本地等价命令 `python3 tools/ready_check.py --all`（单门 `--selfcheck` / `--course` / `--paper`）。
- master 分支保护：required status checks＝上述三个 job 名，strict（分支须与 master 同步），`enforce_admins` 开启——三门全绿方可合并，管理员同样受限。
- 本文件所列一切冻结物（golden 清单、HASHES.lock、冻结子集、种子、容差）改动＝**追加新条目**，不改旧条目；对应文件的重生成一律走 `ready_check` 维护子命令（默认拒绝覆盖）。
- 攻击语料隔离：S5 条目只引 benchmark id；本文件、脚本输出、CI 日志均不含 instruction 文本。

## 1. 门1 三门自检（旧）

- 命令 `python3 audit/run_action1.py`（退出码恒 0，属现状契约）；判定＝三行 ✅ 逐字出现在 stdout（`docs/teaching_api.md` §5.4）。
- 覆盖：1-A/1-B/1-C 三注入分别被 C1/C2/C3 判红并定位；健康 session 全绿零误报；PPO 25 回合评测产出图与 CSV。

## 2. 门2 课程一致性（`ready_check --course`）

| # | 检查 | 判据 |
|---|---|---|
| 2.1 | 三点一致 | `course_manifest.yaml` `course.tag`＝`course-2026A` 存在且为附注 tag；`tag^{commit}`＝`pinned_commit` `bc8fa5018592c0efdadc3c471be16f46dc422dc1`；`same_as` `paper-sync-v1.1` 可见时须同点 |
| 2.2 | 契约版本 | `docs/teaching_api.md` 头「契约版本：v1.0.0」＝manifest `course.contract.version` |
| 2.3 | golden 完整 | `golden/course-2026A/MANIFEST.sha256` 所列 15 件全部存在且哈希相等（§4） |
| 2.4 | A/B 同机复跑 | manifest `entries` 三入口在 course tag 临时 worktree（A）与 HEAD 树（B）各跑一遍，归一化后 **逐字节相等**；任何机器强制 |
| 2.5 | golden 对照 | 策略 `strict`（裁定②收敛后）：15 件＝9 件逐字节 ＋ 4 份 session（舍 4 位，容差 1e-4 等价护栏；CI 实测舍 4 位后已逐字节同）＋ 2 张 PNG（像素精确等价），任何机器强制；`READY_CHECK_GOLDEN=report` 仅供调试 |

- 2.5 的理由：PPO 推理经 torch 浮点，跨 BLAS 实现（Accelerate / OpenBLAS / MKL）末位可能不同并传入 session JSON；跨机等价性由 2.4 的 A/B 保证。**收敛令（CSO-028-R1 裁定②）**：CI 依赖钉版 `requirements-ci.txt`（与基准机逐版本一致，消 PNG 差异）＋ session JSON 定点化（消浮点尾差），目标 **golden 15/15 跨平台**；达成后策略由 `bench-strict` 收紧为 `strict`；实在收不掉的极少数逐件在 §6 列明豁免理由——豁免清单不得静默膨胀。
- 归一化规则（manifest `entries[].outputs[].normalize` / `compare`）：`audit/eval_summary.json` 去 `generated_at` 后 `json.dumps(indent=2, ensure_ascii=False)`；**四份 session JSON `json_round` 4 位 ＋ `compare: numeric_tol`（浮点 |Δ|≤1e-4 视为相等；结构/键/整数/布尔/字符串逐字节精确）**；**两张 PNG 零归一化 ＋ `compare: pixel_exact`（解码后逐像素相等，零容差）**；stdout 中树根（含 realpath 形）替换为 `<ROOT>`、临时目录替换为 `<TMP>`；其余 9 件零归一化。所有归一化施加在比较层，**course tag 旧入口本身逐字节不动**（A/B 门仍对原始产物成立）。
- **四份 session 为何不是逐字节（裁定②「收不掉者逐件列明理由」）**：CI 实测（run 34218626251，依赖已与基准机逐版本钉死）舍 6 位后仍各有 50 处差异、|Δ| 恰为 1e-6——跨 BLAS（Accelerate vs OpenBLAS）的 PPO 推理原始尾差（估算均值≈3e-8、尾部≈1e-6）落在舍入边界即翻转；以 CI 数据再舍到 k 位的残余差异估算：k=6→200、k=5→8、k=4→5、k=3→0（k=3 的 0 属本次运气，翻转概率非零）。**结论：任何固定位数舍入都留有非零翻转概率，会把 strict 门变成随机红灯**；确定性做法＝舍 4 位（0.1 mm / 1e-4 rad，远细于任何有意义的行为回归）＋ 容差 1e-4 的数值等价（原始差 <1e-4 时必判等），结构与非浮点字段仍逐字节。这 4 件是「容差等价」而非「豁免」——比较规则成文、可复算、不含人工白名单。
- **两张 PNG 为何不是逐字节**：CI 实测像素 0 差（1430×546 与 1170×650，RGBA 逐像素相同），差异只在 PNG 容器字节（36169 vs 41134、60491 vs 67642）。先试「规范化重编码」（PIL 固定参数重编码）——**跨平台仍异**（run 34219106750）：各平台 Pillow 轮子捆绑的 zlib 实现不同，deflate 流不可跨平台确定。确定性做法＝**比内容不比容器**：`compare: pixel_exact`（解码→RGBA→逐像素相等，零容差），golden 存基准机原始 PNG（可直接查看）。这 2 件是「像素精确等价」而非「豁免」。
- 策略：裁定②收敛后 `golden.policy: strict`（任何机器强制；`bench-strict`/`report` 仅供调试）。
- 运行环境：`OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONHASHSEED=0 MPLBACKEND=Agg`（录制与复跑同）。
- 种子封存：manifest `seeds`（run_action1 SEED_SESSION 11 / SEED_EVAL 100..124 / N_LIVE 240 / N_DISCONNECT 15；record_fork SEED 7 / 500 步 / 动作 [0.6,0.25]；make_gt_map seed 42；env SLIP_FACTOR 0.05）。
- 未纳入 golden 的入口及原因：manifest `excluded_entries`（长驻服务、需 ROS 2/Chrome、非确定输出）。

## 3. 门3 论文复现（`ready_check --paper`）

| # | 检查 | 判据 / 容差 |
|---|---|---|
| 3.1 | artifacts 只增不改 | `artifacts/HASHES.lock`（锚 `paper-p4-v1` @ `b83ec8c0838fbea2a4f9f0682e018c4fce023ef8`，22 条）：**冻结路径**（数据/脚本/报告，19 条）sha256 不变；**只增路径**（台账/索引：`benchmark/FROZEN.md`、`ERRATA.md`、`README.md`，`# append-only:` 指令行）当前内容须以锚点 commit 内容为前缀（追加合法、改写/删行判红）；新增允许；`artifacts/benchmark/` 下新增须落 `artifacts/benchmark/v<N≥2>…/` 新目录（新基准＝新目录＋新版本号）。两种语义的依据：FROZEN.md 自身家规为「只增不删」，与「哈希不变」按文件性质分工 |
| 3.2a | 冻结子集 A（字段等价） | `artifacts/eval/ci_frozen_subset.json`：S5 且 `expected_action=reject` 的 **14 条**（只引 id）× 四模型日志（1.5B / 3B / Fallback 2 / Teacher）：`parsed.action`、`parsed.targets`（列表、顺序敏感）、`system_action`、`score` 逐条精确相等 |
| 3.2b | 冻结子集 B（数值逐位） | 四模型 n=120；score_sum **72 / 88 / 116 / 117**；分层 score 和：1.5B {S1 24,S2 6,S3 20,S4 20,S5 2}，3B {24,14,21,13,16}，Fallback 2 {24,23,23,22,24}，Teacher {24,23,23,23,24}；Table 2 n=93 reached=93；压测第四轮 n=50、`result` 计数 {not_reached: 50}（该轮判据为 0 崩 0 僵，`result` 字段按日志原值冻结） |
| 3.3 | S5 派生脚本 | `derive_s5_attribution.py` 内置断言（Table 5 三行四列 + §5.1 事实）exit 0；输出与 `artifacts/eval/s5_attribution.md` 逐字节相等（sha256 `00f5c3ad…`） |
| 3.4 | D4 白名单外计数 | `run_count_oov_targets.sh` 四行 `\| <col> \| 120 \| 120 \| 120 \| 0 \| 0 \| — \| 无 \|`；脚本 SHA256 `a83707e7…`＝FROZEN 登记值 |
| 3.5 | 平台论文数字 | PPO 25 回合 `{n 25, success 21, collision 3, timeout 1, avg_steps_success 80.8}`（＝论文 84%/12%/4%、约 81 步；受 2.5 golden 策略：同机强制、异机 report）；真分叉 `{ATE_RMSE 0.831123, final_err 1.532276, max_err 1.54648, final_yaw_drift_deg −53.6709}`（纯 numpy，任何机器强制） |

- 容差：**零容差**——字符串/列表精确相等，整数精确相等，浮点按脚本输出位数（6 位 / 4 位）精确相等。
- 复跑口径：**派生链复跑**（冻结脱敏日志 → 论文数字，零 API 调用）。
- **定位（CSO-028-R1 裁定④，设计而非妥协）**：CI 门3 的职责是守护「冻结证据 → 论文数字」推导链的完整性，防代码漂移悄改统计口径；LLM 真推理天然不可入 CI（2.5-pro 暗关闸是亲历教训，见 FROZEN.md「拍板型号更正追加」），其复跑属「复现审计」级事件，需要时由人工令执行。其可复现性由 `artifacts/benchmark/FROZEN.md` 的温度闸与正典登记承载。
- 子集 A 与子集 B 的 id 集合、期望值由 `ready_check --write-frozen-subset` 于 2026-09-08 自四份日志生成（HEAD b83ec8c 工件）；改动＝新版本文件＋本节追加。

## 4. golden 基准输出集清单（录制 2026-09-08，`course-2026A` @ bc8fa50，基准机 Mac14,9；15 件，归一化后 sha256；**本表为第五次录制（裁定②第三针：PNG 回存原始字节、比像素）**，历次见 RECORD.json history）

| 文件 | sha256 |
|---|---|
| audit/eval_episodes.csv | `31b430433291fde94a4f4d56d06a14eaf766daa222656e6545ebc7328cf5666c` |
| audit/eval_metrics.png（原始 PNG；对照＝像素精确） | `27a494b9e8e8bcc07d36b322c70ac0afabdbd97a6ae79074f2ceb524b9f3fe0f` |
| audit/eval_summary.json（去 generated_at） | `f826bfd72ce54dbfde2a2618708dc7a3097d23184b3ce35e99b567438ec59ac4` |
| audit/run_action1.stdout.txt | `17a30396c4d55e7bb2faa97096ed1814cf41393fa3f8b943585ed653d5c3731c` |
| audit/sessions/healthy.json（json_round 4；对照＝容差 1e-4 等价） | `4629350b1a55c0e8e22e7c65613602d52128df8a0a33be596ca007f96135bb33` |
| audit/sessions/injected_1-A_truth_copy.json（json_round 4；对照＝容差 1e-4 等价） | `14ca3c956ce6b315a95bf422e74cf372b9774fc412aa7782162a168bb39c51fb` |
| audit/sessions/injected_1-B_seq_freeze.json（json_round 4；对照＝容差 1e-4 等价） | `fc3f64e7487443c799b735a0ceb72c7eb10e2c84966a7e6c7114b2f03580d5eb` |
| audit/sessions/injected_1-C_stall_running.json（json_round 4；对照＝容差 1e-4 等价） | `6f4f6764f67691106b2b97762f69172f621c471d44292f8ca1f94c0ca6e7235a` |
| diagnostics/fork_after.csv | `26bb035df8441528f474282946a75f2add811be483a2ca2f78af01f1e65d91b3` |
| diagnostics/fork_before.csv | `913841b5b50b8aae89b3764e8e5620d09aa1d48833a7d0661fd163a926557e69` |
| diagnostics/fork_error_curve.png（原始 PNG；对照＝像素精确） | `e25a37b13a18f5c3d783fdb43156a87831076fcd9f0b630b03135c76ab218b11` |
| diagnostics/record_fork.stdout.txt | `5380e337c1bb0d10c04995d68751ccab0a55c32ab187c4d8697876ee2b4342ed` |
| nav/make_gt_map.stdout.txt | `b671806fdc43f5ccdde5420aafaa56cc0cc97e07124474ab39526b6bbae68b01` |
| nav/map_gt.pgm | `16522b3b0853e2f6e130e4cf3a5c3e9bf80db583a38a8fd004005e12450c3985` |
| nav/map_gt.yaml | `bdb0309814a2aa3753cb54af9940edda63188e742f6f0025b99d622fedb6bd2a` |

- `nav/map_gt.pgm` 哈希＝`artifacts/benchmark/FROZEN.md`「修复包与作废注记 ｜ 2026-08-22」登记的世界定义 Mac 参考哈希 `16522b3b…`：课程冻结面与论文复现面指向**同一个世界**（seed 42）。
- 库内已跟踪图件 `audit/eval_metrics.png`、`diagnostics/fork_error_curve.png` 与本次基准机再生逐字节一致（course tag 图件即在本机同环境生成）。
- 录制机指纹、环境与入口清单：`golden/course-2026A/RECORD.json`。

## 5. 基准机与性能预算

- `tools/bench/BENCH-MACHINE.md`（机型/测法/两口径基线）；原始读数 `tools/bench/baseline_course-2026A.json`；秤＝`tools/bench/cpu_usage.py`。

## 6. 运行记录（追加式）

- 2026-09-08 基准机本地 `ready_check --all` 首跑：门1 🟢（4 项）｜门2 🟢（11 项：三点一致、契约 v1.0.0、golden 15 件完整、A/B 15 件逐字节、golden strict 逐字节）｜门3 🟢（26 项：HASHES.lock 22 条不变、子集 A 14×4 等价、子集 B 数值逐位、Table 2 93/93、压测 50、S5 派生逐字节、D4 四列 0/120、PPO 21/3/1、ATE 0.831123）。
  - 守卫脚本自身两处 bug 由首跑红灯揪出并修复后重录 golden：stdout 归一化未覆盖 macOS `/var`→`/private/var` realpath；HASHES.lock 锚点行解析列偏移。红测能红，门为真。
- CI 首跑（GitHub Actions run 34212854586，ubuntu-24.04 x86_64：AMD EPYC 7763 / Intel Xeon 8573C；py 3.13，torch 2.14.0+cpu，numpy 2.5.3，matplotlib 3.11.1）：三 job 全部 success，各约 1 分钟。门2：三点一致、契约 v1.0.0、golden 15 件清单完整、**A/B 15 件逐字节一致**；golden 对照（report）：一致 9 / 不一致 6——不一致件＝4 份 session JSON（torch 跨 BLAS 浮点末位进入位姿小数）＋2 张 PNG（matplotlib 3.11.1 vs 3.11.0 编码差异）；eval_episodes.csv / eval_summary.json / 三份 stdout / fork_before·after.csv / map_gt.pgm·yaml 跨平台全部一致 → PPO 计数 21/3/1、均步 80.8、ATE 0.831123 跨平台不变。门3：26 项全 PASS（PPO 计数 report 模式一致）。结论：`bench-strict` 策略成立——同机逐字节强制、异机 A/B 强制＋数值一致；若要跨机逐字节，须锁定 torch/numpy/matplotlib 版本与 BLAS 实现，留待 T0 施工令决定，本令不改。
- 2026-09-08 **CSO-028-R1 裁定①核验（内容同一性）**：08-24 12:56 GMT 时点公开仓状态＝`5a62edf`（08-23 05:07 PDT 后无提交直至 09-05）。`HASHES.lock` 22 条对照 `5a62edf` 的 `artifacts/`：**冻结数据件 11 件逐字节同一**（`benchmark_v1_frozen.csv`、`disputes.md`、6 份脱敏日志、3 份报告；且与 README@5a62edf 声明哈希逐条一致）；**只增 2 件**（`FROZEN.md` +7390 B、`s4_datapack.md` +1867 B，B 以 A 为前缀）；**改写 1 件**（`README.md` 索引，2497→4530 B）；**新增 8 件**（ERRATA/派生脚本/D4 计数/支撑件/waypoints，均 09-05 CSO-022/023/025 令下产物）；**删除 0 件**。结论：冻结件全同 → **锚成立**；两日期＝两个事件：**08-24 12:56 GMT＝v1 投递**（5 页，`6248c06b…`，CMT 回下载逐字节同，DECISIONS 09-04 查1），**09-05 18:32 PDT＝r5 终稿经 CMT Edit Submission 提交**（6 页，`1ab1b676…`，随 09-04「Accept with revision suggestions」修订；09-06 正式录用）。发表稿＝r5，其 §5.1 按 CSO-025 勘误与 b83ec8c 的派生脚本输出一致，故复现面锚定 b83ec8c（内容为锚、日期为注）。
- 2026-09-08 **CSO-028-R1 裁定③破坏性演练（GitHub 侧，诱饵规则）**：诱饵 tag `paper-drill-test`（落 `paper*-*` 面）试删→**GH013 Cannot delete this tag**；试改写→**GH013 Cannot update this protected ref / Cannot force-push**；master 空提交试直推→**GH006 3 of 3 required status checks are expected**。三项全拒；真锚全程未触。诱饵经「停用 ruleset→删→恢复」受控清理并核回（ruleset active、真锚 3/3 在）；该两步绕行为 GitHub 平台固有残余风险，对冲＝`tools/mirror_check.sh`。记录件：dream-os `50_product/platform/drill-2026-09-08/`。
- 2026-09-08 **双远端巡检首跑抓到真漂移**：`paper1-final`、`paper2-final` 两 tag 与 `paper2-embodied-simlite` 冻结分支只在 Gitee（GitHub 镜像 08-09 建立时仅带 Paper-87 引用）。处置：两 tag 审计零命中→经 `publish.sh --tag` 镜像到 GitHub；分支 `e2b6474` 树命中凭证审计**误报**（`embodied_env.py:398` 注释词，DECISIONS 09-05 已判误报、词根收紧待「第三分支处置令」）→推送前硬门拒推，**挂账豁免**（`mirror_check.sh` WAIVED，只报不红），解除时删行并记本节。
- 2026-09-08 golden 第三次录制（裁定②）：session 四件 `json_round` 6 位；`RECORD.json` 新增 `history`（补记 03:02 守卫修复重录、03:58 定点化重录）与 `normalization` 字段；CI 依赖钉版 `requirements-ci.txt`；gate2 新增 `--dump` 产物上传（`gate2-outputs`）供跨平台差异度量。**CI 复跑结果见后续追加。**
- 2026-09-08 **CI 复跑（run 34218626251，guard/cso-028-r1，依赖钉版生效：numpy 2.4.6 / torch 2.12.1+cpu / matplotlib 3.11.0 与基准机一致）**：三 job success；A/B 15 件逐字节；冻结路径 19 件不变、只增路径 3 件前缀校验过；golden 对照 report 仍 9/15——6 件差异定性：4 份 session 舍 6 位后各 50 处、|Δ|=1e-6（边界翻转）；2 张 PNG 像素 0 差、仅编码字节异。据此收敛第二针：session 舍 4 位＋容差 1e-4 等价、PNG 规范化重编码、策略 strict；golden 第四次录制（RECORD.json history 第 3 条）。**下一次 CI 结果见后续追加。**
- 2026-09-08 **CI 复跑（run 34219106750，收敛第二针）**：gate1/gate3 success；gate2 **13/15**——四份 session 舍 4 位后**逐字节相同**（容差护栏未触发）；两张 PNG 经规范化重编码后跨平台**仍异**（Pillow 捆绑 zlib 差异）。第三针：PNG 改 `compare: pixel_exact`（像素精确等价），golden 第五次录制（RECORD.json history 第 4 条）。**下一次 CI 结果见后续追加。**
