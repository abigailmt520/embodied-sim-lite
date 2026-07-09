# Embodied-SimLite

> **轻量化具身智能数字孪生「验证」平台** —— 面向具身智能教学中的**系统审计素养**培养。
>
> 不追求"在完美仿真里跑通算法"，而是教学生区分「**看起来对**」与「**被证明对**」：用一套可被审计的数字孪生，量化感知误差、检测系统自欺。纯 Python + 浏览器即可运行，无需 Gazebo 等重型物理引擎。

---

## 1. 平台简介

Embodied-SimLite 是一个轻量化的具身智能（自主导航/避障）数字孪生平台，设计哲学是**彻底解耦物理推演、AI 决策与孪生渲染**，并坚持一条架构铁律：

> **后端是唯一真理源（single source of truth），前端是纯观测视窗。** 前端永不本地推演位姿；后端断流时，前端冻结画面并显式标 OFFLINE，绝不用本地积分"续算"假装在线。

在此地基上，平台提供一组**可被审计**的能力：真分叉里程计（让"误差"是真的）、防自欺完整性审计（让"审计"自己先被证明能抓假）、强化学习评测，以及 ROS 2 桥接。它面向教学：让学生对 Sim-to-Real gap 有量化认知、对"看似工作"的黑盒系统具备反证伪能力。

---

## 2. 核心功能模块

### 2.1 后端唯一真理源 + 前端纯观测架构
- **后端**（`inference_server.py` + `embodied_env.py`）：纯 numpy 物理内核（差速底盘运动学 + 解析式 LiDAR + O(1) 碰撞检测），由 FastAPI 以 ~60Hz 异步心跳驱动，承载 PPO 策略推理，是唯一真理源。
- **前端**（内联于 `inference_server.py` 的 Three.js + litegraph）：仅渲染后端经 WebSocket 下发的状态，**不承担任何物理计算**。
- **断流即冻结 + OFFLINE**：WS 断开时前端冻结画面并弹出 OFFLINE 遮罩（不做 dead-reckoning）。

  ![真实浏览器 OFFLINE](audit/offline_screenshot.png)

### 2.2 真分叉里程计（true-fork odometry）
- `embodied_env._integrate_odom()` 在真值位姿之外，**独立积分一条带"真打滑漂移"的里程计**：对轮速施加乘性偏差 + 比例噪声（噪声取自带种子 RNG，可复现，非 hardcode）。
- **真值 Truth 保持无噪声基准**；里程计 Odom 随行程**单调偏离真值**——累积误差真实非零（开环 500 步实测 ATE_RMSE ≈ **0.83 m**）。
- 打滑系数可配置，`slip=0` 时里程计逐位退化为 `odom ≡ truth`，作为对照。

  ![真分叉误差曲线](diagnostics/fork_error_curve.png)

### 2.3 防自欺完整性审计（anti-self-deception integrity audit）
平台最核心的教学卖点：**审计仪自身必须先被证明"能抓假"**——一个永远显绿的审计就是它自己最反对的"波将金村"。`audit/integrity_audit.py` 提供三项正交检查：

| 检查 | 抓什么自欺 |
|---|---|
| **C1 真值-里程计真分叉 / TRUTH_ODOM_FORK** | 里程计被接回真值（误差链路死掉，`Truth≡Odom`） |
| **C2 帧序号单调 / SEQ_INTEGRITY** | 数据在更新、帧序号却冻结/倒退（帧序号撒谎） |
| **C3 断流冻结 / FEED_LIVENESS** | 断流却仍声明 online / 显示"运行中" |

通过 `audit/fault_injection.py` 向健康系统**真实注入**三类假仪表，审计逐一**判红并定位**（帧号/seq/误差/recv_t）；健康系统则**全绿不误报**。下图为"红/绿对照"证据：第一列健康全绿，后三列每类注入被对应检查判红。

  ![完整性审计 红/绿对照](audit/audit_redgreen_matrix.png)

### 2.4 强化学习（PPO）评测
`audit/run_action1.py` 用配套 PPO 权重在 **N=25 张各不相同的随机地图**上评测，输出成功率/碰撞率/超时率/平均到达步数，确定性可复现：

