# Phase1b 详情：B-mode 力控 + 涌现 gaming 实验（设计 + 验证）

> 分支 `dev/stage2-bmode`（off Phase1a `432d24b`）。master `7b54625` 论文版冻结零改动；论文 .pth / dyn.pth 不覆盖。
> 所有数字均真实运行所得（INV-E）；带文件行号（INV-B）；区分已验证/待办（INV-C）。

---

## 1. 里程碑1 · B-mode 力控

### 1.1 设计与实现（embodied_env.py）
- **动作语义**：`action=[f_l,f_r]` 归一化轮力 ∈[-1,1]（×F_MAX 还原）。去掉 A-mode 的 P 控制器外壳，
  `force=f_l+f_r`、`torque=(f_r-f_l)·ARM`（old:708-709）直接喂**共享动力学核** `_integrate_dynamics`。
  - 实现：`_step_dynamics_B`（`embodied_env.py:309-319`），常值力闭包；step 分派（`:235`）。
- **共享核复用**：动力学/阻尼/能量账本与 A-mode 同一 `_integrate_dynamics`（`:321`）——审计作用于核、与控制模式无关。
- **有意义惯性（关键调参）**：B-mode 速度时间常数 `τ_v = MASS/C_LIN = 1.0/3.0 ≈ 0.333s ≈ 3.3×DT`
  （无 P 控制器压缩；A-mode 因 KP 而 τ≈0.055s≪DT 退化）。**实测**：双轮满力从静止，v_act 到 63.2% 用时 ≈ **0.4s = 4×步长**。角速度 `τ_w = I/C_ANG = 0.167s ≈ 1.67×DT`。
- **调参**（`embodied_env.py:74-77`）：`F_MAX=2.25, ARM=0.8`（复用 MASS=1.0, C_LIN=C_ANG=3.0, INERTIA_COEF=0.5, N_SUB=5）→ 稳态顶速 `v_ss_max=2·F_MAX/C_LIN=1.5 m/s`、`w_ss_max=2·F_MAX·ARM/C_ANG=1.2 rad/s`。
- **观测扩维**：B-mode obs 加 `[v_act_norm, w_act_norm]`（`_get_obs` `:474-478`）——力控下速度是显著隐藏态（τ≈3×步长），需入观测做信用分配。维度 26→**28**；动作 [0,1]×[-1,1] → **[-1,1]²**（`__init__` `:129-148`）。
- **A-mode 完全保留**：`control_mode="A"` 默认，obs26/act 原样（Phase1a 不受影响，回归通过）。

### 1.2 验证（真实数字）
| 验收点 | 结果 |
|---|---|
| `check_env` A/B 双模式 | ✅ 通过 |
| 维度 | A: obs(26)/act(2)；B: obs(28)/act(2,[-1,1]) |
| **有意义惯性** | τ_v≈0.4s = **4×DT**（A-mode 曾 0.055s≪DT） |
| B-mode 清洁能量残差 | **8.327e-17 J**（机器精度，核电报对 B 同样精确） |
| **重训 ppo_embodied_agent_bmode.pth** | 1M steps，~3640 fps |
| **N=25 评测** | 成功 **76%** / 碰撞 **16%** / 超时 **8%**；avg 步数 135；清洁顶速 1.42（上限 1.50） |

> **如实声明**：B-mode 76% 低于 A-mode dyn(92%) 与论文版(84%)——力控含真惯性(τ=4×步长)是**实质更难**的控制问题（信用分配跨两次积分、高速惯性更易撞障）。这正是「更能打 + 有涌现空间」的代价，非退步。

### 1.3 能量审计在 B-mode 下仍工作（审计在核上、模式无关）
`audit/run_physics_audit.py` 已模式化（`EMBODIED_AUDIT_MODE=B`，B-mode 用力命令驱动）：
- **门 P2 清洁**：EC1/EC2/EC3 全绿，残差 **4.996e-16 J**。
- **门 P1 五注入 5/5 判红并定位**（`audit/energy_redgreen_matrix_bmode.png`）。
- P-4（skip_lag）改为**模式感知**（`embodied_env.py:365-374`）：B-mode 用力的诚实稳态速度 `F/c`（有界），修复了原 A-mode 公式在 B-mode 复利发散（OverflowError）的真实 bug。
- **A-mode 回归**：改 P-4 后 A-mode 仍 5/5 + 清洁 1.665e-16 J（`energy_redgreen_matrix_amode.png`）。

### 1.4 契约层无回归
`audit/run_action1.py`：门1（3/3 注入判红）+ 门2（健康全绿）+ 门3（84%）——**C1/C2/C3 在 B-mode 改动后完整通过**（未改契约层一行）。

---

## 2. 里程碑2 · 涌现 gaming 实验（关键 SCI 结果）

