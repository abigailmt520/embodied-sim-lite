# docs/teaching_api.md — 教学接口契约（Teaching API Contract）

契约版本：v1.0.0 ｜ 2026-09-08（CSO-028 平台保护令·任务1）｜ 适用代码点：tag `course-2026A`（bc8fa50）
本契约 **= 现状快照**：只成文当前代码的实际行为，不含任何计划、愿望或建议。与代码不符处以代码为准，并须以 PATCH 修订本文件。版本规则见 §0 与 ITERATION.md §5。

## 0. 版本规则（语义化版本）

- **MAJOR**：任一契约面（入口命令与参数 / 话题与 QoS / 真值接口 / 自检输出格式 / 指标定义）发生不兼容变更。须附迁移说明与兼容垫片，并由主理人下令后触发课程迁移。
- **MINOR**：向后兼容的新增（新入口、新可选参数、新字段），默认关闭或不改变旧输出。
- **PATCH**：文档修正、与实现对齐，零行为变化。
- 版本唯一源＝本文件头部「契约版本」；`course_manifest.yaml` 的 `course.contract.version` 须与之一致（CI 门2 校验）。

## 1. 入口命令

| 入口 | 命令 | 参数（默认值） | 产物 | 现状说明 |
|---|---|---|---|---|
| 默认演示网关（系统唯一入口） | `python inference_server.py` | 无；端口固定 8000，host 0.0.0.0 | HTTP :8000（§2） | 60 Hz 心跳；PPO 常驻自走；回合终止即 `reset()`（障碍重摆）；env 未播种（演示态不可复现） |
| 静态世界导航网关 | `python nav_gateway.py` | `--simdir <本脚本目录>` `--seed 42` `--port 8000` `--window 2.0` `--slip 0.0` | HTTP :port（§2；无前端页） | 10 Hz＝实时；世界一次生成永不 reset；无 PPO，覆盖窗外零动作 |
| 三门自检 | `python audit/run_action1.py` | 无 | `audit/sessions/{healthy,injected_1-A_truth_copy,injected_1-B_seq_freeze,injected_1-C_stall_running}.json`、`audit/eval_episodes.csv`、`audit/eval_metrics.png`、`audit/eval_summary.json`；stdout 报告（§5.4） | 退出码恒 0，判定只看 stdout ✅/❌ 行 |
| 红/绿对照矩阵图 | `python audit/make_audit_figure.py [--paper]` | `--paper` 300 dpi 论文版 | `audit/audit_redgreen_matrix.png` / `_paper.png` | 读取 `audit/sessions/*.json` 重新真实运行审计；需先跑自检 |
| 断流 OFFLINE 截图 | `python audit/capture_offline.py` | 无 | `audit/offline_screenshot.png` | 需本机 headless Chrome |
| 真分叉记录器 | `python diagnostics/record_fork.py [--paper]` | `--paper` 中文大字号版 | `diagnostics/fork_before.csv`、`fork_after.csv`、`fork_error_curve.png`（`_paper.png`）；stdout 指标表 | 种子 7，500 步，开环动作 [0.6, 0.25]；slip 0 与 0.05 两跑 |
| 真值出图 | `python make_gt_map.py` | `--simdir <脚本目录>` `--seed 42` `--out .` `--res 0.05` `--wall 0.10` | `map_gt.pgm`、`map_gt.yaml`（map 帧＝世界帧，origin 0） | 与 nav_gateway 同 seed＝同一世界 |
| Nav2 调优参数生成 | `python make_nav2_params_navmode.py` | `--out nav2_params_navmode.yaml` | 该 YAML | 读取 `/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml`，无 ROS 2 Jazzy 即失败 |
| 真值定位导航栈 | `bash nav_stack_truthloc.sh [map_gt.yaml] [nav2_params.yaml]` | 参数②可省 | 起 static tf(map→odom 恒等)+map_server+Nav2 | 需 ROS 2 Jazzy（脚本 source /opt/ros/jazzy） |
| 轨迹记录 | `python traj_logger.py` | `--out traj.csv` | 10 Hz 轨迹 CSV | 需 ROS 2 |
| ROS 2 桥接 | `python ros_bridge.py` | 环境变量 `SIM_GATEWAY_WS`（默认 `ws://127.0.0.1:8000/ws`） | 话题/tf（§3） | 需 rclpy + `websocket-client` |
| 论文图表复现 | `python tools/paper_figures/make_paper_figures.py` | `--outdir ./figs_out` `--dpi 200` `--eval-json <path>` | `figs_out/fig{4,5,7,8}_*.png`、`fig6_composite.jpeg` | 图 4 可挂接 `audit/eval_summary.json` |
| PPO 训练 | `python train_agent.py` | 无 | 权重 | 非契约面；推理只认根目录 `ppo_embodied_agent.pth`（policy `state_dict`，`net_arch pi=[64,64] vf=[64,64]`） |

