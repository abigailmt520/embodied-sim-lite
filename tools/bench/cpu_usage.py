#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cpu_usage.py —— 教学终端 CPU 占用测量脚本（CSO-028 任务3：≤10% 硬门的「秤」）

两种测法（口径不同，报告同时给出，禁止混用）：
  kernel   无网关的物理内核+PPO 推理吞吐：进程 CPU 时间 / 步数 → 每步 CPU 毫秒，
           并折算为「以 10Hz 决策实时运行时占单核百分比」与「60Hz 心跳折算值」。跨机可比。
  gateway  真实起 inference_server.py（或 nav_gateway.py），可挂 K 个 WebSocket 观测客户端，
           以 1Hz 用 `ps -o %cpu` 采样 T 秒：均值/中位/P95/最大。%cpu 口径 = 单核为 100%（macOS/Linux ps 惯例），
           同时给出 / 机器逻辑核数 的整机占比。这是「教学终端上平台跑起来占多少」的直接读数。

用法：python3 tools/bench/cpu_usage.py [--mode kernel|gateway|both] [--steps 6000] [--duration 30]
                                      [--clients 1] [--server inference_server.py] [--port 8000] [--out result.json]
基线：tools/bench/baseline_course-2026A.json（course tag 上在基准机实测，见 BENCH-MACHINE.md）。
"""
import argparse
import datetime
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def machine_info():
    info = {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "ncpu": os.cpu_count(), "python": platform.python_version(), "hw_model": "", "cpu_brand": "", "mem_gb": None}
    try:
        if info["system"] == "Darwin":
            q = lambda k: subprocess.run(["sysctl", "-n", k], capture_output=True, text=True).stdout.strip()
            info["hw_model"], info["cpu_brand"] = q("hw.model"), q("machdep.cpu.brand_string")
            info["mem_gb"] = round(int(q("hw.memsize")) / 2**30, 1)
        elif info["system"] == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith("model name"):
                    info["cpu_brand"] = line.split(":", 1)[1].strip(); break
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    info["mem_gb"] = round(int(line.split()[1]) / 2**20, 1); break
    except Exception:
        pass
    for m in ("numpy", "torch", "stable_baselines3", "gymnasium", "fastapi", "uvicorn"):
        try:
            info[m] = __import__(m).__version__
        except Exception:
            info[m] = None
    return info


def bench_kernel(steps):
    sys.path.insert(0, str(ROOT))
    import numpy as np, torch
    from stable_baselines3 import PPO
    from embodied_env import EmbodiedNavEnv
    torch.set_num_threads(1)
    env = EmbodiedNavEnv(slip=EmbodiedNavEnv.SLIP_FACTOR)
    model = PPO("MlpPolicy", env, policy_kwargs=dict(net_arch=dict(pi=[64, 64], vf=[64, 64])), device="cpu")
    model.policy.load_state_dict(torch.load(ROOT / "ppo_embodied_agent.pth", map_location="cpu"))
    model.policy.eval()
    obs, _ = env.reset(seed=0)
    for _ in range(200):  # 预热
        a, _ = model.predict(obs, deterministic=True); obs, *_r = env.step(a)
        if _r[1] or _r[2]: obs, _ = env.reset()
    c0, w0 = time.process_time(), time.perf_counter()
    for _ in range(steps):
        a, _ = model.predict(obs, deterministic=True)
        obs, reward, term, trunc, info = env.step(a)
        if term or trunc:
            obs, _ = env.reset()
    c1, w1 = time.process_time(), time.perf_counter()
    cpu_ms = (c1 - c0) * 1000 / steps
    return {"steps": steps, "cpu_ms_per_step": round(cpu_ms, 4), "wall_ms_per_step": round((w1 - w0) * 1000 / steps, 4),
            "steps_per_sec_headless": round(steps / (w1 - w0), 1),
            "equiv_pct_one_core_at_10hz": round(cpu_ms * 10 / 10, 3),   # 10 步/s × cpu_ms/1000 s × 100%
            "equiv_pct_one_core_at_60hz": round(cpu_ms * 60 / 10, 3)}


def _ws_client(url, stop, counter):
    try:
        from websockets.sync.client import connect
        with connect(url, max_size=None) as ws:
            while not stop.is_set():
                ws.recv(timeout=2); counter[0] += 1
    except Exception:
        pass


def bench_gateway(server, port, duration, clients):
    proc = subprocess.Popen([sys.executable, server, *(["--port", str(port)] if server != "inference_server.py" else [])],
                            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        health = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    health = json.loads(r.read()); break
            except Exception:
                time.sleep(0.5)
        if health is None:
            raise RuntimeError(f"{server} 未在 30s 内就绪（端口 {port} 被占？）")
        stop, counter, threads = threading.Event(), [0], []
        for _ in range(clients):
            t = threading.Thread(target=_ws_client, args=(f"ws://127.0.0.1:{port}/ws", stop, counter), daemon=True); t.start(); threads.append(t)
        time.sleep(3)  # 稳态
        samples = []
        for _ in range(duration):
            out = subprocess.run(["ps", "-o", "%cpu=", "-p", str(proc.pid)], capture_output=True, text=True).stdout.strip()
            if out:
                samples.append(float(out))
            time.sleep(1)
        stop.set()
        frames = counter[0]
        s = sorted(samples)
        p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))] if s else None
        ncpu = os.cpu_count() or 1
        return {"server": server, "clients": clients, "duration_s": duration, "n_samples": len(samples),
                "health": health, "frames_received_total": frames,
                "pct_one_core": {"mean": round(statistics.fmean(samples), 2), "median": round(statistics.median(samples), 2),
                                 "p95": p95, "max": max(samples)} if samples else None,
                "pct_of_machine_mean": round(statistics.fmean(samples) / ncpu, 3) if samples else None,
                "basis": "ps %cpu：单核=100%；pct_of_machine = 均值/逻辑核数"}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["kernel", "gateway", "both"], default="both")
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--clients", type=int, default=1)
    ap.add_argument("--server", default="inference_server.py")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--out")
    a = ap.parse_args()
    res = {"recorded": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True).stdout.strip(),
           "machine": machine_info()}
    if a.mode in ("kernel", "both"):
        res["kernel"] = bench_kernel(a.steps)
        k = res["kernel"]
        print(f"[kernel] {k['cpu_ms_per_step']} ms CPU/步 ｜ 折算 10Hz 实时 ≈ {k['equiv_pct_one_core_at_10hz']}% 单核 ｜ 60Hz 心跳 ≈ {k['equiv_pct_one_core_at_60hz']}% 单核 ｜ 无头吞吐 {k['steps_per_sec_headless']} 步/s")
    if a.mode in ("gateway", "both"):
        res["gateway"] = bench_gateway(a.server, a.port, a.duration, a.clients)
        g = res["gateway"]
        print(f"[gateway] {a.server} clients={a.clients} {a.duration}s：%cpu 单核口径 均值 {g['pct_one_core']['mean']} / 中位 {g['pct_one_core']['median']} / P95 {g['pct_one_core']['p95']} / 最大 {g['pct_one_core']['max']} ｜ 整机占比 {g['pct_of_machine_mean']}% ｜ 收帧 {g['frames_received_total']}")
    m = res["machine"]
    print(f"[machine] {m['hw_model'] or m['machine']} ｜ {m['cpu_brand']} ｜ {m['ncpu']} 核 ｜ {m['mem_gb']} GB ｜ {m['system']} {m['release']} ｜ py {m['python']} torch {m['torch']} numpy {m['numpy']}")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[out] {a.out}")


if __name__ == "__main__":
    main()
