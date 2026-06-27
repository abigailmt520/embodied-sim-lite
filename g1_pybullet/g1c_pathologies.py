# -*- coding: utf-8 -*-
"""
g1c_pathologies.py  ——  G1c · 其余原生病理 + 契约层 + joint（3D 真引擎）
========================================================================
- 物理病理(非循环): 能量注入(弹性反弹/大步长引擎数值增益) → 能量审计能否抓。
- 契约层(支撑·移植): C1-C3 在 3D 真值/odom 状态空间, 用我们的上报注入器(odom接回truth/断流谎称在线)测。
- joint(支撑): 上报轨迹 vs PyBullet 物理墙 联合交叉核对。
每条如实报告 catch/miss。warm-start 幽灵力: 诚实尝试 + 标注隔离难度。
"""

import os
import sys

import numpy as np
import pybullet as p

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pb_helpers as H


# ── 病理 1：能量注入（弹性反弹，引擎数值增益）──────────────────────────
def pathology_energy_injection(dt=1.0 / 120.0):
    H.connect(dt=dt)
    pl = p.loadURDF("plane.urdf"); p.changeDynamics(pl, -1, restitution=1.0)
    ball = H.add_ball(1.0, [0, 0, 2.0], 0.1, damping=0.0)
    p.changeDynamics(ball, -1, restitution=1.0)      # e=1 守恒系统（无外功）
    E = []
    for _ in range(1500):
        E.append(H.mechanical_energy(ball, 1.0)); p.stepSimulation()
    p.disconnect()
    ok, det, excess = H.energy_conservation_check(E, work_in=0.0, floor_abs=1e-2)
    print(f"\n[病理1·能量注入] 弹性反弹(e=1,守恒) dt={1/dt:.0f}Hz: E0={E[0]:.2f} → max={max(E):.2f} J")
    print(f"  能量审计(守恒上界): {'🔴红 抓到' if not ok else '🟢绿 漏掉'} — {det}")
    print(f"  🔴 非循环: 注入来自 PyBullet 离散接触求解器(e=1 本应守恒), 非我们手设。")
    return (not ok)


# ── 病理 2(诚实尝试)：warm-start 幽灵力 ───────────────────────────────
def pathology_warmstart_ghost():
    """接触断开瞬间的伪冲量。诚实尝试：堆叠后突然移除支撑，看断开瞬间是否有异常动量/能量跳变。
    隔离难: 与正常重力下落混叠。如实报告能否干净测出。"""
    H.connect(dt=1.0 / 240.0)
    p.loadURDF("plane.urdf")
    base = H.add_box_body(0, [0, 0, 0.25], (0.3, 0.3, 0.25), damping=0.0)  # 静态支撑
    top = H.add_box_body(1.0, [0, 0, 0.6], (0.1, 0.1, 0.1), damping=0.0)
    for _ in range(240):
        p.stepSimulation()                    # 稳定接触(warm-start 建立)
    pos0, _, v0, _ = H.base_state(top)
    p.removeBody(base)                         # 突然撤支撑 → 接触断开瞬间
    dKE = []
    for _ in range(5):
        _, _, v, _ = H.base_state(top)
        dKE.append(0.5 * 1.0 * float(np.dot(v, v)))
        p.stepSimulation()
    p.disconnect()
    # 断开后应是纯自由落体(竖直加速)，水平速度应≈0；幽灵冲量会给非物理横向速度
    print(f"\n[病理2·warm-start幽灵力] 撤支撑后 top 块速度演化(应纯竖直自由落体):")
    print(f"  断开瞬间 v0={v0}, 之后 KE 序列={[round(k,4) for k in dKE]}")
    lateral = abs(v0[0]) + abs(v0[1])
    print(f"  横向速度 |vx|+|vy|={lateral:.4e} m/s ({'🔴 异常横向(疑幽灵冲量)' if lateral>1e-3 else '🟢 无异常横向'})")
    print(f"  ⚠️ 如实标注：warm-start 幽灵力与正常重力下落混叠、难干净隔离；本测仅查断开瞬态横向异常，"
          f"非完整诊断。{'此例未见显著异常' if lateral<=1e-3 else ''}")
    return None     # 不计入 catch/miss 主结论（隔离难，诚实 scope）


