# -*- coding: utf-8 -*-
"""
pb_helpers.py  ——  G1 · PyBullet 真引擎泛化：场景/孪生上报/不变量/审计 复用层
================================================================================
把 2D 平台的审计**逻辑**移植到 PyBullet（独立第三方真引擎），测两件事：
  1) 物理层（能量/动量/非穿透/EC5'）能否抓 **PyBullet 自己的原生数值病理**（非循环·皇冠）。
  2) 契约层（C1-C3+CI）/ joint 在 3D 真引擎状态空间下是否仍 работает（移植后用我们的上报注入器）。

🔴 架构红线：保持「引擎内部高保真态=truth；派生 odom/传感上报=report」（后端唯一真理源、前端纯观测）。
   绝不把 frontend-physics-authority / local-dead-reckoning 移植进来。

🔴 非循环要点：物理病理由**引擎真实数值**产生（设诱发条件，不手设故障状态）；审计逻辑是我们的，
   但被测故障来自 PyBullet。
"""

import os
import sys

import numpy as np
import pybullet as p
import pybullet_data

# 复用 2D 平台审计逻辑（纯函数，状态流/几何）——审计逻辑移植，2D 平台不改
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audit"))
from integrity_audit import check_truth_odom_fork, check_seq_integrity, check_feed_liveness  # noqa: E402
from joint_audit import traj_vs_map, _circle_aabb_pen                                          # noqa: E402

G = 9.8


# ====================================================================
# 场景
# ====================================================================
def connect(dt=1.0 / 240.0, gravity=True):
    p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -G if gravity else 0)
    p.setTimeStep(dt)
    return dt


def add_wall(center, half_extents):
    """加一面薄墙（GEOM_BOX，静态）。返回 (uid, aabb_xy=(xmin,xmax,ymin,ymax))。"""
    cx, cy, cz = center
    hx, hy, hz = half_extents
    col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents)
    uid = p.createMultiBody(0, col, -1, center, [0, 0, 0, 1])   # mass=0 → 静态
    aabb = (cx - hx, cx + hx, cy - hy, cy + hy)
    return uid, aabb


def add_ball(mass, pos, radius=0.1, damping=0.0):
    col = p.createCollisionShape(p.GEOM_SPHERE, radius=radius)
    uid = p.createMultiBody(mass, col, -1, pos, [0, 0, 0, 1])
    p.changeDynamics(uid, -1, linearDamping=damping, angularDamping=damping)
    return uid


def add_box_body(mass, pos, half_extents=(0.1, 0.1, 0.1), damping=0.0):
    col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents)
    uid = p.createMultiBody(mass, col, -1, pos, [0, 0, 0, 1])
    p.changeDynamics(uid, -1, linearDamping=damping, angularDamping=damping)
    return uid


# ====================================================================
# 物理真值读出（truth）
# ====================================================================
def base_state(uid):
    """返回 (pos(3,), quat(4,), v(3,), w(3,))——PyBullet 高保真真值。"""
    pos, quat = p.getBasePositionAndOrientation(uid)
    v, w = p.getBaseVelocity(uid)
    return np.array(pos), np.array(quat), np.array(v), np.array(w)


def kinetic_energy(uid, mass, inertia_diag=None):
    """½m‖v‖² + ½ωᵀIω（单刚体；inertia_diag 缺省取近似球惯量可忽略转动项）。"""
    _, _, v, w = base_state(uid)
    ke = 0.5 * mass * float(np.dot(v, v))
    if inertia_diag is not None:
        ke += 0.5 * float(np.dot(inertia_diag, w * w))
    return ke


def potential_energy(uid, mass):
    pos, _, _, _ = base_state(uid)
    return mass * G * float(pos[2])


def mechanical_energy(uid, mass, inertia_diag=None):
    return kinetic_energy(uid, mass, inertia_diag) + potential_energy(uid, mass)


def linear_momentum(uid, mass):
    _, _, v, _ = base_state(uid)
    return mass * v


# ====================================================================
# 孪生上报层（report = 由 truth 派生的 odom，镜像 2D _integrate_odom）
# ====================================================================
class OdomReporter:
    """后端唯一真理源(truth) → 派生 odom 上报(report)：吃真值速度 + 打滑噪声积分（航迹推算）。
    与 2D 平台 _integrate_odom 同构：v_odom=v*(1+slip)+N(0,slip)*|v|。绝不本地推演替代真值。"""

    def __init__(self, init_xy, slip=0.05, seed=0):
        self.odom = np.array(init_xy, dtype=np.float64)
        self.slip = slip
        self.rng = np.random.default_rng(seed)

    def update(self, truth_v_xy, dt):
        v = np.array(truth_v_xy, dtype=np.float64)
        if self.slip > 0:
            v = v * (1 + self.slip) + self.rng.normal(0, self.slip, 2) * np.abs(v)
        self.odom = self.odom + v * dt
        return self.odom.copy()


