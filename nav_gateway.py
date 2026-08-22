#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态世界导航网关（nav_gateway.py）——SLAM/Nav2 实验模式的真理源。

动机：默认入口 inference_server.py 是「回合制 RL 演示」语义，与导航实验存在三项
结构性错配（详见 README 5.9 / Architecture 7.3）：
  ①每回合重摆障碍（到达/碰撞/500 步截断即 reset）→ 障碍物无法建成稳定地图，
    导航统计跨回合不可比；
  ②60Hz 心跳 × DT=0.1s = 物理时间以 6 倍墙钟速推进 → 与 Nav2 墙钟控制错拍；
  ③PPO 常驻自走 → 与外部控制争抢本体。

本网关与 inference_server.py 的差异（其余 ws 契约一致，ros_bridge.py 零改动直连）：
  1. 世界恒定：--seed 一次生成布局，全程不 reset（障碍不再重摆）
  2. --slip 默认 0.0：里程计漂移关闭（odom==truth）；需要真分叉对照可显式传 0.05
  3. 无 PPO：动作 = /cmd_vel 覆盖（2s 窗口），窗口外零动作停车——本体不自走
  4. 心跳 = 1/DT = 10Hz 实时物理（sim 时间 == 墙钟时间）
  5. 无前端页面（观测面 = rviz2）；/health 保留自检
已知特性：动作空间 v∈[0,1] 无倒车，Nav2 的 backup 恢复行为等效 no-op。

配套：make_gt_map.py 以同一 --seed 生成真值占据栅格（map 帧 == 世界帧），
跳过 SLAM 直接供 Nav2/AMCL 使用。勿与 inference_server.py 同时运行（同占 8000）。

用法：python3 nav_gateway.py [--simdir .] [--seed 42] [--port 8000] [--slip 0.0]
"""

import argparse
import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simdir", default=str(Path(__file__).resolve().parent),
                    help="embodied_env.py所在目录（默认=本脚本目录）")
    ap.add_argument("--seed", type=int, default=42, help="世界种子（须与make_gt_map一致）")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--window", type=float, default=2.0, help="覆盖窗口秒")
    ap.add_argument("--slip", type=float, default=0.0,
                    help="里程计打滑系数（默认0=关闭漂移；对照实验可传0.05）")
    return ap.parse_args()


ARGS = parse_args()
sys.path.insert(0, str(Path(ARGS.simdir).expanduser().resolve()))
from embodied_env import EmbodiedNavEnv  # noqa: E402

from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
import uvicorn  # noqa: E402

env = EmbodiedNavEnv(seed=ARGS.seed, slip=ARGS.slip)   # 一次生成，永不reset
TICK_DT = float(env.DT)                          # 1:1实时（=10Hz）


class Override:
    """最近一次/cmd_vel覆盖：窗口内有效；窗口外=零动作停车（无PPO兜底）。"""

    def __init__(self, window_s):
        self.window_s = window_s
        self._action = None
        self._expiry = 0.0

    def submit(self, linear, angular, now):
        v = float(np.clip(linear / env.MAX_LIN_VEL, 0.0, 1.0))
        w = float(np.clip(angular / env.MAX_ANG_VEL, -1.0, 1.0))
        self._action = np.array([v, w], dtype=np.float32)
        self._expiry = now + self.window_s

    def get(self, now):
        return self._action if now < self._expiry else None


override = Override(ARGS.window)


class Manager:
    def __init__(self):
        self.active = set()

    async def connect(self, ws):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws):
        self.active.discard(ws)

    async def broadcast(self, msg):
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = Manager()
START_TS = time.time()
tick_n = 0
terminated_seen = 0


async def sim_loop():
    global tick_n, terminated_seen
    loop = asyncio.get_event_loop()
    next_tick = loop.time()
    print(f">>> 静态世界网关: seed={ARGS.seed} slip={ARGS.slip} tick={1 / TICK_DT:.0f}Hz "
          f"起点真值=({env.pos[0]:.2f},{env.pos[1]:.2f},{np.degrees(env.theta):.0f}°) 永不reset")
    while True:
        now = loop.time()
        act = override.get(now)
        action = act if act is not None else np.array([0.0, 0.0], dtype=np.float32)
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated and act is not None:
            terminated_seen += 1   # 碰撞/RL目标事件只计数、不reset（世界与位姿延续）
        tick_n += 1
        state = env.get_render_state(reward=float(reward), terminated=bool(terminated),
                                     truncated=bool(truncated), info=info)
        state["control_mode"] = "override" if act is not None else "idle"
        state["step"] = int(state.get("seq", tick_n))   # 桥按step去重：保证逐tick递增
        await manager.broadcast(json.dumps(state, separators=(",", ":")))
        next_tick += TICK_DT
        dt = next_tick - loop.time()
        if dt > 0:
            await asyncio.sleep(dt)
        else:
            next_tick = loop.time()   # 单tick超时：重置基准防追赶连发


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(sim_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Embodied-SimLite Nav Gateway (static world)", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
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
                override.submit(float(cv.get("linear", 0.0)),
                                float(cv.get("angular", 0.0)),
                                asyncio.get_event_loop().time())
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


@app.get("/health")
async def health():
    return {"mode": "nav-static", "seed": ARGS.seed, "slip": ARGS.slip,
            "tick_hz": round(1 / TICK_DT, 1), "tick_n": tick_n,
            "uptime_s": round(time.time() - START_TS, 1),
            "robot_truth": {"x": round(float(env.pos[0]), 3),
                            "y": round(float(env.pos[1]), 3),
                            "theta_deg": round(float(np.degrees(env.theta)), 1)},
            "terminated_events": terminated_seen,
            "clients": len(manager.active)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=ARGS.port, log_level="warning")
