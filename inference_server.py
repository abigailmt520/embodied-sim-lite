# -*- coding: utf-8 -*-
"""
inference_server.py
===================
「算力置换架构」之推理态：60Hz 异步推理 + 孪生状态广播网关 + 前端观测域宿主。

本文件是【系统级唯一启动入口】。它一肩三挑：
    1. 承载 PPO 策略网络，以严密 60Hz 心跳驱动纯计算物理内核 embodied_env.py；
    2. 通过 `@app.get("/")` 直出整套 Three.js 孪生观测域前端（迁移自旧版 ProductV1.0）；
    3. 通过 `/ws` 广播 `env.get_render_state()` 的新版嵌套数据契约，并接收 ROS 2 桥接器
       下发的 `/cmd_vel` 人工覆盖指令，实现「虚实控制权无缝切换」（Override Control）。

第一性原理（彻底解耦）：
    - 物理推演：完全交由 embodied_env.py（纯 numpy 同步状态机），本文件不含任何物理逻辑；
      旧版 ProductV1.0 中的 `physics_loop()` 与全局 `state` 字典已彻底废弃，不再迁移。
    - AI 决策：PPO 策略网络在本文件以 60Hz 推理；可被 ROS 2 人工指令在 2s 窗口内抢占。
    - 孪生渲染：仅由前端 Three.js 消费广播状态，服务端不参与渲染。

每个 tick 的数据流：
    读取 Observation → (Override? 人工指令 : PPO 推理) Action → env.step() 推进物理 →
    序列化孪生状态 → WebSocket 广播给所有前端观测窗 / ROS 2 桥接器。

依赖：fastapi, uvicorn, websockets, stable-baselines3, torch, numpy。
运行：python inference_server.py   （或 uvicorn inference_server:app --host 0.0.0.0 --port 8000）
"""

import asyncio
import json
from contextlib import asynccontextmanager

import numpy as np
import torch
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from stable_baselines3 import PPO

from embodied_env import EmbodiedNavEnv

# —— 必须与 train_agent.py 完全一致，否则 load_state_dict 形状不匹配 ——
MODEL_PATH = "ppo_embodied_agent.pth"
POLICY_KWARGS = dict(net_arch=dict(pi=[64, 64], vf=[64, 64]))
TICK_HZ = 60.0                     # 孪生心跳频率
TICK_DT = 1.0 / TICK_HZ

# —— 虚实控制权切换：收到 /cmd_vel 后，在此窗口内屏蔽 RL 自动推理，优先执行人工覆盖 ——
OVERRIDE_WINDOW_S = 2.0


# ====================================================================
# 人工覆盖控制器（Override Control）：ROS 2 /cmd_vel → 抢占 RL 推理
# ====================================================================
class OverrideController:
    """缓存最近一次 ROS 2 人工指令，并在 OVERRIDE_WINDOW_S 内抢占 RL 自动推理。

    cmd_vel 为真实物理量（linear.x m/s、angular.z rad/s），此处统一换算回 env 的
    归一化动作空间 [v∈[0,1], w∈[-1,1]]，使物理内核对「人工/AI」两路控制完全无感。
    """

    def __init__(self, window_s: float = OVERRIDE_WINDOW_S):
        self.window_s = window_s
        self._action: np.ndarray | None = None
        self._expiry = 0.0

    def submit(self, linear: float, angular: float, now: float):
        v = float(np.clip(linear / EmbodiedNavEnv.MAX_LIN_VEL, 0.0, 1.0))
        w = float(np.clip(angular / EmbodiedNavEnv.MAX_ANG_VEL, -1.0, 1.0))
        self._action = np.array([v, w], dtype=np.float32)
        self._expiry = now + self.window_s

    def active(self, now: float) -> bool:
        return self._action is not None and now < self._expiry

    def get(self, now: float) -> np.ndarray | None:
        """窗口内返回人工动作；窗口过期返回 None（交还 RL）。"""
        return self._action if self.active(now) else None


override = OverrideController()


# ====================================================================
# WebSocket 连接管理器：维护所有前端观测窗 / ROS 2 桥接器，统一广播
# ====================================================================
class ConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, message: str):
        # 复制一份避免广播过程中集合被并发修改；失联连接顺手清理
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()

# 全局单例：推理环境内核 + 策略模型（在 lifespan 中初始化）
env = EmbodiedNavEnv(render_mode=None)
model: PPO | None = None