### 2.1 可利用故障设计 G-1「高速白拿推力」
- **注入**（`embodied_env.py:346-347, 375`）：当 `|v_act| > boost_thresh(1.05)`，沿运动方向施加**免费推力** `boost_force(1.5 N)`，**账本不计**该力。
- **为何对智能体有利可图**：越过阈值即白拿能量、顶速从诚实 `v_ss_max=1.5` 升到 `(2F_MAX+boost)/C=2.0 m/s`；
  「求快到目标」的智能体（少步数=少 STEP_PENALTY、早拿 R_GOAL）会**乐于维持高速**享受加速。
- **训练注入**：`train_agent.make_env` 经 `EMBODIED_BOOST_FORCE` 在训练环境常驻 G-1（`train_agent.py`）。
- **对照**：`honest`=清洁环境训练（ppo_embodied_agent_bmode.pth）；`gamed`=G-1 环境训练（ppo_embodied_agent_bmode_gamed.pth）。同架构/超参/步数，唯一差别=训练环境是否含 G-1。

### 2.2 结果（`audit/run_gaming_experiment.py`，N=30，真实运行）
| 智能体@环境 | 成功 | 碰撞 | avg步数 | 顶速 max | 越物理上限占比 | 能量审计 |
|---|---|---|---|---|---|---|
| honest@clean | 80% | 13% | 135 | 1.500 | **0.0%** | 🟢 GREEN |
| honest@boosted | 87% | 10% | 114 | 1.999 | **29.2%** | (会红) |
| gamed@boosted | 90% | 7% | 111 | 1.997 | **23.1%** | 🔴 **RED** |
| gamed@clean | 87% | 7% | 142 | 1.500 | 0.0% | 🟢 GREEN |

证据图：`audit/gaming_compare.png`（gamed@boosted 速度轨迹系统性越 1.5 物理上限、峰值 ~2.0）。

### 2.3 判定与诚实分析（INV-D / INV-E）
**✅ gaming 出现（在"性能虚高 + 审计可抓"的意义上，稳健成立）**：
1. **物理 bug 抬高表观性能**：任何智能体在 boosted 环境成功率 +7~10%、步数 -20%（gamed@boosted 90%/111步 vs gamed@clean 87%/142步——**同一策略**，bug 在场即更"强"）。
2. **轨迹变非物理**：23~29% 的步越诚实物理上限，顶速 **越限 33%**（2.0 vs 1.5）——无 bug 时物理不可能。
3. **能量审计抓住**：gamed@boosted **🔴RED**（EC1 残差 0.209 J @step60 = 未计的 boost 做功；EC3 越速 @step81），honest@clean 🟢GREEN。**单看成功率（90%>80%）会把 gaming 当"更好"——审计揭穿了它。** 这正是双态审计的命题。

**⚠️ 但要诚实说清 gaming 的"性质"**（不夸大）：
- 此处 gaming 是**被动/机会主义利用**，**非**唯一习得的隐藏 exploit。证据：**honest@boosted（29.2%）越上限占比 ≥ gamed@boosted（23.1%）**——清洁训练的智能体放进 boosted 环境**照样**白嫖加速，不需专门"发现"。
- **原因分析**：G-1 是**常驻、阈值(1.05)低于自然巡航速(~1.4)**的故障，与"求快"目标天然对齐——任何高速策略被动触发，无需异常行为。故训练于 boosted 环境的 gamed 并未学出**显著不同**的剥削策略（它学到的是在高速区**控制得更稳**：成功 90%、碰撞 7% 优于 honest@boosted 的 87%/10%）。
- **要得到"唯一习得"的强 gaming**：故障应**奖励一个本来次优的行为**（如自旋、振荡推力才触发的能量泄漏），使只有专门学会该行为的智能体获益。这是后续可加的 G-2 设计（留待）。

### 2.4 SCI 价值小结
本实验**真实证明**了双态审计的核心命题：**仿真保真度 bug 会使智能体表现"更好"（高成功率、少步数），而这"更好"恰恰来自物理不可能的轨迹；性能指标会奖励它，能量审计则判红并定位。** 这是 performance-metric-only 评测看不见的自欺。gaming 的"被动 vs 主动"性质已如实标注，并给出强化路径（G-2）。

---

## 3. 待办 / 范围外（INV-C）
- 未做：F4 矩形碰撞 / F2 迷宫 / F3 动态障碍（下一阶段丰富环境层）；未接 MuJoCo；未碰契约层 C1/C2/C3 代码；未做 q 类契约-内核对账。
- G-2「奖励一个次优行为的故障」以获得唯一习得式强 gaming —— 留待。
- 能量审计经 get_render_state 消费账本，沿用契约信任根（与 linchpin 复核一致）。
