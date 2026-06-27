# Phase2 详情：F4 矩形碰撞 + F2 迷宫（丰富环境层，设计 + 验证）

> 分支 `dev/stage3-maze`（off Phase1c `5e2af1c`）。master `7b54625` 冻结零改动；论文/dyn/bmode/bmode_gamed/g2gamed.pth 均不覆盖。
> 数字真实运行所得（INV-E）；带行号（INV-B）。🔴 物理/碰撞/lidar 全后端，前端纯观测不变（INV-D）。

---

## 1. 里程碑1 · F4 矩形碰撞 + F2 迷宫 + 奖励重设计

### 1.1 地图后端抽象（embodied_env.py）
- `map_type`（`:149-163`）：`random_circle`（默认，10×10 随机圆，**Phase0-1c 行为逐字节保留、零回归**）/ `maze`（40×40 手工墙体迷宫）。
- `MAZE_WALLS`（`:109-129`）：**19 段 AABB**（4 外墙 + 死亡长廊/混沌迷宫/U型死锁谷/极限一线天，移植 old:616-640 的命名场景到 [0,40]）。
- 实例化 arena 尺寸/墙列表/碰撞语义；`random_circle` 无内墙、`maze` 19 墙。

### 1.2 F4 矩形碰撞（全后端，复用 old 算法）
- **射线-AABB 雷达**（`_ray_aabbs` `:607`，slab 法向量化 over 射线）：maze 用之（含外墙）；random_circle 仍用 `_ray_walls`（场地边界）。🔴 全后端解析，非原版前端 raycasting。
- **圆-AABB 碰撞 + 穿透推出**（`_circle_aabb_overlap` `:641` + `_resolve_wall_collisions` `:668`）：AABB 最近点求穿透，沿法向推出（圆心入框时沿最小穿透轴，old:649-655）；**2 次迭代解角落**（old:645）。
- **回弹**（`BOUNCE=0.5` `:106`）：撞墙后 `v_act,w_act ← e·(·)`，KE 掉到 e²，**E_contact=(1−e²)·KE_前 ≥ 0 耗散**（复刻 old 的 v*=0.5 衰减，非真 2D 反射——unicycle 标量模型一致）。
- **odom 不做碰撞修正**（守审计哲学，不复活 old:744 的隐式校正）。
- 实测（直冲外墙）：机器人被钉在 x=38.8（=39−半径，推出精确）、v_act 撞后 ×0.5、**残余穿透=0**、E_contact_act==E_contact_decl=0.24（≥0）、能量残差 ~1e-16 J。

### 1.3 🔴 碰撞语义 + 奖励重设计
- `collision_mode`：`terminate`（论文版，撞即终止+R_COLLISION=−200，random_circle 默认）/ `bounce`（maze 默认）。
- **bounce 重设计**（`_compute_reward` `:523`）：撞墙**不终止**（已推出+回弹），改**每接触步 R_CONTACT=−5**（`:107`）；仅到达终止、超时截断。
- **对 R_COLLISION/训练的影响**：终止式 −200 大额惩罚 → 每步 −5 小额接触惩罚；回合**更长**（无猝死，平均 402 步、52% 超时），智能体学会**带真碰撞导航**（平均 3.1 接触步——撞墙后回弹继续而非死亡），这正是丰富环境层的目标。

### 1.4 重训 maze 策略（ppo_embodied_agent_maze.pth）
- A-mode（迷宫导航用目标速度更易学）、maze、bounce，1.5M steps（~2900 fps，19 墙 lidar/碰撞略慢）。
- **N=25 固定种子评测**：成功 **48%** (12/25) / 超时 **52%** / 平均 402 步 / 平均接触 3.1 步。
- **如实声明**：48% 反映 40×40 **对抗性迷宫**之难（原版为「击败 SLAM/Nav2」而设计：死亡长廊/U型死锁/一线天）。这是真碰撞物理 + 复杂拓扑的诚实数字，非退步；简化迷宫/更多步数/B-mode 可提升，但 F4/F2 实现本身是本 Phase 交付。