def load_model() -> PPO:
    """重建与训练期同构的 PPO，并载入 .pth 权重（policy state_dict）。

    说明：直接构造 PPO 时不会真正训练，仅用于复现网络结构以承接 state_dict。
    若你保留了 SB3 原生 zip 存档，亦可用更鲁棒的：
        return PPO.load("ppo_embodied_agent", device="cpu")
    """
    m = PPO("MlpPolicy", env, policy_kwargs=POLICY_KWARGS, device="cpu")
    state_dict = torch.load(MODEL_PATH, map_location="cpu")
    m.policy.load_state_dict(state_dict)
    m.policy.eval()   # 推理态：关闭 dropout/batchnorm 等训练行为
    return m


# ====================================================================
# 后台异步协程：60Hz 严密心跳推理循环（含人工覆盖抢占）
# ====================================================================
async def simulation_loop():
    """以漂移补偿的方式维持精确 60Hz，逐 tick 决策并广播孪生状态。

    决策权仲裁：若 2s 覆盖窗口内收到过 ROS 2 /cmd_vel，则执行人工动作；否则 PPO 自动推理。
    """
    loop = asyncio.get_event_loop()
    obs, info = env.reset()
    next_tick = loop.time()

    while True:
        now = loop.time()

        # —— 1) 决策权仲裁：人工覆盖优先，否则 PPO 推理 ——
        manual = override.get(now)
        if manual is not None:
            action = manual          # 虚实切换：ROS 2 人工指令抢占
        else:
            # 小型 MLP 的 predict 为亚毫秒级同步运算，直接在事件循环内执行即可；
            # 若换用重型网络，应改为 await loop.run_in_executor(...) 避免阻塞心跳。
            action, _ = model.predict(obs, deterministic=True)

        # —— 2) 物理步进（物理内核对人工/AI 两路控制完全无感）——
        obs, reward, terminated, truncated, info = env.step(action)

        # —— 3) 序列化并广播孪生状态给所有前端观测窗 / ROS 2 桥接器 ——
        state = env.get_render_state(reward=reward, terminated=terminated,
                                     truncated=truncated, info=info)
        # 服务端增补一个控制权标记（不污染 env 契约），供前端遥测显示
        state["control_mode"] = "override" if manual is not None else "rl"
        await manager.broadcast(json.dumps(state, separators=(",", ":")))

        # —— 4) 回合结束自动复位，让孪生演示持续滚动 ——
        if terminated or truncated:
            obs, info = env.reset()

        # —— 5) 漂移补偿心跳：sleep 剩余时间而非固定 1/60，抑制累计时钟漂移 ——
        next_tick += TICK_DT
        sleep_time = next_tick - loop.time()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        else:
            # 单 tick 超时（计算来不及）：重置基准，避免追赶式连发
            next_tick = loop.time()


