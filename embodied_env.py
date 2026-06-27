# -*- coding: utf-8 -*-
"""
embodied_env.py
================
Embodied-SimLite 轻量化具身智能孪生环境（标准 gymnasium.Env 封装）。

设计哲学：
    本环境是「算力置换架构」的物理内核。它本身**不包含**任何网络/渲染/异步时钟逻辑，
    是一个纯 numpy 的同步函数式状态机。这样保证了：
        - 训练期：被 train_agent.py 以硬件极限速度反复调用 step()，单核满载狂奔；
        - 推理期：被 inference_server.py 以 60Hz 异步心跳节流调用，对外广播孪生状态。
    同一份物理内核，两种调度外壳，互不污染。

物理模型（刻意极简，零刚体动力学依赖）：
    - 运动学积分（差速底盘 / unicycle 模型）：
          theta_{t+1} = theta_t + w * dt
          x_{t+1}     = x_t + v * cos(theta) * dt
          y_{t+1}     = y_t + v * sin(theta) * dt
    - 防穿模：圆形障碍物 + 圆形底盘，单障碍检测为 O(1)（圆心距 < 半径和即碰撞）。
    - LiDAR：解析式「射线-圆」与「射线-墙」求交，无需逐像素扫描，单射线-单障碍亦为 O(1)。
"""

import numpy as np
import gymnasium as gym
from gymnasium import spaces