# ====================================================================
# 物理审计（移植 EC1 能量预算 / EC5' 几何非穿透 思想到 3D 真引擎）
# ====================================================================
def energy_audit_series(E_series, W_series=None, floor_abs=1e-2, floor_rel=1e-2, k_persist=3):
    """EC1(3D)：机械能预算。无外力做功时 ΔE 应≈0（守恒）；有作动器功 W 时 ΔE≈W。
    floor 须 > 引擎积分器噪声本底（实测 ~8e-4 J/step）。连续 k 步超界判红。
    返回 (ok, detail, max_resid)。"""
    E = np.asarray(E_series, dtype=np.float64)
    dE = np.diff(E)
    W = np.zeros_like(dE) if W_series is None else np.asarray(W_series, dtype=np.float64)[:len(dE)]
    resid = dE - W
    run = 0; first = None; worst = 0.0
    for i, r in enumerate(resid):
        fl = floor_abs + floor_rel * abs(E[i])
        if abs(r) > fl:
            if run == 0:
                first = i
            run += 1
            if abs(r) > abs(worst):
                worst = r
            if run >= k_persist:
                return False, f"能量预算残差连续{run}步超界(自step{first})；最大残差{worst:.3e}J", float(worst)
        else:
            run = 0
    return True, f"能量预算自洽（最大单步残差 {np.max(np.abs(resid)):.3e}J 在噪声本底内）", float(np.max(np.abs(resid)))


def energy_conservation_check(E_series, work_in=0.0, floor_abs=1e-2, floor_rel=0.02):
    """EC1(守恒版)：守恒系统(无外功 work_in≈0)机械能应受 E0+做功 上界限制。
    max(E) 显著超过 E0+work_in（超噪声本底）= 能量被引擎注入（病理）。抓弹性反弹能量增益等。"""
    E = np.asarray(E_series, dtype=np.float64)
    e0 = E[0]
    bound = e0 + work_in + floor_abs + floor_rel * abs(e0)
    excess = float(E.max() - bound)
    if excess > 0:
        i = int(np.argmax(E))
        return False, (f"机械能超守恒上界：max(E)={E.max():.3f}J > E0+功+本底 {bound:.3f}J "
                       f"(超出 {excess:.3f}J @step{i}) — 引擎注入能量"), excess
    return True, f"机械能守恒（max(E)={E.max():.3f}J ≤ 上界 {bound:.3f}J，在噪声本底内）", excess


def ec5prime_truth_vs_map(truth_xy_traj, walls_aabb, radius, pen_floor=1e-3):
    """EC5'(3D 平面投影)：真值(x,y)轨迹 vs 声称墙几何（不信任引擎接触报告，几何重算）。
    抓引擎碰撞检测漏掉的真值真穿墙（如高速穿模）。复用 2D joint_audit 几何。"""
    r = traj_vs_map(np.asarray(truth_xy_traj), walls_aabb, radius, "truth")
    r["check"] = "EC5P_TRUTH_MAP_3D"
    return r


def _segment_crosses_aabb(p0, p1, aabb, radius):
    """线段 p0→p1（按半径膨胀）是否与墙 AABB 相交（slab 法）。供高速穿模的扫掠检测。"""
    xmin, xmax, ymin, ymax = aabb
    xmin -= radius; xmax += radius; ymin -= radius; ymax += radius
    d = np.asarray(p1, float) - np.asarray(p0, float)
    tmin, tmax = 0.0, 1.0
    for lo, hi, o, dd in ((xmin, xmax, p0[0], d[0]), (ymin, ymax, p0[1], d[1])):
        if abs(dd) < 1e-12:
            if o < lo or o > hi:
                return False
        else:
            t1, t2 = (lo - o) / dd, (hi - o) / dd
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1); tmax = min(tmax, t2)
            if tmin > tmax:
                return False
    return True


def ec5prime_swept(truth_xy_traj, walls_aabb, radius):
    """EC5'（扫掠版）：检查相邻真值帧的**线段**是否穿过任一墙 AABB。
    抓「高速穿模」——物体单步位移 > 墙厚而在帧间跳过墙时，逐帧点检测会漏，扫掠线段检测能抓。"""
    T = np.asarray(truth_xy_traj)
    crossings = []
    for i in range(len(T) - 1):
        for w in walls_aabb:
            if _segment_crosses_aabb(T[i], T[i + 1], w, radius):
                crossings.append(i)
                break
    if crossings:
        return {"check": "EC5P_SWEPT_3D", "ok": False, "status": "RED",
                "detail": f"真值轨迹线段穿过声称墙：{len(crossings)} 段非法，首穿 @帧{crossings[0]}"
                          f"（高速穿模：单步跳过墙体）",
                "locator": {"first_crossing_frame": crossings[0], "n_crossings": len(crossings),
                            "pos0": [round(float(T[crossings[0]][0]), 3), round(float(T[crossings[0]][1]), 3)]}}
    return {"check": "EC5P_SWEPT_3D", "ok": True, "status": "GREEN",
            "detail": "真值轨迹无线段穿墙（扫掠非穿透合法）", "locator": None}


def engine_reported_penetration(uid, wall_uids):
    """引擎自报穿透：getClosestPoints 的最负距离（穿模时引擎可能漏报→为0）。供对照 EC5'。"""
    worst = 0.0
    for w in wall_uids:
        for cp in p.getClosestPoints(uid, w, distance=0.05):
            d = cp[8]   # contactDistance（穿透为负）
            if d < 0:
                worst = max(worst, -d)
    return worst