# ====================================================================
# FastAPI 生命周期：启动时载入模型并拉起后台心跳，关闭时优雅取消
# ====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    model = load_model()
    print(f">>> 模型已载入: {MODEL_PATH}，启动 {TICK_HZ:.0f}Hz 孪生推理心跳...")
    task = asyncio.create_task(simulation_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        print(">>> 推理心跳已停止。")


app = FastAPI(title="Embodied-SimLite Inference Gateway", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """统一 WS 端点：前端 Three.js 观测窗 + ROS 2 桥接器均连此端点。

    - 下行：服务端按 60Hz 广播 env.get_render_state() 的孪生状态。
    - 上行：仅识别 ROS 2 桥接器下发的人工覆盖控制
            {"cmd_vel": {"linear": <m/s>, "angular": <rad/s>}}；其余消息忽略。
    """
    await manager.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            cv = data.get("cmd_vel") if isinstance(data, dict) else None
            if isinstance(cv, dict):
                override.submit(
                    linear=float(cv.get("linear", 0.0)),
                    angular=float(cv.get("angular", 0.0)),
                    now=asyncio.get_event_loop().time(),
                )
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


@app.get("/health")
async def health():
    """健康检查 / 连接信息。"""
    return {
        "service": "Embodied-SimLite Inference Gateway",
        "tick_hz": TICK_HZ,
        "clients": len(manager.active),
        "ws_endpoint": "/ws",
    }


# ====================================================================
# Task 1：前后端服务大一统 —— 迁移自旧版 ProductV1.0 的 Three.js 孪生观测域
# Task 2：ws.onmessage 已重写，严格适配 embodied_env.get_render_state() 的嵌套契约
# ====================================================================
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Embodied-SimLite | RL 推理孪生观测域</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/litegraph.js/css/litegraph.css">
    <style>
        body, html { margin: 0; padding: 0; width: 100vw; height: 100vh; overflow: hidden; background-color: #1a1a1a; font-family: sans-serif; color: white; }
        #main-container { display: flex; width: 100vw; height: 100vh; flex-direction: row; }
        #left-panel { flex: 0 0 36%; height: 100%; border-right: 1px solid #333; background-color: #222; position: relative; min-width: 200px; }
        #resizer { width: 6px; cursor: ew-resize; background-color: #333; transition: background 0.2s; z-index: 100; }
        #resizer:hover { background-color: #00ffcc; }
        #right-panel { flex: 1; height: 100%; background-color: #111; position: relative; overflow: hidden; min-width: 200px; }
        canvas { display: block; outline: none; }

        .panel-title {
            position: absolute; top: 10px; left: 20px;
            color: #00ffcc; font-family: monospace;
            z-index: 1000; pointer-events: none;
            text-shadow: 1px 1px 2px black;
            background: rgba(0,0,0,0.6);
            padding: 8px 12px; border-radius: 6px;
        }
        .app-brand { display: block; font-size: 1.2em; font-weight: bold; color: #fff; margin-bottom: 4px; }

        #telemetry { position: absolute; top: 20px; right: 20px; background: rgba(0,0,0,0.8); padding: 15px; border-radius: 8px; font-family: monospace; border: 1px solid #444; z-index: 1000; pointer-events: none; min-width: 240px;}
        .tel-row { display: flex; justify-content: space-between; margin: 5px 0; font-size: 13px; }
        .truth { color: #00ffcc; }
        .odom { color: #ff4444; }
        #canvas-container { width: 100%; height: 100%; display: block; }

        #view-hint {
            position: absolute; bottom: 20px; right: 20px; color: rgba(255,255,255,0.5);
            font-family: monospace; font-size: 12px; pointer-events: none; z-index: 1000;
        }

        /* ---- 论文截图模式（?screenshot=1）：全局字号 ≥16px、遥测行高加大、
                隐藏与演示无关的操作提示，供期刊单栏（约 8cm）印刷截图 ---- */
        body.screenshot-mode { font-size: 16px; }
        body.screenshot-mode .panel-title { font-size: 1.35em; }
        body.screenshot-mode .app-brand { font-size: 1.25em; }
        body.screenshot-mode #telemetry { min-width: 330px; padding: 20px; }
        body.screenshot-mode .tel-row { font-size: 17px; margin: 11px 0; }
        body.screenshot-mode #telemetry h3 { font-size: 19px; }
        body.screenshot-mode #telemetry p { font-size: 16px; }
        body.screenshot-mode #view-hint { display: none; }
    </style>
</head>
<body>
    <div id="main-container">
        <div id="left-panel">
            <h2 class="panel-title">
                <span class="app-brand">Embodied-SimLite | RL 推理孪生观测域</span>
                🧩 模块一：感知与控制蓝图
            </h2>
            <canvas id="node-canvas"></canvas>
        </div>
        <div id="resizer"></div>
        <div id="right-panel">
            <h2 class="panel-title">🌐 模块二：Cyber-Physical 孪生观测域</h2>
            <div id="telemetry">
                <h3 style="margin-top:0; color:#fff; border-bottom:1px solid #555; padding-bottom:5px;">📡 遥测数据(Telemetry)</h3>
                <div class="tel-row truth"><span>真实坐标 X:</span><span id="true_x">0.00</span></div>
                <div class="tel-row truth"><span>真实坐标 Y:</span><span id="true_y">0.00</span></div>
                <div class="tel-row truth"><span>真实朝向 Yaw:</span><span id="true_yaw">0.00</span></div>
                <hr style="border: 0.5px solid #333;">
                <div class="tel-row odom"><span>里程计 X:</span><span id="odom_x">0.00</span></div>
                <div class="tel-row odom"><span>里程计 Y:</span><span id="odom_y">0.00</span></div>
                <div class="tel-row odom"><span>里程计 Yaw:</span><span id="odom_yaw">0.00</span></div>
                <hr style="border: 0.5px solid #333;">
                <div class="tel-row" style="color:#ffcc00;"><span>距目标:</span><span id="dist_val">0.00 m</span></div>
                <div class="tel-row" style="color:#ffcc00;"><span>步数 / 即时奖励:</span><span id="step_reward">0 / 0.0</span></div>
                <div class="tel-row" style="color:#ffaa00; font-weight:bold;"><span>🕹️ 控制权:</span><span id="ctrl_mode">RL 自动</span></div>
                <div class="tel-row" style="color:#ff4444; font-weight:bold;"><span>回合状态:</span><span id="epi_status">运行中</span></div>
                <p>状态: <span id="wsStatus" style="color: yellow;">连接中...</span></p>
            </div>
            <div id="view-hint">左键: 旋转 | 右键: 平移 | 滚轮: 缩放 | R键: 视角归位</div>
            <!-- INV-1 / D-017：WS 断流时显式 OFFLINE 遮罩，画面冻结、严禁本地推演续算 -->
            <div id="offline-overlay" style="display:none; position:absolute; inset:0; z-index:2000;
                 background:rgba(20,0,0,0.55); backdrop-filter:grayscale(0.8) blur(1px);
                 display:none; align-items:center; justify-content:center; pointer-events:none;">
                <div style="font-family:monospace; text-align:center; color:#ff6666;
                     border:2px solid #ff4444; border-radius:12px; padding:22px 30px;
                     background:rgba(0,0,0,0.8);">
                    <div style="font-size:1.6em; font-weight:bold;">⚠ OFFLINE</div>
                    <div style="margin-top:8px; color:#ffaaaa;">真理源链路中断 · 画面已冻结</div>
                    <!-- 检查点名称为论文 v1.1 术语(与论文图 2 行名一致) -->
                    <div id="c3-term" style="margin-top:6px; font-size:0.85em; color:#ffbbbb;">完整性检查点：C3 断流冻结 / FEED_LIVENESS</div>
                    <div style="margin-top:4px; font-size:0.8em; color:#cc8888;">前端不做本地推演（dead-reckoning），等待后端重连…</div>
                </div>
            </div>
            <div id="canvas-container"></div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/litegraph.js/build/litegraph.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>

    <script>
        // 旧蓝图节点的扁平镜像：x/y/yaw 来自真值 d.robot；ox/oy/oyaw 来自里程计 d.odom（带打滑漂移）
        window.simData = { x: 0, y: 0, yaw: 0, ox: 0, oy: 0, oyaw: 0, v: 0 };

        window.onload = function() {
            // ---- 论文截图模式（?screenshot=1）：放大字号/行距、隐藏操作提示、
            //      双语文案取中文部分（论文 v1.1 术语），供论文图 2/图 3 期刊截图 ----
            const screenshotMode = new URLSearchParams(window.location.search).get('screenshot') === '1';
            if (screenshotMode) {
                document.body.classList.add('screenshot-mode');
                document.getElementById('c3-term').innerText = '完整性检查点：C3 断流冻结';
            }

            // 统一连到推理网关的 /ws（取代旧版 /ws/simulation）
            const wsUrl = `ws://${window.location.host}/ws`;
            const ws = new WebSocket(wsUrl);

            // ---- INV-1 / D-017：断流即冻结并显式标 OFFLINE（前端永不本地推演位姿）----
            // 说明：本前端的位姿只在 ws.onmessage 中被赋值，animate() 不做任何积分，
            // 故断流后画面自然冻结（非 dead-reckoning）。下列函数只负责把"冻结"这一事实
            // 显式化，消除"连接断开却仍显示运行中"的孪生权威性矛盾。
            function setOffline() {
                document.getElementById('wsStatus').innerHTML = "<span style='color: #ff6666;'>❌ 连接断开 (OFFLINE · 画面冻结)</span>";
                document.getElementById('offline-overlay').style.display = 'flex';
                const st = document.getElementById('epi_status');
                st.innerText = '⚠ OFFLINE'; st.style.color = '#ff6666';
            }
            function clearOffline() {
                document.getElementById('offline-overlay').style.display = 'none';
            }

            ws.onopen = () => { clearOffline(); document.getElementById('wsStatus').innerHTML = "<span style='color: lime;'>✅ 推理网关在线</span>"; };
            ws.onclose = () => setOffline();
            ws.onerror = () => setOffline();

            var graph = new LGraph();
            var canvas = new LGraphCanvas("#node-canvas", graph);

            graph.onBeforeStep = function() {
                for (let i = 0; i < graph._nodes.length; ++i) {
                    if (graph._nodes[i].pos[1] < 170) graph._nodes[i].pos[1] = 170;
                }
            };

            function syncCanvasSize() {
                const lp = document.getElementById('left-panel');
                const cv = document.getElementById('node-canvas');
                cv.width = lp.clientWidth; cv.height = lp.clientHeight;
                if (canvas) { canvas.resize(); canvas.draw(true, true); }
            }

            // ---------- 蓝图节点（教学/可视化用途；控制权已交给 RL/ROS，节点不再回写 ws） ----------
            function WatchNode() {
                this.addInput("X", "number"); this.addInput("Y", "number"); this.addInput("Yaw", "number");
                this.properties = { x: 0, y: 0, yaw: 0 };
                this.color = "#143"; this.bgcolor = "#264"; this.size = [160, 70]; this.title_text_color = "#00ffcc";
            }
            WatchNode.title = "👁️ 姿态监视器 (Pose)";
            WatchNode.prototype.onExecute = function() {
                this.properties.x = this.getInputData(0) || 0; this.properties.y = this.getInputData(1) || 0; this.properties.yaw = this.getInputData(2) || 0;
            };
            WatchNode.prototype.onDrawBackground = function(ctx) {
                if (this.flags.collapsed) return;
                ctx.fillStyle = "#00ffcc"; ctx.font = "bold 14px monospace";
                let x_val = (this.properties.x || 0).toFixed(2);
                let y_val = (this.properties.y || 0).toFixed(2);
                let yaw_deg = ((this.properties.yaw || 0) * 180 / Math.PI) % 360;
                if (yaw_deg > 180) yaw_deg -= 360; else if (yaw_deg < -180) yaw_deg += 360;
                ctx.fillText(`${x_val}`, 50, 25);
                ctx.fillText(`${y_val}`, 50, 45);
                ctx.fillText(`${yaw_deg.toFixed(1)}°`, 50, 65);
            };
            LiteGraph.registerNodeType("分析/监视器", WatchNode);

            function OdomNode() {
                this.addOutput("估计 X", "number"); this.addOutput("估计 Y", "number"); this.addOutput("估计 Yaw", "number");
                this.color = "#622"; this.bgcolor = "#833"; this.size = [180, 80]; this.title_text_color = "#00ffcc";
            }
            OdomNode.title = "⚙️ 轮式里程计(Odom)";
            OdomNode.prototype.onExecute = function() { this.setOutputData(0, window.simData.ox); this.setOutputData(1, window.simData.oy); this.setOutputData(2, window.simData.oyaw); };
            LiteGraph.registerNodeType("传感/里程计", OdomNode);

            function TruthNode() {
                this.addOutput("真实 X", "number"); this.addOutput("真实 Y", "number"); this.addOutput("真实 Yaw", "number");
                this.color = "#266"; this.bgcolor = "#388"; this.size = [180, 80]; this.title_text_color = "#00ffcc";
            }
            TruthNode.title = "🛰️ 真实位置(Truth)";
            TruthNode.prototype.onExecute = function() { this.setOutputData(0, window.simData.x); this.setOutputData(1, window.simData.y); this.setOutputData(2, window.simData.yaw); };
            LiteGraph.registerNodeType("传感/真实定位", TruthNode);

            var nTruth = LiteGraph.createNode("传感/真实定位"); nTruth.pos=[30, 200]; graph.add(nTruth);
            var nOdom = LiteGraph.createNode("传感/里程计"); nOdom.pos=[30, 320]; graph.add(nOdom);
            var nWatchTruth = LiteGraph.createNode("分析/监视器"); nWatchTruth.pos=[300, 200]; graph.add(nWatchTruth);
            var nWatchOdom = LiteGraph.createNode("分析/监视器"); nWatchOdom.pos=[300, 320]; graph.add(nWatchOdom);
            nTruth.connect(0, nWatchTruth, 0); nTruth.connect(1, nWatchTruth, 1); nTruth.connect(2, nWatchTruth, 2);
            nOdom.connect(0, nWatchOdom, 0); nOdom.connect(1, nWatchOdom, 1); nOdom.connect(2, nWatchOdom, 2);
            graph.start();

            // ==========================================
            // 3D 渲染与控制
            // ==========================================
            const rp = document.getElementById('right-panel');
            const scene = new THREE.Scene();
            const camera = new THREE.PerspectiveCamera(45, rp.clientWidth/rp.clientHeight, 0.1, 1000);

            // 初始视角先给个占位，待收到 arena 尺寸后聚焦到场地中心
            let initialCameraPos = new THREE.Vector3(5, -8, 12);
            let initialCameraTarget = new THREE.Vector3(5, 5, 0);
            camera.position.copy(initialCameraPos);
            camera.lookAt(initialCameraTarget);

            const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(rp.clientWidth, rp.clientHeight);
            document.getElementById('canvas-container').appendChild(renderer.domElement);

            const controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;
            controls.dampingFactor = 0.05;
            controls.screenSpacePanning = true;
            controls.minDistance = 2;
            controls.maxDistance = 80;
            controls.maxPolarAngle = Math.PI / 2 - 0.05;
            controls.target.copy(initialCameraTarget);

            scene.add(new THREE.AmbientLight(0xffffff, 0.7));
            const light = new THREE.DirectionalLight(0xffffff, 0.8); light.position.set(5, 10, 10); scene.add(light);

            const grid = new THREE.GridHelper(40, 40, 0x444444, 0x222222);
            grid.rotation.x = Math.PI/2;
            scene.add(grid);

            // ---------- 动态场景：场地边界 / 圆形障碍 / 目标点（全部由新版契约驱动） ----------
            const wallMat = new THREE.MeshLambertMaterial({color: 0x555577});
            let arenaBuilt = false;

            function buildArena(w, h) {
                // 地板
                const floor = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
                    new THREE.MeshLambertMaterial({color: 0x182838}));
                floor.position.set(w/2, h/2, -0.01);
                scene.add(floor);
                // 四面边界墙（与 env 的 0..w / 0..h 轴对齐场地一致）
                const t = 0.1, hh = 0.4;
                const segs = [
                    [w, t, w/2, 0], [w, t, w/2, h],   // 下、上
                    [t, h, 0, h/2], [t, h, w, h/2],   // 左、右
                ];
                segs.forEach(([sw, sh, cx, cy]) => {
                    const m = new THREE.Mesh(new THREE.BoxGeometry(sw, sh, hh), wallMat);
                    m.position.set(cx, cy, hh/2);
                    scene.add(m);
                });
                // 聚焦到场地中心
                initialCameraTarget = new THREE.Vector3(w/2, h/2, 0);
                initialCameraPos = new THREE.Vector3(w/2, h/2 - 0.85*h, 1.3*h);
                camera.position.copy(initialCameraPos);
                controls.target.copy(initialCameraTarget);
                controls.update();
                arenaBuilt = true;
            }

            // 圆形障碍：障碍集每个回合 reset 会变，检测到变化即整体重建
            const obstacleMat = new THREE.MeshLambertMaterial({color: 0xff6600});
            let obstacleMeshes = [];
            let obstacleSig = "";
            function syncObstacles(obstacles) {
                const sig = obstacles.map(o => `${o.x.toFixed(2)},${o.y.toFixed(2)},${o.r.toFixed(2)}`).join('|');
                if (sig === obstacleSig) return;
                obstacleSig = sig;
                obstacleMeshes.forEach(m => scene.remove(m));
                obstacleMeshes = [];
                obstacles.forEach(o => {
                    const geo = new THREE.CylinderGeometry(o.r, o.r, 0.6, 24);
                    const m = new THREE.Mesh(geo, obstacleMat);
                    m.rotation.x = Math.PI / 2;       // 柱体轴朝 +Z
                    m.position.set(o.x, o.y, 0.3);
                    scene.add(m);
                    obstacleMeshes.push(m);
                });
            }

            // 目标点：随回合 reset 变化
            let goalMesh = null;
            function syncGoal(goal) {
                if (!goalMesh) {
                    goalMesh = new THREE.Mesh(
                        new THREE.CylinderGeometry(goal.radius, goal.radius, 0.04, 32),
                        new THREE.MeshBasicMaterial({color: 0x00ff66, transparent: true, opacity: 0.55}));
                    goalMesh.rotation.x = Math.PI / 2;
                    scene.add(goalMesh);
                }
                goalMesh.position.set(goal.x, goal.y, 0.02);
            }

            // ---------- 小车本体（robotGroup）与里程计幻影（ghostGroup） ----------
            const chassisGeo = new THREE.BoxGeometry(0.4, 0.3, 0.18);
            const robotGroup = new THREE.Group();
            const chassis = new THREE.Mesh(chassisGeo, new THREE.MeshLambertMaterial({color: 0x00cc88}));
            chassis.position.set(0, 0, 0.12);
            robotGroup.add(chassis);

            const arrowShape = new THREE.Shape();
            arrowShape.moveTo(0.22, 0); arrowShape.lineTo(-0.12, 0.15);
            arrowShape.lineTo(-0.04, 0); arrowShape.lineTo(-0.12, -0.15);
            arrowShape.lineTo(0.22, 0);
            const arrowGeo = new THREE.ShapeGeometry(arrowShape);
            const arrow = new THREE.Mesh(arrowGeo, new THREE.MeshBasicMaterial({color: 0xffffff}));
            arrow.position.set(0.05, 0, 0.22);
            robotGroup.add(arrow);
            scene.add(robotGroup);

            // 里程计幻影：渲染后端下发的 d.odom（带打滑漂移）。随时间它会可见地偏离绿色本体——这就是"真分叉"
            const ghostGroup = new THREE.Group();
            const gChassis = new THREE.Mesh(chassisGeo, new THREE.MeshLambertMaterial({color: 0xff3333, transparent: true, opacity: 0.45}));
            gChassis.position.set(0, 0, 0.12);
            ghostGroup.add(gChassis);
            const gArrow = new THREE.Mesh(arrowGeo, new THREE.MeshBasicMaterial({color: 0xffaaaa, transparent: true, opacity: 0.55}));
            gArrow.position.set(0.05, 0, 0.22);
            ghostGroup.add(gArrow);
            scene.add(ghostGroup);

            // ---------- LiDAR 射线：直接消费服务端解析式测距，不再做前端 raycasting ----------
            const lidarMat = new THREE.LineBasicMaterial({ color: 0x00ffff, transparent: true, opacity: 0.6 });
            const lidarGeo = new THREE.BufferGeometry();
            const lidarLines = new THREE.LineSegments(lidarGeo, lidarMat);
            scene.add(lidarLines);

            function updateLidar(robot, lidar) {
                // env 射线偏移：linspace(-π, π, N, endpoint=False) → off_i = -π + i*(2π/N)
                const N = lidar.length;
                if (N === 0) return;
                const positions = new Float32Array(N * 6);
                const z = 0.22;
                for (let i = 0; i < N; i++) {
                    const off = -Math.PI + i * (2 * Math.PI / N);
                    const ang = robot.theta + off;
                    const dist = lidar[i];
                    const b = i * 6;
                    positions[b]   = robot.x;            positions[b+1] = robot.y;            positions[b+2] = z;
                    positions[b+3] = robot.x + Math.cos(ang) * dist;
                    positions[b+4] = robot.y + Math.sin(ang) * dist;
                    positions[b+5] = z;
                }
                lidarGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
                lidarGeo.attributes.position.needsUpdate = true;
                lidarGeo.computeBoundingSphere();
            }

            // ==========================================
            // 🎯 Task 2：ws.onmessage 严格适配 get_render_state() 的新版嵌套契约
            //   契约：{ robot:{x,y,theta,radius}, goal:{x,y,radius},
            //          obstacles:[{x,y,r}], lidar:[m], lidar_range, arena:{w,h},
            //          step, reward, terminated, truncated, distance, control_mode }
            // ==========================================
            ws.onmessage = (e) => {
                clearOffline();   // 收到下行即在线：撤除 OFFLINE 冻结遮罩
                const d = JSON.parse(e.data);
                const robot = d.robot;
                const odom = d.odom || d.robot;   // 真理源 odom；向后兼容：旧契约无 odom 时回退真值

                // 扁平镜像：真值取 d.robot，里程计取 d.odom（不再用真值伪造 odom）
                window.simData.x = robot.x; window.simData.y = robot.y; window.simData.yaw = robot.theta;
                window.simData.ox = odom.x; window.simData.oy = odom.y; window.simData.oyaw = odom.theta;

                if (!arenaBuilt && d.arena) buildArena(d.arena.w, d.arena.h);
                if (d.obstacles) syncObstacles(d.obstacles);
                if (d.goal) syncGoal(d.goal);

                // 小车本体位姿（真值 Truth）
                robotGroup.position.set(robot.x, robot.y, 0);
                robotGroup.rotation.z = robot.theta;
                // 里程计幻影（Odom，带打滑漂移；随时间偏离本体）
                ghostGroup.position.set(odom.x, odom.y, 0);
                ghostGroup.rotation.z = odom.theta;

                // 雷达射线
                if (d.lidar) updateLidar(robot, d.lidar);

                // ---------- 遥测面板 ----------
                document.getElementById('true_x').innerText = robot.x.toFixed(2) + ' m';
                document.getElementById('true_y').innerText = robot.y.toFixed(2) + ' m';
                let ty = (robot.theta * 180 / Math.PI) % 360; if (ty > 180) ty -= 360; else if (ty < -180) ty += 360;
                document.getElementById('true_yaw').innerText = ty.toFixed(1) + '°';

                document.getElementById('odom_x').innerText = odom.x.toFixed(2) + ' m';
                document.getElementById('odom_y').innerText = odom.y.toFixed(2) + ' m';
                let oy_deg = (odom.theta * 180 / Math.PI) % 360; if (oy_deg > 180) oy_deg -= 360; else if (oy_deg < -180) oy_deg += 360;
                document.getElementById('odom_yaw').innerText = oy_deg.toFixed(1) + '°';

                document.getElementById('dist_val').innerText = (d.distance != null ? d.distance.toFixed(2) : '—') + ' m';
                document.getElementById('step_reward').innerText = `${d.step} / ${(d.reward != null ? d.reward.toFixed(2) : '0.00')}`;

                const isOverride = d.control_mode === 'override';
                const cm = document.getElementById('ctrl_mode');
                cm.innerText = isOverride ? 'ROS 2 人工覆盖' : 'RL 自动';
                cm.style.color = isOverride ? '#ff4444' : '#00ffcc';

                const st = document.getElementById('epi_status');
                if (d.terminated && d.distance != null && d.distance < (d.goal ? d.goal.radius : 0.4)) {
                    st.innerText = '🎯 到达目标'; st.style.color = '#00ff66';
                } else if (d.terminated) {
                    st.innerText = '💥 碰撞'; st.style.color = '#ff4444';
                } else if (d.truncated) {
                    st.innerText = '⏱ 超时'; st.style.color = '#ffaa00';
                } else {
                    st.innerText = '运行中'; st.style.color = '#cccccc';
                }
            };

            function animate() {
                requestAnimationFrame(animate);
                controls.update();
                renderer.render(scene, camera);
            }
            animate();

            window.addEventListener('keydown', (e) => {
                if(e.target.tagName.toLowerCase() === 'input') return;
                if (e.key.toLowerCase() === 'r') {
                    camera.position.copy(initialCameraPos);
                    controls.target.copy(initialCameraTarget);
                    controls.update();
                }
            });

            const resizer = document.getElementById('resizer'); const leftPanel = document.getElementById('left-panel'); let isResizing = false;
            resizer.addEventListener('mousedown', () => { isResizing = true; document.body.style.cursor = 'ew-resize'; });
            window.addEventListener('mousemove', (e) => {
                if (!isResizing) return; let percent = (e.clientX / window.innerWidth) * 100;
                if (percent > 15 && percent < 85) { leftPanel.style.flexBasis = percent + '%'; syncCanvasSize(); camera.aspect = rp.clientWidth / rp.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(rp.clientWidth, rp.clientHeight); }
            });
            window.addEventListener('mouseup', () => { isResizing = false; document.body.style.cursor = 'default'; });
            window.addEventListener('resize', () => { syncCanvasSize(); camera.aspect = rp.clientWidth / rp.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(rp.clientWidth, rp.clientHeight); });
            syncCanvasSize();
        };
    </script>
</body>
</html>
"""


@app.get("/")
async def index():
    """直出 Three.js 孪生观测域前端（迁移自旧版 ProductV1.0 的 html_content）。"""
    return HTMLResponse(HTML_CONTENT)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
