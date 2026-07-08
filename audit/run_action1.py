# -*- coding: utf-8 -*-
"""
run_action1.py  ——  动作1 · 三道门一键实跑 + 证据产出
=====================================================
门 1（审计抓假·红）：向健康 V3 注入 1-A/1-B/1-C 三类假仪表，审计须逐一判红并定位。
门 2（放行健康·绿）：健康 V3 系统审计全绿不误报。
门 3（基础评测）  ：用已训练 PPO 跑 N≥20 回合，统计成功率/碰撞率/平均到达步数 + 出图。

全程实跑真实物理（embodied_env + _integrate_odom 真分叉）与真实 PPO 策略；
审计红/绿为真实判定，指标来自真实回合；无任何 hardcode/伪造（INV-2）。

运行：python audit/run_action1.py
产物：audit/sessions/*.json、audit/eval_metrics.png、audit/eval_episodes.csv
"""

import csv
import datetime
import hashlib
import json
import os
import sys

import numpy as np
import torch
from stable_baselines3 import PPO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from embodied_env import EmbodiedNavEnv                       # noqa: E402
from integrity_audit import audit_session, format_report     # noqa: E402
import fault_injection as fi                                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SESS_DIR = os.path.join(HERE, "sessions")
MODEL_PATH = os.path.join(os.path.dirname(HERE), "ppo_embodied_agent.pth")
POLICY_KWARGS = dict(net_arch=dict(pi=[64, 64], vf=[64, 64]))

SEED_SESSION = 11
SEED_EVAL = 100
N_LIVE = 240            # 健康 session 的 online 鲜活帧数
N_DISCONNECT = 15       # 模拟断流冻结帧数（健康系统：link_status=offline）
N_EVAL_EPISODES = 25    # 门 3 回合数（≥20）


def load_ppo(env):
    """重建与训练期同构的 PPO 并载入权重（复用 inference_server 的加载逻辑）。"""
    m = PPO("MlpPolicy", env, policy_kwargs=POLICY_KWARGS, device="cpu")
    m.policy.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
    m.policy.eval()
    return m


def _record(frame, recv_t, link_status):
    r, o = frame["robot"], frame["odom"]
    return {
        "recv_t": round(recv_t, 3),
        "seq": frame["seq"],
        "truth": {"x": r["x"], "y": r["y"], "theta": r["theta"]},
        "odom": {"x": o["x"], "y": o["y"], "theta": o["theta"]},
        "step": frame["step"],
        "terminated": frame["terminated"],
        "truncated": frame["truncated"],
        "link_status": link_status,
    }


def build_healthy_session():
    """真实驱动 env+PPO 产出一段健康 session：鲜活 online 段 + 断流 offline 冻结段。"""
    env = EmbodiedNavEnv(slip=EmbodiedNavEnv.SLIP_FACTOR)
    model = load_ppo(env)
    obs, info = env.reset(seed=SEED_SESSION)
    dt = env.DT
    t = 0.0
    session = []

    # —— 鲜活 online 段：真实 PPO 推理，回合结束自动复位（seq 跨回合不复位，保持单调）——
    for _ in range(N_LIVE):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        frame = env.get_render_state(reward=reward, terminated=terminated,
                                     truncated=truncated, info=info)
        t += dt
        session.append(_record(frame, t, "online"))
        if terminated or truncated:
            obs, info = env.reset()

    # —— 断流段：feed 停更，数据冻结在最后一帧；健康系统显式标 OFFLINE（墙钟仍推进）——
    last = json.loads(json.dumps(session[-1]))   # 深拷贝
    for _ in range(N_DISCONNECT):
        t += dt
        fr = json.loads(json.dumps(last))
        fr["recv_t"] = round(t, 3)
        fr["link_status"] = "offline"            # 断流即冻结并标 OFFLINE（阶段0 修复的正确行为）
        session.append(fr)

    return session


