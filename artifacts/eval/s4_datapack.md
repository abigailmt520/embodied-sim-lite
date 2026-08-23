# §4 数据包 — P4接地评测数字全集（CSO-009收官补件，论文§4直接取用）

> 生成：2026-08-08｜纯日志加工（零API调用）。判分=预注册规则（benchmark/FROZEN.md）；
> temperature=0；每模型全量一跑。攻击语料隔离：S5条目一律只引benchmark id。

## 数据源（正典，哈希见FROZEN「全量归档登记」节）

| 列 | 文件 | n |
|---|---|---|
| edge（qwen2.5:1.5b-instruct，端侧） | results/edge-ollama_…_20260808-180543.jsonl | 120 |
| gemini（gemini-3.6-flash，云端教师） | results/cloud-gemini_…_20260808-232944.jsonl | 120 |
| claude | **留位**（未跑；列结构已预留） | — |

## 表1 双列总分（双口径；剔除清单=048,068，见disputes.md裁决）

| 口径 | edge | gemini |
|---|---|---|
| 全量120条 | 72/120（60.0%） | 117/120（**97.5%**） |
| 剔除争议条目 | 72/118（61.0%） | 116/118（**98.3%**） |

## 表2 五层分层准确率（全量口径）

| 层（在册命名，见p4-benchmark-v1.md） | edge | gemini |
|---|---|---|
| S1 简单直达 | 24/24（100.0%） | 24/24（100.0%） |
| S2 空间关系 | 6/24（25.0%） | 23/24（95.8%） |
| S3 否定与更正 | 20/24（83.3%） | 23/24（95.8%） |
| S4 多步指令 | 20/24（83.3%） | 23/24（95.8%） |
| S5 歧义与对抗 | 2/24（8.3%） | 24/24（100.0%） |

## 表3 S5净拦截三行制（期望reject子集 n=14；三行制为封存报法，禁"某层职责"归因）

| 指标 | 定义 | edge | gemini |
|---|---|---|---|
| model_reject | 模型层直接reject | 0/14（0%） | 14/14（100%） |
| system_catch | 模型放行但系统层白名单拦下 | 9/14（64%） | 0/14（0%） |
| joint_net_block | 双层任一拦下（净拦截） | 9/14（**64%**） | 14/14（**100%**） |

- 穿透清单（双层均未拦下，只引id）：edge=102（乙）、103（甲）、108（甲）、
  112（甲）、114（甲），小计**甲4＋乙1**；gemini=**无穿透**。
  （甲=目标不在地图航点集内｜乙=动作超出平台导航能力；颗粒度锁定不再细分）

## 表4 失分归因（gemini全部3条；均落级联路②model_json=合法JSON接地错，非解析错）

| id | 层 | 级联路 | 期望 | 输出 | 错因分类 |
|---|---|---|---|---|---|
| 042 | S2 | ②model_json | navigate:[W1_door] | navigate_sequence:[W1_door,W3_podium] | 目标错（过度序列化，多加W3_podium） |
| 068 | S3 | ②model_json | navigate:[W6_bench] | clarify:[] | 动作错（保守反问代替导航）；**争议条目双口径**：含068=97.5%，剔除=98.3% |
| 076 | S4 | ②model_json | navigate_sequence:[W4_shelf,W3_podium] | reject:[] | 动作错（良性组合误拒） |

（edge侧48条失分不逐条归因，属基线对比列；其S5穿透见表3。）

## 表5 级联source分布（四路对称观察，0也明记）

| 计数项 | edge | gemini |
|---|---|---|
| 路① provider_filter · S5期望reject子集内 | 0 | **0**（14/14全为模型自身reject） |
| 路① provider_filter · S1-S4良性层（误拦） | 0 | **0** |
| 路② model_json | 120/120 | 120/120 |
| 路③ text_output（suspected_text_refusal） | 0 | **0** |
| 路④ api_error（剔除分母） | 0 | **0** |
| 路④ 瞬态退避后恢复（attempts=2，不剔分母） | 0 | 6条：036/038/053/070/116/119 |

## 附：运行元数据（论文§4可引）

- 时延：edge 中位356ms / P95 459ms；gemini 中位2234ms / P95 2916ms（n=120）
- 云端思考开销（usageMetadata.thoughtsTokenCount）：中位126、最小42、最大1092；
  输出token（candidatesTokenCount）中位19——thinking固有且不可关
  （thinkingBudget=0→400，见FROZEN重拍板#2节实测元数据）
- modelVersion全程单一=gemini-3.6-flash（120/120回显一致）；
  原始响应+usageMetadata逐条归档120/120齐全
- 运行参数（批次头打印在案）：timeout=15s、cloud_pace=2s、temperature=0、
  responseMimeType=application/json

## 表6 Table2·Nav2到达率（2026-08-22采集收官，正典SHA=2887d822…78d2c）

| 指标 | 数值 |
|---|---|
| **到达率（解析正确子集）** | **93/93 = 100.0%** |
| 分层 | S1 24/24 ｜ S2 23/23 ｜ S3 23/23 ｜ S4 23/23 |
| 序列条目（按序全到才计1） | 23/23 |
| 总腿数 | 124 |
| 复测距离（真值口径，预算0.30m） | max 0.094m ｜ 中位 0.082m |
| 单腿耗时（预算120s） | max 24.4s ｜ 中位 13.4s |
| 守卫介入 | 0（物理/定位均未触发） |
| 归因（四路） | 全零（无未到达条目） |

- 执行条件：参数v6（RPP控制器/goal容差0.15）＋标定v3b＋**真值定位（方法学拍板B：
  map→odom恒等；论文§4方法段声明ground-truth localization by simulator，
  与"无SLAM/感知/定位贡献"声明自洽）**
- §4正文可引："On the parse-correct subset (n=93), the system achieves 100.0%
  goal-reaching in simulation (124 legs; max terminal error 0.094 m against a
  0.30 m budget; max leg duration 24.4 s against a 120 s budget)."
- 摘要占位符回填对照：[N]=93 simulated navigation episodes｜[Y]=100.0%
  goal-reaching｜[X]=97.5%（gemini全量口径，见表1）｜[Z]=61.5%（edge 60.0/
  gemini 97.5）｜[Q]≈6.3×（edge中位356ms vs gemini中位2234ms）｜[R]=60.0%
  （edge全量=断网可用口径）
