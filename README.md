## Embodied-SimLite ｜ 具身智能数字孪生：SLAM建图与动态Nav2联合评测基准

*  本项目旨在解决高校机器人/具身智能教学中，【Ubuntu + ROS 2 + Gazebo仿真】带来的硬件门槛高、易死机，以及底层算法呈现黑盒化的痛点。*

## ✨ 核心特性 (Key Features)

*   🌐 **纯 Web 端零部署 (Zero-Deployment)**：无需笨重的 Gazebo物理引擎，仅需浏览器即可体验 60Hz 的高保真数字孪生环境。
*   ⚖️ **1:1 动力学配平 (Kinematic-Dynamic Alignment)**：底层引擎内置 AABB 绝对刚体碰撞锁死与主动电机制动，实现物理积分稳态速度与 Nav2 下发的 DWB 运动学指令完美咬合，告别越界冲刺。
*   ⏱️ **工业级时空对齐 (Spatio-Temporal Synchronization)**：采用严格的时间戳令牌（Lidar Stamp）与 10Hz 限流拦截机制，消灭浏览器休眠引发的“位姿图撕裂 (Pose Graph Tearing)” Bug。
*   ⚔️ **40x40 六维复合极限压测场 (Benchmark Arena)**：内置长廊退化区、闭环迷宫、U型死锁谷、极窄一线天等经典压测地形。
*   🏃‍♂️ **多智能体动态博弈 (Multi-Agent Dynamic Obstacles)**：全域注入具有物理刚体阻挡效应的“高速巡逻车”，为 Nav2 的局部规划器（TEB/DWA）提供严苛的动态避让与重规划考场。

## 🛠️ 技术栈 (Tech Stack)

*   **智能体生成**：DeepSeek 大语言模型 (全栈结对编程生成)
*   **前端渲染层**：Three.js (3D 孪生) + LiteGraph.js (节点蓝图控制) + Web Workers (免疫休眠机制)
*   **后端计算层**：Python FastAPI + Uvicorn + Websockets
*   **中枢桥接层**：ROS 2 Jazzy + `rclpy` (动态 TF 广播与 SensorData QoS)


## 📖 极简运行指南 (Quick Start)

仅需两步，即可在本地唤醒这台工业级评测基准：

### Step 1: 启动物理与孪生引擎 (Server)
在任意安装了 Python 的终端执行：
```bash
pip install fastapi uvicorn websockets
python Product1.0.py

```
启动后，在浏览器访问 http://localhost:8000 即可进入孪生控制台。

Step 2: 唤醒 ROS 2 通信桥接 (ROS 2 Bridge)
在配置了 ROS 2 Jazzy 的环境中执行：
```bash
python3 sim_ros2_bridgeV1.0.py

```
桥接器启动后，将自动监听 /cmd_vel 与 /cmd_vel_nav 指令，并向 ROS 2 环境高频广播 /odom、/scan 以及动态 /tf 坐标树。此时，您可以直接启动 Cartographer 或 Nav2 节点进行联合压测！

## 🤖 AI 赋能声明 (AI Empowerment)
本项目的核心架构（包括 B/S 通信链路、Three.js 坐标系转换、全域 AABB 碰撞检测算法等）是在 DeepSeek 大模型 的全链条赋能下完成的。AI 的介入不仅将数百小时的底层代码敲击缩短至数日，更成功跨越了跨学科底层物理引擎开发的专业鸿沟。

![输入图片说明](QQ20260503-221343.png)![输入图片说明](QQ20260503-221413.png)