# Embodied-SimLite 实验工作单：ROS 2 端到端联调与系统审计

> 配套仓库 README 第 5 节「ROS 2 端到端闭环自行验证（SLAM 建图 + Nav2 导航）」。
> 本工作单要求**如实记录**：通过与不通过都是有效结果，排障过程本身就是实验成果的一部分——区分「看起来对」与「被证明对」。

| 姓名 | 学号 | 日期 | ROS 2 发行版 | 部署方式（同机 / 跨机） |
|---|---|---|---|---|
| | | | | |

---

## 一、实验目标

1. 在真实 ROS 2 环境中打通「数字孪生 → 桥接 → SLAM 建图 → Nav2 导航 → 控制回注」的端到端闭环；
2. 在 ROS 层完成两个**审计观察点**的取证：`/odom` 为漂移里程计而非真值；`map→odom` 校正量非恒等；
3. 产出一套带命令行与时间戳的**过程性证据截图**（E1–E8）。

## 二、环境准备（第 0 步）

```bash
# ROS 2 侧一次性安装（Humble 为例，Jazzy 换包名前缀）
sudo apt install ros-humble-slam-toolbox ros-humble-navigation2 \
                 ros-humble-nav2-bringup ros-humble-teleop-twist-keyboard
pip install websocket-client

# 终端 A（宿主机或本机）：启动推理网关
python inference_server.py           # 浏览器确认 http://localhost:8000 正常

# 终端 B（ROS 2 环境）：启动桥接；跨机必须指定网关 IP
SIM_GATEWAY_WS=ws://<网关IP>:8000/ws python ros_bridge.py
```

**预期**：终端 B 打印 `✅ 已成功连接到推理网关！`。
**注意**：此后若出现 `requesting incompatible QoS` 的 WARN 不要忽略——它点名了哪个订阅者连不上 `/scan`，是第 3 关排障的直接线索。

- [ ] 网关已启动，浏览器可见孪生画面
- [ ] 桥接已连接（📸 **截图 E1**：桥接终端启动命令 + ✅ 连接日志）

## 三、五关任务

### 第 1 关：话题与 tf 冒烟

```bash
ros2 topic list                                # 应含 /odom /scan
ros2 topic hz /odom                            # ≈60 Hz
ros2 topic echo /scan --once                   # 24 个 ≤5.0 的测距值
ros2 run tf2_ros tf2_echo odom base_footprint  # 位姿随本体运动变化
ros2 run tf2_tools view_frames                 # 产出 frames.pdf
```

**判据**：tf 树为 `odom → base_footprint → {base_link, laser_frame}`；`/odom` 数值与浏览器中**红色幻影**（里程计）一致而非绿色真值。

- [ ] /odom 实测频率：________ Hz
- [ ] tf 树结构正确（📸 **截图 E3**：frames.pdf）
- [ ] 📸 **截图 E2**：`topic hz /odom` + `echo /scan --once` 输出

### 第 2 关：人工覆盖（虚实控制权切换）

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

**判据**：按 `i`/`j`/`l` 本体即时响应，浏览器控制模式由青色「RL 自动」切红色「ROS 2 人工覆盖」，停手 2 秒自动交还。按 `,`（后退）本体不动是**设计使然**（v 被网关截断为 0），请如实记录而非当作故障。

- [ ] 覆盖生效、2 秒后自动交还（实测交还耗时：________ s）
- [ ] 后退指令无效已确认并理解原因
- [ ] 📸 **截图 E5**（同屏）：teleop 终端 + 浏览器控制模式变红 + 桥接 🕹️ 日志

### 第 3 关：rviz2 观测

Fixed Frame 设 `odom`；Add → LaserScan（`/scan`）、Odometry（`/odom`）、TF。

> ⚠️ **必踩坑预告**：展开 LaserScan → Topic 小三角，**Reliability 改 Best Effort，Durability 保持 Volatile**——两项都要核对，只改一项仍收不到点。改对的标志是桥接终端不再新增 QoS WARN。`Status: Ok` 不代表收到数据，以画面上是否出现激光点为准。

**判据**：24 个激光点勾出 10×10 m 场地边界与圆形障碍。

- [ ] 修改前的 QoS WARN 已截图（📸 **截图 E8-前**）
- [ ] 修改后激光点出现（📸 **截图 E8-后**；E8 前后对照即排障过程证据）
- [ ] 📸 **截图 E4**（同屏）：rviz2 里程计轨迹 + 浏览器孪生（绿真值/红幻影）→ **审计观察点一**

### 第 4 关：SLAM 建图（slam_toolbox）

```bash
ros2 launch slam_toolbox online_async_launch.py use_sim_time:=false
ros2 node list          # 必须确认 /slam_toolbox 在列——「无地图」最常见原因是它没启动
```

rviz2 中 Fixed Frame 切 `map`、Add → Map（`/map`），用 teleop 缓速绕场 1–2 圈。

