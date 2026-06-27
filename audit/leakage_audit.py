# -*- coding: utf-8 -*-
"""
leakage_audit.py  ——  Phase3 · 契约层「互信息泄漏审计」（CI 审计，C1 的原理化泛化）
==================================================================================
不变量：合法上报通道（odom）与 truth 的互信息，受其**噪声预算**上界限制；
        泄漏 = I(odom; truth) 超过该噪声预算界。与物理层「能量守恒残差」对称
        （物理：ΔE 守恒；契约：I(report;truth) ≤ 噪声预算）。

🔴 工程判断（对 Opus 原设计的修正，见 docs/Phase3 §3「设计坑」）：
  原设计「I(odom_pos;truth_pos) ≤ ½log(1+Var/σ²)」对**绝对位置**不成立——odom 是航迹推算
  (dead-reckoning) 的**累积积分**，回合开始 odom≡truth、其后累积漂移；绝对位置 MI 由共享
  轨迹相关性主导（非噪声通道），且复位后近无穷。**正确做法：对逐步位移增量 (Δpos) 估 MI**
  （无记忆通道）。噪声预算界用**声称噪声模型再加噪 truth 增量**的 MI（蒙特卡洛操作化），
  闭式 ½log(1+SNR) 仅作参照（其 AWGN 假设对乘性 slip 噪声只近似成立）。

判据（CI 审计，镜像 C1/EC 门控）：滑窗内估 I(Δodom;Δtruth)，超「噪声预算界 + 余量」
        且持续 → 判红 + 定位。

可靠性（INV-E）：KSG 对高 MI（高信噪比/近确定性）饱和、有偏；故对平台部署的 slip=0.05
        （odom 很准、预算界 ~3.3 nats 逼近 KSG 可靠上限）检出力受限（L-3 旋转泄漏会漏）；
        在 slip≈0.3 的可估区间三类泄漏均干净检出。详见 run_leakage_audit.py 实测 + 文档。
"""

import numpy as np

from mi_estimator import ksg_mi, increments

MARGIN_NATS = 0.4     # 噪声预算界之上的判红余量（由清洁/再加噪 MC 方差标定）
K_PERSIST = 2         # 连续超界窗口数阈值（镜像 C3 STALE_TOL）


def _result(name, desc, ok, detail, locator=None):
    return {"check": name, "desc": desc, "status": "GREEN" if ok else "RED",
            "ok": bool(ok), "detail": detail, "locator": locator}


# ---- 噪声预算界：声称噪声模型再加噪 truth 增量的 MI（操作化）+ 闭式参照 ----
def noise_budget_bound(d_truth, slip, n_mc=5, seed=0):
    """对 truth 增量按声称 slip 模型再加噪，估其 I(Δtruth;Δodom_legit) 为噪声预算界（nats）。

    声称模型（embodied_env:494-495 的增量近似）：Δodom = (1+slip)·Δtruth + slip·|Δtruth|·N(0,I)。
    返回 (budget_mean, budget_std, closed_form_ref)。
    """
    rng = np.random.default_rng(seed)
    mag = np.linalg.norm(d_truth, axis=1, keepdims=True)
    mis = []
    for _ in range(n_mc):
        legit = (1.0 + slip) * d_truth + slip * mag * rng.normal(0, 1, d_truth.shape)
        mis.append(ksg_mi(d_truth, legit))
    # 闭式参照：½log(1+SNR)，SNR=Var(Δtruth)/Var(noise)，noise≈slip·|Δtruth|（每分量、近似）
    var_truth = float(np.mean(np.var(d_truth, axis=0)))
    var_noise = float(slip ** 2 * np.mean(mag ** 2))
    closed = 0.5 * np.log(1.0 + var_truth / max(var_noise, 1e-12)) * d_truth.shape[1]
    return float(np.mean(mis)), float(np.std(mis)), float(closed)


def estimate_leakage_mi(truth_traj, odom_traj):
    """对一段 (truth_pos, odom_pos) 轨迹估 I(Δodom; Δtruth)（全样本，nats）。"""
    dT, dO = increments(truth_traj), increments(odom_traj)
    return ksg_mi(dT, dO)


