# -*- coding: utf-8 -*-
"""
g1b_tunneling.py  ——  G1b · 触发 PyBullet 原生高速穿模，测物理审计能否抓（非循环·皇冠）
============================================================================================
🔴 非循环：只设**诱发条件**（薄墙 + 高速 + 默认步长、无 CCD），让 PyBullet 自己的离散碰撞
   检测漏掉快速物体 → 真值真穿墙。**不手设故障状态**。测物理审计（EC5' 几何/扫掠）能否抓到。
检查点 2：如实报告抓到 or 漏掉；区分诱发条件 vs 手设故障。
"""

import os
import sys

import numpy as np
import pybullet as p

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pb_helpers as H


def run(speed, wall_half_thick=0.02, dt=1.0 / 120.0, ccd=False):
    """地面上以 speed 直冲薄墙。返回 (truth_xy, wall_aabb, eng_pen_max, tunneled)。"""
    H.connect(dt=dt)
    p.loadURDF("plane.urdf")
    wall_uid, wall_aabb = H.add_wall([2.0, 0, 0.3], [wall_half_thick, 1.0, 0.3])
    m = 1.0
    ball = H.add_ball(m, [0, 0, 0.1], radius=0.1, damping=0.0)
    p.changeDynamics(ball, -1, restitution=0.9, rollingFriction=0.0)
    if ccd:
        p.changeDynamics(ball, -1, ccdSweptSphereRadius=0.1)   # 开 CCD 作对照（默认关）
    p.resetBaseVelocity(ball, [speed, 0, 0], [0, 0, 0])
    truth_xy = []; eng_pen = 0.0
    for _ in range(400):
        pos, _, _, _ = H.base_state(ball)
        truth_xy.append([pos[0], pos[1]])
        eng_pen = max(eng_pen, H.engine_reported_penetration(ball, [wall_uid]))
        if pos[0] > 3.5:
            break
        p.stepSimulation()
    p.disconnect()
    truth_xy = np.array(truth_xy)
    tunneled = truth_xy[:, 0].max() > 2.5          # 越到墙后远端 = 穿过去了
    return truth_xy, wall_aabb, eng_pen, tunneled


def main():
    print("=" * 80)
    print("  G1b · 触发 PyBullet 原生高速穿模 → 测物理审计（检查点 2）")
    print("=" * 80)
    R = 0.1; DT = 1.0 / 120.0
    print(f"\n  墙: x∈[1.98,2.02]（半厚0.02m）, 步长 1/120s. 诱发条件=高速(单步位移≫墙厚) + 默认无CCD\n")
    print(f"  {'速度(m/s)':<10}{'单步位移':<10}{'穿过?':<8}{'引擎自报穿透':<14}{'EC5点检测':<12}{'EC5扫掠':<12}")
    rows = {}
    for speed in (50.0, 200.0, 400.0):
        truth_xy, wall_aabb, eng_pen, tunneled = run(speed, dt=DT)
        disp = speed * DT
        r_pt = H.ec5prime_truth_vs_map(truth_xy, [wall_aabb], R)        # 逐帧点检测(体半径)
        r_sw = H.ec5prime_swept(truth_xy, [wall_aabb], 0.0)            # 扫掠：中心-vs-墙芯 穿越
        rows[speed] = {"tunneled": tunneled, "eng_pen": eng_pen,
                       "ec5_point_red": not r_pt["ok"], "ec5_swept_red": not r_sw["ok"]}
        print(f"  {speed:<10}{disp:<10.4f}{'是🔴' if tunneled else '否(挡住)':<7}"
              f"{eng_pen:<14.2e}{'🔴红' if not r_pt['ok'] else '🟢绿':<12}{'🔴红' if not r_sw['ok'] else '🟢绿':<12}")

    print("\n" + "=" * 80)
    print("  检查点 2 结论（PyBullet 自己的高速穿模 → 物理审计能否抓）")
    print("=" * 80)
    fast = rows[200.0]
    if fast["tunneled"] and fast["eng_pen"] < 1e-9:
        print(f"  ✅ 诱发成功且**纯净**：200 m/s 时球**真穿墙**，**引擎自报穿透=0**——")
        print(f"     PyBullet 自己的离散碰撞检测**完全漏检**（非我们手设故障，是引擎真实数值病理）。")
        if fast["ec5_swept_red"] and not fast["ec5_point_red"]:
            print(f"  ✅ 物理审计**抓到**：EC5'**扫掠版判红**；而 EC5'逐帧点检测**也漏**（球单步跳过整面墙、无帧落墙内）")
            print(f"     ——与引擎漏检同因（离散采样）。故高速穿模**必须扫掠**线段检测才抓得到。")
            print(f"  🔴 非循环坐实：故障来自 PyBullet 自身数值穿模，我们的审计逻辑（扫掠 EC5'）抓到了**我们没造的引擎的真实病理**。")
        elif fast["ec5_swept_red"]:
            print(f"  ✅ 物理审计抓到：EC5'扫掠+点检测均判红。非循环坐实。")
        else:
            print(f"  ❌ 物理审计**漏掉**：EC5'(点+扫掠)均未抓 → 诚实负结果，框架未泛化到此病理。")
    elif fast["tunneled"]:
        print(f"  ⚠️ 穿模但引擎仍报部分穿透({fast['eng_pen']:.1e})；EC5'扫掠={'红' if fast['ec5_swept_red'] else '绿'}。")
    else:
        print(f"  ⚠️ 200 m/s 未穿模 → 需更强诱发；如实标注。")
    catch = fast["tunneled"] and fast["ec5_swept_red"] and fast["eng_pen"] < 1e-9
    return catch


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