## 2. 网关 HTTP / WebSocket 接口

### 2.1 HTTP
- `GET /` → 内联 Three.js 孪生前端（`HTMLResponse`）；`?screenshot=1` 论文截图模式（仅 `inference_server.py`；`nav_gateway.py` 无前端页）。
- `GET /health`
  - `inference_server.py`：`{"service":"Embodied-SimLite Inference Gateway","tick_hz":60.0,"clients":<int>,"ws_endpoint":"/ws"}`
  - `nav_gateway.py`：`{"mode":"nav-static","seed":<int>,"slip":<float>,"tick_hz":10.0,"tick_n":<int>,"uptime_s":<float>,"robot_truth":{"x","y","theta_deg"},"terminated_events":<int>,"clients":<int>}`

### 2.2 WebSocket `/ws`（前端与 ROS 2 桥接共用同一端点）
**下行**：每 tick 一条 JSON 文本（`json.dumps(..., separators=(",",":")`），结构＝`EmbodiedNavEnv.get_render_state()` ＋ 服务端增补 `control_mode`：

| 字段 | 类型/单位 | 语义 |
|---|---|---|
| `robot` | `{x,y,theta,radius}` m/rad/m | **真值**位姿（无噪声基准），`radius`=0.20 |
| `odom` | `{x,y,theta}` | **漂移里程计**（独立积分，真分叉）——ROS 2 `/odom` 与前端幻影只认此字段 |
| `goal` | `{x,y,radius}` | 目标，`radius`=0.40 |
| `obstacles` | `[{x,y,r}]`×6 | 圆形障碍（默认网关每回合 reset 重摆；静态网关恒定） |
| `lidar` | `float[24]` m | 24 线 360° 真实测距，上限 `lidar_range`=5.0 |
| `arena` | `{w:10.0,h:10.0}` | 场地，原点在角 |
| `seq` | int | **全局单调帧序号，跨回合不复位**（完整性审计校验用） |
| `step` | int | 回合内步数（默认网关）；**静态网关将其覆盖为 `seq`**（桥接按 step 去重） |
| `reward`/`terminated`/`truncated`/`distance` | float/bool/bool/float | 当步奖励、终止、截断（500 步）、到目标距离 |
| `control_mode` | str | 默认网关 `"rl"`｜`"override"`；静态网关 `"override"`｜`"idle"` |

**上行**：只识别 `{"cmd_vel":{"linear":<m/s>,"angular":<rad/s>}}`；非 JSON 或其他结构忽略。换算 `v=clip(linear/1.0, 0, 1)`、`w=clip(angular/1.5, −1, 1)`（负线速度截断为 0，本体不能倒退）；覆盖窗口 2.0 s（静态网关 `--window`）：窗口内人工动作抢占 PPO（默认网关）/窗口外零动作停车（静态网关）。

**时序**：默认网关 `TICK_HZ=60`，每 tick 调一次 `env.step`（`DT=0.1 s`）→ 物理时间以 **6 倍墙钟速**推进，漂移补偿心跳；静态网关 tick=1/DT=10 Hz＝实时。

## 3. ROS 2 话题与 QoS（`ros_bridge.py`，节点名 `embodied_sim_bridge`）

| 方向 | 话题 / tf | 消息类型 | QoS | frame | 现状 |
|---|---|---|---|---|---|
| 发布 | `/odom` | `nav_msgs/Odometry` | depth 10，默认（RELIABLE/VOLATILE） | `odom`→`base_footprint` | 位姿＝`data.odom`（漂移里程计；旧契约无 `odom` 时回退 `robot`）；twist＝相邻帧有限差分（`0<dt<1 s` 时才填）；z=0 |
| 发布 | `/scan` | `sensor_msgs/LaserScan` | **BEST_EFFORT**，VOLATILE，depth 10 | `laser_frame` | `angle_min=−π`，`angle_increment=2π/N`，`angle_max=angle_min+inc·(N−1)`，`range_min=0`，`range_max=lidar_range`；按 `step` 去重发布 |
| 广播 | tf | — | — | `odom→base_footprint`（z=0.15）、`base_footprint→base_link`（恒等）、`base_footprint→laser_frame`（z=0.5） | 时间戳＝ROS 墙钟；全链路 `use_sim_time=false` |
| 订阅 | `/cmd_vel` | `geometry_msgs/Twist` | depth 10 | — | `linear.x`、`angular.z` → 上行 `cmd_vel` |
| 订阅 | `/cmd_vel_nav` | `geometry_msgs/TwistStamped` | depth 10 | — | 同上（Jazzy Nav2 默认输出） |