- 地图：10 m × 10 m 方形竞技场，四面墙；每回合随机生成 6 个圆形障碍（半径 0.4–0.9 m）。
- 任务：每回合随机起点 + 随机目标（强制相距 > 5.66 m，排除"一步到位"）；随机初始朝向。
- 传感/动作：24 线 360° LiDAR（量程 5 m）；连续动作 `[v, w]`，10 Hz 决策，纯运动学。
- **实测结果**：成功率 **84%** / 碰撞率 **12%** / 超时率 **4%**（N=25，种子 100–124）；平均到达 ~81 步。

  ![PPO 基础评测](audit/eval_metrics.png)

> 说明：本评测只提供"真实可复现的基础指标"，不追求高性能、不调参、不做新旧基线对比。指标如实呈现。

### 2.5 ROS 2 桥接（需 Ubuntu + ROS 2 环境）
`ros_bridge.py` 做纯协议翻译：把孪生状态翻为 ROS 2 话题 `/odom`（发布**漂移里程计**，与真分叉一致）、`/scan`、`tf`；把 `/cmd_vel` 翻为对推理网关的人工覆盖指令（2 秒窗口内抢占 PPO，实现虚实控制权切换）。

> ⚠️ **ROS 2 桥接需在 Ubuntu + ROS 2（rclpy）环境中运行与验证**；其 `/scan`+`/odom`+`tf` 可作为上层 SLAM/Nav2 的数据源，但本仓库未对 rviz2/Nav2 端到端闭环做自动化验证，请在你的 ROS 2 环境中自行联调。

---

## 3. 环境依赖与安装

**平台核心（Python 部分）**，实测 Python 3.13（3.10+ 应兼容）：

```bash
git clone https://gitee.com/yfeng620/embodied-sim-lite.git
cd embodied-sim-lite
pip install -r requirements.txt      # numpy / gymnasium / torch / stable-baselines3 / fastapi / uvicorn / websockets / matplotlib
```

**ROS 2 桥接（可选，需 Ubuntu + ROS 2）**：`rclpy / tf2_ros / geometry_msgs / nav_msgs / sensor_msgs`（随 ROS 2 发行版提供）+ `pip install websocket-client`。

仓库已附带配套预训练权重 `ppo_embodied_agent.pth`（约 53 KB），**无需自行训练即可直接复现推理与评测**。

---

## 4. 各模块运行方式

```bash
# ① 启动平台（系统唯一入口）：60Hz PPO 推理 + 孪生前端
python inference_server.py
#    浏览器打开 http://localhost:8000 ，即见 3D 孪生 + 控制蓝图 + 遥测面板
#    （绿色为真值本体，红色幻影为里程计，随时间可见其漂移脱离——这就是真分叉）
#    论文截图模式：打开 http://localhost:8000/?screenshot=1
#    → 全局字号 ≥16px、遥测面板行距加大、隐藏操作提示、双语标签取中文，供论文插图重截

# ② 跑防自欺审计 + RL 评测（三道门一键实跑）
python audit/run_action1.py
#    → 门1：注入 1-A/1-B/1-C 假仪表，审计逐一判红并定位
#    → 门2：健康系统三项全绿、零误报
#    → 门3：PPO × 25 回合成功率/碰撞率/到达步数 + 出图 audit/eval_metrics.png
#    → 同时导出机器可读汇总 audit/eval_summary.json（n_maps/计数/比例/时间戳/策略标识，
#       供 tools/paper_figures/make_paper_figures.py --eval-json 复现论文图 4）

# ③ 生成"红/绿对照"审计证据图（需先跑过 ②）
python audit/make_audit_figure.py        # → audit/audit_redgreen_matrix.png
#    加 --paper：大字号 300dpi 输出 audit_redgreen_matrix_paper.png（论文图 2）

# ④ 截取真实断流 OFFLINE 画面（headless Chrome；需本机装有 Chrome）
python audit/capture_offline.py          # → audit/offline_screenshot.png

# ⑤ 复现真分叉 before/after 误差曲线
python diagnostics/record_fork.py        # → diagnostics/fork_error_curve.png
#    加 --paper：额外输出大字号中文版 fork_error_curve_paper.png（论文图 3）

# ⑥（可选）从零训练 PPO（产出新的 ppo_embodied_agent.pth）
python train_agent.py

# ⑦（需 ROS 2 环境）启动 ROS 2 桥接节点
python ros_bridge.py                     # 默认连 ws://127.0.0.1:8000/ws
#    跨机：SIM_GATEWAY_WS=ws://<网关IP>:8000/ws python ros_bridge.py
```

