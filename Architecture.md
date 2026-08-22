# Embodied-SimLite 架构升级文档 V2

> 里程碑：**重构并统一 RL 物理内核与虚实控制网关**
> 第一性原理：**彻底解耦物理推演、AI 决策与孪生渲染**
> 状态：服务端（推理网关 + 孪生前端 + 数据契约）本地实测通过（见文末「验证结果」）；ROS 2 桥接部分需在 Ubuntu + ROS 2 环境中验证，端到端闭环（rviz2/SLAM/Nav2）的架构视角见本文档第 7 节，逐步操作与判据见 README 第 5 节。
> 说明：本文档成稿于 V2 重构期；其后里程计已升级为**真分叉**（注入真打滑漂移，非 `odom≡truth`），并新增**防自欺完整性审计**与全局帧序号 `seq`——以下内容已据此更新，详见仓库 README。

---

## 1. 升级背景与历史债务

旧版 `ProductV1.0.py` 把三件本应正交的事情焊死在一个进程里：

- **物理推演**：`physics_loop()` 在 FastAPI 内以 60Hz 异步循环跑刚体/里程计/动态障碍；
- **通信与渲染**：同一文件托管 Three.js 前端，并通过 `/ws/simulation` 双向收发；
- **全局可变状态**：一个巨大的 `state` 字典，被物理循环、WebSocket 收发、碰撞解析共享读写。

这种耦合带来两个致命问题：

1. **无法极速训练**：物理逻辑被 `asyncio.sleep(1/60)` 的时钟和 WebSocket 序列化牢牢绑死，强化学习需要的「单核满载、以硬件极限反复 `step()`」根本无从谈起。
2. **数据契约混乱**：前端、后端、ROS 2 桥接器各自读写扁平字段 `x/y/yaw/ox/oy/oyaw/lidar/...`，任何一处字段改名都会三向连锁崩溃。

V2 的目标，就是把这三层彻底切开，并以一份**纯计算物理内核**为公约数重建整个系统。

---

## 2. 核心设计哲学：算力置换架构（Compute-Swap Architecture）

### 2.1 一句话定义

> **同一份纯计算物理内核（`embodied_env.py`），套两种不同的「调度外壳」：训练态剥离一切时钟与通信让单核狂奔；推理态重新裹上 60Hz 异步心跳对外广播孪生状态。两种外壳互不污染。**

「置换」指的就是：训练和推理消耗的是同一份算力预算，只是把它**从「等时钟/等网络」置换成了「纯计算」**——训练时把渲染、通信、节流的开销全部退还给 CPU 用于 `step()` 迭代。

### 2.2 三层解耦

| 层 | 载体 | 职责 | 明确不做的事 |
|----|------|------|--------------|
| **物理推演** | `embodied_env.py`（`EmbodiedNavEnv`） | 纯 numpy 同步函数式状态机：运动学积分、O(1) 圆-圆碰撞、解析式射线投射 LiDAR | 不含任何网络 / 渲染 / 异步时钟逻辑 |
| **AI 决策** | `inference_server.py`（PPO 策略网络） | 60Hz 逐 tick 推理动作；可被人工指令抢占 | 不含任何物理积分逻辑 |
| **孪生渲染** | `inference_server.py` 内嵌的 Three.js 前端 | 仅消费广播状态做可视化 | 不参与物理计算（V2 已删除前端 raycasting） |

### 2.3 物理内核为何能「一核两用」

`EmbodiedNavEnv` 是标准 `gymnasium.Env`，它的关键特性是**无副作用、无 I/O、无睡眠**：

- 运动学：差速底盘（unicycle）半隐式积分；
- 碰撞：圆形底盘 vs 圆形障碍，圆心距判定，单障碍 O(1)；
- LiDAR：解析式「射线-圆」「射线-墙」求交，向量化 O(N_RAYS)，无需逐像素扫描。

正因为它只是「输入动作 → 返回观测/奖励」的纯函数式 `step()`，所以：