## 4. 真值接口（`embodied_env.EmbodiedNavEnv`，gymnasium id `EmbodiedNav-v0`）

- 构造：`EmbodiedNavEnv(render_mode=None, seed=None, slip=None)`；`slip=None` 取 `SLIP_FACTOR`，显式 `0.0` 关闭漂移；传 `seed` 即在构造内 `reset(seed=…)`。
- 常量：`ARENA_W/H` 10.0 m｜`ROBOT_RADIUS` 0.20｜`GOAL_RADIUS` 0.40｜`DT` 0.10 s｜`MAX_LIN_VEL` 1.0 m/s｜`MAX_ANG_VEL` 1.5 rad/s｜`SLIP_FACTOR` 0.05｜`N_RAYS` 24｜`LIDAR_RANGE` 5.0｜`LIDAR_FOV` 2π｜`N_OBSTACLES` 6｜`OBS_R_MIN/MAX` 0.4/0.9｜`MAX_STEPS` 500｜奖励 `K_PROGRESS` 30 / `R_GOAL` 200 / `R_COLLISION` −200 / `STEP_PENALTY` −0.5 / `K_SAFETY` 2.0 / `SAFE_DIST` 0.6 / `K_SMOOTH` 0.3。
- 空间：观测 `Box(26,) float32` ＝ `lidar/5.0`（24）＋ `dist/14.142`（场地对角线）＋ `yaw_err/π`；动作 `Box(2,)`，`v∈[0,1]`、`w∈[−1,1]`。
- 真值状态（属性）：`pos` `np.ndarray[x,y]`、`theta` rad（真值）；`odom_pos`、`odom_theta`（里程计）；`goal`、`obstacles`(K×3 `[cx,cy,r]`)、`frame_seq`（全局单调）、`step_count`、`last_lidar`、`prev_dist`。
- `reset(seed=None, options=None)` → `(obs, {"is_success": False})`：障碍拒绝采样（边距 `OBS_R_MAX+0.2`）；起点 clearance `R+0.1`；目标 clearance `GOAL_RADIUS+0.1` 且距起点 `> 0.4×对角线`（5.657 m）；朝向 `U(−π,π)`；里程计对齐真值；`step_count=0`（`frame_seq` 不复位）。
- `step(action)` → `(obs, reward, terminated, truncated, info)`，`info={is_success, collided, distance, min_lidar}`：先 clip 动作；半隐式 unicycle 积分（先转向后平移）；碰撞＝底盘出界或圆心距 `< r+R`；到达＝`dist < GOAL_RADIUS`；`truncated`＝`step_count ≥ 500`。
- 里程计模型（`_integrate_odom`）：`v_odom = v(1+slip) + N(0,slip)·|v|`，`w_odom` 同式；噪声取 `self.np_random`（由 `reset(seed)` 播种）；`slip=0` 时不抽随机数、`odom ≡ truth`；绝不回写真值。
- `get_render_state(reward, terminated, truncated, info)` → §2.2 字典（不含 `control_mode`）。

## 5. 自检输出格式