---

## 5. 目录结构

```
embodied-sim-lite/
├── embodied_env.py          # 物理内核（gymnasium 环境）：运动学 + 真分叉里程计 _integrate_odom + 解析 LiDAR + 帧序号 seq
├── inference_server.py      # 唯一入口：FastAPI + 60Hz PPO 推理 + WS 广播 + 内联 Three.js 前端（含 OFFLINE 冻结）
├── ros_bridge.py            # ROS 2 桥接（需 ROS 2 环境）：孪生状态→/odom·/scan·tf；/cmd_vel→人工覆盖
├── train_agent.py           # PPO 训练脚本（超实时，剥离时钟）
├── ppo_embodied_agent.pth   # 配套预训练权重（开箱复现推理/评测）
├── Architecture.md          # 架构说明文档
├── requirements.txt
├── audit/                   # 防自欺完整性审计 + 评测
│   ├── integrity_audit.py   #   审计仪：C1 真值-里程计真分叉 / C2 帧序号单调 / C3 断流冻结（论文 v1.1 术语）
│   ├── fault_injection.py   #   假仪表注入器（自证抓假，仅测试用）
│   ├── run_action1.py       #   三门一键实跑：抓假(红) + 健康(绿) + PPO 评测
│   ├── make_audit_figure.py #   红/绿对照矩阵图
│   ├── capture_offline.py   #   headless Chrome 截真实断流 OFFLINE 画面
│   └── *.png                #   结果图（红绿对照 / 评测 / OFFLINE）
└── diagnostics/             # 真分叉诊断
    ├── record_fork.py       #   真分叉记录器（before/after 误差曲线）
    └── fork_error_curve.png
```

---

## 6. 能力边界（如实声明，不夸大）

- **纯运动学**：物理内核为零惯性运动学积分，未建模动力学/加速率限制。
- **里程计只"漂移"、不"校正"**：平台提供 Odom 真漂移的可视化与审计，**未实现 EKF/SLAM 等定位校正**。
- **ROS 2 端到端闭环需自行验证**：`ros_bridge.py` 在 ROS 2 环境下提供 `/odom`+`/scan`+`tf` 与人工覆盖；rviz2/Nav2/SLAM 的完整闭环未在本仓库做自动化验证。
- **评测为基础指标**：N=25 的随机地图基础指标，非性能调优结果，不含新旧基线对比。

---

## 7. 相关论文

- **图表复现**:论文全部统计图表(图 4/图 5/图 7/图 8,后两幅为 v1_2 更正版)及图 6 实拍合成图
  可由 [`tools/paper_figures/`](tools/paper_figures/) 一键复现;
  论文图 2 由 `audit/make_audit_figure.py --paper` 生成,图 3 由 `diagnostics/record_fork.py --paper` 生成,
  图 4 可通过 `--eval-json audit/eval_summary.json` 挂接平台实测评测结果,形成可复现闭环。
- **引用格式**:见 [CITATION.cff](CITATION.cff);开源许可为 Apache-2.0(见 [LICENSE](LICENSE))。

### 平台检查点与论文 3.2 节术语对照

| 平台内部标识符 | 论文 3.2 节术语(显示名) | 实现位置 |
|---|---|---|
| `C1_TRUTH_ODOM_FORK` | C1 真值-里程计真分叉 / TRUTH_ODOM_FORK | `audit/integrity_audit.py` `check_truth_odom_fork()` |
| `C2_SEQ_INTEGRITY` | C2 帧序号单调 / SEQ_INTEGRITY | `audit/integrity_audit.py` `check_seq_integrity()` |
| `C3_FEED_LIVENESS` | C3 断流冻结 / FEED_LIVENESS | `audit/integrity_audit.py` `check_feed_liveness()` |

内部标识符保持不变以兼容既有 session 数据;显示层文案(审计报告、红/绿矩阵图、前端 OFFLINE 遮罩)已统一为论文 v1.1 术语,与论文图 2 行名逐字一致。

---

## 8. 许可证

见 [LICENSE](LICENSE)。