```
                    ┌─────────────────────────────┐
                    │   embodied_env.py（纯内核）   │
                    │   reset() / step() / 无 I/O   │
                    └──────────────┬──────────────┘
            训练外壳 ↙                          ↘ 推理外壳
 ┌────────────────────────┐         ┌──────────────────────────────┐
 │  train_agent.py         │         │  inference_server.py          │
 │  剥离时钟，单核满速循环   │         │  asyncio 60Hz 心跳 + WS 广播   │
 │  → PPO 权重 .pth/.zip    │         │  → 孪生观测域 / ROS 2 桥接     │
 └────────────────────────┘         └──────────────────────────────┘
```

### 2.4 推理态落地链路（每个 tick 的数据流）

```
读取 Observation
   → 决策权仲裁（Override? 人工指令 : PPO 推理）
   → env.step(action)  推进物理一帧
   → env.get_render_state()  序列化孪生状态
   → manager.broadcast(json)  WebSocket 广播给所有前端 / ROS 2 桥接器
   → 回合 terminated/truncated 则 env.reset()，孪生演示持续滚动
   → 漂移补偿心跳：sleep 剩余时间而非固定 1/60，抑制累计时钟漂移
```

漂移补偿是 60Hz 精度的关键：以 `next_tick += TICK_DT` 为基准累加，`sleep(next_tick - now)`，单 tick 超时则重置基准，避免「追赶式连发」。

### 2.5 统一数据契约（`get_render_state()` 新版嵌套格式）

V2 用一份**嵌套契约**取代旧版扁平字段，渲染端与 ROS 2 端只认这一份结构：

```jsonc
{
  "robot":    { "x": 2.35, "y": 6.66, "theta": 2.40, "radius": 0.20 },  // 真值 Truth（无噪声基准）
  "odom":     { "x": 2.41, "y": 6.49, "theta": 2.31 },  // 里程计（含真打滑漂移，独立于真值）
  "goal":     { "x": 0.58, "y": 7.31, "radius": 0.40 },
  "obstacles":[ { "x": .., "y": .., "r": .. }, ... ],   // 每回合 reset 重新生成
  "lidar":    [ 5.0, 3.2, ... ],                         // 24 路真实测距 (m)
  "lidar_range": 5.0,
  "arena":    { "w": 10.0, "h": 10.0 },                  // 原点在角，0..w / 0..h
  "seq": 1234,                  // 全局单调帧序号（跨回合不复位，供完整性审计校验）
  "step": 81, "reward": -0.5,
  "terminated": false, "truncated": false,
  "distance": 1.82,
  "control_mode": "rl"          // 服务端增补：rl | override（不污染 env 契约）
}
```

> 设计：真值 `robot` 为无噪声基准；里程计 `odom` 由 `embodied_env._integrate_odom()` 注入**真打滑漂移**独立积分，随行程单调偏离真值（**真分叉**，见 README「真分叉里程计」）。前端「里程计幻影」`ghostGroup` 渲染 `odom`、随时间脱离真值本体；ROS 2 `/odom` 发布 `odom`（漂移里程计）而非真值。`seq` 为全局单调帧序号，供防自欺审计校验帧序单调。

### 2.6 服务大一统：唯一启动入口

`inference_server.py` 现在一肩三挑，是**系统唯一入口**：

- `@app.get("/")` → 直出整套 Three.js 孪生观测域（HTML 由旧版迁入，`HTMLResponse`）；
- `@app.get("/health")` → 健康检查 JSON（旧版占用 `/` 的健康信息退居于此）；
- `@app.websocket("/ws")` → 下行广播孪生状态 + 上行接收人工覆盖指令。

旧版 `physics_loop()` 与全局 `state` 字典**已彻底废弃，不再迁移**——物理推演完全由 `embodied_env.py` 接管。

---

## 3. 2s 虚实覆盖抢占机制（Override Control）