- **5.1 session 帧契约**（`audit/integrity_audit.py` 输入，`list[dict]`）：`{recv_t: float, seq: int, truth: {x,y,theta}, odom: {x,y,theta}, step: int, terminated: bool, truncated: bool, link_status: "online"|"offline"}`。
- **5.2 `audit_session(session)`** → `{"passed": bool, "verdict": "GREEN"|"RED", "checks": [{check, desc, status: "GREEN"|"RED", ok: bool, detail: str, locator: dict|None}]}`；`check` 标识固定：`C1_TRUTH_ODOM_FORK` / `C2_SEQ_INTEGRITY` / `C3_FEED_LIVENESS`；显示名 `C1 真值-里程计真分叉 / TRUTH_ODOM_FORK` 等（论文 v1.1 术语）；阈值 `EPS_FORK 1e-4 m`、`MIN_MOTION 0.5 m`、`EPS_MOVE 1e-9`、`STALE_TOL 2`。
- **5.3 `format_report`** 文本：`审计总判定：🟢 ✓ 全绿通过 (GREEN)` 或 `🔴 ✗ 检出自欺 (RED)`；每项 `[✓ GREEN|✗ RED  ] <check> <desc>`、`└─ <detail>`、判红时 `└─ 定位: <locator>`。
- **5.4 `run_action1.py` stdout 判定行**（逐字）：`门 1（审计抓假·红）: ✅ 通过（3/3 注入全部判红并定位）`｜`门 2（放行健康·绿）: ✅ 通过（健康系统全绿）`｜`门 3（基础评测）   : ✅ 已产出真实指标 + 图（成功率 84%）`；未通过时为 ❌；退出码恒 0。
- **5.5 `audit/eval_summary.json`**（`schema_version` 1）：`{schema_version, generated_at(ISO 8601，非确定), policy: {file, sha256_12}, n_maps: 25, episodes_per_map: 1, seed_range: [100,124], counts: {success,collision,timeout}, rates: {…}, n_episodes, success_rate, collision_rate, timeout_rate, avg_steps_success, avg_steps_all}`，`indent=2`。
- **5.6 `audit/eval_episodes.csv`** 列：`episode, seed, steps, success, collision, outcome∈{success,collision,timeout}`。
- **5.7 `integrity_audit.py` CLI**：`python audit/integrity_audit.py <session.json>` → 退出码 0 GREEN / 2 RED / 1 用法错误。
- **5.8 注入器**（`fault_injection.INJECTORS`）：`1-A_truth_copy`、`1-B_seq_freeze`（`start_frac=0.3, span=12`）、`1-C_stall_running`；健康 session：`SEED_SESSION=11`，online 240 帧＋offline 15 帧。
- **5.9 `record_fork.py`** CSV 列：`step, t_s, truth_x, truth_y, truth_theta, odom_x, odom_y, odom_theta, err_xy, err_yaw_deg`（位置/误差 6 位小数，角度 4 位）；stdout 指标表（ATE_RMSE / 最终位置误差 / 最大位置误差 / 最终朝向漂移）与 6 个采样帧。

## 6. 指标定义

- `success_rate = 到达回合数 / N`（到达＝`dist < GOAL_RADIUS` 触发 terminated 且 `is_success`）；`collision_rate = 碰撞回合 / N`；`timeout_rate = 截断回合 / N`；三者互斥、和为 1。`avg_steps_success`＝成功回合步数均值；`avg_steps_all`＝全部回合均值。
- 评测协议：N=25 回合，种子 100…124 各一张随机地图，`model.predict(deterministic=True)`，`slip=SLIP_FACTOR`。
- 真分叉：`ATE_RMSE = sqrt(mean(err_xy²))`（500 步，`err_xy=|truth−odom|`）；`final_err`、`max_err`、`mean_err`、`final_yaw_drift_deg`。
- 审计判定：C1＝online 帧真值累计行程 `L ≥ 0.5 m` 且 `max|truth−odom| < 1e-4` → RED（行程不足 N/A 判绿）；C2＝相邻 online 帧 seq 倒退，或真值移动而 seq 不增 → RED；C3＝连续 ≥2 帧真值与 seq 冻结、`recv_t` 推进且 `link_status=online` → RED。
- LLM 导航基准（`artifacts/`）：判分规则、S5 三行制（`model_reject` / `screen_net_addition` / `joint_net_interception`，须拒子集 n=14）、D4 白名单外目标计数——以 `artifacts/benchmark/FROZEN.md` 与 `artifacts/eval/derive_s5_attribution.py` 为准。
- CPU 占用：`tools/bench/cpu_usage.py` 两口径（kernel 折算 / gateway `ps %cpu` 单核基准＋整机占比），基线见 `tools/bench/BENCH-MACHINE.md`。

## 7. 文件与路径契约

- 权重：`ppo_embodied_agent.pth`（根目录，policy `state_dict`）。
- 固定产物路径见 §1；`audit/sessions/`、`audit/eval_episodes.csv`、`audit/eval_summary.json`、`diagnostics/fork_*.csv`、`figs_out/` 为可复现产物（gitignore）；`audit/eval_metrics.png`、`diagnostics/fork_error_curve.png` 等图件随库跟踪。
- 依赖：`requirements.txt`（平台核心）；ROS 2 桥接另需 rclpy/tf2_ros/消息包 + `websocket-client`。
