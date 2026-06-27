# Embodied-SimLite · 平台迭代主文档（活文档）

> **单一累积文档**：每个平台迭代任务都更新此处。记录各 Phase 的设计决策/实现/验证（真实数字），
> 以及**当前平台状态**（分支、权重、能力、局限）。目的：平台演进可追溯，未来接手者/AI 不必重新逆向。
> 🔴 红线：master `7b54625`（已投稿论文版）**永久冻结**；所有迭代在 dev 分支；论文权重不覆盖。
> 最后更新：2026-06-26（Phase1b 完成）

---

## 1. 当前平台状态（CURRENT STATE）

### 1.1 分支
| 分支 | 内容 | 基于 |
|---|---|---|
| `master` | 🔒 **冻结** 论文投稿版（零惯性运动学 + 契约审计 C1/C2/C3 + 真分叉 odom + ROS2） | — |
| `dev/stage1-dynamics` | Phase1a：动力学核 + A-mode + 能量审计 EC1-EC3 + 5 注入器 | master `7b54625` |
| `dev/stage2-bmode` | Phase1b：B-mode 力控 + 涌现 gaming 实验 | Phase1a `432d24b` |

### 1.2 权重文件（各自配置，互不覆盖）
| 文件 | 配置 | 性能(N=25/30 固定种子) | 所在分支 |
|---|---|---|---|
| `ppo_embodied_agent.pth` | 🔒论文版 · 零惯性运动学 · obs26/act[v,w] | 成功84%/碰撞12%/超时4% | master |
| `ppo_embodied_agent_dyn.pth` | A-mode 目标速度跟踪动力学 · obs26/act[v,w] | 92%/8%/0% | dev/stage1 |
| `ppo_embodied_agent_bmode.pth` | B-mode 力控(τ=4×步长) · obs28/act[f_l,f_r] | 76%/16%/8% | dev/stage2 |
| `ppo_embodied_agent_bmode_gamed.pth` | B-mode + G-1 故障环境训练（gaming 实验） | 见 §3.2 | dev/stage2 |

### 1.3 当前能力矩阵
| 维度 | 状态 |
|---|---|
| **控制模式** | A=目标速度跟踪(P 控制器)；B=原始轮力力控。共享动力学核（力→牛顿+黏性阻尼→N_SUB 半隐式积分）。`ENABLE_DYNAMICS=False` 退回零惯性运动学（论文版行为） |
| **物理保真度** | 简化动力学（质量/惯量/黏性阻尼）；能量账本精确电报（清洁残差 ~1e-16 J）。**未含**刚体/碰撞动力学 |
| **契约层审计** | C1 真分叉 / C2 帧序单调 / C3 断流即冻结（**未改、回归通过**） |
| **物理层审计** | EC1 能量预算残差 / EC2 无凭空能量 / EC3 执行器速度上限。5 物理注入器 P-1..P-5 自证抓假（A/B 模式各 5/5） |
| **里程计** | 真分叉 odom（吃实际速度 v_act + 打滑漂移），C1 保留 |
| **地图** | 10×10 随机圆形障碍（程序化生成）。**未含**墙体迷宫/动态障碍 |
| **前端** | Three.js 纯观测、断流冻结 OFFLINE（未改）；契约加性新增 v_act/energy 字段 |
| **ROS2** | /odom·/scan·tf + cmd_vel 人工覆盖（未改） |

### 1.4 已知局限
- **A-mode 动力学温和**（τ≈0.055s≪步长、近马尔可夫）→ 旧策略零损迁移、无涌现空间。**B-mode（τ=4×步长）才有有意义惯性 + 涌现 gaming**。
- **涌现 gaming 当前为被动利用**（G-1 故障与"求快"目标对齐，honest 智能体也会白嫖）；强"唯一习得"gaming 需 G-2（奖励次优行为的故障）。
- 能量/物理审计经 get_render_state 消费账本，**沿用契约信任根**（契约=信任边界，见 linchpin 复核）；契约-内核对账(q 类)未做。
- 未做：F4 矩形碰撞 / F2 迷宫 / F3 动态障碍 / B-mode 之外的丰富环境层；未接 MuJoCo。

---

## 2. Phase 演进史（设计决策 + 验证结果）