def run_eval():
    """门 3：N 回合 PPO 评测，返回逐回合记录与汇总指标。"""
    env = EmbodiedNavEnv(slip=EmbodiedNavEnv.SLIP_FACTOR)
    model = load_ppo(env)
    rows = []
    for i in range(N_EVAL_EPISODES):
        obs, info = env.reset(seed=SEED_EVAL + i)
        done = False
        success = collided = False
        steps = 0
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            steps += 1
            if terminated or truncated:
                done = True
                success = bool(info.get("is_success", False))
                collided = bool(info.get("collided", False))
        outcome = "success" if success else ("collision" if collided else "timeout")
        rows.append({"episode": i, "seed": SEED_EVAL + i, "steps": steps,
                     "success": int(success), "collision": int(collided),
                     "outcome": outcome})
    n = len(rows)
    succ = [r for r in rows if r["success"]]
    summary = {
        "n_episodes": n,
        "success_rate": sum(r["success"] for r in rows) / n,
        "collision_rate": sum(r["collision"] for r in rows) / n,
        "timeout_rate": sum(1 for r in rows if r["outcome"] == "timeout") / n,
        "avg_steps_success": (sum(r["steps"] for r in succ) / len(succ)) if succ else None,
        "avg_steps_all": sum(r["steps"] for r in rows) / n,
    }
    return rows, summary