# ====================================================================
# CI 审计：滑窗 I(Δodom;Δtruth) 超「噪声预算界+余量」且持续 → 判红
# ====================================================================
def ci_audit(truth_traj, odom_traj, slip, window=500, stride=250, margin=MARGIN_NATS):
    """对 (truth_pos, odom_pos) 轨迹跑 CI 审计。返回 result（含全样本 MI、界、逐窗）。"""
    dT, dO = increments(truth_traj), increments(odom_traj)
    N = dT.shape[0]
    budget, b_std, closed = noise_budget_bound(dT, slip)
    thresh = budget + margin
    mi_full = ksg_mi(dT, dO)

    # 滑窗 + 持续门控
    over_run = 0
    flagged_from = None
    win_mis = []
    for s in range(0, max(1, N - window + 1), stride):
        wm = ksg_mi(dT[s:s + window], dO[s:s + window])
        win_mis.append((s, round(wm, 3)))
        if wm > thresh:
            if over_run == 0:
                flagged_from = s
            over_run += 1
        else:
            over_run = 0
    # 窗口太少时退化到全样本判定
    persistent = over_run >= K_PERSIST or (len(win_mis) < K_PERSIST + 1 and mi_full > thresh)
    leak = (mi_full > thresh) and persistent

    loc = {"mi_full_nats": round(mi_full, 3), "budget_nats": round(budget, 3),
           "budget_std": round(b_std, 3), "threshold_nats": round(thresh, 3),
           "closed_form_ref_nats": round(closed, 3), "excess_nats": round(mi_full - budget, 3),
           "n_increments": N, "flagged_window_from": flagged_from}
    if leak:
        return _result("CI_MI_LEAKAGE", "I(odom;truth) 是否未超噪声预算界", False,
                       f"互信息 I(Δodom;Δtruth)={mi_full:.3f} nats 超噪声预算界 {budget:.3f}"
                       f"(+余量{margin}) {thresh:.3f}；超出 {mi_full-budget:+.3f} nats（泄漏）", loc)
    return _result("CI_MI_LEAKAGE", "I(odom;truth) 是否未超噪声预算界", True,
                   f"互信息 I={mi_full:.3f} nats ≤ 噪声预算界 {budget:.3f}(+余量) {thresh:.3f}"
                   f"（合法，未泄漏）", loc)


# ====================================================================
# 泄漏注入器（契约层，藏 odom 上报；仅测试自证抓假，绝不进生产）
#   作用于 (truth_traj, odom_traj_orig) → 返回被泄漏的 odom_traj。
# ====================================================================
def inject_l1_full_leak(truth_traj, odom_traj):
    """L-1 全泄漏：odom 偷偷返回 truth（Δodom=Δtruth）。误差≈0，C1 也能抓。"""
    return np.asarray(truth_traj, dtype=np.float64).copy()


def inject_l2_partial_leak(truth_traj, odom_traj, shrink=0.25):
    """L-2 部分泄漏：odom 返回 truth + 比声称小的噪声（每步误差缩到 shrink 倍）。
    仍有系统漂移（误差不为零）→ C1 易漏；但信息超预算 → CI 抓。"""
    T = np.asarray(truth_traj, np.float64); O = np.asarray(odom_traj, np.float64)
    dT, dO = increments(T), increments(O)
    err = dO - dT
    dO_new = dT + shrink * err               # 误差缩小 → 噪声小于声称 → 部分泄漏
    out = np.empty_like(T); out[0] = T[0]
    out[1:] = T[0] + np.cumsum(dO_new, axis=0)
    return out


def inject_l3_privileged(truth_traj, odom_traj, deg=35.0):
    """L-3 特权确定性变换：odom 增量=旋转后的 truth 增量（确定可逆函数）。
    位置误差**大**（C1 看到大误差→误判合法）但完全由 truth 决定 → I=∞ → CI 抓。
    复刻「odom 返回特权特征（确定函数 of truth）替代含噪观测」。"""
    T = np.asarray(truth_traj, np.float64)
    dT = increments(T)
    th = np.deg2rad(deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    dO_new = dT @ R.T                        # 确定性旋转（无噪声）
    out = np.empty_like(T); out[0] = T[0]
    out[1:] = T[0] + np.cumsum(dO_new, axis=0)
    return out


LEAK_INJECTORS = {
    "L-1_full_leak": inject_l1_full_leak,
    "L-2_partial_leak": inject_l2_partial_leak,
    "L-3_privileged": inject_l3_privileged,
}
LEAK_DESCRIPTIONS = {
    "L-1_full_leak": "odom 偷偷=truth（全泄漏，误差≈0，C1 也抓）",
    "L-2_partial_leak": "odom=truth+比声称小的噪声（部分泄漏，仍漂移→C1 易漏）",
    "L-3_privileged": "odom=truth 的确定性旋转（特权变换，大误差但确定→C1 误判合法）",
}