### Phase0 · 盘点与设计（只读，未改 master）
- 原版(ProductV1.0) vs MVP 功能盘点；审计覆盖度盘点（C1-C3 能抓/抓不到的 false-negative 面）；
  linchpin 复核（信任根=get_render_state 返回字典）；Stage1/Phase1 迁移设计。
- 详情：见 V3 工作目录 `版本功能盘点_原版vsMVP.md` / `审计覆盖度盘点_自欺故障分类地基.md` /
  `审计信任根复核_linchpin确认.md` / `Stage1-动力学迁移设计.md` / `Phase1-富化平台迁移设计.md`。

### Phase1a · 动力学核 + A-mode + 能量审计（dev/stage1-dynamics, `432d24b`）
- **决策**：动作=目标速度(A)，后端 P 控制器→力→动力学核积分；odom 吃 v_act；契约加性 v_act/energy。
- **能量账本精确电报**：v_mid=½(v_n+v_{n+1}) 结算 → 清洁残差 **1.665e-16 J**（优于设计 O(h³) 估计）。
- **A-mode 刹车=真实减速力**（F=-KP·v_act），消除原版 v*=0.5 硬不连续。
- **验证**：维度不变(26/2)；重训 dyn.pth → **92%/8%/0%**；能量审计清洁绿 + 5/5 注入红；契约 C1-C3 无回归。
- **真实教训**：P-5 谎报质量在"定命令"下逃逸（稳态 F=cv 与质量无关）→ 改"变命令(持续暂态)"修复。
- 详情：V3 `Phase1a-动力学实现验证报告.md`。

### Phase1b · B-mode 力控 + 涌现 gaming（dev/stage2-bmode, 本次）
- **决策**：动作=原始轮力(B)，去 P 控制器、复用核；调 F_MAX/ARM 使 **τ_v=0.333s≈4×步长（有意义惯性）**；obs 加速度反馈(28)。
- **验证**：B-mode 重训 → **76%/16%/8%**（力控实质更难，如实）；能量审计 B-mode 清洁绿(4.996e-16) + 5/5 红；A-mode 回归 5/5；契约 C1-C3 无回归。
- **涌现 gaming（关键 SCI 结果）**：注入 G-1「高速白拿推力」可利用故障，对比 honest/gamed 智能体。
  **结果**：boosted 环境下智能体系统性越物理上限（23~29%、顶速越限 33%）、表观性能虚高（成功 +7~10%、步数 -20%），**能量审计判红并定位**（gamed@boosted EC1+EC3 红）。**诚实标注**：此 gaming 为被动利用（honest 也白嫖），非唯一习得；强 gaming 需 G-2。
- 详情：[docs/Phase1b-Bmode-Gaming.md](docs/Phase1b-Bmode-Gaming.md)。

---

## 3. 关键复现命令

```bash
# A-mode 重训（dyn）
EMBODIED_CONTROL_MODE=A EMBODIED_MODEL_PATH=ppo_embodied_agent_dyn.pth python train_agent.py
# B-mode 重训（bmode）
EMBODIED_CONTROL_MODE=B EMBODIED_MODEL_PATH=ppo_embodied_agent_bmode.pth python train_agent.py
# 物理能量审计红绿对照（A 或 B）
EMBODIED_AUDIT_MODE=A python audit/run_physics_audit.py   # → energy_redgreen_matrix_amode.png
EMBODIED_AUDIT_MODE=B python audit/run_physics_audit.py   # → energy_redgreen_matrix_bmode.png
# gaming 智能体训练 + 实验
EMBODIED_CONTROL_MODE=B EMBODIED_BOOST_FORCE=1.5 EMBODIED_MODEL_PATH=ppo_embodied_agent_bmode_gamed.pth python train_agent.py
python audit/run_gaming_experiment.py     # → gaming_compare.png, gaming_summary.json
# 契约层回归
python audit/run_action1.py
```

---

## 4. 下一步候选（待 Abi/Opus 定夺）
- G-2 唯一习得式强 gaming（奖励次优行为的故障）。
- 丰富环境层：F4 矩形碰撞（撞即terminate vs bounce 可配）、F2 40×40 迷宫、F3 动态障碍。
- 契约-内核对账（q 类，破信任根盲区）。
