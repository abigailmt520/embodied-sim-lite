# -*- coding: utf-8 -*-
"""
energy_audit.py  ——  Phase1a · 物理层能量审计（动力学保真度自欺检测）
=====================================================================
契约层 integrity_audit.py（C1/C2/C3）的**物理层**对应物。输入一段逐帧能量账本流，
输出 EC1/EC2/EC3 三项检查的 红/绿 + 定位。审计自身先被证明「能抓假」（见 run_physics_audit.py）。

可审守恒量 = 机械能 E = ½m·v² + ½I·w²。动作空间 A 下系统非孤立（执行器注入 + 阻尼耗散），
故审「能量预算自洽」而非绝对守恒：
        每步应有  ΔE ≈ W_act − D_damp   （W_act=执行器净做功, D_damp=阻尼耗散）

三项检查（逐帧账本契约，list[dict]）：
    EC1 ENERGY_BUDGET   —— 预算残差 r=ΔE−(W_act−D_damp) 必须在数值下限内。抓一切破坏能量账本自洽者。
    EC2 NO_FREE_ENERGY  —— 动能增量不得超过执行器做功（ΔE≤W_act，阻尼只会耗能）。抓「能量凭空创生」。
    EC3 ACTUATOR_BOUND  —— 实际速度不得越执行器物理上限。抓「速度越界 / 动能跃变」。

账本帧记录契约：
    {"step","seq","E_kin","dE","W_act","D_damp","v_act","w_act"}

判据（保守 + 持续门控，镜像契约层 C1 行程门控 / C3 STALE_TOL 抗抖）：
    残差/越能必须 **连续 ≥ K_PERSIST 步** 超下限才判红，避免单步数值瞬态误报。
纯 stdlib，无 env/torch 依赖；可独立对任意账本 session（含离线 json）运行。
"""

# ---- 数值下限（清洁残差到机器精度 ~1e-16；故障残差 ~1e-2..1e-1，分离极宽）----
EPS_ABS = 1e-6        # 绝对能量下限 (J)
EPS_REL = 1e-3        # 相对下限：floor = EPS_REL·(|W_act|+|D_damp|+|ΔE|) + EPS_ABS
K_PERSIST = 3         # 连续超限帧数阈值（抗单步瞬态；仿 C3 STALE_TOL）

# 执行器物理速度上限（与 embodied_env.V_PHYS_MAX / W_PHYS_MAX 对齐；可在 audit_session 覆盖）
V_PHYS_MAX = 1.25     # = MAX_LIN_VEL * 1.25
W_PHYS_MAX = 1.875    # = MAX_ANG_VEL * 1.25


def _floor(f):
    return EPS_REL * (abs(f["W_act"]) + abs(f["D_damp"]) + abs(f["dE"])) + EPS_ABS


def _result(name, desc, ok, detail, locator=None):
    return {"check": name, "desc": desc, "status": "GREEN" if ok else "RED",
            "ok": bool(ok), "detail": detail, "locator": locator}


# ====================================================================
# EC1 · 能量预算残差（抓一切破坏 ΔE=W_act−D_damp 自洽者）
# ====================================================================
def check_energy_budget(session):
    run = 0
    run_start = None
    worst = 0.0
    for i, f in enumerate(session):
        r = f["dE"] - (f["W_act"] - f["D_damp"])
        if abs(r) > _floor(f):
            if run == 0:
                run_start = i
            run += 1
            if abs(r) > abs(worst):
                worst = r
            if run >= K_PERSIST:
                return _result(
                    "EC1_ENERGY_BUDGET", "能量预算 ΔE=W_act−D_damp 是否自洽", False,
                    f"预算残差连续 {run} 帧超下限（自 step={session[run_start]['step']} 起）；"
                    f"最大残差 r={worst:.3e} J（清洁应 ~1e-16）",
                    locator={"first_step": session[run_start]["step"],
                             "first_seq": session[run_start]["seq"],
                             "max_residual_J": round(worst, 6),
                             "floor_J": round(_floor(session[run_start]), 9)})
        else:
            run = 0
    return _result("EC1_ENERGY_BUDGET", "能量预算 ΔE=W_act−D_damp 是否自洽", True,
                   "所有帧预算残差均在数值下限内（ΔE 与 W_act−D_damp 自洽）")