class EmbodiedNavEnv(gym.Env):
    """轻量化自主导航避障环境。

    观测空间 (Observation, 连续)：
        [ lidar_0 ... lidar_{N-1},  dist_norm,  yaw_err_norm ]   维度 = N + 2
        - lidar_i      : 第 i 根激光射线归一化测距，∈ [0, 1]（1 表示无障碍达到量程上限）
        - dist_norm    : 底盘到目标点的相对距离 / 场地对角线，∈ [0, 1]
        - yaw_err_norm : 朝向目标的偏航角误差 / π，∈ [-1, 1]

    动作空间 (Action, 连续)：
        [ v, w ]
        - v : 线速度指令，∈ [0, 1]    （内部乘以 MAX_LIN_VEL 还原为真实 m/s，不允许倒退）
        - w : 角速度指令，∈ [-1, 1]   （内部乘以 MAX_ANG_VEL 还原为真实 rad/s）
    """

    metadata = {"render_modes": [None]}

    # ====================== 物理 / 场景 常量 ======================
    ARENA_W = 10.0          # 场地宽 (m)
    ARENA_H = 10.0          # 场地高 (m)
    ROBOT_RADIUS = 0.20     # 底盘半径 (m)
    GOAL_RADIUS = 0.40      # 到达判定半径 (m)
    DT = 0.10               # 运动学积分步长 (s)，对应 10Hz 决策频率

    MAX_LIN_VEL = 1.0       # 线速度上限 (m/s)，v=1.0 时的目标速度（A-mode 指令上限）
    MAX_ANG_VEL = 1.5       # 角速度上限 (rad/s)，|w|=1.0 时的目标角速度

    # ====================== 动力学核（Phase1a · F1 简化动力学迁后端）======================
    # 设计：动作 [v,w] 解释为「目标速度」；后端用 质量/惯量/黏性阻尼 把「实际速度」
    #       一阶趋向目标，再由实际速度积分位姿。零刚体依赖、纯 numpy、可解析能量审计。
    # 分层：_integrate_dynamics() 是共享核（接受 力/力矩 函数）；A-mode 在其外包一层 P 控制器
    #       （目标速度→力）。未来 B-mode 直接喂原始轮力 [f_l,f_r]，复用同一核。
    ENABLE_DYNAMICS = True   # True=力控动力学（含惯性/阻尼）；False=退回原零惯性运动学（回归对照）
    MASS         = 1.0       # 车体质量 m (kg)（沿用原版默认 old:710）
    INERTIA_COEF = 0.5       # 转动惯量 I = INERTIA_COEF * MASS（沿用原版 κ=0.5, old:711）
    C_LIN        = 3.0       # 线性黏性阻尼系数 (kg/s)：把原版后乘 *0.95 改写为标准力项 -c·v（可审）
    C_ANG        = 3.0       # 角向黏性阻尼系数
    KP_V         = 12.0      # A-mode 速度跟踪 P 增益（目标速度→执行器力）
    KP_W         = 12.0      # A-mode 角速度跟踪 P 增益
    N_SUB        = 5         # 每个 env.step 的物理子步数（h = DT / N_SUB）

    # ---------------------- B-mode 力控（Phase1b）----------------------
    # 动作 = 原始轮力 [f_l, f_r]（归一化 ∈[-1,1]，内部 ×F_MAX）。去掉 A-mode 的 P 跟踪层，
    # 直接 force=f_l+f_r、torque=(f_r-f_l)·ARM（old:708-709），喂同一动力学核。
    # 「有意义惯性」：B-mode 速度时间常数 τ_v = MASS/C_LIN（无 P 控制器加速），
    #   = 1.0/3.0 ≈ 0.333s ≈ 3.3×DT —— 与步长可比/更大（A-mode 因 KP 而 τ≈0.055s≪DT 退化）。
    F_MAX        = 2.25      # 单轮力上限 (N)：双轮满力 force=2·F_MAX → 稳态 v_ss_max=2·F_MAX/C_LIN=1.5 m/s
    ARM          = 0.8       # 差动力臂；torque=(f_r-f_l)·ARM → 稳态 w_ss_max=2·F_MAX·ARM/C_ANG=1.2 rad/s
    # B-mode 物理速度上限（稳态顶速 + 10% 余量供 EC3 越界判定；超过即非物理）
    V_PHYS_MAX_B = (2.0 * F_MAX / C_LIN) * 1.10
    W_PHYS_MAX_B = (2.0 * F_MAX * ARM / C_ANG) * 1.10

    # 执行器物理速度上限（A-mode：稳态 v_ss=KP/(KP+C)·MAX，留 25% 余量供越界审计 EC3 判定）
    V_PHYS_MAX   = MAX_LIN_VEL * 1.25
    W_PHYS_MAX   = MAX_ANG_VEL * 1.25

    # ====================== 里程计漂移（D-018：Odom 真打滑）======================
    # 轮式里程计相对真值的「打滑系数」：odom 积分施加乘性偏差 + 同量级比例噪声，
    # 使里程计随行程单调偏离真值（真分叉）。=0 时 odom 与 truth 逐位重合，
    # 退化为原理想运动学内核——作为 before 对照档与「无打滑」回归基准。
    SLIP_FACTOR = 0.05

    N_RAYS = 24             # LiDAR 核心射线数（降采样后）
    LIDAR_RANGE = 5.0       # LiDAR 量程上限 (m)
    LIDAR_FOV = 2.0 * np.pi # 视场角，2π 表示 360° 环视

    N_OBSTACLES = 6         # 圆形障碍物数量
    OBS_R_MIN = 0.4         # 障碍物半径下限
    OBS_R_MAX = 0.9         # 障碍物半径上限

    MAX_STEPS = 500         # 单回合步数上限（用于 truncated）

    # ====================== 奖励函数 权重 ======================
    # 【核心调参区】下列权重直接决定智能体的「性格」，注释给出工程含义与调参方向。
    K_PROGRESS   = 30.0     # ↑ 稠密进度奖励：每靠近目标 1m 给 +30。这是学习的主信号，
                            #    必须显著大于其它项，否则智能体会陷入原地观望的局部最优。
    R_GOAL       = 200.0    # ↑ 到达目标的阶段性大额正奖励（触发 terminated）。
    R_COLLISION  = -200.0   # ↓ 碰撞的大额负奖励（触发 terminated）。与 R_GOAL 量级对称，
                            #    避免智能体学会「宁可撞墙也要冲目标」的赌徒策略。
    STEP_PENALTY = -0.5     # ↓ 每步固定惩罚：逼迫智能体走最短路径，规避冗余兜圈。
    K_SAFETY     = 2.0      # ↓ 近距安全软惩罚系数：进入安全缓冲区后线性增大惩罚，
                            #    在「硬碰撞」之前提前塑造避让行为，让学习曲线更平滑。
    SAFE_DIST    = 0.6      # 安全缓冲区距离阈值 (m)，min(lidar) 小于它即开始软惩罚。
    K_SMOOTH     = 0.3      # ↓ 角速度平滑惩罚系数：抑制原地高频抖动，输出更顺滑的轨迹。

    def __init__(self, render_mode=None, seed=None, slip=None, control_mode="A"):
        super().__init__()
        self.render_mode = render_mode
        # 里程计打滑系数（可配置）：None 取类常量 SLIP_FACTOR；显式传 0.0 即关闭漂移
        self.slip_factor = float(self.SLIP_FACTOR if slip is None else slip)

        # 控制模式：'A'=目标速度跟踪（Phase1a，obs26/act[v,w]）；'B'=原始轮力（Phase1b，obs28/act[f_l,f_r]）
        assert control_mode in ("A", "B"), "control_mode 必须为 'A' 或 'B'"
        self.control_mode = control_mode

        # 观测空间：N 根 lidar(0~1) + dist(0~1) + yaw_err(-1~1)；B-mode 额外加 v_act/w_act 反馈
        #   （力控下速度是显著隐藏态，τ≈3×步长，智能体需观测实际速度方能做力→运动信用分配）
        base_low = [np.zeros(self.N_RAYS, dtype=np.float32),
                    np.array([0.0, -1.0], dtype=np.float32)]
        base_high = [np.ones(self.N_RAYS, dtype=np.float32),
                     np.array([1.0, 1.0], dtype=np.float32)]
        if control_mode == "B":
            base_low.append(np.array([-1.0, -1.0], dtype=np.float32))   # v_act_norm, w_act_norm
            base_high.append(np.array([1.0, 1.0], dtype=np.float32))
        self.observation_space = spaces.Box(
            low=np.concatenate(base_low), high=np.concatenate(base_high), dtype=np.float32)

        # 动作空间：A=[v∈[0,1], w∈[-1,1]]；B=[f_l∈[-1,1], f_r∈[-1,1]]（归一化轮力，内部×F_MAX）
        if control_mode == "B":
            self.action_space = spaces.Box(
                low=np.array([-1.0, -1.0], dtype=np.float32),
                high=np.array([1.0, 1.0], dtype=np.float32), dtype=np.float32)
        else:
            self.action_space = spaces.Box(
                low=np.array([0.0, -1.0], dtype=np.float32),
                high=np.array([1.0, 1.0], dtype=np.float32), dtype=np.float32)

        # 场地对角线，用于距离归一化
        self._max_dist = float(np.hypot(self.ARENA_W, self.ARENA_H))

        # 预计算 LiDAR 各射线相对底盘朝向的角度偏移（360° 均匀分布）
        self._ray_offsets = np.linspace(
            -self.LIDAR_FOV / 2.0, self.LIDAR_FOV / 2.0,
            self.N_RAYS, endpoint=False, dtype=np.float64,
        )

        # 运行时状态（在 reset 中初始化）
        self.pos = None          # 底盘位置 np.array([x, y])（真值 Truth，无噪声基准）
        self.theta = None        # 底盘朝向 (rad)（真值 Truth）
        self.v_act = 0.0         # 实际线速度 (m/s)（动力学积分态；零惯性档恒等于目标速度）
        self.w_act = 0.0         # 实际角速度 (rad/s)
        self.odom_pos = None     # 里程计位置 np.array([x, y])（带打滑漂移，独立积分）
        self.odom_theta = None   # 里程计朝向 (rad)（带打滑漂移）
        self.goal = None         # 目标点 np.array([x, y])
        self.obstacles = None    # 障碍物 np.array([[cx, cy, r], ...])
        self.prev_dist = None    # 上一步到目标的距离（用于进度奖励差分）
        self.step_count = 0
        # 全局单调帧序号（跨回合不复位），供完整性审计校验"帧序单调"——区别于会复位的 step_count
        self.frame_seq = 0
        self.last_lidar = None   # 缓存最近一次 lidar，供渲染/广播复用

        # —— 能量审计账本（本 step 的真实数字，供 energy_audit 消费）——
        #    ΔE_kin 应 ≈ W_act − D_damp（精确遥测，clean 残差到机器精度，见 _integrate_dynamics）
        self.E_kin = 0.0         # 当前动能 ½m·v_act² + ½I·w_act²
        self.last_dE = 0.0       # 本 step 动能变化量
        self.last_W_act = 0.0    # 本 step 执行器净做功（按"声称"力，供审计对账）
        self.last_D_damp = 0.0   # 本 step 阻尼耗散（按"声称"阻尼系数 C_LIN/C_ANG）
        # 物理故障注入钩子（None=清洁；audit/physics_injection.py 设置；仅测试，绝不进生产）
        # 形如 {"mode": "P-1_neg_damp", ...}；藏在 _integrate_dynamics 内部破坏真实积分。
        self.physics_fault = None

        if seed is not None:
            self.reset(seed=seed)

    # ------------------------------------------------------------------
    # gymnasium 标准接口：reset
    # ------------------------------------------------------------------
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)  # 初始化 self.np_random（带种子的随机数发生器）

        # 1) 随机生成障碍物（拒绝采样：避免压在场地边缘）
        obstacles = []
        margin = self.OBS_R_MAX + 0.2
        for _ in range(self.N_OBSTACLES):
            r = self.np_random.uniform(self.OBS_R_MIN, self.OBS_R_MAX)
            cx = self.np_random.uniform(margin, self.ARENA_W - margin)
            cy = self.np_random.uniform(margin, self.ARENA_H - margin)
            obstacles.append([cx, cy, r])
        self.obstacles = np.array(obstacles, dtype=np.float64)

        # 2) 随机起点与目标（拒绝采样：不与任何障碍物重叠，且两者保持足够间距）
        self.pos = self._sample_free_point(clearance=self.ROBOT_RADIUS + 0.1)
        while True:
            self.goal = self._sample_free_point(clearance=self.GOAL_RADIUS + 0.1)
            if np.linalg.norm(self.goal - self.pos) > 0.4 * self._max_dist:
                break  # 保证导航任务有足够长度，避免一步到位的退化样本

        # 3) 初始朝向随机
        self.theta = float(self.np_random.uniform(-np.pi, np.pi))

        # 4) 里程计在回合开始时与真值标定对齐（累积误差从 0.000 起算）
        self.odom_pos = self.pos.copy()
        self.odom_theta = self.theta

        # 5) 动力学态复位：实际速度归零，回合从静止起步；能量账本清零
        self.v_act = 0.0
        self.w_act = 0.0
        self.E_kin = 0.0
        self.last_dE = 0.0
        self.last_W_act = 0.0
        self.last_D_damp = 0.0

        self.step_count = 0
        self.prev_dist = float(np.linalg.norm(self.goal - self.pos))

        obs = self._get_obs()
        info = {"is_success": False}
        return obs, info

    # ------------------------------------------------------------------
    # gymnasium 标准接口：step（运动学更新 + O(1) 碰撞检测 + 奖励）
    # ------------------------------------------------------------------
    def step(self, action):
        action = np.clip(action, self.action_space.low, self.action_space.high)
        a0, a1 = float(action[0]), float(action[1])

        # —— 1+2) 动力学核推进真值位姿，并结算能量账本（按控制模式分派）——
        if self.control_mode == "B":
            # B-mode：动作=归一化原始轮力 [f_l, f_r]（×F_MAX 还原），去 P 控制器、直接喂核。
            self._step_dynamics_B(a0 * self.F_MAX, a1 * self.F_MAX)
            # 平滑正则用「实际角速度」（无 w_cmd 概念），抑制无谓自旋。
            w_cmd = self.w_act / self.MAX_ANG_VEL
        else:
            # A-mode：动作=目标速度 [v, w]；ENABLE_DYNAMICS=False 退回零惯性运动学。
            self._step_dynamics(a0 * self.MAX_LIN_VEL, a1 * self.MAX_ANG_VEL)
            w_cmd = a1

        # —— 2b) 里程计积分（D-018 真打滑）：吃「实际速度」v_act/w_act（轮速编码器感知实际而非指令），
        #         施加打滑误差 → 真实分叉（C1 不变）。位置积分由动力学核已完成，此处仅 odom。
        self._integrate_odom(self.v_act, self.w_act)

        self.step_count += 1
        self.frame_seq += 1        # 全局帧序号单调自增（跨回合不复位）

        # —— 3) 计算几何量 ——
        dist = float(np.linalg.norm(self.goal - self.pos))
        lidar = self._cast_lidar()           # 真实测距（米）
        self.last_lidar = lidar
        min_lidar = float(lidar.min())

        # —— 4) 终止判定 ——
        collided = self._check_collision(min_lidar)
        reached = dist < self.GOAL_RADIUS
        terminated = bool(collided or reached)
        truncated = bool(self.step_count >= self.MAX_STEPS)

        # —— 5) 奖励合成 ——
        reward = self._compute_reward(
            dist=dist, w_cmd=w_cmd, min_lidar=min_lidar,
            collided=collided, reached=reached,
        )
        self.prev_dist = dist

        obs = self._get_obs(lidar=lidar)
        info = {
            "is_success": reached,
            "collided": collided,
            "distance": dist,
            "min_lidar": min_lidar,
        }
        return obs, reward, terminated, truncated, info

    # ------------------------------------------------------------------
    # 动力学核（Phase1a · F1）：力 → 牛顿+黏性阻尼 → 半隐式子步积分 → 真值位姿
    #   分层：_integrate_dynamics 是共享核（接受 力/力矩 闭包，按当前实际速度求值）；
    #         _step_dynamics 是 A-mode 外壳（目标速度→P 控制器力）。B-mode 未来直接喂原始力。
    # ------------------------------------------------------------------
    def _step_dynamics(self, v_tgt, w_tgt):
        """A-mode：把目标速度经 P 控制器化为执行器力，调用共享核推进真值位姿。

        ENABLE_DYNAMICS=False：退回零惯性运动学（v_act≡v_tgt、w_act≡w_tgt 直接积分），
        作为「无动力学」回归对照（能量账本在此档无物理意义，置零）。
        """
        if not self.ENABLE_DYNAMICS:
            self.v_act, self.w_act = v_tgt, w_tgt
            self.theta = self._wrap_angle(self.theta + self.w_act * self.DT)
            self.pos = self.pos + np.array(
                [self.v_act * np.cos(self.theta), self.v_act * np.sin(self.theta)]
            ) * self.DT
            self.E_kin = 0.5 * self.MASS * self.v_act ** 2 \
                + 0.5 * self.INERTIA_COEF * self.MASS * self.w_act ** 2
            self.last_dE = self.last_W_act = self.last_D_damp = 0.0
            return

        # A-mode P 控制器：力/力矩 = 增益 ×（目标速度 − 当前实际速度），逐子步按实时 v_act 求值。
        # 当 v_tgt=0 时 F=KP·(0−v_act)=−KP·v_act 为「真实减速力」→ 天然刹车，
        # 取代原版 v*=0.5 硬不连续（old:716），且其负功如实进入能量账本。
        lin_force_of = lambda v: self.KP_V * (v_tgt - v)
        ang_force_of = lambda w: self.KP_W * (w_tgt - w)
        self._integrate_dynamics(lin_force_of, ang_force_of)

    def _step_dynamics_B(self, f_l, f_r):
        """B-mode：原始轮力 → 净力/差动力矩 → 共享核（去掉 A-mode 的 P 跟踪层）。

        force=f_l+f_r、torque=(f_r−f_l)·ARM（old:708-709）。力对子步「恒定」（不随 v 变），
        故 lin_force_of/ang_force_of 为常值闭包——动力学/阻尼/能量账本与 A-mode 共用同一核，
        审计（EC1/EC2/EC3）作用于核、与控制模式无关。
        有意义惯性：v 的时间常数 τ_v=MASS/C_LIN≈0.333s≈3.3×DT（无 P 控制器压缩）。
        """
        force = f_l + f_r
        torque = (f_r - f_l) * self.ARM
        self._integrate_dynamics(lambda v: force, lambda w: torque)

    def _integrate_dynamics(self, lin_force_of, ang_force_of):
        """共享动力学核：N_SUB 个半隐式子步，牛顿 + 黏性阻尼，结算精确能量账本。

        守恒律遥测（关键，能量审计的地基）：
            离散半隐式更新 v_{n+1}=v_n+(h/m)(F−c·v_n) 对 ½m·v² 精确电报：
                ΔKE = h·F·v_mid − h·c·v_n·v_mid,  v_mid=½(v_n+v_{n+1})
            故定义 W_act=Σ F·v_mid·h、D_damp=Σ c·v_n·v_mid·h（用「声称」常数）后，
            清洁运行残差 r=ΔE−(W_act−D_damp) 应到机器精度（≈0）。
            注入器（physics_fault）只改「实际积分」而账本仍按声称常数结算 → 残差变非零（被审计抓）。
        """
        h = self.DT / self.N_SUB
        m_decl = self.MASS                       # 声称质量（账本/动能用）
        I_decl = self.INERTIA_COEF * self.MASS   # 声称转动惯量
        c_lin_decl, c_ang_decl = self.C_LIN, self.C_ANG

        # —— 故障注入参数解包（清洁档全部取声称值；注入档悄悄改「实际」积分参数）——
        f = self.physics_fault or {}
        mode = f.get("mode")
        c_lin_eff = f.get("c_lin_eff", c_lin_decl)   # 实际积分用阻尼（P-1 负/ P-3 置零）
        c_ang_eff = f.get("c_ang_eff", c_ang_decl)
        force_mult = f.get("force_mult", 1.0)        # 实际力倍率（P-2 双计=2.0）
        m_eff = f.get("m_eff", m_decl)               # 实际积分质量（≠声称则 P-5 谎报）
        skip_lag = f.get("skip_lag", False)          # P-4：跳过惯性滞后，实际速度瞬达/越目标
        overshoot = f.get("overshoot", 1.0)          # P-4：>1 则越过执行器上限（供 EC3 判定）
        # G-1 涌现 gaming 故障：当 |v0|>boost_thresh，沿运动方向施加「免费」推力 boost_force，
        #   账本不计该力 → 高速时白拿能量（稳态顶速越物理上限），对「求快到目标」的智能体有利可图。
        boost_force = f.get("boost_force", 0.0)
        boost_thresh = f.get("boost_thresh", 0.0)

        E0 = 0.5 * m_decl * self.v_act ** 2 + 0.5 * I_decl * self.w_act ** 2
        W_act = 0.0
        D_damp = 0.0

        for _ in range(self.N_SUB):
            v0, w0 = self.v_act, self.w_act
            F = lin_force_of(v0)
            tau = ang_force_of(w0)

            if skip_lag:
                # P-4：无视惯性/阻尼，实际速度直接锁到 overshoot×「该作动状态的应有稳态速度」。
                #      overshoot>1 → 持续越执行器上限 + 动能凭空跃变（破坏执行器功率界）。
                # 稳态速度按模式求（皆有界，避免子步复利发散）：
                #   A-mode：F=KP(v_tgt−v0) ⇒ 应有稳态 = v_tgt = v0 + F/KP；
                #   B-mode：F 为原始力 ⇒ 应有稳态 = F/c_decl（角向 tau/c_ang_decl）。
                if self.control_mode == "B":
                    v_tgt_eq = (force_mult * F) / (c_lin_decl if c_lin_decl else 1.0)
                    w_tgt_eq = (force_mult * tau) / (c_ang_decl if c_ang_decl else 1.0)
                else:
                    v_tgt_eq = v0 + (F / self.KP_V if self.KP_V else 0.0)
                    w_tgt_eq = w0 + (tau / self.KP_W if self.KP_W else 0.0)
                v_new = overshoot * v_tgt_eq
                w_new = overshoot * w_tgt_eq
            else:
                # G-1：高速时白拿免费推力（账本不计）——能量凭空注入、顶速越物理上限。
                boost = boost_force * np.sign(v0) if (boost_force and abs(v0) > boost_thresh) else 0.0
                a = (force_mult * F + boost - c_lin_eff * v0) / m_eff
                alpha = (force_mult * tau - c_ang_eff * w0) / (self.INERTIA_COEF * m_eff)
                v_new = v0 + a * h
                w_new = w0 + alpha * h

            v_mid = 0.5 * (v0 + v_new)
            w_mid = 0.5 * (w0 + w_new)
            # 账本按「声称」力与「声称」阻尼结算（注入器改实际、账本仍声称 → 残差暴露故障）
            W_act += (F * v_mid + tau * w_mid) * h
            D_damp += (c_lin_decl * v0 * v_mid + c_ang_decl * w0 * w_mid) * h

            self.v_act, self.w_act = v_new, w_new
            self.theta = self._wrap_angle(self.theta + self.w_act * h)
            self.pos = self.pos + np.array(
                [self.v_act * np.cos(self.theta), self.v_act * np.sin(self.theta)]
            ) * h

        # 动能用「声称」质量计（P-5 谎报时 E_kin 与真实积分不自洽 → 残差非零）
        self.E_kin = 0.5 * m_decl * self.v_act ** 2 + 0.5 * I_decl * self.w_act ** 2
        self.last_dE = self.E_kin - E0
        self.last_W_act = W_act
        self.last_D_damp = D_damp

    # ------------------------------------------------------------------
    # 里程计积分（D-018：注入真打滑漂移，使 Odom 随时间真实偏离 Truth）
    # ------------------------------------------------------------------
    def _integrate_odom(self, v, w):
        """以「带打滑的感知速度」独立积分里程计位姿。

        物理直觉（差速轮里程计漂移的教科书模型）：
            轮速编码器对真实运动的感知存在乘性偏差 + 随机噪声，dead-reckoning 逐步累积：
                v_odom = v*(1+slip) + N(0, slip)*|v|     线速度：系统性偏差 + 比例噪声
                w_odom = w*(1+slip) + N(0, slip)*|w|     角速度：系统性偏差 + 比例噪声
        要点：
            - 噪声与速度成正比 → 机器人静止时里程计不漂移（物理正确）；
            - 系统性偏差项 → 误差随累计行程单调增长（即"真分叉"，非随机游走式抵消）；
            - 噪声来自 self.np_random（带种子）→ 完全可复现，绝非 hardcode 的假曲线（INV-2）；
            - slip=0 时 v_odom≡v、w_odom≡w 且不抽取随机数 → 与真值逐位重合（退化为原行为）。
        约束：本函数只读 (v,w) 与自身 odom 状态，绝不回写 self.pos/self.theta（真值不受污染）。
        """
        slip = self.slip_factor
        if slip <= 0.0:
            # 退化档（before 对照 / slip=0 回归）：里程计与真值同式积分，odom≡truth，误差恒 0
            v_odom, w_odom = v, w
        else:
            v_odom = v * (1.0 + slip) + self.np_random.normal(0.0, slip) * abs(v)
            w_odom = w * (1.0 + slip) + self.np_random.normal(0.0, slip) * abs(w)

        # 与真值同构的半隐式 unicycle 积分，但作用于里程计自身状态与"感知速度"
        self.odom_theta = self._wrap_angle(self.odom_theta + w_odom * self.DT)
        self.odom_pos = self.odom_pos + np.array(
            [v_odom * np.cos(self.odom_theta), v_odom * np.sin(self.odom_theta)]
        ) * self.DT

    # ------------------------------------------------------------------
    # 奖励函数（稠密塑形：进度主导 + 安全软约束 + 步数/平滑正则）
    # ------------------------------------------------------------------
    def _compute_reward(self, dist, w_cmd, min_lidar, collided, reached):
        # (a) 稠密进度奖励：与「距离减少量」成正比，提供持续的梯度信号
        reward = self.K_PROGRESS * (self.prev_dist - dist)

        # (b) 步数固定惩罚：鼓励短路径，避免无效兜圈
        reward += self.STEP_PENALTY

        # (c) 角速度平滑惩罚：抑制原地高频抖动，轨迹更顺滑
        reward -= self.K_SMOOTH * abs(w_cmd)

        # (d) 近距安全软惩罚：进入安全缓冲区即线性惩罚（碰撞前提前避让）
        if min_lidar < self.SAFE_DIST:
            reward -= self.K_SAFETY * (self.SAFE_DIST - min_lidar) / self.SAFE_DIST

        # (e) 稀疏终止奖励
        if reached:
            reward += self.R_GOAL
        elif collided:
            reward += self.R_COLLISION

        return float(reward)

    # ------------------------------------------------------------------
    # 观测构造（归一化）
    # ------------------------------------------------------------------
    def _get_obs(self, lidar=None):
        if lidar is None:
            lidar = self._cast_lidar()
            self.last_lidar = lidar

        lidar_norm = (lidar / self.LIDAR_RANGE).astype(np.float32)         # ∈ [0,1]

        dist = float(np.linalg.norm(self.goal - self.pos))
        dist_norm = np.float32(min(dist / self._max_dist, 1.0))           # ∈ [0,1]

        goal_angle = np.arctan2(self.goal[1] - self.pos[1],
                                self.goal[0] - self.pos[0])
        yaw_err = self._wrap_angle(goal_angle - self.theta)
        yaw_err_norm = np.float32(yaw_err / np.pi)                         # ∈ [-1,1]

        parts = [lidar_norm, np.array([dist_norm, yaw_err_norm], dtype=np.float32)]
        if self.control_mode == "B":
            # B-mode 速度反馈：力控下速度是显著隐藏态（τ≈3×步长），需入观测做信用分配。
            v_norm = np.float32(np.clip(self.v_act / self.V_PHYS_MAX_B, -1.0, 1.0))
            w_norm = np.float32(np.clip(self.w_act / self.W_PHYS_MAX_B, -1.0, 1.0))
            parts.append(np.array([v_norm, w_norm], dtype=np.float32))
        obs = np.concatenate(parts)
        # 防御性裁剪：杜绝浮点误差导致越界，确保通过 env_checker 与 SB3 校验
        return np.clip(obs, self.observation_space.low, self.observation_space.high)

    # ------------------------------------------------------------------
    # LiDAR：解析式射线投射（向量化，O(N_RAYS) numpy 运算）
    # ------------------------------------------------------------------
    def _cast_lidar(self):
        """返回每根射线的真实测距 (m)，上限截断为 LIDAR_RANGE。"""
        angles = self.theta + self._ray_offsets                  # (N,) 绝对射线角
        dirs = np.stack([np.cos(angles), np.sin(angles)], axis=1)  # (N,2) 单位方向
        dists = np.full(self.N_RAYS, self.LIDAR_RANGE, dtype=np.float64)
        P = self.pos

        # —— (1) 射线 vs 圆形障碍物（解析求交）——
        for cx, cy, r in self.obstacles:
            L = np.array([cx, cy]) - P                # 射线原点指向圆心
            tca = dirs @ L                            # (N,) 圆心在射线上的投影长度
            d2 = (L @ L) - tca ** 2                   # (N,) 圆心到射线的垂距平方
            hit = (d2 <= r * r) & (tca > 0)           # 射线确实穿过该圆且圆在前方
            thc = np.sqrt(np.clip(r * r - d2, 0.0, None))
            t0 = tca - thc                            # 近交点参数（即测距）
            valid = hit & (t0 > 0)
            dists = np.where(valid, np.minimum(dists, t0), dists)

        # —— (2) 射线 vs 场地四面墙（轴对齐边界求交）——
        dists = self._ray_walls(P, dirs, dists)

        return np.clip(dists, 0.0, self.LIDAR_RANGE)

    def _ray_walls(self, P, dirs, dists):
        """射线与轴对齐矩形场地边界求交，逐墙向量化更新最小测距。"""
        dx, dy = dirs[:, 0], dirs[:, 1]
        with np.errstate(divide="ignore", invalid="ignore"):
            # 垂直墙 x = 0 与 x = ARENA_W
            for wx in (0.0, self.ARENA_W):
                t = (wx - P[0]) / dx
                y_hit = P[1] + t * dy
                valid = (dx != 0) & (t > 0) & (y_hit >= 0) & (y_hit <= self.ARENA_H)
                dists = np.where(valid, np.minimum(dists, t), dists)
            # 水平墙 y = 0 与 y = ARENA_H
            for wy in (0.0, self.ARENA_H):
                t = (wy - P[1]) / dy
                x_hit = P[0] + t * dx
                valid = (dy != 0) & (t > 0) & (x_hit >= 0) & (x_hit <= self.ARENA_W)
                dists = np.where(valid, np.minimum(dists, t), dists)
        return dists

    # ------------------------------------------------------------------
    # O(1) 碰撞检测：圆-圆 + 出界
    # ------------------------------------------------------------------
    def _check_collision(self, min_lidar):
        # (a) 出界：底盘圆超出场地
        x, y = self.pos
        if (x - self.ROBOT_RADIUS < 0 or x + self.ROBOT_RADIUS > self.ARENA_W or
                y - self.ROBOT_RADIUS < 0 or y + self.ROBOT_RADIUS > self.ARENA_H):
            return True
        # (b) 与障碍物穿模：圆心距 < 半径和（每个障碍 O(1)）
        diff = self.obstacles[:, :2] - self.pos                 # (K,2)
        center_dist = np.linalg.norm(diff, axis=1)              # (K,)
        if np.any(center_dist < self.obstacles[:, 2] + self.ROBOT_RADIUS):
            return True
        return False

    # ------------------------------------------------------------------
    # 工具：采样自由点 / 角度归一化
    # ------------------------------------------------------------------
    def _sample_free_point(self, clearance):
        """在场地内拒绝采样一个不与障碍物重叠的点。"""
        for _ in range(200):
            p = np.array([
                self.np_random.uniform(clearance, self.ARENA_W - clearance),
                self.np_random.uniform(clearance, self.ARENA_H - clearance),
            ])
            diff = self.obstacles[:, :2] - p
            d = np.linalg.norm(diff, axis=1)
            if np.all(d > self.obstacles[:, 2] + clearance):
                return p
        return p  # 兜底：极端拥挤时返回最后一次采样

    @staticmethod
    def _wrap_angle(a):
        """将任意角度归一化到 [-π, π]。"""
        return (a + np.pi) % (2.0 * np.pi) - np.pi

    # ------------------------------------------------------------------
    # 孪生渲染状态导出（供 inference_server.py 序列化广播给 Three.js）
    # ------------------------------------------------------------------
    def get_render_state(self, reward=0.0, terminated=False,
                         truncated=False, info=None):
        """返回可 JSON 序列化的孪生观测域状态字典（前端数据契约）。"""
        info = info or {}
        lidar = self.last_lidar if self.last_lidar is not None else self._cast_lidar()
        # 里程计位姿（带打滑漂移，独立于真值）；reset 前为 None 时回退到真值以防序列化报错
        odom_pos = self.odom_pos if self.odom_pos is not None else self.pos
        odom_theta = self.odom_theta if self.odom_theta is not None else self.theta
        return {
            "robot": {
                "x": float(self.pos[0]),
                "y": float(self.pos[1]),
                "theta": float(self.theta),
                "radius": self.ROBOT_RADIUS,
            },
            # 里程计（Odom）：前端直接渲染本字段，禁止再用真值伪造（破除"假仪表"）
            "odom": {
                "x": float(odom_pos[0]),
                "y": float(odom_pos[1]),
                "theta": float(odom_theta),
            },
            "goal": {"x": float(self.goal[0]), "y": float(self.goal[1]),
                     "radius": self.GOAL_RADIUS},
            "obstacles": [
                {"x": float(o[0]), "y": float(o[1]), "r": float(o[2])}
                for o in self.obstacles
            ],
            "lidar": [float(d) for d in lidar],       # 真实测距 (m)，前端可画射线
            "lidar_range": self.LIDAR_RANGE,
            "arena": {"w": self.ARENA_W, "h": self.ARENA_H},
            "seq": int(self.frame_seq),    # 全局单调帧序号（完整性审计校验帧序单调用）
            "step": int(self.step_count),
            "reward": float(reward),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "distance": float(info.get("distance", np.linalg.norm(self.goal - self.pos))),
            # —— Phase1a 加性字段（向后兼容：旧前端/契约层审计忽略未知键，零影响）——
            "v_act": float(self.v_act),     # 实际线速度（含惯性滞后；前端可显示"指令 vs 实际"）
            "w_act": float(self.w_act),     # 实际角速度
            "energy": {                      # 能量账本（供 energy_audit 消费；本 step 真实数字）
                "E_kin": float(self.E_kin),       # 当前动能 ½m·v² + ½I·w²
                "dE": float(self.last_dE),        # 本 step 动能变化
                "W_act": float(self.last_W_act),  # 执行器净做功（按声称力）
                "D_damp": float(self.last_D_damp),  # 阻尼耗散（按声称阻尼系数）
            },
        }


# 注册到 gymnasium（可选，便于 gym.make("EmbodiedNav-v0")）
try:
    gym.register(id="EmbodiedNav-v0", entry_point=EmbodiedNavEnv, max_episode_steps=EmbodiedNavEnv.MAX_STEPS)
except Exception:
    pass  # 重复注册时静默跳过


if __name__ == "__main__":
    # 自检：API 合规性 + 随机策略冒烟测试
    from gymnasium.utils.env_checker import check_env

    env = EmbodiedNavEnv()
    check_env(env)  # 通过即说明完全符合 gymnasium 标准接口
    print("[OK] check_env passed.")

    obs, info = env.reset(seed=0)
    print(f"[OK] obs shape = {obs.shape}, dtype = {obs.dtype}")
    total = 0.0
    for _ in range(50):
        a = env.action_space.sample()
        obs, r, term, trunc, info = env.step(a)
        total += r
        if term or trunc:
            obs, info = env.reset()
    print(f"[OK] 50-step random rollout done, accumulated reward = {total:.2f}")
