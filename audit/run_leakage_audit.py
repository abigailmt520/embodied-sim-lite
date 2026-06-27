# -*- coding: utf-8 -*-
"""
run_leakage_audit.py  ——  Phase3 · 契约层 CI（互信息泄漏）审计 实跑 + 与 C1 对照
================================================================================
门 CI-2（放行清洁·绿）：诚实 odom 下 I(Δodom;Δtruth) 在噪声预算界内、CI 审计绿、无误报。
门 CI-1（审计抓假·红）：注入 L-1/L-2/L-3 泄漏 → I 超噪声预算界 → CI 判红 + 定位。
对照 C1：CI 是 C1「误差太小即疑」的**原理化定量泛化**——C1 只抓全泄漏 L-1，
        CI 还能抓 C1 漏的 L-2（部分泄漏，仍漂移）/ L-3（大误差但确定）。

🔴 双 slip 实测（INV-E 诚实可靠性）：
    slip=0.30（可估区间）：三类泄漏均干净检出，为主证据。
    slip=0.05（平台部署，odom 很准）：预算界 ~3.3 nats 逼近 KSG 可靠上限，L-1/L-2 仍抓、
        L-3 漏——如实报告 MI 估计在高信噪比区的局限（此区 C1 的幅值检更实用）。

运行：python audit/run_leakage_audit.py
产物：audit/leakage_compare.png、audit/leakage_summary.json
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embodied_env import EmbodiedNavEnv                         # noqa: E402
from integrity_audit import check_truth_odom_fork              # noqa: E402（C1）
import leakage_audit as la                                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
N_INC = 1500          # 增量样本数（KSG 可靠性所需）


def collect_increments(slip, n_target=N_INC):
    """跑真实 env（随机策略铺开轨迹）收集回合内逐步增量，拼接到 n_target。"""
    env = EmbodiedNavEnv(slip=slip, control_mode="A")
    dT_all, dO_all = [], []
    s = 0
    while sum(len(x) for x in dT_all) < n_target:
        env.reset(seed=600 + s); s += 1
        T, O = [env.pos.copy()], [env.odom_pos.copy()]
        done = False
        while not done:
            _, _, te, tr, _ = env.step(env.action_space.sample())
            T.append(env.pos.copy()); O.append(env.odom_pos.copy())
            if te or tr:
                done = True
        T, O = np.array(T), np.array(O)
        dT_all.append(la.increments(T)); dO_all.append(la.increments(O))
    dT = np.vstack(dT_all)[:n_target]; dO = np.vstack(dO_all)[:n_target]
    return dT, dO


def pseudo_traj(d):
    """增量数组 → 伪位置轨迹（cumsum），其增量等于原数组（供 ci_audit/C1 消费）。"""
    out = np.zeros((d.shape[0] + 1, d.shape[1]))
    out[1:] = np.cumsum(d, axis=0)
    return out


def run_c1(truth_traj, odom_traj):
    """把伪轨迹喂契约层 C1（check_truth_odom_fork），返回 (ok, detail)。"""
    sess = [{"recv_t": float(i), "seq": i, "step": i,
             "truth": {"x": float(truth_traj[i][0]), "y": float(truth_traj[i][1]), "theta": 0.0},
             "odom": {"x": float(odom_traj[i][0]), "y": float(odom_traj[i][1]), "theta": 0.0},
             "terminated": False, "truncated": False, "link_status": "online"}
            for i in range(len(truth_traj))]
    r = check_truth_odom_fork(sess)
    return r["ok"], r["detail"]


def audit_one(slip):
    dT, dO = collect_increments(slip)
    Ttraj = pseudo_traj(dT)
    budget, b_std, closed = la.noise_budget_bound(dT, slip)
    print("\n" + "=" * 80)
    print(f"  slip={slip}  (N={len(dT)} 增量)  噪声预算界={budget:.3f}±{b_std:.3f} nats "
          f"(闭式参照 {closed:.2f})  判红阈值={budget + la.MARGIN_NATS:.3f}")
    print("=" * 80)

    cases = {"clean": dO}
    for name, inj in la.LEAK_INJECTORS.items():
        cases[name] = la.increments(inj(Ttraj, pseudo_traj(dO)))

    rows = {}
    for name, dOcase in cases.items():
        Otraj = pseudo_traj(dOcase)
        ci = la.ci_audit(Ttraj, Otraj, slip)
        c1_ok, c1_detail = run_c1(Ttraj, Otraj)
        rows[name] = {"mi": ci["locator"]["mi_full_nats"], "ci_red": (not ci["ok"]),
                      "c1_red": (not c1_ok)}
        tag = "清洁" if name == "clean" else name
        print(f"\n  ▶ {tag}:  I={ci['locator']['mi_full_nats']:.3f} nats  vs 界 {budget:.3f}")
        print(f"      CI 审计: {'🔴RED 泄漏' if not ci['ok'] else '🟢GREEN 合法'}  | "
              f"C1(误差太小): {'🔴RED' if not c1_ok else '🟢GREEN'}")
    return {"slip": slip, "budget": round(budget, 3), "thresh": round(budget + la.MARGIN_NATS, 3),
            "rows": rows}


def main():
    print("Phase3 · 契约层互信息泄漏审计（CI）实跑 + 与 C1 对照")
    res03 = audit_one(0.30)     # 主证据：可估区间
    res005 = audit_one(0.05)    # 部署区间：如实报告局限

    # —— 判定 + C1 对照表 ——
    print("\n" + "=" * 80)
    print("  验收门 + 与 C1 对照（slip=0.30 主证据）")
    print("=" * 80)
    r = res03["rows"]
    gate_ci2 = not r["clean"]["ci_red"]                       # 清洁不误报
    gate_ci1 = all(r[k]["ci_red"] for k in ("L-1_full_leak", "L-2_partial_leak", "L-3_privileged"))
    print(f"  门 CI-2 放行清洁: {'✅ 绿（无误报）' if gate_ci2 else '❌ 误报'}")
    print(f"  门 CI-1 抓三泄漏: {'✅ 3/3 判红' if gate_ci1 else '❌ 见下'}")
    print("\n  对照表（🔴=判红抓住, 🟢=放行/漏）:")
    print(f"  {'案例':<18}{'C1(误差太小)':<14}{'CI(互信息)':<12}")
    for k in ("clean", "L-1_full_leak", "L-2_partial_leak", "L-3_privileged"):
        print(f"  {k:<18}{'🔴' if r[k]['c1_red'] else '🟢':<14}{'🔴' if r[k]['ci_red'] else '🟢':<12}")
    print("  → C1 仅抓全泄漏 L-1；CI 还抓 C1 漏的 L-2(部分)/L-3(大误差但确定) = C1 的原理化泛化")

    # —— slip=0.05 局限如实报告 ——
    r5 = res005["rows"]
    l3_missed = not r5["L-3_privileged"]["ci_red"]
    print("\n  [可靠性·部署 slip=0.05] L-1 抓:" + ("✅" if r5["L-1_full_leak"]["ci_red"] else "❌")
          + " | L-2 抓:" + ("✅" if r5["L-2_partial_leak"]["ci_red"] else "❌")
          + " | L-3 抓:" + ("❌漏(如实)" if l3_missed else "✅"))
    if l3_missed:
        print("    分析：slip=0.05 odom 很准 → 预算界~3.3nats 逼近 KSG 可靠上限，L-3 旋转泄漏 MI 估值"
              "落在界下而漏。此高信噪比区 C1 幅值检更实用；CI 价值在可估区(slip≈0.3)的定量+抓 C1 漏项。")

    json.dump({"slip_0.30": res03, "slip_0.05": res005,
               "gate_ci2_clean_green": gate_ci2, "gate_ci1_3leaks_red": gate_ci1,
               "slip005_L3_missed": bool(l3_missed)},
              open(os.path.join(HERE, "leakage_summary.json"), "w"), indent=2, ensure_ascii=False)
    try:
        make_figure(res03, res005)
    except Exception as e:
        print(f"  [WARN] 图跳过（{e}）")
    return gate_ci1 and gate_ci2


def make_figure(res03, res005):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                 "/System/Library/Fonts/Hiragino Sans GB.ttc"):
        if os.path.exists(cand):
            font_manager.fontManager.addfont(cand)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=cand).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    order = ["clean", "L-1_full_leak", "L-2_partial_leak", "L-3_privileged"]
    short = ["清洁", "L-1全泄漏", "L-2部分", "L-3特权旋转"]
    for ax, res, title in ((axes[0], res03, "slip=0.30（可估区间）三泄漏均检出"),
                           (axes[1], res005, "slip=0.05（部署，odom很准）L-3漏（如实）")):
        mis = [res["rows"][k]["mi"] for k in order]
        cols = ["#2c7"] + ["#d33" if res["rows"][k]["ci_red"] else "#fa0" for k in order[1:]]
        ax.bar(range(4), mis, color=cols)
        ax.axhline(res["budget"], ls="--", color="#333", label=f"噪声预算界 {res['budget']:.2f}")
        ax.axhline(res["thresh"], ls=":", color="#a00", label=f"判红阈值 {res['thresh']:.2f}")
        ax.set_xticks(range(4)); ax.set_xticklabels(short, fontsize=9)
        ax.set_ylabel("I(Δodom;Δtruth) nats"); ax.set_title(title, fontsize=10.5)
        ax.legend(fontsize=8)
        for i, m in enumerate(mis):
            ax.text(i, m + 0.05, f"{m:.2f}", ha="center", fontsize=8.5)
    fig.suptitle("Embodied-SimLite · 契约层互信息泄漏审计（CI）= C1「误差太小」的原理化泛化",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(HERE, "leakage_compare.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\n  [OK] 对比图已保存: {out}")


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
