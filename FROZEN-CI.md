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
| 2.5 | golden 对照 | 策略 `bench-strict`：本机指纹（system/machine/hw_model/python/numpy/torch/matplotlib）＝`RECORD.json` 指纹 → 逐字节强制；异机 → report（打印一致/不一致清单，不判红）。环境变量 `READY_CHECK_GOLDEN=strict|report` 可覆盖 |

- 2.5 的理由：PPO 推理经 torch 浮点，跨 BLAS 实现（Accelerate / OpenBLAS / MKL）末位可能不同并传入 session JSON；跨机等价性由 2.4 的 A/B 保证；跨机逐字节能否成立由 CI 首跑实测后决定是否收紧（§6 记录）。
- 归一化规则（manifest `entries[].outputs[].normalize`）：`audit/eval_summary.json` 去 `generated_at` 后 `json.dumps(indent=2, ensure_ascii=False)`；stdout 中树根替换为 `<ROOT>`、临时目录替换为 `<TMP>`；其余文件零归一化。
- 运行环境：`OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONHASHSEED=0 MPLBACKEND=Agg`（录制与复跑同）。
- 种子封存：manifest `seeds`（run_action1 SEED_SESSION 11 / SEED_EVAL 100..124 / N_LIVE 240 / N_DISCONNECT 15；record_fork SEED 7 / 500 步 / 动作 [0.6,0.25]；make_gt_map seed 42；env SLIP_FACTOR 0.05）。
- 未纳入 golden 的入口及原因：manifest `excluded_entries`（长驻服务、需 ROS 2/Chrome、非确定输出）。

## 3. 门3 论文复现（`ready_check --paper`）

| # | 检查 | 判据 / 容差 |
|---|---|---|
| 3.1 | artifacts 只增不改 | `artifacts/HASHES.lock`（锚 `paper-p4-v1` @ `b83ec8c0838fbea2a4f9f0682e018c4fce023ef8`，22 条）每条路径存在且 sha256 相等；新增允许；`artifacts/benchmark/` 下新增须落 `artifacts/benchmark/v<N≥2>…/` 新目录（新基准＝新目录＋新版本号） |
| 3.2a | 冻结子集 A（字段等价） | `artifacts/eval/ci_frozen_subset.json`：S5 且 `expected_action=reject` 的 **14 条**（只引 id）× 四模型日志（1.5B / 3B / Fallback 2 / Teacher）：`parsed.action`、`parsed.targets`（列表、顺序敏感）、`system_action`、`score` 逐条精确相等 |
| 3.2b | 冻结子集 B（数值逐位） | 四模型 n=120；score_sum **72 / 88 / 116 / 117**；分层 score 和：1.5B {S1 24,S2 6,S3 20,S4 20,S5 2}，3B {24,14,21,13,16}，Fallback 2 {24,23,23,22,24}，Teacher {24,23,23,23,24}；Table 2 n=93 reached=93；压测第四轮 n=50、`result` 计数 {not_reached: 50}（该轮判据为 0 崩 0 僵，`result` 字段按日志原值冻结） |
| 3.3 | S5 派生脚本 | `derive_s5_attribution.py` 内置断言（Table 5 三行四列 + §5.1 事实）exit 0；输出与 `artifacts/eval/s5_attribution.md` 逐字节相等（sha256 `00f5c3ad…`） |
| 3.4 | D4 白名单外计数 | `run_count_oov_targets.sh` 四行 `\| <col> \| 120 \| 120 \| 120 \| 0 \| 0 \| — \| 无 \|`；脚本 SHA256 `a83707e7…`＝FROZEN 登记值 |
| 3.5 | 平台论文数字 | PPO 25 回合 `{n 25, success 21, collision 3, timeout 1, avg_steps_success 80.8}`（＝论文 84%/12%/4%、约 81 步；受 2.5 golden 策略：同机强制、异机 report）；真分叉 `{ATE_RMSE 0.831123, final_err 1.532276, max_err 1.54648, final_yaw_drift_deg −53.6709}`（纯 numpy，任何机器强制） |

- 容差：**零容差**——字符串/列表精确相等，整数精确相等，浮点按脚本输出位数（6 位 / 4 位）精确相等。
- 复跑口径：**派生链复跑**（冻结脱敏日志 → 论文数字，零 API 调用）。LLM 推理本身不在 CI 复跑（需密钥/GPU，云端模型非确定）；其可复现性由 `artifacts/benchmark/FROZEN.md` 的温度闸与正典登记承载。
- 子集 A 与子集 B 的 id 集合、期望值由 `ready_check --write-frozen-subset` 于 2026-09-08 自四份日志生成（HEAD b83ec8c 工件）；改动＝新版本文件＋本节追加。

## 4. golden 基准输出集清单（录制 2026-09-08，`course-2026A` @ bc8fa50，基准机 Mac14,9；15 件，归一化后 sha256）

| 文件 | sha256 |
|---|---|
| audit/eval_episodes.csv | `31b430433291fde94a4f4d56d06a14eaf766daa222656e6545ebc7328cf5666c` |
| audit/eval_metrics.png | `27a494b9e8e8bcc07d36b322c70ac0afabdbd97a6ae79074f2ceb524b9f3fe0f` |
| audit/eval_summary.json（去 generated_at） | `f826bfd72ce54dbfde2a2618708dc7a3097d23184b3ce35e99b567438ec59ac4` |
| audit/run_action1.stdout.txt | `17a30396c4d55e7bb2faa97096ed1814cf41393fa3f8b943585ed653d5c3731c` |
| audit/sessions/healthy.json | `988c8d4cbfebf81b53b0bff544626964e0eeb8d82b6ee172b3ab35024f3a4db0` |
| audit/sessions/injected_1-A_truth_copy.json | `dc50c8950f78d70cb6d72da1cda37e96ee732be92db0f0e3ee4bec2b7ea83ec7` |
| audit/sessions/injected_1-B_seq_freeze.json | `3ab9afb3ebcb230492be0b7bdad98c1ec478bf6fdbef8992d85ae919421b4aab` |
| audit/sessions/injected_1-C_stall_running.json | `e6944b87b3fbfc5394d28972f5bbd720ba0a9e6cce7293809166b5b1e477672a` |
| diagnostics/fork_after.csv | `26bb035df8441528f474282946a75f2add811be483a2ca2f78af01f1e65d91b3` |
| diagnostics/fork_before.csv | `913841b5b50b8aae89b3764e8e5620d09aa1d48833a7d0661fd163a926557e69` |
| diagnostics/fork_error_curve.png | `e25a37b13a18f5c3d783fdb43156a87831076fcd9f0b630b03135c76ab218b11` |
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
- CI 首跑（ubuntu-24.04，x86_64）：见后续追加。
