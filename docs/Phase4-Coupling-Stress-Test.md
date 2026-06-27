# Phase4 详情：双态耦合压测（report×physics）—— 用反自欺纪律压测核心论点本身

> 分支 `dev/stage5-coupling`（off Phase3 `af81e14`）。master `7b54625` 冻结零改动；所有已有 .pth 不覆盖。
> 数字真实运行（INV-E）；带行号（INV-B）。🔴 本 Phase 的最高纪律：**诚实判定耦合是否真实存在，绝不调参硬凑**。

---

## 0. 命题与最重要的诚实判据
**目标**：构造一个自欺，使 (a) 契约层单独跑=过、(b) 物理层单独跑=过，但 (c) report×physics 联合=抓住。
这才证明「双态耦合」，而非两个并排审计。

**🔴 真耦合 vs 假耦合的判别（本 Phase 的核心贡献）**：仿真有两条位置信号——
`truth`（物理真值）与 `odom`（契约上报）。穿墙自欺是否**真耦合**，由 `truth_vs_map` 判别：
- **`truth_vs_map` 红**（真值真穿墙）→ 物理内（真值 vs 地图，二者都在物理侧）**独力可抓** → **非真耦合**（只是 EC5 实现缺口）。
- **`truth_vs_map` 绿 且 `odom_vs_map` 红**（真值合法、唯上报非法）→ 既非物理内、也非契约自洽可抓，**唯 report×physics 联合可抓** → **真耦合**。

判据形式化（`joint_audit.coupling_verdict` `:60`）：`truth_vs_map.ok ∧ ¬odom_vs_map.ok ⟺ TRUE_COUPLING`。

---

## 1. 实现
- **穿墙幽灵物理故障**（`embodied_env._resolve_wall_collisions:691-693`）：`physics_fault["phantom_walls"]=[idx]`
  使碰撞检测层**剔除指定墙** → 机器人「合法地」穿过（不碰撞、动量守恒、能量自洽，账本 penetration 仍 0）。
- **联合审计**（`joint_audit.py`）：`traj_vs_map`（`:37`）逐帧查机器人圆是否落入声称墙 AABB；
  `coupling_verdict`（`:60`）返回 `truth_vs_map / odom_vs_map / verdict∈{TRUE_COUPLING, PHYSICS_INTERNAL, NO_VIOLATION}`。
- **压测**（`run_coupling_test.py`）：两场景各跑 物理 EC1-EC5 + 契约 C1/C2/C3+CI + 联合 truth/odom_vs_map。

---

## 2. 场景 A · 字面「穿墙幽灵」（真值真穿墙）—— 🔴 如实判：**非真耦合**
`scenario_a` (`:88`)：迷宫内剔除死亡长廊左墙(idx4)，机器人 [v=1] 直冲穿过。**真实运行结果**：
| 层 | 结果 |
|---|---|
| 物理层 EC1-EC5 | 🟢 全过（无碰撞→无能量异常，账本 penetration=0）|
| 契约层 C1/C2/C3+CI | 🟢 全过（odom 是真值的诚实 dead-reckoning）|
| 联合 truth_vs_map | **🔴 真值穿墙** |
| 联合 odom_vs_map | 🔴 上报穿墙 |
| **判定** | **PHYSICS_INTERNAL** |

**🔴 诚实结论**：字面穿墙幽灵**不是真耦合**。`truth_vs_map` 红 = 真值真穿墙 → **物理内（真值 vs 声称地图）独力可抓**，
不需上报通道。当前 EC1-EC5 漏它，**仅因 EC5 信任账本的 penetration 字段**（幽灵墙不在碰撞系统 → 报 0），
是 **EC5 实现缺口**（与 linchpin 信任根盲区同源），而非「必须靠两层耦合」。一个完善的 EC5'（独立用真值 vs 声称
全地图重算穿透）就能物理内抓住它。**未为凑耦合而调参——如实判 PHYSICS_INTERNAL。**

---

## 3. 场景 B · 真耦合变体（真值诚实，odom 伪造穿墙）—— ✅ **真耦合**
`scenario_b` (`:104`)：真值诚实跑（被 idx4 墙挡住、合法回弹），但 odom 被伪造成一条匀速直线穿墙航迹
（内部自洽 dead-reckoning）。**真实运行结果**：
| 层 | 结果 |
|---|---|
| 物理层 EC1-EC5 | 🟢 全过（真值诚实动力学）|
| 契约层 C1/C2/C3+CI | 🟢 全过（伪造 odom 匀速自洽：C1 误差大→不疑泄漏、CI 低 MI、C2/C3 正常）|
| 联合 truth_vs_map | **🟢 真值合法** |
| 联合 odom_vs_map | **🔴 上报穿墙** |
| **判定** | **TRUE_COUPLING** |

**结论**：真耦合**可构造**。真值合法（物理内 truth_vs_map 绿）+ 物理层过 + 契约层过，**唯 `odom_vs_map`(report×physics) 红**
→ 既非物理内（真值合法）、也非契约自洽（odom 自洽）可抓，**唯把上报轨迹对照声称物理地图的联合检查可抓**。
这是双态耦合的真实存在性证明。

---

## 4. 核心发现（供论文）
1. **「两层各自过、唯联合抓」的真耦合自欺确实存在**（场景 B）——双态耦合非空，论点成立。
2. **但耦合的本质是「自欺落在 report，而 physics 真值诚实」**：判据 = `truth_vs_map 绿 ∧ odom_vs_map 红`。
   若真值本身违反物理（truth_vs_map 红），则物理内可抓、不构成真耦合（场景 A）。
3. **反例的价值**：朴素的「穿墙幽灵」（真值穿墙）**看起来**像耦合（现有 EC/契约都过、只有联合红），
   但那是 **EC5 实现缺口**冒充耦合。诚实判据 `truth_vs_map` 把二者分开，避免把「审计缺口」误当「耦合论据」——
   这正是用反自欺纪律压测论点本身：**真耦合的论据必须排除「单层本可抓、只是没实现」的伪耦合**。
4. **平台启示**：现有物理层 EC5 信任账本 penetration（未独立重算真值 vs 地图）→ 建议补 EC5'（物理内真值 vs 声称地图）
   以堵场景 A 类缺口；而场景 B 类真耦合则**必须**靠 report×physics 联合审计层（本 Phase 新增 joint_audit）。

---

## 5. 待办 / 范围外（INV-C）
- 把 joint_audit 接入运行时审计管线（real-time 联合监控）；补 EC5' 物理内真值-vs-地图重算（堵场景 A 缺口）。
- 未接 MuJoCo；未碰契约 C1-3 / 物理 EC1-5 既有判据；未做 F3 动态障碍；未做 q 类对账（contract-内核独立通道仍 out of scope）。
- 无回归：碰撞 CF 3/3、能量 P 5/5、契约 C1-3、maze env_checker 均通过（env 仅加 phantom_walls 测试钩子）。
