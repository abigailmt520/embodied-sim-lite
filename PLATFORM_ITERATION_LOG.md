# Embodied-SimLite · 平台迭代主文档（活文档）

> **单一累积文档**：每个平台迭代任务都更新此处。记录各 Phase 的设计决策/实现/验证（真实数字），
> 以及**当前平台状态**（分支、权重、能力、局限）。目的：平台演进可追溯，未来接手者/AI 不必重新逆向。
> 🔴 红线：master `7b54625`（已投稿论文版）**永久冻结**；所有迭代在 dev 分支；论文权重不覆盖。
> 最后更新：2026-06-27（Phase4b 完成）

---

## 1. 当前平台状态（CURRENT STATE）

### 1.1 分支
| 分支 | 内容 | 基于 |
|---|---|---|
| `master` | 🔒 **冻结** 论文投稿版（零惯性运动学 + 契约审计 C1/C2/C3 + 真分叉 odom + ROS2） | — |
| `dev/stage1-dynamics` | Phase1a：动力学核 + A-mode + 能量审计 EC1-EC3 + 5 注入器 | master `7b54625` |
| `dev/stage2-bmode` | Phase1b/1c：B-mode 力控 + G-1/G-2 gaming 实验 | Phase1a `432d24b` |
| `dev/stage3-maze` | Phase2：F4 矩形碰撞 + F2 40×40 迷宫 + 碰撞故障审计 | Phase1c `5e2af1c` |
| `dev/stage4-mi-leakage` | Phase3：契约层互信息泄漏审计（CI，C1 原理化泛化） | Phase2 `3cc426e` |
| `dev/stage5-coupling` | Phase4：双态耦合压测（report×physics 联合审计 + 真/假耦合判据） | Phase3 `af81e14` |
| `dev/stage6-ec5prime` | Phase4b：EC5'（物理内真值-vs-地图）+ 常驻三层套件（判据分离收尾） | Phase4 `9f188b1` |

### 1.2 权重文件（各自配置，互不覆盖）
| 文件 | 配置 | 性能(N=25/30 固定种子) | 所在分支 |
|---|---|---|---|
| `ppo_embodied_agent.pth` | 🔒论文版 · 零惯性运动学 · obs26/act[v,w] | 成功84%/碰撞12%/超时4% | master |
| `ppo_embodied_agent_dyn.pth` | A-mode 目标速度跟踪动力学 · obs26/act[v,w] | 92%/8%/0% | dev/stage1 |
| `ppo_embodied_agent_bmode.pth` | B-mode 力控(τ=4×步长) · obs28/act[f_l,f_r] | 76%/16%/8% | dev/stage2 |
| `ppo_embodied_agent_bmode_gamed.pth` | B-mode + G-1 故障环境训练（**被动 gaming，涌现**） | Phase1b §2.2 | dev/stage2 |
| `ppo_embodied_agent_g2gamed.pth` | B-mode + G-2 故障环境训练（**唯一习得 gaming，未涌现**） | Phase1c §2.2 | dev/stage2 |
| `ppo_embodied_agent_maze.pth` | A-mode + 40×40 迷宫 + 矩形碰撞(bounce) | 成功48%/超时52% | dev/stage3 |

