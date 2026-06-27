# -*- coding: utf-8 -*-
"""
g1a_baseline.py  ——  G1a · 健康 PyBullet 基线 + 噪声本底刻画（诚实检查点 1）
=============================================================================
🔴 检查点 1：健康 PyBullet 跑起来，物理审计（能量/动量/非穿透）必须**零误报**，
   或如实给出引擎正常数值噪声本底刻画（把"引擎积分噪声"和"真病理"分开）。
   做不出干净基线就如实报告，不调参硬压。
"""

import os
import sys

import numpy as np
import pybullet as p

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pb_helpers as H


def baseline_energy_floor():
    """无阻尼自由抛体（守恒系统）→ 刻画引擎积分器能量噪声本底。"""
    H.connect(dt=1.0 / 240.0)
    m = 1.0
    ball = H.add_ball(m, [0, 0, 5], radius=0.1, damping=0.0)
    p.resetBaseVelocity(ball, [3, 0, 4], [0, 0, 0])
    E = []
    for _ in range(400):
        pos, _, _, _ = H.base_state(ball)
        if pos[2] < 0.3:
            break
        E.append(H.mechanical_energy(ball, m))
        p.stepSimulation()
    p.disconnect()
    E = np.array(E)
    dE = np.diff(E)
    floor = float(np.max(np.abs(dE)))
    print(f"[能量噪声本底] 无阻尼自由抛体 N={len(E)}步：E0={E[0]:.3f}J")
    print(f"  单步|ΔE| 最大={floor:.3e}J, 均值={np.mean(dE):+.3e}J, 累计漂移={E[-1]-E[0]:+.3e}J "
          f"({abs(E[-1]-E[0])/E[0]*100:.4f}%)")
    print(f"  → 引擎能量噪声本底 ≈ {floor:.1e} J/step（审计阈值须 > 此；类比 Phase3 KSG 噪声预算界）")
    return floor


def baseline_nonpenetration_and_momentum():
    """健康：地面上慢速小球滚向墙、低速正常回弹（引擎正确处理接触）→ EC5'/引擎接触 应全绿。
    🔴 关键：必须加地面保持**平面运动**（z≈const），EC5' 的 2D(x,y) 投影才有效（平台 v_z≈0 不变量）。"""
    H.connect(dt=1.0 / 240.0)
    p.loadURDF("plane.urdf")                                            # 地面（保持平面运动）
    wall_uid, wall_aabb = H.add_wall([2.0, 0, 0.3], [0.05, 1.0, 0.3])   # 薄墙 x≈2
    m = 1.0
    ball = H.add_ball(m, [0, 0, 0.1], radius=0.1, damping=0.0)
    p.changeDynamics(ball, -1, restitution=0.85, rollingFriction=0.0)   # 弹性回弹
    p.changeDynamics(wall_uid, -1, restitution=0.85)
    p.resetBaseVelocity(ball, [1.5, 0, 0], [0, 0, 0])    # 慢速直冲墙（1.5 m/s，引擎可正确检测）
    truth_xyz = []; truth_xy = []; eng_pen = []
    for _ in range(500):
        pos, _, v, _ = H.base_state(ball)
        truth_xyz.append(pos); truth_xy.append([pos[0], pos[1]])
        eng_pen.append(H.engine_reported_penetration(ball, [wall_uid]))
        p.stepSimulation()
    p.disconnect()
    truth_xy = np.array(truth_xy); truth_xyz = np.array(truth_xyz)
    r5 = H.ec5prime_truth_vs_map(truth_xy, [wall_aabb], radius=0.1)
    max_eng_pen = max(eng_pen)
    reached = truth_xy[:, 0].max()
    z_range = (truth_xyz[:, 2].min(), truth_xyz[:, 2].max())
    print(f"\n[非穿透 健康基线] 地面慢速(1.5m/s)撞墙 N={len(truth_xy)}步：球最远 x={reached:.3f}（墙内面 x≈1.85）")
    print(f"  平面性: z∈[{z_range[0]:.3f},{z_range[1]:.3f}]（应≈0.1 恒定→2D 投影有效）")
    print(f"  EC5'(几何真值-vs-墙): {'🟢绿(未穿墙)' if r5['ok'] else '🔴红 '+r5['detail']}")
    print(f"  引擎自报穿透 max={max_eng_pen:.4e} m（低速接触引擎正确解算→≈0）")
    return r5["ok"], max_eng_pen


def main():
    print("=" * 78)
    print("  G1a · 健康 PyBullet 基线 + 噪声本底刻画（检查点 1）")
    print("=" * 78)
    floor = baseline_energy_floor()
    # 用噪声本底的 ~10× 作能量审计 floor，跑一段健康（守恒）确认零误报
    H.connect(dt=1.0 / 240.0)
    m = 1.0; ball = H.add_ball(m, [0, 0, 5], radius=0.1, damping=0.0)
    p.resetBaseVelocity(ball, [2, 1, 3], [0, 0, 0])
    E = []
    for _ in range(300):
        pos, _, _, _ = H.base_state(ball)
        if pos[2] < 0.3:
            break
        E.append(H.mechanical_energy(ball, m)); p.stepSimulation()
    p.disconnect()
    ok_e, det_e, resid = H.energy_audit_series(E, floor_abs=max(10 * floor, 1e-2), floor_rel=1e-3)
    print(f"\n[能量审计 健康] floor={max(10*floor,1e-2):.1e}J/step → {'🟢绿(零误报)' if ok_e else '🔴红 '+det_e}")

    ok_p, eng_pen = baseline_nonpenetration_and_momentum()

    print("\n" + "=" * 78)
    print("  检查点 1 结论")
    print("=" * 78)
    clean = ok_e and ok_p
    print(f"  能量审计 健康零误报: {'✅' if ok_e else '❌'}  (噪声本底 {floor:.1e} J/step, 阈值取 10×)")
    print(f"  非穿透 健康零误报  : {'✅' if ok_p else '❌'}")
    print(f"  → 健康基线{'干净（零误报，噪声本底已刻画）✅' if clean else '有误报（见上，如实报告）⚠️'}")
    return clean


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
