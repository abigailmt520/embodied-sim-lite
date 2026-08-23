# artifacts/ — 论文评测数据发布包（P4 · ICCWAMTIP 2026投稿配套）

配套论文：*A Cloud--Edge Architecture for LLM-Based Instruction Grounding with
Semantic-Level Safety for Low-Cost Mobile-Robot Navigation: A Simulation Study*
（投稿中；录用后此处补卷期信息）。作者：Yue Feng（通讯）、Yuheng Qing。本包与论文§4全部数字一一对应。

## 内容清单

- `benchmark/`：120条五层中文指令基准（**投稿前冻结**，SHA-256在FROZEN.md）＋
  冻结台账＋争议条款（2条双口径）
- `eval/s4_datapack.md`：§4数据包（Table 1/2与S5三行制的全部口径与数字）
- `logs/`：四份正典批次日志（**已脱敏**：整块剥除provider_meta等API请求细节；
  保留provider+model字符串作为计费路由溯源，属实验协议要求）
- `reports/`：压测第四轮裁决报告（0崩0僵PASS）＋Table 2批量报告（93/93=100.0%）

## 脱敏与审计声明（2026-08-22）

- 凭证级词表审计（AIza\*/api_key/GEMINI_API_KEY/Bearer/sk-\*/authorization/
  x-goog/API端点/secret/password/token赋值）：**零命中**
- 信息级扫描：仅存模型串`gemini-3.6-flash`等溯源标识（保留系有意为之）
- 安全评测层（S5）样本为提示注入/危险指令语料，**引用时请只用其基准编号**
  （如"102号"），请勿在issue/文档中复述样本文本——数据与指令分离原则

## 文件哈希（SHA-256前16位）

| 文件 | 哈希 |
|---|---|
| `benchmark/FROZEN.md` | `072a328b07c3d0ea…` |
| `benchmark/benchmark_v1_frozen.csv` | `101477654d98d4d8…` |
| `benchmark/disputes.md` | `922179a5719f75eb…` |
| `eval/s4_datapack.md` | `c44ef29fec7fd0e1…` |
| `logs/stress_round4_sanitized.jsonl` | `9519bd91947d6ca0…` |
| `logs/table1_cloud_sanitized.jsonl` | `519054ee2f084157…` |
| `logs/table1_edge_sanitized.jsonl` | `e175b25adaa70165…` |
| `logs/table2_canonical_sanitized.jsonl` | `2887d822efc70ecc…` |
| `reports/stress_report_round4.md` | `e528de0a93b4bb3a…` |
| `reports/stress_round4_VERDICT-NOTE.md` | `57e2f0bb488d815d…` |
| `reports/table2_report_canonical.md` | `7954a79406c8a2d7…` |

复现入口见仓库根README §5.9（静态世界导航模式+真值定位三件套）。