### 1.3 当前能力矩阵
| 维度 | 状态 |
|---|---|
| **控制模式** | A=目标速度跟踪(P 控制器)；B=原始轮力力控。共享动力学核（力→牛顿+黏性阻尼→N_SUB 半隐式积分）。`ENABLE_DYNAMICS=False` 退回零惯性运动学（论文版行为） |
| **物理保真度** | 简化动力学（质量/惯量/黏性阻尼）+ **F4 矩形碰撞**（圆-AABB 穿透推出+回弹 e=0.5）；能量+碰撞账本精确电报（清洁残差 ~1e-16 J）。**未含**刚体接触动力学 |
| **契约层审计** | C1 真分叉 / C2 帧序单调 / C3 断流即冻结（**未改、回归通过**）；**+ CI 互信息泄漏审计**（I(Δodom;Δtruth)≤噪声预算界，C1 原理化泛化，可估区 slip≈0.3 抓 L-1/L-2/L-3） |
| **物理层审计** | EC1 能量预算 / EC2 无凭空能量 / EC3 执行器上限 / EC4 碰撞非负 / EC5 非穿透(账本) / **EC5' 真值-vs-地图(物理内几何重算，不信任账本)**。注入器 P-1..P-5 + CF-1..CF-3（EC5' 零误报，仅真值真穿墙时红）|
| **联合审计（report×physics 常驻）** | `audit_suite` + `joint_audit`：JOINT odom-vs-声称地图。**判据分离**：EC5' 红⇒物理内单层可抓(非耦合)；EC5' 绿 ∧ JOINT 红⇒真耦合（唯联合可抓）。三层常驻套件 `run_suite`（Phase4/4b）|
| **里程计** | 真分叉 odom（吃实际速度 v_act + 打滑漂移），C1 保留；碰撞不修正 odom（守"只漂移不校正"） |
| **地图** | `random_circle` 10×10 随机圆（默认，零回归）/ `maze` **40×40 手工墙体迷宫**（19 AABB，射线-AABB 雷达 + 圆-矩形碰撞）。**未含**动态障碍 |
| **碰撞语义** | `terminate`（撞即终止，论文版）/ `bounce`（穿透推出+回弹+每步接触惩罚 R_CONTACT、不终止，迷宫导航用） |
| **前端** | Three.js 纯观测、断流冻结 OFFLINE（未改）；契约加性新增 v_act/energy 字段 |
| **ROS2** | /odom·/scan·tf + cmd_vel 人工覆盖（未改） |

### 1.4 已知局限
- **A-mode 动力学温和**（τ≈0.055s≪步长、近马尔可夫）→ 旧策略零损迁移、无涌现空间。**B-mode（τ=4×步长）才有有意义惯性 + 涌现 gaming**。
- **涌现 gaming 存在「可发现性-特异性」内在权衡**（Phase1b/1c 实证）：G-1（对齐型，触发于高速）**涌现易但 honest 也白嫖29%**（低特异性）；G-2（反常型，触发于双轮idle）**honest 0%白嫖（高特异性）但 RL 未自发涌现**（exploit 偏离奖励梯度）。能量审计**两者都能在违反发生时判红**（G-2 脚本证明）；难点在「智能体是否表现出违反」。强唯一习得 gaming 需 reward-shaping/课程/甜区 exploit。
- 能量/物理审计经 get_render_state 消费账本，**沿用契约信任根**（契约=信任边界，见 linchpin 复核）；契约-内核对账(q 类)未做。
- **CI 互信息审计在高信噪比（小 slip）退化**：KSG 估计对近确定性通道饱和，部署 slip=0.05（odom 很准）下仅可靠抓全泄漏 L-1，L-2/L-3 漏；此区 C1 幅值检更实用。CI 在可估区（slip≈0.3）干净定量。二者互补。
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

### Phase1c · G-2 唯一习得 gaming（dev/stage2-bmode, 本次）
- **决策**：设计 G-2「idle-coast」故障——仅当**双轮都近零作动（啥也不做）**滑行才白拿大额前向力。
  实测诚实智能体双轮同时 idle 占比=0% → 唯有学会该**反常行为**才获利（高特异性）。
- **🔴 真实负结果（如实报告，INV-E）**：G-2 环境训练的 g2gamed **未涌现** idle-coast（idle 0.0%、性能反降 70% vs 83%）。
  三对照：① 未学会反常行为 ❌；② **honest@g2boosted 0% 白嫖 ✅**（对照 G-1 的 29%，高特异性达成）；
  ③ 审计在该行为发生时**确判红**（脚本化 idle-coast：EC1 残差 0.673J + EC2 + EC3，顶速 2.0）——失败纯在 RL 发现侧、非审计侧。
- **科学发现**：**可发现性-特异性权衡**——对齐型 exploit 涌现易但归因难；反常型 exploit 归因清晰但 RL 难自发发现（off-gradient）。
- 详情：[docs/Phase1c-G2-UniqueGaming.md](docs/Phase1c-G2-UniqueGaming.md)。

