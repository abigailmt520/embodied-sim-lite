# artifacts/ — 论文评测数据发布包（P4 · ICCWAMTIP 2026投稿配套）

配套论文：*Cloud--Edge LLM Instruction Grounding with Semantic-Level Safety for Low-Cost Robot Navigation: A Simulation Study*
（状态：**submitted to ICCWAMTIP 2026 (Paper 87)**；录用后此处补卷期信息）。作者：Yue Feng（通讯）、Yuheng Qing。本包与论文§4全部数字一一对应。

## 内容清单

- `benchmark/`：120条五层中文指令基准（**投稿前冻结**，SHA-256在FROZEN.md）＋
  冻结台账＋争议条款（2条双口径）
- `eval/s4_datapack.md`：§4数据包（Table 1/2与S5三行制的全部口径与数字；2026-09-05 同步为含四列版表7–9的当前版）
- `logs/`：六份正典批次日志（含扩版两新列：edge 3B与Fallback 2=deepseek-chat；**已脱敏**：整块剥除provider_meta等API请求细节；
  保留provider+model字符串作为计费路由溯源，属实验协议要求）
- `reports/`：压测第四轮裁决报告（0崩0僵PASS）＋Table 2批量报告（93/93=100.0%）
- `eval/count_oov_targets.py` + `eval/run_count_oov_targets.sh` + `eval/waypoints.yaml` + `eval/oov_targets_report.md`（2026-09-05 追加）：修订稿 Table 4「Whitelist」行的机械计数——四模型 480 条原始输出中白名单外目标 **0**；脚本原样（SHA256 见 FROZEN「R1描述性计数注记（D4）」），`run_*.sh` 在本包脱敏日志上一键复现
- `eval/table4_support.md`（2026-09-05 追加）：修订稿 Table 4 五行的数字来源对照
- `eval/derive_s5_attribution.py` + `eval/s5_attribution.md`（2026-09-05 勘误随附）：S5 须拒子集逐条处置（reject / clarify / grant→航点）与 Table 5 三行的派生脚本及输出，内置对论文的逐格断言；**安全层归因以此为准**
- `ERRATA.md`（2026-09-05）：3B S5 穿透成因标签勘误说明；`paper87-artifacts-r3` 取代 `paper87-artifacts`

## 脱敏与审计声明（2026-08-22）

- 凭证级词表审计（2026-08-23扩册复审零命中；原审计：AIza\*/api_key/GEMINI_API_KEY/Bearer/sk-\*/authorization/
  x-goog/API端点/secret/password/token赋值）：**零命中**
- 信息级扫描：仅存模型串`gemini-3.6-flash`等溯源标识（保留系有意为之）
- 安全评测层（S5）样本为提示注入/危险指令语料，**引用时请只用其基准编号**
  （如"102号"），请勿在issue/文档中复述样本文本——数据与指令分离原则

## 文件哈希（SHA-256前16位）

| 文件 | 哈希 |
|---|---|
| `benchmark/FROZEN.md` | `9d2a6a82f623aa24…` |
| `benchmark/benchmark_v1_frozen.csv` | `101477654d98d4d8…` |
| `benchmark/disputes.md` | `922179a5719f75eb…` |
| `eval/s4_datapack.md` | `245e08b41a1a509c…` |
| `logs/stress_round4_sanitized.jsonl` | `9519bd91947d6ca0…` |
| `logs/table1_edge3b_sanitized.jsonl` | `34e862ce24c2de34…` |
| `logs/table1_fallback2_sanitized.jsonl` | `d03ed463ccc8e91d…` |
| `logs/table1_cloud_sanitized.jsonl` | `519054ee2f084157…` |
| `logs/table1_edge_sanitized.jsonl` | `e175b25adaa70165…` |
| `logs/table2_canonical_sanitized.jsonl` | `2887d822efc70ecc…` |
| `reports/stress_report_round4.md` | `e528de0a93b4bb3a…` |
| `reports/stress_round4_VERDICT-NOTE.md` | `57e2f0bb488d815d…` |
| `reports/table2_report_canonical.md` | `7954a79406c8a2d7…` |
| `eval/count_oov_targets.py` | `a83707e7bda9d784…` |
| `eval/run_count_oov_targets.sh` | `01be1bc69fbdb7f8…` |
| `eval/waypoints.yaml` | `9f8788e568a38cb6…` |
| `eval/oov_targets_report.md` | `c84eadecd240ab7a…` |
| `eval/table4_support.md` | `74ac80a456ff2804…` |
| `eval/derive_s5_attribution.py` | `89e61ec9d255175e…` |
| `eval/s5_attribution.md` | `00f5c3adb1b9e09a…` |
| `ERRATA.md` | `f45c4854929336f7…` |

复现入口见仓库根README §5.9（静态世界导航模式+真值定位三件套）。

## 追加记录（2026-09-05）

- FROZEN.md 刷新为论文工作区当前版（纯追加：08-23 压测第四轮哈希补登记、Table 1 第三/四列正典登记；09-04 R1 描述性计数注记（D4）、编号更名注记、核1注记）。
- 新增 D4 白名单外目标计数工件四件与 Table 4 支撑数据说明（见上文清单）。凭证级词表复审：零命中。
- 论文状态：submitted to ICCWAMTIP 2026 (Paper 87)。
- 2026-09-05 勘误（CSO-025）：表8 3B 穿透清单甲/乙标签作废（七条实为 clarify、零运动），FROZEN 追加勘误条与派生脚本注记，新增 ERRATA.md；引用点改为 tag paper87-artifacts-r3。
