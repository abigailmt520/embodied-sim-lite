# -*- coding: utf-8 -*-
"""
run_physics_audit.py  ——  Phase1a · 物理层能量审计「红绿对照」一键实跑 + 证据产出
====================================================================================
门 P2（放行清洁·绿）：清洁动力学下能量审计 EC1/EC2/EC3 全绿、零误报（残差在数值下限内）。
门 P1（审计抓假·红）：向动力学积分核注入 P-1..P-5 五类物理自欺，能量审计须逐一判红并定位。

全程实跑真实 embodied_env 动力学核（_integrate_dynamics 真积分 + 真能量账本）；
注入器藏积分器内部（真破坏轨迹），审计红/绿为真实判定，残差为真实数字（无 hardcode）。

驱动方式（开环「正弦变命令」法，可复现、与策略无关）：
    命令随步数正弦变化（v_tgt∈[0.15,0.95]、w_tgt∈[-0.9,0.9]），贯穿 STEPS 步不复位。
    为何变命令而非定命令：质量只在「加速」时可观测（稳态 F=c·v 与质量无关）——
    定命令下系统很快进入稳态、P-5 谎报质量在稳态零残差而逃逸（实测教训）。持续变命令
    使系统恒处暂态 → 加速度持续 → 质量/力类故障每步显形，同时正弦峰值令 v_act 持续越上限（P-4）。

运行：python audit/run_physics_audit.py
产物：audit/physics_sessions/*.json、audit/energy_redgreen_matrix.png
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embodied_env import EmbodiedNavEnv                         # noqa: E402
from energy_audit import audit_session, format_report          # noqa: E402
import physics_injection as pi                                 # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SESS_DIR = os.path.join(HERE, "physics_sessions")
SEED = 7
STEPS = 200


def command(t):
    """开环正弦变命令（目标速度域 [v∈[0,1], w∈[-1,1]]）：持续暂态以暴露质量/力类故障。"""
    v = 0.55 + 0.40 * np.sin(2 * np.pi * t / 24.0)   # ∈[0.15,0.95]，峰值持续越上限供 P-4
    w = 0.90 * np.sin(2 * np.pi * t / 17.0)          # ∈[-0.9,0.9]
    return np.array([v, w], dtype=np.float32)


def record_session(configure_fault):
    """跑 STEPS 步固定命令，逐帧记录能量账本（取自 get_render_state 契约的 energy 字段）。

    configure_fault(env): 在 reset 后配置 env.physics_fault（清洁档为 no-op）。
    贯穿不复位：复位会清零能量账本，无法呈现连续残差累积。
    """
    env = EmbodiedNavEnv(slip=0.0)        # 关打滑：能量审计只看动力学，排除 odom 噪声干扰
    env.reset(seed=SEED)
    configure_fault(env)
    rows = []
    for t in range(STEPS):
        env.step(command(t))
        st = env.get_render_state()       # 经契约取能量账本（与平台真理源同源）
        e = st["energy"]
        rows.append({
            "step": st["step"], "seq": st["seq"],
            "E_kin": e["E_kin"], "dE": e["dE"],
            "W_act": e["W_act"], "D_damp": e["D_damp"],
            "v_act": st["v_act"], "w_act": st["w_act"],
        })
    return rows


def main():
    os.makedirs(SESS_DIR, exist_ok=True)
    print("=" * 76)
    print("  Phase1a · 物理层能量审计  ——  红绿对照实跑（清洁绿 + 五注入红）")
    print("=" * 76)

    # ---- 门 P2：清洁基线 → 期望全绿 ----
    clean = record_session(pi.clean)
    json.dump(clean, open(os.path.join(SESS_DIR, "clean.json"), "w"))
    print("\n" + "─" * 76)
    print("【门 P2｜审计放行清洁动力学（期望：全绿、零误报）】")
    print("─" * 76)
    res_clean = audit_session(clean)
    print(format_report(res_clean))
    # 报告清洁残差量级（应 ~机器精度）
    max_r = max(abs(f["dE"] - (f["W_act"] - f["D_damp"])) for f in clean)
    print(f"    清洁残差 max|ΔE−(W_act−D_damp)| = {max_r:.3e} J")
    gate_p2 = res_clean["passed"]

    # ---- 门 P1：注入 P-1..P-5 → 期望逐一判红并定位 ----
    print("\n" + "─" * 76)
    print("【门 P1｜审计抓假：注入 P-1..P-5，期望逐一判红并定位】")
    print("─" * 76)
    gate1 = {}
    matrix = {"clean": res_clean}
    for name, inj in pi.INJECTORS.items():
        sess = record_session(inj)
        json.dump(sess, open(os.path.join(SESS_DIR, f"injected_{name}.json"), "w"))
        res = audit_session(sess)
        matrix[name] = res
        tgt = pi.EXPECTED_CHECK[name]
        tgt_red = any((not c["ok"]) and c["check"] == tgt for c in res["checks"])
        caught = (not res["passed"]) and tgt_red
        gate1[name] = caught
        print(f"\n  ▶ 注入 [{name}]：{pi.DESCRIPTIONS[name]}")
        print(f"    期望判红检查项：{tgt}")
        print(format_report(res))
        print(f"    → 抓假{'成功 ✅' if caught else '失败 ❌（需分析，禁掩盖 INV-D）'}")
    gate1_ok = all(gate1.values())

    # ---- 汇总 ----
    print("\n" + "=" * 76)
    print("  验收门汇总")
    print("=" * 76)
    print(f"  门 P1（审计抓假·红）: {'✅ 通过（5/5 注入各判红并定位）' if gate1_ok else '❌ 未通过（见上）'}")
    print(f"  门 P2（放行清洁·绿）: {'✅ 通过（清洁全绿、零误报）' if gate_p2 else '❌ 未通过（误报）'}")

    # ---- 红绿矩阵图 ----
    try:
        make_matrix_figure(matrix)
    except Exception as e:
        print(f"  [WARN] 矩阵图跳过（{e}）")

    return gate1_ok and gate_p2


def make_matrix_figure(matrix):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import FancyBboxPatch

    for cand in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                 "/System/Library/Fonts/Hiragino Sans GB.ttc"):
        if os.path.exists(cand):
            font_manager.fontManager.addfont(cand)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=cand).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False

    GF, GE, GT = "#d7f3e3", "#2faa6a", "#11623b"
    RF, RE, RT = "#fbd9d9", "#d84141", "#8a1c1c"
    HF, HT = "#2b2f3a", "#ffffff"

    rows = [("EC1_ENERGY_BUDGET", "EC1 · 能量预算\nΔE=W−D 自洽"),
            ("EC2_NO_FREE_ENERGY", "EC2 · 无凭空能量\nΔE≤W_act"),
            ("EC3_ACTUATOR_BOUND", "EC3 · 执行器上限\n|v|≤v_max")]
    cols = [("clean", "清洁动力学\n(门P2)"),
            ("P-1_neg_damp", "P-1\n负阻尼"),
            ("P-2_force_double", "P-2\n力双计"),
            ("P-3_drop_dissipation", "P-3\n丢耗散"),
            ("P-4_skip_lag", "P-4\n越上限"),
            ("P-5_mass_misreport", "P-5\n谎报质量")]

    by = {}
    for ck in matrix:
        by[ck] = {c["check"]: c for c in matrix[ck]["checks"]}

    nrow, ncol = len(rows), len(cols)
    fig, ax = plt.subplots(figsize=(15.5, 6.4))
    ax.set_xlim(0, ncol + 1.3); ax.set_ylim(0, nrow + 1.4); ax.axis("off")
    cw, rh = 1.0, 0.95
    x0, y0 = 1.3, 0.25

    def box(x, y, w, h, fc, ec):
        ax.add_patch(FancyBboxPatch((x + 0.04, y + 0.04), w - 0.08, h - 0.08,
                     boxstyle="round,pad=0.0,rounding_size=0.06", fc=fc, ec=ec, lw=1.6))

    for j, (_, label) in enumerate(cols):
        x = x0 + j * cw
        box(x, y0 + nrow * rh, cw, rh * 0.95, HF, HF)
        ax.text(x + cw / 2, y0 + nrow * rh + rh * 0.46, label, ha="center", va="center",
                color=HT, fontsize=10.5, fontweight="bold")
    for i, (_, label) in enumerate(rows):
        y = y0 + (nrow - 1 - i) * rh
        box(0.08, y, 1.2, rh, HF, HF)
        ax.text(0.08 + 1.2 / 2, y + rh / 2, label, ha="center", va="center",
                color=HT, fontsize=10, fontweight="bold")

    for i, (rk, _) in enumerate(rows):
        y = y0 + (nrow - 1 - i) * rh
        for j, (ck, _) in enumerate(cols):
            x = x0 + j * cw
            chk = by[ck][rk]
            if chk["ok"]:
                box(x, y, cw, rh, GF, GE)
                ax.text(x + cw / 2, y + rh * 0.62, "✓ PASS", ha="center", va="center",
                        color=GT, fontsize=12, fontweight="bold")
            else:
                box(x, y, cw, rh, RF, RE)
                loc = chk.get("locator") or {}
                val = (loc.get("max_residual_J") or loc.get("max_excess_J")
                       or loc.get("max_overshoot") or "")
                ax.text(x + cw / 2, y + rh * 0.66, "✗ FAIL", ha="center", va="center",
                        color=RT, fontsize=12, fontweight="bold")
                ax.text(x + cw / 2, y + rh * 0.30, f"@step{loc.get('first_step','?')}\n{val}",
                        ha="center", va="center", color=RT, fontsize=7.6)

    fig.suptitle("Embodied-SimLite · 物理层能量审计 红/绿对照 (Energy Audit RED/GREEN)",
                 fontsize=14.5, fontweight="bold", y=0.99)
    ax.text((ncol + 1.3) / 2, 0.03,
            "门P2：清洁动力学三项全绿、零误报（残差≈机器精度）  |  "
            "门P1：P-1..P-5 五类物理自欺各被能量审计判红并定位——物理审计自身已被证明「能抓假」",
            ha="center", va="center", fontsize=9, color="#333")
    out = os.path.join(HERE, "energy_redgreen_matrix.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\n  [OK] 红绿矩阵图已保存: {out}")


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 2)