### Phase2 · F4 矩形碰撞 + F2 迷宫（dev/stage3-maze, 本次）
- **决策**：地图后端抽象（random_circle 默认零回归 / maze 40×40 手工 19 墙）；F4 圆-AABB 穿透推出+回弹（全后端，复用 old 算法）+ 射线-AABB 雷达；碰撞语义 terminate/bounce 可配。
- **奖励重设计**：bounce 模式撞墙不终止（R_COLLISION −200 终止 → R_CONTACT −5 每接触步），让智能体带真碰撞导航。
- **验证**：maze 重训（A-mode/bounce）成功 48%/超时 52%/平均接触 3.1 步（40×40 对抗迷宫之难，如实）；能量审计 5/5 + 契约 C1-C3 无回归；直冲撞墙推出精确（x 钉 38.8、穿透 0、残差 1e-16）。
- **碰撞故障类**：CF-1 过度回弹增能 / CF-2 不修正穿透 / CF-3 幽灵耗散 + EC4 碰撞非负 / EC5 非穿透。清洁绿 + 3/3 各特征检查判红（CF-1→EC4、CF-2→EC5、CF-3→EC1）。
- **机会性**：honest maze 含碰撞轨迹能量审计 🟢GREEN——无自然碰撞 gaming（诚实回弹只耗能、无甜区 exploit），不强凑。
- 详情：[docs/Phase2-Maze-Collision.md](docs/Phase2-Maze-Collision.md)。

### Phase3 · 契约层互信息泄漏审计 CI（dev/stage4-mi-leakage, 本次，纯审计层新增）
- **决策**：把 C1「误差太小即疑」升级为原理化「I(report;truth) ≤ 噪声预算界」，与物理 EC1 守恒残差对称（双态 formalization 收尾）。KSG k-NN 估 MI、再加噪 MC 操作化噪声预算界、滑窗+持续判据。
- **🔴 修正 Opus 原设计坑**：绝对位置 MI 不可用（dead-reckoning 累积，由轨迹相关性主导）→ 改**逐步增量 MI**（无记忆通道）；闭式 ½log(1+SNR) 对乘性 slip 噪声只近似 → 改再加噪 MC 预算界。
- **验证（slip=0.30 可估区）**：清洁绿（I=2.49≤界2.28+余量）；L-1/L-2/L-3 真实 MI 4.04/3.25/3.07 均超界 → 3/3 判红。
- **与 C1 对照**：C1 仅抓全泄漏 L-1；**CI 还抓 C1 漏的 L-2(部分泄漏仍漂移)/L-3(大误差但确定)** = C1 的原理化定量泛化。
- **🔴 可靠性如实报告**：KSG 对高 SNR 饱和 → 平台部署 slip=0.05（odom 很准、界~3.3nats 逼近估计上限）下 L-1 仍抓、**L-2/L-3 漏**；此区 C1 幅值检更实用。CI 价值在可估区的定量 + 抓 C1 漏项，**与 C1 互补而非全面更强**。
- 详情：[docs/Phase3-MI-Leakage.md](docs/Phase3-MI-Leakage.md)。

### Phase4 · 双态耦合压测 report×physics（dev/stage5-coupling, 本次）
- **目标**：用反自欺纪律压测论文核心论点——「两层各自过、唯联合抓」的耦合自欺**能否真的构造**。
- **实现**：穿墙幽灵故障（碰撞检测剔除一面墙，`embodied_env:691`）+ joint_audit（轨迹 vs 声称地图非穿透）。
- **🔴 核心诚实判据**：真耦合 ⟺ `truth_vs_map 绿 ∧ odom_vs_map 红`（真值合法、唯上报非法 → 既非物理内、也非契约自洽可抓）。
- **场景 A 字面穿墙幽灵（真值真穿墙）**：物理🟢+契约🟢，但 **truth_vs_map 🔴** → **PHYSICS_INTERNAL = 非真耦合**（物理内真值-vs-地图可抓；现有 EC5 漏它仅因信任账本 penetration = EC5 实现缺口）。**未硬凑、如实判非耦合。**
- **场景 B 真耦合变体（真值诚实、odom 伪造穿墙）**：物理🟢+契约🟢+**truth_vs_map 🟢**，唯 **odom_vs_map 🔴** → **TRUE_COUPLING**：真耦合可构造、双态耦合非空。
- **发现**：真耦合的本质是「自欺落在 report 而 physics 真值诚实」；朴素穿墙幽灵是 EC5 缺口冒充耦合，诚实判据把二者分开——避免把「审计缺口」误当「耦合论据」。
- 详情：[docs/Phase4-Coupling-Stress-Test.md](docs/Phase4-Coupling-Stress-Test.md)。