### 3.1 目标

当前 PPO 在推理网关内自动决策并下发控制。但真实部署中，操作员或 Nav2 需要随时通过 ROS 2 `/cmd_vel` **人工介入**。机制目标是：

> 一旦收到人工 `/cmd_vel`，立即**无缝挂起并抢占** PPO 的控制权，在接下来的 **2 秒**内只执行人工指令；窗口过期后**自动交还** RL，实现虚实控制权的无缝切换。

### 3.2 完整链路

```
ROS 2 节点 (teleop / Nav2)
   │  发布 geometry_msgs/Twist 到 /cmd_vel（或 /cmd_vel_nav 的 TwistStamped）
   ▼
ros_bridge.py  EmbodiedRos2Bridge.process_cmd(v_x, w_z)
   │  透传真实物理量，不做缩放：
   │  ws.send({"cmd_vel": {"linear": v_x, "angular": w_z}})
   ▼
inference_server.py  /ws 上行 handler
   │  解析 cmd_vel → override.submit(linear, angular, now)
   ▼
OverrideController（2s 窗口仲裁器）
   │  归一化换算 + 记录过期时刻 expiry = now + 2.0
   ▼
simulation_loop()  每 tick 决策权仲裁
       manual = override.get(now)
       action = manual if manual is not None else model.predict(obs)
```

### 3.3 关键工程细节

**(a) 归一化在网关侧完成，桥接器保持通用**
ROS 2 的 `cmd_vel` 是真实物理量（`linear.x` m/s、`angular.z` rad/s）。桥接器**原样透传**，由网关 `OverrideController` 统一换算回 env 的归一化动作空间，使物理内核对「人工 / AI」两路控制完全无感：

```python
v = clip(linear  / MAX_LIN_VEL, 0.0, 1.0)   # MAX_LIN_VEL = 1.0 m/s
w = clip(angular / MAX_ANG_VEL, -1.0, 1.0)  # MAX_ANG_VEL = 1.5 rad/s
```

这样桥接器不必知道任何 env 内部常量，未来换车型只改网关一处。

**(b) 时间窗口仲裁器**
`OverrideController` 缓存「最近一次动作 + 过期时刻」，仲裁逻辑极简：

```python
class OverrideController:
    def submit(self, linear, angular, now):
        self._action = np.array([v, w], dtype=np.float32)
        self._expiry = now + self.window_s          # window_s = 2.0

    def get(self, now):
        return self._action if (self._action is not None and now < self._expiry) else None
```

- **抢占**：窗口内 `get()` 返回人工动作，`simulation_loop` 直接采用，跳过 `model.predict`；
- **续期**：持续发布 `/cmd_vel` 会不断刷新 `expiry`，人工控制可无限延续；
- **自动交还**：停发 2 秒后 `get()` 返回 `None`，决策权无缝回到 PPO。

**(c) 不污染物理契约的可视化反馈**
网关在广播前给状态字典**增补** `control_mode` 字段（`rl` / `override`），前端遥测面板据此把「控制权」标红显示为「ROS 2 人工覆盖」。该字段是服务端增补，**不写入** `embodied_env.get_render_state()`，保持物理内核契约纯净。

**(d) 时钟一致性**
`submit` 与 `get` 都使用同一个 `asyncio` 事件循环时钟 `loop.time()`（单调时钟），与 60Hz 心跳同源，确保 2s 窗口精确、不受 wall-clock 跳变影响。

---

## 4. 文件职责一览（V2）