# ── 契约层(移植·支撑)：C1-C3 在 3D truth/odom + 我们的上报注入器 ──────────
def contract_layer_3d():
    H.connect(dt=1.0 / 240.0); p.loadURDF("plane.urdf")
    husky = p.loadURDF("husky/husky.urdf", [0, 0, 0.1])
    wheels = [j for j in range(p.getNumJoints(husky))
              if "wheel" in p.getJointInfo(husky, j)[1].decode()]
    rep = H.OdomReporter(init_xy=[0, 0], slip=0.05, seed=1)
    truth_xy, odom_xy = [[0, 0]], [[0, 0]]
    for _ in range(600):
        for j in wheels:                       # 差速：左右轮不同速 → 转弯前进
            tgt = 8.0 if j in wheels[1::2] else 5.0
            p.setJointMotorControl2(husky, j, p.VELOCITY_CONTROL, targetVelocity=tgt, force=40)
        p.stepSimulation()
        pos, _, v, _ = H.base_state(husky)
        truth_xy.append([pos[0], pos[1]])
        odom_xy.append(list(rep.update([v[0], v[1]], 1.0 / 240.0)))
    p.disconnect()
    truth = np.array(truth_xy); odom = np.array(odom_xy)

    def c123(truth, odom):
        sess = [{"recv_t": float(i), "seq": i, "step": i,
                 "truth": {"x": float(truth[i][0]), "y": float(truth[i][1]), "theta": 0.0},
                 "odom": {"x": float(odom[i][0]), "y": float(odom[i][1]), "theta": 0.0},
                 "terminated": False, "truncated": False, "link_status": "online"}
                for i in range(len(truth))]
        return (H.check_truth_odom_fork(sess)["ok"], H.check_seq_integrity(sess)["ok"],
                H.check_feed_liveness(sess)["ok"])

    print(f"\n[契约层 3D·移植] husky 差速行驶 N={len(truth)}步, odom=真值速度+slip 航迹推算")
    h = c123(truth, odom)
    print(f"  健康: C1={'🟢' if h[0] else '🔴'} C2={'🟢' if h[1] else '🔴'} C3={'🟢' if h[2] else '🔴'} "
          f"→ {'全绿(无误报)✅' if all(h) else '有误报'}")
    # 注入器1-A: odom 接回 truth → C1 应抓
    leak = c123(truth, truth)
    print(f"  注入 odom=truth(全泄漏): C1={'🔴抓' if not leak[0] else '🟢漏'} (期望 C1 红)")
    # 注入: 帧序冻结(数据动 seq 不动) → C2 应抓
    sess = [{"recv_t": float(i), "seq": (i if i < 300 else 300), "step": i,
             "truth": {"x": float(truth[i][0]), "y": float(truth[i][1]), "theta": 0.0},
             "odom": {"x": float(odom[i][0]), "y": float(odom[i][1]), "theta": 0.0},
             "terminated": False, "truncated": False, "link_status": "online"} for i in range(len(truth))]
    c2red = not H.check_seq_integrity(sess)["ok"]
    print(f"  注入 seq冻结(数据动): C2={'🔴抓' if c2red else '🟢漏'} (期望 C2 红)")
    return all(h), (not leak[0]), c2red, truth, odom


# ── joint(支撑)：上报轨迹 vs PyBullet 墙 ──────────────────────────────
def joint_3d(truth, odom):
    from joint_audit import ec5_prime, joint_report_vs_map
    # 声称墙：husky 行驶区外放一面墙(truth 不穿、合法)；伪造 odom 穿墙
    wall_aabb = (3.0, 3.1, -5.0, 5.0)
    radius = 0.3
    ec5p = ec5_prime(truth, [wall_aabb], radius)          # 真值合法
    fake_odom = np.array([[i * 0.02, 0.0] for i in range(len(truth))])  # 直穿 x=3 墙
    jr = joint_report_vs_map(fake_odom, [wall_aabb], radius)
    print(f"\n[joint 3D·支撑] 声称墙 x∈[3.0,3.1]")
    print(f"  EC5'(真值 husky vs 墙): {'🟢绿 合法' if ec5p['ok'] else '🔴红'}")
    print(f"  joint(伪造 odom 穿墙 vs 墙): {'🔴红 抓' if not jr['ok'] else '🟢绿 漏'} (期望红)")
    return ec5p["ok"], (not jr["ok"])


def main():
    print("=" * 80)
    print("  G1c · 其余原生病理 + 契约层 + joint（3D 真引擎）")
    print("=" * 80)
    e_caught = pathology_energy_injection()
    pathology_warmstart_ghost()
    h_ok, c1_red, c2_red, truth, odom = contract_layer_3d()
    ec5_ok, joint_red = joint_3d(truth, odom)

    print("\n" + "=" * 80)
    print("  G1c 小结")
    print("=" * 80)
    print(f"  物理病理·能量注入: {'✅ 审计抓到' if e_caught else '❌ 漏'}")
    print(f"  契约层 健康零误报: {'✅' if h_ok else '❌'} | 注入 C1(全泄漏){'✅抓' if c1_red else '❌漏'} "
          f"C2(seq冻结){'✅抓' if c2_red else '❌漏'}")
    print(f"  joint 真值合法绿+伪造odom穿墙红: {'✅' if (ec5_ok and joint_red) else '❌'}")
    return e_caught and h_ok and c1_red and c2_red and ec5_ok and joint_red


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
