# -*- coding: utf-8 -*-
"""
mi_estimator.py  ——  Phase3 · 连续变量互信息估计（KSG / Kraskov k-NN，估计器1）
===============================================================================
为契约层「互信息泄漏审计」提供 I(X;Y) 的非参数估计（X,Y 可多维连续）。

KSG 估计器 1（Kraskov-Stögbauer-Grassberger 2004）：
    I(X;Y) = ψ(k) + ψ(N) − <ψ(n_x+1) + ψ(n_y+1)>
其中对每个样本点，在联合空间 (X,Y) 用 Chebyshev(max) 范数找第 k 近邻距离 ε_i，
n_x/n_y = 在各自边际空间内距该点 < ε_i 的点数。ψ=digamma。

可靠性注记（INV-E，务必如实看待）：
    - 连续 MI 估计**有偏有方差**；样本量 N 越小、维度越高，偏差/方差越大。
    - 对**确定性关系**（如 odom=truth），真 MI=+∞，KSG 返回一个随 N 增长的**有限大值**（不会真无穷）。
      故「全泄漏」表现为 MI 远超界、但非字面无穷——审计据此判红仍有效。
    - 本模块对各维**标准化**后再估（使 max 范数跨维可比）；返回值钳到 ≥0（MI 非负）。
"""

import numpy as np

try:
    from scipy.special import digamma
    from scipy.spatial import cKDTree
    _HAVE_SCIPY = True
except Exception:                       # 兜底：scipy 不可用时用简化实现
    _HAVE_SCIPY = False


def _as2d(a):
    a = np.asarray(a, dtype=np.float64)
    return a.reshape(-1, 1) if a.ndim == 1 else a


def _standardize(a):
    """逐维标准化（零均值单位方差）；常数维加微小抖动避免退化。"""
    mu = a.mean(axis=0, keepdims=True)
    sd = a.std(axis=0, keepdims=True)
    sd = np.where(sd < 1e-12, 1.0, sd)
    return (a - mu) / sd


def ksg_mi(X, Y, k=4, standardize=True, seed=0):
    """KSG 估计 I(X;Y)（nats）。X:(N,dx), Y:(N,dy)。N 不足或 scipy 缺失时退化处理。"""
    X, Y = _as2d(X), _as2d(Y)
    N = X.shape[0]
    if N <= k + 2:
        return 0.0
    if standardize:
        X, Y = _standardize(X), _standardize(Y)
    if not _HAVE_SCIPY:
        return _binned_mi(X, Y)        # 兜底
    rng = np.random.default_rng(seed)
    # 加极微抖动打破并列距离（KSG 对并列敏感）
    X = X + rng.normal(0, 1e-10, X.shape)
    Y = Y + rng.normal(0, 1e-10, Y.shape)
    XY = np.hstack([X, Y])
    tree = cKDTree(XY)
    dists, _ = tree.query(XY, k=k + 1, p=np.inf)   # 含自身，取第 k+1 个=第 k 近邻
    eps = dists[:, -1]
    tx, ty = cKDTree(X), cKDTree(Y)
    nx = np.array([len(tx.query_ball_point(X[i], eps[i] - 1e-12, p=np.inf)) - 1
                   for i in range(N)])
    ny = np.array([len(ty.query_ball_point(Y[i], eps[i] - 1e-12, p=np.inf)) - 1
                   for i in range(N)])
    mi = digamma(k) + digamma(N) - np.mean(digamma(nx + 1) + digamma(ny + 1))
    return float(max(0.0, mi))


def _binned_mi(X, Y, bins=8):
    """兜底：等频分箱直方图 MI（仅 scipy 缺失时用；偏差更大）。"""
    def disc(a):
        out = np.zeros(a.shape[0], dtype=np.int64)
        for j in range(a.shape[1]):
            q = np.quantile(a[:, j], np.linspace(0, 1, bins + 1)[1:-1])
            out = out * bins + np.digitize(a[:, j], q)
        return out
    xd, yd = disc(X), disc(Y)
    N = X.shape[0]
    mi = 0.0
    for xv in np.unique(xd):
        px = np.mean(xd == xv)
        for yv in np.unique(yd):
            py = np.mean(yd == yv)
            pxy = np.mean((xd == xv) & (yd == yv))
            if pxy > 0:
                mi += pxy * np.log(pxy / (px * py))
    return float(max(0.0, mi))


def increments(traj):
    """轨迹 (T,2) → 逐步位移增量 (T-1,2)。"""
    traj = np.asarray(traj, dtype=np.float64)
    return traj[1:] - traj[:-1]


if __name__ == "__main__":
    # 自检：已知 MI 的高斯通道 Y = X + N(0,σ²)，理论 I=½log(1+Var(X)/σ²)
    rng = np.random.default_rng(1)
    N = 2000
    x = rng.normal(0, 1, (N, 1))
    for sigma in (0.3, 1.0):
        y = x + rng.normal(0, sigma, (N, 1))
        theo = 0.5 * np.log(1 + 1.0 / sigma ** 2)
        est = ksg_mi(x, y, k=4)
        print(f"σ={sigma}: KSG I={est:.3f} nats, 理论 ½log(1+1/σ²)={theo:.3f} nats")
    # 确定性 Y=X：MI→∞，KSG 返回大有限值
    print(f"确定性 Y=X: KSG I={ksg_mi(x, x, k=4):.3f} nats (应远大于上面, 但有限)")