| 文件 | 角色 | V2 变更 |
|------|------|---------|
| `embodied_env.py` | 纯计算物理内核 + 新版数据契约 `get_render_state()` | 作为契约基准，本次**未改动** |
| `train_agent.py` | 训练外壳（剥离时钟，单核满速） | — |
| `inference_server.py` | **唯一入口**：60Hz 推理心跳 + `/` 直出前端 + `/ws` 广播/覆盖 | 迁入 HTML、新增 `/` 路由、`OverrideController`、决策权仲裁；废弃 `physics_loop`/`state` |
| `ros_bridge.py` | ROS 2 协议翻译层 | `on_message` 读 `data["odom"]`(漂移里程计)/`data["lidar"]`；`/cmd_vel` 透传为 `{"cmd_vel":{...}}`；连 `/ws`（需 ROS 2 环境运行） |
| `Architecture.md` | 本文档 | 成稿于 V2 重构期，其后随真分叉/审计/ROS 2 闭环章节持续更新 |

---

## 5. 验证结果（服务端本地实测）

> 下列为**服务端**（推理网关 + 前端 + 数据契约 + 覆盖机制）本地实测结果。
> 涉及真实 ROS 2 话题/rviz2/Nav2 的端到端闭环**需在 Ubuntu + ROS 2 环境中验证**，不在本机覆盖范围——闭环架构见第 7 节，推荐验证路径与逐级判据见 README 第 5 节。

启动 `inference_server.py` 实测：

| 验证项 | 结果 |
|--------|------|
| 模型载入 + 60Hz 心跳 | ✅ `模型已载入: ppo_embodied_agent.pth` / `Uvicorn running on :8000` |
| `GET /` 直出前端 | ✅ `content-type: text/html`，返回完整 Three.js 页面（`/health` 退居 JSON） |
| 新版嵌套契约广播 | ✅ keys = `robot/goal/obstacles/lidar/lidar_range/arena/step/reward/...`；24 路雷达、`lidar_range=5.0`、6 障碍、10×10 场地 |
| RL 实际驱动 | ✅ 连续帧中 `robot.x` 持续变化 |
| `/cmd_vel` 抢占 | ✅ 下发后 `control_mode` 立即翻为 `override` |
| 2s 覆盖窗口释放 | ✅ 停发后 **~2.01s** 自动交还 `rl`（实测 2.01s，期望 2.0s） |

---

## 6. 联调测试步骤（复现指引）

```bash
# 1) 启动推理网关（系统唯一入口）
cd Embodied-SimLiteV3
python inference_server.py            # 监听 0.0.0.0:8000

# 2) 浏览器打开孪生观测域，验证纯 RL 闭环
#    http://localhost:8000/

# 3) 另开终端，启动 ROS 2 桥接节点（需 ROS 2 环境）
python ros_bridge.py                  # 默认连 ws://127.0.0.1:8000/ws
# 跨机器：SIM_GATEWAY_WS=ws://<网关IP>:8000/ws python ros_bridge.py

# 4) 验证虚实控制权无缝切换
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.5}, angular: {z: 0.8}}'
#    → 网关遥测切「ROS 2 人工覆盖」；停发 2 秒后自动交还「RL 自动」

# 5) 端到端闭环（rviz2 观测 → slam_toolbox 建图 → Nav2 导航）
#    架构与数据流见本文档第 7 节；逐关操作命令、通过判据与排查表见 README 第 5 节
#    （五关递进：话题/tf 冒烟 → 人工覆盖 → rviz2 → SLAM 建图 → Nav2 闭环）
```

---

## 7. ROS 2 端到端闭环架构（SLAM 建图 + Nav2 导航，自行验证）

> ⚠️ 本节描述闭环的**架构与设计约束**；该闭环未在本仓库做自动化验证，逐步操作命令、通过判据与常见问题排查见 README 第 5 节。

### 7.1 完整闭环数据流

