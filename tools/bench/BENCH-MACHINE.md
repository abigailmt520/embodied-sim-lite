# tools/bench/BENCH-MACHINE.md — 性能基准机入册（CSO-028 平台保护令·任务3：≤10% 硬门的「秤」）

## 1. 基准机（＝golden 录制机）

| 项 | 值 |
|---|---|
| 机型 | `Mac14,9`（MacBook Pro 14″ 2023，Apple M2 Pro） |
| CPU / 内存 | Apple M2 Pro，12 逻辑核｜16 GB |
| OS | macOS 26.5.1（Darwin 25.5.0），arm64 |
| Python | 3.13.12（miniconda base 环境） |
| 关键库 | numpy 2.4.6｜torch 2.12.1｜stable-baselines3 2.9.0｜gymnasium 1.3.0｜matplotlib 3.11.0｜fastapi 0.137.1｜uvicorn 0.49.0｜websockets 16.0 |
| 指纹正典 | `golden/course-2026A/RECORD.json` → `fingerprint`（ready_check 以此判定「同机」） |

异机读数只能与**同机**基线比较；跨机器数字不可直接比。

## 2. 测法（`tools/bench/cpu_usage.py`）

| 模式 | 做什么 | 读数 | 口径 |
|---|---|---|---|
| `kernel` | 无网关：`EmbodiedNavEnv.step` + PPO `predict`（torch 单线程），预热 200 步后跑 N 步（默认 6000），取进程 CPU 时间 | 每步 CPU 毫秒；折算「10 Hz 实时占单核%」＝ms×10/10、「60 Hz 心跳占单核%」＝ms×60/10；无头吞吐 步/s | 与网关无关的内核成本，跨版本比较最稳 |
| `gateway` | 真实起 `inference_server.py`（或 `--server nav_gateway.py`），挂 K 个 WebSocket 观测客户端（默认 1），稳态 3 s 后以 1 Hz `ps -o %cpu` 采样 T 秒（默认 30） | 均值 / 中位 / P95 / 最大（单核口径）＋ 整机占比＝均值/逻辑核数 | **`ps %cpu` 单核＝100%**（macOS/Linux 惯例）；整机占比＝任务管理器口径 |

运行条件：基准机无其他重负载；端口 8000 空闲；`--out` 保存原始 JSON。

## 3. 基线（course-2026A 平台代码，2026-09-08，本机）

| 测项 | 读数 |
|---|---|
| kernel（6000 步） | **0.1623 ms CPU/步**；10 Hz 实时折算 0.162% 单核；60 Hz 心跳折算 0.974% 单核；无头吞吐 6161.8 步/s |
| `inference_server.py` 空载（0 客户端，30 s） | 均值 **15.95%** 单核（中位 16.15 / P95 17.2 / 最大 17.4）＝整机 **1.33%** |
| `inference_server.py` 1 观测客户端（30 s） | 均值 **19.04%** 单核（中位 19.35 / P95 20.8 / 最大 21.1）＝整机 **1.59%**；30 s 收帧 2034 |
| `nav_gateway.py` 1 客户端（20 s，10 Hz） | 均值 **1.74%** 单核（P95 2.4 / 最大 2.8）＝整机 **0.15%**；收帧 234 |

原始 JSON：`tools/bench/baseline_course-2026A.json`。60 Hz 空载 16% 单核 vs kernel 折算 0.97%：差额为 asyncio 心跳/JSON 序列化/uvicorn 事件循环开销，属网关本身成本。

## 4. ≤10% 硬门如何读（待 CSO 确认口径）

- TA-049 T0：「教学终端 CPU 占用 ≤10% 为硬指标」。《计算机教育》论文图 5 给出本平台「约 3%」（`tools/paper_figures` 常量 `FIG5_SIMLITE_CPU=3`），系普通教学终端整机占比（任务管理器口径）的实测。
- 与论文自洽的读法＝**整机占比**：基线 1.3–1.6%，距 10% 余量充足。单核口径（16–19%）供工程内部比较，不作硬门读数。
- 两口径同时登记；硬门以哪一口径计，由 CSO 确认后在本文件追加一条（只增不删）。
- T0 验收用法：新功能**开关关闭态**，同机同法复测，`gateway_1client` 均值不高于基线且 kernel 每步 CPU 不高于基线（差异 >2% 单核须解释）；开关打开态另测另记，不与关闭态混表。