### 1.5 无回归确认
- **能量审计**（random_circle，EMBODIED_AUDIT_MODE=B）：清洁绿（残差 4.996e-16）+ **P-1..P-5 5/5 判红**。
- **契约 C1/C2/C3**：门1（3/3 注入红）+ 门2（健康全绿）+ 门3（84%）——全通过。
- `audit_session` 加 `with_collision` 开关（默认 False）→ 旧调用零影响；EC1 加 E_contact_decl 项在无碰撞时退化（E_contact=0）→ 旧 P 审计不变。

---

## 2. 里程碑2 · 碰撞保真度故障类 + 审计

### 2.1 三个碰撞自欺注入器（physics_injection.py，藏 `_resolve_wall_collisions` 内）
| 注入 | 改了什么（行号） | 破坏的守恒律 |
|---|---|---|
| **CF-1 over_bounce** | 回弹恢复系数 e=1.3>1（`_resolve_wall_collisions` 读 `bounce_eff` `:685`） | 碰撞能量非负（碰撞凭空增能） |
| **CF-2 skip_pushout** | 跳过穿透推出（机器人留墙内，`skip_pushout` `:686`） | 非穿透不变量 |
| **CF-3 phantom_contact** | 账本声称碰撞耗散、实际不衰减速度（`phantom_contact` `:687`） | 能量账本自洽（碰撞版波将金村） |

### 2.2 新增审计检查（energy_audit.py）
- **EC1 扩展**：预算残差 `r = ΔE − (W_act − D_damp − E_contact_decl)`（含声称碰撞耗散；无碰撞退化为原式）。
- **EC4 COLLISION_NONNEG**：`E_contact_act ≥ 0`（碰撞只耗能不增能，单帧增能即判）。
- **EC5 NON_PENETRATION**：解算后 `penetration ≤ 1e-4 m`（推出后不得与墙重叠）。

### 2.3 验证（真实数字，`audit/run_collision_audit.py`，证据图 `collision_redgreen_matrix.png`）
**门 C2 清洁**：EC1-EC5 全绿，18 碰撞帧、能量残差 **1.943e-16 J**、残余穿透 **0 m**。
**门 C1 三注入 3/3 判红并定位**（各由特征检查抓住）：
| 注入 | EC1 | EC4 | EC5 | 抓假 | 定位 |
|---|:---:|:---:|:---:|:---:|---|
| 清洁 | 🟢 | 🟢 | 🟢 | — | 残差1.9e-16 |
| CF-1 过度回弹 | 🔴 | 🔴 | 🟢 | ✅ | E_contact_act=−0.221 J @step23 |
| CF-2 不修正穿透 | 🟢 | 🟢 | 🔴 | ✅ | penetration=0.698 m @step34 |
| CF-3 幽灵耗散 | 🔴 | 🟢 | 🟢 | ✅ | 残差 0.240 J @step23 |

- 每注入有**特异签名**：CF-1→EC4（碰撞增能）、CF-2→EC5（残余穿透）、CF-3→EC1（声称耗散无实损）。无漏网、无误报。

### 2.4 机会性观察：迷宫+碰撞环境的自然 gaming（不强凑）
- honest maze 智能体含碰撞轨迹跑能量+碰撞审计 → **🟢GREEN**：未自然出现碰撞能量 gaming。
- 分析：诚实回弹（e≤1）**只耗能**，无可利用的碰撞能量漏洞——除非注入（CF-1 等），否则无甜区 exploit。与 G-1/G-2 一致：审计在**违反发生时**判红，honest 无违反则绿。承接 Phase1c 的「可发现性-特异性权衡」：碰撞场景未自然提供对齐型甜区 exploit。

---

## 3. 待办 / 范围外（INV-C）
- 未做：F3 动态障碍（下一任务）；未接 MuJoCo（自建轻量富化）；未碰契约层 C1-3 代码；未做 q 类对账；未强凑碰撞 gaming 桥接。
- 前端渲染迷宫墙体（get_render_state 已加性导出 `walls` 字段，前端可消费；前端仍纯观测，本 Phase 未改前端代码）。
- 提升 maze 成功率：简化迷宫 / 课程学习 / B-mode 力控版迷宫策略 —— 留待。