```
inference_server.py（唯一真理源：60Hz 心跳 + PPO + OverrideController）
   │  /ws 广播 get_render_state() 嵌套契约
   ▼
ros_bridge.py（纯协议翻译，零状态推演）
   │  发布 /odom（漂移里程计，仅位姿、twist 恒 0）
   │  发布 /scan（24 线 360°、5 m，QoS=BEST_EFFORT）
   │  广播 tf：odom → base_footprint → base_link / laser_frame
   ▼
slam_toolbox（在线建图）                    Nav2（planner + controller + costmap）
   │  发布 map→odom 校正 + /map  ─────────▶   │  订阅 /map、/scan、tf
   │                                          │  输出 /cmd_vel（Humble, Twist）
   │                                          │  或 /cmd_vel_nav（Jazzy+, TwistStamped）
   ▼                                          ▼
ros_bridge.py ── {"cmd_vel":{...}} ──▶ OverrideController（2s 窗口抢占 PPO）──▶ env.step()
                                                                        闭环回到真理源
```

> 需要静态世界（建图/导航量化）时，真理源可换为 `nav_gateway.py`——同一 `/ws` 契约、10Hz 实时、无回合 reset、无 PPO，桥接与下游零改动（README 5.9）。

### 7.2 架构要点（为什么这样设计）

1. **真理源唯一性在 ROS 层同样成立**：桥接不做任何状态推演，SLAM/Nav2 消费的是与孪生前端**同一份** `/ws` 广播——ROS 层不存在第二条物理链路，「后端是唯一真理源」的铁律延伸到了 ROS 生态。
2. **`/odom` 发布漂移里程计是刻意为之**：SLAM 的 `map→odom` 校正量因此**非恒等、随行程持续变化**，成为「真分叉」在 ROS 层的可观测证据；若误发真值 `robot`，校正量恒为单位变换，等价于在 ROS 层复活 C1 型假仪表（`odom≡truth`），与平台防自欺立场自相矛盾。
3. **Nav2 与人工遥控完全同构**：Nav2 的 `/cmd_vel` 与 teleop 走同一条覆盖通道，网关的决策权仲裁对「人工 / Nav2 / RL」三方统一——桥接与网关均无需感知指令来源。
4. **双订阅通道适配两代 Nav2 契约**：`/cmd_vel`（`Twist`，Humble 全链默认）与 `/cmd_vel_nav`（`TwistStamped`，Jazzy 起默认），消息类型不匹配的通道自然不连接，恰好实现按发行版自动选路，无需 remap。

### 7.3 闭环的硬性契约约束（联调前必读）

| 约束 | 来源 | 对 SLAM/Nav2 的影响 |
|---|---|---|
| **v ∈ [0, 1.0] m/s，不能倒退** | 网关 `clip(linear/MAX_LIN_VEL, 0.0, 1.0)` | Nav2 控制器必须禁倒车（DWB `min_vel_x: 0.0` / RPP `allow_reversing: false`），否则倒车轨迹静默失败 |
| **\|w\| ≤ 1.5 rad/s、半径 0.20 m** | `embodied_env.py` 常量 | 控制器速度上限与 costmap `robot_radius` 须与之一致 |
| **`/scan` QoS 为 BEST_EFFORT** | 桥接 `sensor_qos` | 订阅端（rviz2 等）Reliability 必须选 Best Effort，Reliable 端点不建立连接 |
| **`/odom` 仅位姿、twist 恒 0** | 契约无速度字段 | 依赖速度反馈的控制器（DWB 评分）可能异常，建议改用 RPP 等 |
| **时间戳为墙钟** | 桥接 `get_clock().now()` | 全链路 `use_sim_time` 必须为 `false`；跨机部署需 NTP 对时 |
| **默认网关回合制 + 6 倍墙钟速** | `inference_server.py` 回合结束自动 reset（重摆障碍）；60Hz 心跳 × `DT=0.1s` | SLAM 图叠影、导航统计不可复现——量化实验改用 `nav_gateway.py`（静态世界、10Hz 实时，README 5.9） |

### 7.4 边界声明

以上闭环由架构保证「接口对齐」，但**跑通与否受 ROS 2 发行版、Nav2 版本与参数细节影响，本仓库不做自动化验证承诺**。请按 README 第 5 节的五关判据逐级验证，如实记录结果——区分「看起来对」与「被证明对」正是平台的教学立场。