### Phase4b · EC5'（物理内真值-vs-地图）+ 常驻三层套件（dev/stage6-ec5prime, 本次，纯审计层）
- **决策**：补 Phase4 自指的 EC5 缺口——EC5'（`joint_audit.ec5_prime`）不信任账本 penetration、直接用真值对照声称全地图几何重算；joint_audit 固化进常驻三层套件 `audit_suite.run_suite`。
- **场景 A（真值真穿墙）**：EC1-EC5 🟢 但 **EC5' 🔴**（真值落墙 0.200m）→ **PHYSICS_INTERNAL**：物理层单层抓 → 坐实「场景 A=单层缺口（已补 EC5'）、非耦合」。
- **场景 B（真值合法、odom 伪造穿墙）**：物理层(含 EC5')🟢 + 契约 🟢 + **EC5' 🟢（未替 joint 充数）**，唯 **JOINT 🔴** → **TRUE_COUPLING**：坐实「场景 B=真耦合、唯 joint 抓」。
- **🔴 诚实判据**：EC5' **零误报**（30 回合健康 maze 0/30；CF-2/幽灵墙真值真穿墙才红=真违反非误报）；EC5' 未替 joint 充数（场景 B EC5' 绿）；判据分离干净。**未调参硬压。**
- 无回归（CF 3/3、P 5/5、C1-3、CI 3/3）；env 未改。
- 详情：[docs/Phase4b-EC5prime-Suite.md](docs/Phase4b-EC5prime-Suite.md)。

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
# G-1 被动 gaming 训练 + 实验
EMBODIED_CONTROL_MODE=B EMBODIED_BOOST_FORCE=1.5 EMBODIED_MODEL_PATH=ppo_embodied_agent_bmode_gamed.pth python train_agent.py
python audit/run_gaming_experiment.py     # → gaming_compare.png, gaming_summary.json
# G-2 唯一习得 gaming 训练 + 实验
EMBODIED_CONTROL_MODE=B EMBODIED_G2_FORCE=6.0 EMBODIED_MODEL_PATH=ppo_embodied_agent_g2gamed.pth python train_agent.py
python audit/run_g2_gaming_experiment.py  # → g2_gaming_compare.png, g2_gaming_summary.json
# 迷宫(maze) + 矩形碰撞 训练 + 碰撞保真度审计
EMBODIED_CONTROL_MODE=A EMBODIED_MAP_TYPE=maze EMBODIED_MODEL_PATH=ppo_embodied_agent_maze.pth python train_agent.py
python audit/run_collision_audit.py       # → collision_redgreen_matrix.png（CF-1/2/3 红绿对照）
# 契约层互信息泄漏审计 CI（+ 与 C1 对照）
python audit/run_leakage_audit.py         # → leakage_compare.png（slip 0.30/0.05 双区）
# 双态耦合压测 report×physics（真/假耦合判据）
python audit/run_coupling_test.py         # → coupling_summary.json（场景A非耦合/场景B真耦合）
# 契约层回归
python audit/run_action1.py
```

---

## 4. 下一步候选（待 Abi/Opus 定夺）
- 三层套件 `audit_suite` 接入 inference_server 运行时流（real-time 联合监控）。
- F3 动态障碍（巡逻车，移动 AABB；可能提供碰撞/避让甜区 gaming substrate）。
- 提升 maze 成功率：简化迷宫 / 课程学习 / B-mode 力控迷宫策略；前端渲染迷宫墙体（契约已导出 walls）。
- 桥接「可发现性-特异性权衡」：reward-shaping/课程学习引导 G-2 涌现，或换更强探索（RND/model-based）。
- 契约-内核对账（q 类，破信任根盲区）。