# ====================================================================
# EC2 · 无凭空能量（ΔE ≤ W_act，阻尼只会耗能不会增能 → 抓「能量创生」）
# ====================================================================
def check_no_free_energy(session):
    run = 0
    run_start = None
    worst = 0.0
    for i, f in enumerate(session):
        excess = f["dE"] - f["W_act"]    # >0 表示动能增量超过执行器做功（凭空增能）
        if excess > _floor(f):
            if run == 0:
                run_start = i
            run += 1
            worst = max(worst, excess)
            if run >= K_PERSIST:
                return _result(
                    "EC2_NO_FREE_ENERGY", "动能增量是否未超执行器做功（无凭空能量）", False,
                    f"动能凭空增连续 {run} 帧（自 step={session[run_start]['step']} 起）；"
                    f"最大超出 ΔE−W_act={worst:.3e} J —— 系统无功增能（破坏第二定律）",
                    locator={"first_step": session[run_start]["step"],
                             "first_seq": session[run_start]["seq"],
                             "max_excess_J": round(worst, 6)})
        else:
            run = 0
    return _result("EC2_NO_FREE_ENERGY", "动能增量是否未超执行器做功（无凭空能量）", True,
                   "无凭空能量：动能增量恒 ≤ 执行器做功（阻尼只耗能）")


# ====================================================================
# EC3 · 执行器速度上限（抓「速度越物理上限」）
# ====================================================================
def check_actuator_bound(session, v_max=V_PHYS_MAX, w_max=W_PHYS_MAX):
    run = 0
    run_start = None
    worst = 0.0
    for i, f in enumerate(session):
        over = max(abs(f["v_act"]) - v_max, abs(f["w_act"]) - w_max)
        if over > 0:
            if run == 0:
                run_start = i
            run += 1
            worst = max(worst, over)
            if run >= K_PERSIST:
                return _result(
                    "EC3_ACTUATOR_BOUND", "实际速度是否未越执行器物理上限", False,
                    f"速度越上限连续 {run} 帧（自 step={session[run_start]['step']} 起）；"
                    f"最大越限 {worst:.3f}（v_max={v_max}, w_max={w_max}）",
                    locator={"first_step": session[run_start]["step"],
                             "first_seq": session[run_start]["seq"],
                             "max_overshoot": round(worst, 4),
                             "v_act": round(session[run_start]["v_act"], 4)})
        else:
            run = 0
    return _result("EC3_ACTUATOR_BOUND", "实际速度是否未越执行器物理上限", True,
                   "实际线/角速度均未越执行器物理上限")


CHECKS = [check_energy_budget, check_no_free_energy, check_actuator_bound]


def audit_session(session, v_max=V_PHYS_MAX, w_max=W_PHYS_MAX):
    """对账本 session 跑 EC1/EC2/EC3。v_max/w_max 为执行器物理速度上限（A/B 模式不同）。"""
    results = [
        check_energy_budget(session),
        check_no_free_energy(session),
        check_actuator_bound(session, v_max=v_max, w_max=w_max),
    ]
    passed = all(r["ok"] for r in results)
    return {"passed": passed, "verdict": "GREEN" if passed else "RED", "checks": results}


def format_report(audit, title=""):
    lines = []
    if title:
        lines.append(title)
    overall = "🟢 全绿通过 (GREEN)" if audit["passed"] else "🔴 检出物理自欺 (RED)"
    lines.append(f"  能量审计总判定：{overall}")
    for r in audit["checks"]:
        mark = "🟢 GREEN" if r["ok"] else "🔴 RED  "
        lines.append(f"    [{mark}] {r['check']:<20} {r['desc']}")
        lines.append(f"             └─ {r['detail']}")
        if not r["ok"] and r["locator"]:
            lines.append(f"             └─ 定位: {r['locator']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("用法: python energy_audit.py <energy_session.json>")
        sys.exit(1)
    with open(sys.argv[1]) as fh:
        sess = json.load(fh)
    res = audit_session(sess)
    print(format_report(res, title=f"== 能量审计 {sys.argv[1]} =="))
    sys.exit(0 if res["passed"] else 2)