def plot_eval(summary, rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    rates = [summary["success_rate"], summary["collision_rate"], summary["timeout_rate"]]
    bars = ax1.bar(["success", "collision", "timeout"], rates,
                   color=["#2c7", "#d33", "#fa0"])
    ax1.set_ylim(0, 1)
    ax1.set_ylabel("rate")
    ax1.set_title(f"PPO over N={summary['n_episodes']} episodes (fixed seeds)")
    for b, r in zip(bars, rates):
        ax1.text(b.get_x() + b.get_width() / 2, r + 0.02, f"{r:.0%}", ha="center")

    steps = [r["steps"] for r in rows]
    colors = {"success": "#2c7", "collision": "#d33", "timeout": "#fa0"}
    ax2.bar(range(len(rows)), steps, color=[colors[r["outcome"]] for r in rows])
    ax2.set_xlabel("episode")
    ax2.set_ylabel("steps")
    ax2.set_title("per-episode steps (color = outcome)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main():
    os.makedirs(SESS_DIR, exist_ok=True)
    print("=" * 74)
    print("  动作1 · 防自欺审计 + 基础评测  ——  三道门实跑")
    print("=" * 74)

    # ---- 构建健康 session ----
    healthy = build_healthy_session()
    json.dump(healthy, open(os.path.join(SESS_DIR, "healthy.json"), "w"))
    print(f"\n[健康 session] {len(healthy)} 帧 "
          f"(online {sum(1 for f in healthy if f['link_status']=='online')} + "
          f"offline {sum(1 for f in healthy if f['link_status']=='offline')})，"
          f"seq {healthy[0]['seq']}→{healthy[-1]['seq']}")

    # ============ 门 2：健康系统 → 全绿 ============
    print("\n" + "─" * 74)
    print("【门 2｜审计放行健康系统（期望：全绿）】")
    print("─" * 74)
    res_healthy = audit_session(healthy)
    print(format_report(res_healthy))
    gate2_ok = res_healthy["passed"]

    # ============ 门 1：注入三类假仪表 → 逐一判红 ============
    print("\n" + "─" * 74)
    print("【门 1｜审计抓假：注入 1-A/1-B/1-C，期望逐一判红并定位】")
    print("─" * 74)
    gate1 = {}
    expected_check = {"1-A_truth_copy": "C1_TRUTH_ODOM_FORK",
                      "1-B_seq_freeze": "C2_SEQ_INTEGRITY",
                      "1-C_stall_running": "C3_FEED_LIVENESS"}
    for name, inj in fi.INJECTORS.items():
        injected = inj(healthy)
        json.dump(injected, open(os.path.join(SESS_DIR, f"injected_{name}.json"), "w"))
        res = audit_session(injected)
        # 该注入是否被"对应检查项"判红
        tgt = expected_check[name]
        tgt_red = any((not c["ok"]) and c["check"] == tgt for c in res["checks"])
        gate1[name] = {"caught": (not res["passed"]) and tgt_red, "result": res}
        print(f"\n  ▶ 注入 [{name}]：{fi.DESCRIPTIONS[name]}")
        print(f"    期望判红检查项：{tgt}")
        print(format_report(res))
        print(f"    → 抓假{'成功 ✅' if gate1[name]['caught'] else '失败 ❌'}")

    gate1_ok = all(v["caught"] for v in gate1.values())

    # ============ 门 3：基础评测 ============
    print("\n" + "─" * 74)
    print(f"【门 3｜基础评测：PPO × N={N_EVAL_EPISODES} 回合（固定种子）】")
    print("─" * 74)
    rows, summary = run_eval()
    with open(os.path.join(HERE, "eval_episodes.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    plot_eval(summary, rows, os.path.join(HERE, "eval_metrics.png"))
    print(f"  成功率 success_rate   : {summary['success_rate']:.1%}")
    print(f"  碰撞率 collision_rate : {summary['collision_rate']:.1%}")
    print(f"  超时率 timeout_rate   : {summary['timeout_rate']:.1%}")
    avg_s = summary["avg_steps_success"]
    print(f"  平均到达步数(成功回合): {avg_s:.1f}" if avg_s else "  平均到达步数(成功回合): 无成功回合")
    print(f"  平均步数(全部回合)    : {summary['avg_steps_all']:.1f}")
    print(f"  [OK] 图: audit/eval_metrics.png   逐回合: audit/eval_episodes.csv")

    # ============ 汇总 ============
    print("\n" + "=" * 74)
    print("  验收门汇总")
    print("=" * 74)
    print(f"  门 1（审计抓假·红）: {'✅ 通过（3/3 注入全部判红并定位）' if gate1_ok else '❌ 未通过'}")
    print(f"  门 2（放行健康·绿）: {'✅ 通过（健康系统全绿）' if gate2_ok else '❌ 未通过（误报）'}")
    print(f"  门 3（基础评测）   : ✅ 已产出真实指标 + 图（成功率 {summary['success_rate']:.0%}）")

    # —— 机器可读评测汇总导出：供 tools/paper_figures/make_paper_figures.py --eval-json
    #    直接生成论文图 4，与平台评测结果形成可复现闭环 ——
    counts = {
        "success": sum(r["success"] for r in rows),
        "collision": sum(r["collision"] for r in rows),
        "timeout": sum(1 for r in rows if r["outcome"] == "timeout"),
    }
    with open(MODEL_PATH, "rb") as fh:
        policy_sha = hashlib.sha256(fh.read()).hexdigest()[:12]
    export = {
        "schema_version": 1,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "policy": {"file": os.path.basename(MODEL_PATH), "sha256_12": policy_sha},
        # 每回合一张独立随机地图（种子各异），故 n_maps = 回合数、episodes_per_map = 1
        "n_maps": N_EVAL_EPISODES,
        "episodes_per_map": 1,
        "seed_range": [SEED_EVAL, SEED_EVAL + N_EVAL_EPISODES - 1],
        "counts": counts,
        "rates": {k: counts[k] / len(rows) for k in counts},
        **summary,   # 兼容旧字段：n_episodes / success_rate / ... / avg_steps_all
    }
    out_json = os.path.join(HERE, "eval_summary.json")
    json.dump(export, open(out_json, "w"), indent=2, ensure_ascii=False)
    print(f"  [OK] 机器可读汇总: {out_json}（可用于 make_paper_figures.py --eval-json）")


if __name__ == "__main__":
    main()