> 预期管理：默认网关每回合重摆障碍——图中障碍会成叠影，这本身就是「世界在变而系统不自知」
> 的审计观察素材；本关判据只考察 `map→odom` 校正机制是否生效。需要干净地图或导航成功率
> 统计 → 用 README 5.9 静态世界模式（`nav_gateway.py`）。

**判据**：
1. `ros2 topic echo /map --once` 有栅格数据；
2. `ros2 run tf2_ros tf2_echo map odom` **非恒等且随行程变化**——SLAM 正在校正里程计真漂移（**审计观察点二**）；若恒为单位变换，闭环未打通；
3. 存图成功：`ros2 run nav2_map_server map_saver_cli -f simlite_map`。

- [ ] /map 有数据；map→odom 校正量非恒等
- [ ] 存图产物 simlite_map.pgm/.yaml 存在
- [ ] 📸 **截图 E6**（同屏）：rviz2 占据栅格 + `tf2_echo map odom` 非零输出

### 第 5 关：Nav2 导航闭环

复制 `nav2_params.yaml` 修改四处后启动（与 slam_toolbox 同跑，无需 AMCL/map_server）：

| 参数 | 值 | 原因 |
|---|---|---|
| `robot_radius`（两个 costmap） | `0.20` | 与本体半径一致 |
| 控制器 `max_vel_x` / `max_vel_theta` | `≤1.0` / `≤1.5` | 与 env 上限一致 |
| DWB `min_vel_x`（或 RPP `allow_reversing`） | `0.0`（`false`） | **本体不能倒退** |

```bash
ros2 launch nav2_bringup navigation_launch.py use_sim_time:=false params_file:=<改后路径>
```

> 注：默认网关下回合 reset 会中途重摆世界，判据③『Goal succeeded』偶发达成即视为链路打通；
> 导航成功率等量化统计务必改用 README 5.9 静态世界模式。

rviz2 用 **2D Goal Pose** 下发目标。**闭环判据（四条全满足才算打通）**：
1. 桥接终端滚动打印 `🕹️ [人工覆盖下发]`；
2. 本体沿全局路径行进，代价地图中的圆障碍被实时刻画且被避开；
3. Nav2 报 `Goal succeeded`；
4. 停止发令 2 秒后控制模式回落「RL 自动」。

- [ ] 四条判据逐条核对：① [ ] ② [ ] ③ [ ] ④ [ ]
- [ ] 📸 **截图 E7**：rviz2 全局路径 + 代价地图避障 + `Goal succeeded` 日志

## 四、证据截图规范

- 每张截图**必须保留完整命令行与 ROS 时间戳**（证明实跑而非摆拍）；
- 对照类证据（E4/E5/E6/E8）用**双窗口同屏**拍摄；
- 统一 PNG 无损格式，文件名 `E<编号>_<学号>.png`；
- E8 为「排障前后对照」：QoS 报错 → 读警告定位 → 修正 → 激光点出现，完整保留。

| 编号 | 内容 | 证明什么 | 已提交 |
|---|---|---|---|
| E1 | 桥接启动 + ✅ 连接日志 | 跨环境链路建立 | [ ] |
| E2 | `topic hz /odom` + `echo /scan --once` | 数据流真实、≈60 Hz | [ ] |
| E3 | frames.pdf | tf 树完整 | [ ] |
| E4 | rviz2 轨迹 ↔ 浏览器孪生同屏 | 真分叉可观测（审计点一） | [ ] |
| E5 | teleop + 控制模式变红 + 🕹️ 日志 | 虚实控制权切换 | [ ] |
| E6 | 占据栅格 + `tf2_echo map odom` 非零 | SLAM 在校正漂移（审计点二） | [ ] |
| E7 | 全局路径 + 避障 + `Goal succeeded` | Nav2 闭环打通 | [ ] |
| E8 | QoS 报错 ↔ 修复后对照 | 排障过程性证据 | [ ] |

## 五、常见问题速查

| 症状 | 常见原因 | 处理 |
|---|---|---|
| rviz2 无激光点但 Status: Ok | Reliability=Reliable 或 Durability=Transient Local | 两项都核对：Best Effort + Volatile |
| Map 显示 No map received | slam_toolbox 没启动 | `ros2 node list` 确认 `/slam_toolbox` |
| 下发目标后本体不动/抖动 | 控制器输出负线速度被截断 | 禁倒车参数（见第 5 关表） |
| tf 报 extrapolation | 某节点 use_sim_time=true 或跨机时钟不同步 | 全链 `use_sim_time:=false`；NTP 对时 |
| Nav2 有输出但孪生无响应 | 桥接掉线或消息类型不匹配 | 看桥接 ✅/🕹️ 日志；`ros2 topic info /scan --verbose` 逐个核对订阅端 QoS |

## 六、如实记录声明

本人确认以上记录与截图均来自本人实跑结果，未通过之处已如实标注。

签名：____________　日期：____________
