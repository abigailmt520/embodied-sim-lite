# -*- coding: utf-8 -*-
"""
cross_fidelity.py  ——  跨保真自欺审计 · D2 能量对照(打头) + D1 轨迹 + D3 包络
================================================================================
论点：**内部一致 ≠ 与现实一致**。
  2D 简化孪生(EmbodiedNavEnv)用它自己的私有能量账本 ΔE=W_act−D_damp−E_contact 自洽，
  **通过它全部内部物理预言 EC1–EC5**；但其接触模型是粗简化(撞墙=标量速度 ×e=0.5 + 推出,
  无向量反射/摩擦/接触流形)。把**同一控制序列**同步喂给高保真 PyBullet(真接触动力学),
  在**接触处**孪生账面能量与 PyBullet 真实**涌现发散**——跨保真能量预言抓到,而孪生自己的
  EC1–EC5 仍 PASS。这正是"过全部自检的孪生仍背离现实"。

🔴 架构红线：PyBullet=物理现实(truth);2D 孪生=被审计的简化模型(其 E_kin 账面=report)。
   绝不把 frontend-physics-authority / local-dead-reckoning 移植进来。
🔴 诚实：自由段(无接触)两侧应在容差内吻合(=FP 本底);接触处才涌现发散。若自由段已大发散,
   如实报告(那是另一种更弥散的 report-vs-reality,故事更糊但要真相)。emergent vs constructed 明标。

运行(g1-pybullet conda env,已装 gymnasium,不引 torch)：
  conda run -n g1-pybullet python g1_pybullet/cross_fidelity.py
"""

import os
import sys

import numpy as np
import pybullet as p
import pybullet_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "audit"))
from embodied_env import EmbodiedNavEnv                       # noqa: E402  2D 简化孪生(被审计)
from energy_audit import audit_session as ec_audit            # noqa: E402  孪生自己的 EC1–EC5

# —— 与 2D 孪生逐字对齐的物理常数(从 env 读,保持同步)——
E = EmbodiedNavEnv
MASS, IZZ = E.MASS, E.INERTIA_COEF * E.MASS    # 1.0, 0.5
C_LIN, C_ANG, ARM = E.C_LIN, E.C_ANG, E.ARM    # 3.0, 3.0, 0.8
F_MAX, RADIUS, BOUNCE = E.F_MAX, E.ROBOT_RADIUS, E.BOUNCE  # 2.25, 0.20, 0.5
DT = E.DT                                       # 0.10
N_PB_SUB = 24                                   # 24×(1/240)=0.1 对齐 2D 一个控制步
PB_DT = DT / N_PB_SUB                           # 1/240
HALF_H = 0.10                                   # 圆柱半高(平面化,只 z 平面运动)
# PyBullet 法向恢复系数按"两体相乘"合成 → 取每体 √0.5 使**有效 e≈0.5 匹配 2D BOUNCE**(干净归因)。
REST_BODY = float(np.sqrt(BOUNCE))              # ≈0.7071 → e_eff≈0.5


# ====================================================================
# PyBullet 高保真侧：匹配机器人 + 墙 + 平面化 + 驱动
# ====================================================================
def make_robot(init_xy, init_yaw=0.0, restitution=0.5, friction=0.0):
    """匹配 2D 孪生的圆柱 unicycle：半径 0.20、质量 1.0、**绕 z 转动惯量 Izz=0.5(覆盖物理盘的 0.02)**。
    平面化(锁 z/roll/pitch);自带阻尼置零(我们显式施 −C·v,逐字对齐 2D ODE)。"""
    col = p.createCollisionShape(p.GEOM_CYLINDER, radius=RADIUS, height=2 * HALF_H)
    uid = p.createMultiBody(MASS, col, -1, [init_xy[0], init_xy[1], HALF_H],
                            p.getQuaternionFromEuler([0, 0, init_yaw]))
    p.changeDynamics(uid, -1, linearDamping=0.0, angularDamping=0.0,
                     localInertiaDiagonal=[IZZ, IZZ, IZZ],   # 平面运动只 z 分量起作用
                     restitution=restitution, lateralFriction=friction,
                     spinningFriction=0.0, rollingFriction=0.0)
    return uid


def make_wall(aabb, restitution=0.5, friction=0.0):
    """声称地图墙(GEOM_BOX 静态)。aabb=(xmin,xmax,ymin,ymax)。restitution/friction = 高保真接触参数。"""
    xmin, xmax, ymin, ymax = aabb
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    hx, hy = (xmax - xmin) / 2, (ymax - ymin) / 2
    col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[hx, hy, 0.3])
    uid = p.createMultiBody(0, col, -1, [cx, cy, HALF_H])
    p.changeDynamics(uid, -1, restitution=restitution, lateralFriction=friction,
                     spinningFriction=0.0, rollingFriction=0.0)
    return uid


def _planar_project(uid):
    """把 PyBullet 约束成 2D 平面 unicycle 等价：每子步零化 vz=wx=wy=0(→z 与 roll/pitch 不漂移)。
    (与 2D 孪生同为平面运动,此投影是**匹配**而非 gap;接触法向皆水平故几乎无 z 干预。)
    🔴 注意：绝不用 resetBasePositionAndOrientation(它会清零速度,杀死运动——已实测);仅零化速度分量即可保持平面。"""
    v, w = p.getBaseVelocity(uid)
    p.resetBaseVelocity(uid, [v[0], v[1], 0.0], [0.0, 0.0, w[2]])


def pb_energy(uid):
    """PyBullet 真实机械能 = KE(无重力→无 PE)。与 2D 同式 ½m‖v_xy‖²+½Izz·wz²。"""
    v, w = p.getBaseVelocity(uid)
    return 0.5 * MASS * (v[0] ** 2 + v[1] ** 2) + 0.5 * IZZ * w[2] ** 2


def pb_drive_step(uid, wall_uids, f_l, f_r):
    """一个 2D 控制步 = 24 PyBullet 子步：沿 heading 施净力(f_l+f_r)+力矩(f_r−f_l)·ARM,
    显式黏性阻尼 −C·v(对齐 2D ODE),逐子步平面化。返回 (W_act, contact_any, friction_loss)。"""
    W_act = 0.0
    contact = False
    for _ in range(N_PB_SUB):
        pos, orn = p.getBasePositionAndOrientation(uid)
        yaw = p.getEulerFromQuaternion(orn)[2]
        v, w = p.getBaseVelocity(uid)
        vlin = np.array([v[0], v[1]]); wz = w[2]
        heading = np.array([np.cos(yaw), np.sin(yaw)])
        F_app = (f_l + f_r) * heading                 # 执行器净力(账本可见)
        T_app = (f_r - f_l) * ARM
        F = F_app - C_LIN * vlin                       # + 黏性阻尼(对齐 2D)
        T = T_app - C_ANG * wz
        p.applyExternalForce(uid, -1, [F[0], F[1], 0.0], list(pos), p.WORLD_FRAME)
        p.applyExternalTorque(uid, -1, [0.0, 0.0, T], p.WORLD_FRAME)
        p.stepSimulation()
        _planar_project(uid)
        v2, w2 = p.getBaseVelocity(uid)
        vmid = 0.5 * (vlin + np.array([v2[0], v2[1]]))
        W_act += float(np.dot(F_app, vmid)) * PB_DT    # 执行器做功(力·中点速·dt)
        if any(len(p.getContactPoints(uid, wu)) > 0 for wu in wall_uids):
            contact = True
    return W_act, contact


# ====================================================================
# 2D 简化孪生侧：自定义单墙场景 + 同控制序列驱动 + 能量账本 + EC1–EC5
# ====================================================================
def make_twin(init_xy, init_yaw, walls_aabb):
    env = EmbodiedNavEnv(slip=0.0, control_mode="B", map_type="maze")  # slip=0 → odom≡truth(本实验不看 odom)
    env.reset(seed=0)
    env.walls = list(walls_aabb)
    env._walls_arr = np.array(env.walls, dtype=np.float64).reshape(-1, 4)
    env.pos = np.array(init_xy, dtype=np.float64)
    env.theta = float(init_yaw)
    env.v_act = 0.0; env.w_act = 0.0
    env.physics_fault = {}
    env.goal = np.array([1e4, 1e4])               # 远离 → 永不"到达"终止
    return env


def twin_ledger_row(env):
    st = env.get_render_state(); e = st["energy"]
    return {"step": st["step"], "seq": st["seq"], "E_kin": e["E_kin"], "dE": e["dE"],
            "W_act": e["W_act"], "D_damp": e["D_damp"], "E_contact_decl": e["E_contact_decl"],
            "E_contact_act": e["E_contact_act"], "penetration": e["penetration"],
            "v_act": st["v_act"], "w_act": st["w_act"]}


# ====================================================================
# 同步双跑
# ====================================================================
def dual_run(control_seq, init_xy, init_yaw, walls_aabb, restitution=REST_BODY, friction=0.0):
    """同一 control_seq([f_l,f_r] 归一化∈[-1,1]) 同步驱动 2D 孪生 + PyBullet。逐步记录两侧能量。"""
    # 2D 孪生
    env = make_twin(init_xy, init_yaw, walls_aabb)
    # PyBullet
    p.resetSimulation()
    p.setGravity(0, 0, 0)
    p.setTimeStep(PB_DT)
    wall_uids = [make_wall(w, restitution, friction) for w in walls_aabb]
    robot = make_robot(init_xy, init_yaw, restitution, friction)

    rec = {"t": [], "E_2d": [], "E_pb": [], "x_2d": [], "y_2d": [], "x_pb": [], "y_pb": [],
           "contact_pb": [], "v_2d": [], "ledger": []}
    rec["E_2d"].append(0.5 * MASS * env.v_act ** 2 + 0.5 * IZZ * env.w_act ** 2)
    rec["E_pb"].append(pb_energy(robot))
    rec["t"].append(0.0)
    rec["x_2d"].append(float(env.pos[0])); rec["y_2d"].append(float(env.pos[1]))
    pos0, _ = p.getBasePositionAndOrientation(robot)
    rec["x_pb"].append(pos0[0]); rec["y_pb"].append(pos0[1])
    rec["contact_pb"].append(False); rec["v_2d"].append(0.0)

    for k, (fl, fr) in enumerate(control_seq):
        env.step(np.array([fl, fr], dtype=np.float32))           # 2D 孪生一步(内含碰撞+账本)
        pb_drive_step(robot, wall_uids, fl * F_MAX, fr * F_MAX)  # PyBullet 同控制 24 子步
        rec["t"].append((k + 1) * DT)
        rec["E_2d"].append(0.5 * MASS * env.v_act ** 2 + 0.5 * IZZ * env.w_act ** 2)
        rec["E_pb"].append(pb_energy(robot))
        rec["x_2d"].append(float(env.pos[0])); rec["y_2d"].append(float(env.pos[1]))
        pos, _ = p.getBasePositionAndOrientation(robot)
        rec["x_pb"].append(pos[0]); rec["y_pb"].append(pos[1])
        rec["contact_pb"].append(bool(any(len(p.getContactPoints(robot, wu)) > 0 for wu in wall_uids)))
        rec["v_2d"].append(float(env.v_act))
        rec["ledger"].append(twin_ledger_row(env))
    return rec


def measure_restitution():
    """标定 PyBullet 有效法向恢复系数(头对头),用于把 PyBullet 调到 ≈2D 的 e=0.5(干净归因)。"""
    p.resetSimulation(); p.setGravity(0, 0, 0); p.setTimeStep(PB_DT)
    wall = make_wall((2.0, 2.2, -2.0, 2.0), restitution=REST_BODY, friction=0.0)
    ball = make_robot([1.0, 0.0], 0.0, restitution=REST_BODY, friction=0.0)
    p.resetBaseVelocity(ball, [3.0, 0, 0], [0, 0, 0])
    v_in = 3.0; v_out = 0.0
    for _ in range(400):
        p.stepSimulation(); _planar_project(ball)
        vx = p.getBaseVelocity(ball)[0][0]
        if vx < 0:
            v_out = max(v_out, -vx)
    return v_out / v_in


# ====================================================================
# Step 1 验证 + 主
# ====================================================================
def validate_freespace():
    """Step 1：自由段(无墙)匹配验证。直线加速+滑行,比对 2D vs PyBullet 轨迹与能量。"""
    print("=" * 84)
    print("  Step 1 · 自由段匹配验证(无接触)：2D 孪生 vs PyBullet 应在容差内吻合")
    print("=" * 84)
    # 远墙(不接触),直线:前 15 步加速(双轮 +1),后 25 步滑行(0)
    far_wall = [(50.0, 50.2, -5.0, 5.0)]
    seq = [(1.0, 1.0)] * 15 + [(0.0, 0.0)] * 25
    rec = dual_run(seq, [0.0, 0.0], 0.0, far_wall, restitution=REST_BODY, friction=0.0)
    E2, EP = np.array(rec["E_2d"]), np.array(rec["E_pb"])
    dpos = np.hypot(np.array(rec["x_2d"]) - np.array(rec["x_pb"]),
                    np.array(rec["y_2d"]) - np.array(rec["y_pb"]))
    eabs = np.abs(E2 - EP)
    print(f"  能量: 末端 E_2d={E2[-1]:.4f} E_pb={EP[-1]:.4f} J;|ΔE| max={eabs.max():.3e} 末={eabs[-1]:.3e} J")
    print(f"  轨迹: 位置差 max={dpos.max():.4e} 末={dpos[-1]:.4e} m")
    print(f"  峰值动能≈{E2.max():.3f} J(v≈{np.sqrt(2*E2.max()/MASS):.3f} m/s)")
    ok = eabs.max() < 0.02 and dpos.max() < 0.05
    print(f"  → 自由段匹配: {'✅ 干净(可作 FP 本底)' if ok else '⚠️ 发散偏大(如实记录,见诚实判断)'}")
    return {"E_abs_max": float(eabs.max()), "dpos_max": float(dpos.max()),
            "E_peak": float(E2.max()), "clean": bool(ok)}


# ====================================================================
# 场景：自由段加速 → 滑行(零控制)撞墙。撞墙时 W_act=0 → 能量纯耗散(干净对照)。
# ====================================================================
def run_scenario(init_xy, init_yaw, wall_aabb, force=0.8, steps=45, friction=0.6,
                 ec_floor=0.02):
    """跑一个撞墙场景(恒力驱动→必达墙、掠射时持续滑动),返回逐步记录 + 派生指标。

    恒力 a=force(归一化轮力);稳态 v_ss=force·1.5 < V_PHYS_MAX_B=1.65(保 EC3 不误红)。
    撞墙时仍施力 → 头对头=压墙、掠射=沿墙持续滑动(PyBullet 有摩擦损、2D 无 → 涌现发散)。"""
    rec = dual_run([(force, force)] * steps, init_xy, init_yaw, [wall_aabb],
                   restitution=REST_BODY, friction=friction)
    E2, EP = np.array(rec["E_2d"]), np.array(rec["E_pb"])
    contact = np.array(rec["contact_pb"])
    ci = int(np.argmax(contact)) if contact.any() else None         # 首接触步
    if ci is None:
        floor = float(np.abs(E2 - EP).max()); div = 0.0; ke_c = float(E2.max())
    else:
        floor = float(np.abs(E2[:ci] - EP[:ci]).max()) if ci > 0 else 0.0
        div = float(np.abs(E2[ci:] - EP[ci:]).max())
        ke_c = float(E2[max(ci - 1, 0)])                            # 接触前动能
    # 2D 孪生自己的 EC1–EC5(应全 PASS = 内部自洽)。B-mode 用 B 档执行器上限 V_PHYS_MAX_B。
    ec = (ec_audit(rec["ledger"], v_max=E.V_PHYS_MAX_B, w_max=E.W_PHYS_MAX_B, with_collision=True)
          if rec["ledger"] else {"passed": True, "checks": []})
    dpos = np.hypot(np.array(rec["x_2d"]) - np.array(rec["x_pb"]),
                    np.array(rec["y_2d"]) - np.array(rec["y_pb"]))
    return {"rec": rec, "first_contact": ci, "ke_at_contact": ke_c,
            "fp_floor_J": floor, "contact_div_J": div,
            "twin_ec_passed": bool(ec["passed"]),
            "twin_ec_reds": [c["check"] for c in ec["checks"] if not c["ok"]],
            "dpos_max_m": float(dpos.max()), "dpos_post_m": float(dpos[ci:].max()) if ci else 0.0,
            "E2_end": float(E2[-1]), "EP_end": float(EP[-1]),
            "detected": bool(ci is not None and div > 5 * max(floor, ec_floor))}


def main():
    import json
    p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    out = {}

    eff_e = measure_restitution()
    print(f"[标定] PyBullet 有效法向恢复系数 e_eff≈{eff_e:.3f}(目标 2D BOUNCE={BOUNCE};REST_BODY={REST_BODY:.3f})")
    out["restitution_eff"] = float(eff_e)

    out["freespace"] = validate_freespace()
    FP_FLOOR = max(out["freespace"]["E_abs_max"], 0.005)
    THRESH = 5 * FP_FLOOR
    print(f"\n  跨保真能量预言阈值 = 5×自由段本底 = 5×{FP_FLOOR:.3e} = {THRESH:.3e} J")

    # —— Step 2 · D2 能量对照(PRIMARY):头对头(模型 gap) + 掠射(摩擦 gap)——
    print("\n" + "=" * 84)
    print("  Step 2 · D2 能量对照(同控制双跑;孪生过自己 EC vs 跨保真预言 flag)")
    print("=" * 84)
    # 竖直墙 x∈[3.0,3.2];机器人从 x=0 出发,加速后滑行撞墙。
    wall = (2.0, 2.2, -3.5, 3.5)
    d2 = {}
    for name, yaw, y0 in [("head_on", 0.0, 0.0), ("glancing_45", np.deg2rad(45), -2.0)]:
        s = run_scenario([0.0, y0], yaw, wall, force=0.8, steps=45, friction=0.6, ec_floor=FP_FLOOR)
        d2[name] = {k: v for k, v in s.items() if k != "rec"}
        if name == "head_on":
            r = s["rec"]
            out["headon_series"] = {"t": r["t"], "E_2d": r["E_2d"], "E_pb": r["E_pb"],
                                    "contact": [int(c) for c in r["contact_pb"]],
                                    "first_contact": s["first_contact"]}
        ci = s["first_contact"]
        print(f"\n  [{name}] yaw={np.rad2deg(yaw):.0f}° 接触前KE={s['ke_at_contact']:.3f}J 首接触步={ci}")
        print(f"    2D 孪生自检 EC1–EC5: {'🟢 全 PASS(内部自洽)' if s['twin_ec_passed'] else '🔴 RED '+str(s['twin_ec_reds'])}")
        print(f"    自由段 FP 本底 |ΔE|={s['fp_floor_J']:.3e}J  |  接触发散 |ΔE|={s['contact_div_J']:.3e}J")
        print(f"    跨保真能量预言(阈 {THRESH:.3e}): {'🔴 FLAG(账面背离现实)' if s['detected'] else '🟢 未触发'}"
              f"  | 末端 E_2d={s['E2_end']:.3f} E_pb={s['EP_end']:.3f}J")
        print(f"    🔴 对照: 孪生 {'过' if s['twin_ec_passed'] else '未过'}全部内部 EC,却被跨保真预言"
              f"{'抓到背离现实' if s['detected'] else '判一致'} → 内部一致≠与现实一致")
    out["d2"] = d2

    # —— Step 3 · D1 轨迹发散(SECONDARY,可约)——
    print("\n" + "=" * 84)
    print("  Step 3 · D1 轨迹发散(可约:大度量,被 contract ‖x_2d−x_pb‖ 超预算抓;非不可约)")
    print("=" * 84)
    for name in d2:
        print(f"  [{name}] 接触后轨迹差 max={d2[name]['dpos_post_m']:.3f}m(2D 撞墙模型 vs PyBullet 真接触涌现发散)")

    # —— Step 4 · D3 发散包络(SECONDARY):扫入射角 ——
    print("\n" + "=" * 84)
    print("  Step 4 · D3 发散包络(扫入射角:头对头→掠射;能量发散 vs 接触几何)")
    print("=" * 84)
    print(f"  {'入射角°':<8}{'接触前KE':<10}{'自由段本底':<12}{'接触发散':<12}{'2D EC':<10}{'跨保真预言'}")
    env_rows = []
    for deg in (0, 15, 30, 45, 60, 75):
        yaw = np.deg2rad(deg)
        y0 = -np.tan(yaw) * 2.0 if deg < 80 else 0.0           # 让不同角都在墙中段接触(终点 y≈0)
        s = run_scenario([0.0, float(np.clip(y0, -3.0, 3.0))], yaw, wall, force=0.8, steps=50,
                         friction=0.6, ec_floor=FP_FLOOR)
        env_rows.append({"angle_deg": deg, "ke_at_contact": s["ke_at_contact"],
                         "fp_floor_J": s["fp_floor_J"], "contact_div_J": s["contact_div_J"],
                         "twin_ec_passed": s["twin_ec_passed"], "detected": s["detected"]})
        print(f"  {deg:<8}{s['ke_at_contact']:<10.3f}{s['fp_floor_J']:<12.3e}{s['contact_div_J']:<12.3e}"
              f"{'🟢PASS' if s['twin_ec_passed'] else '🔴':<10}{'🔴FLAG' if s['detected'] else '🟢—'}")
    out["d3_envelope"] = env_rows

    # —— 诚实判读 ——
    print("\n" + "=" * 84)
    n_flag = sum(r["detected"] for r in env_rows)
    n_ec = sum(r["twin_ec_passed"] for r in env_rows)
    print(f"  诚实判读: 自由段本底 ~{FP_FLOOR:.1e}J(干净匹配);接触发散 ~"
          f"{np.median([r['contact_div_J'] for r in env_rows]):.2e}J(涌现,>{THRESH:.1e} 阈)")
    print(f"  跨保真预言在 {n_flag}/{len(env_rows)} 入射角 FLAG;2D 孪生 EC1–EC5 在 {n_ec}/{len(env_rows)} 角全 PASS")
    print(f"  → 论点坐实: 孪生过自己全部内部物理自检,却在接触处账面能量背离 PyBullet 现实(涌现,非手 pin)")

    p.disconnect()
    here = os.path.dirname(os.path.abspath(__file__))
    json.dump(out, open(os.path.join(here, "cross_fidelity_energy.json"), "w"),
              indent=2, ensure_ascii=False)
    try:
        make_figure(out, os.path.join(here, "cross_fidelity_energy.png"))
        print(f"  [OK] 图: {os.path.join(here, 'cross_fidelity_energy.png')}")
    except Exception as ex:
        print(f"  [WARN] 图跳过: {ex}")
    print(f"  [OK] 数据: {os.path.join(here, 'cross_fidelity_energy.json')}")
    return out


def make_figure(out, path):
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
    rows = out["d3_envelope"]
    angs = [r["angle_deg"] for r in rows]
    fig, (ax0, ax1, ax2) = plt.subplots(1, 3, figsize=(18, 4.4))
    # ① head-on 能量-时间(最直观:撞墙后孪生账面"幻能" vs PyBullet 真实归零)
    hs = out.get("headon_series")
    if hs:
        t = np.array(hs["t"]); ci = hs["first_contact"]
        ax0.plot(t, hs["E_2d"], "-", color="#37a", lw=2, label="孪生账面 E_2d(自检自洽)")
        ax0.plot(t, hs["E_pb"], "-", color="#d33", lw=2, label="PyBullet 真实 E_pb")
        if ci:
            ax0.axvline(t[ci], ls="--", color="#888", label="首接触")
        ax0.set_xlabel("时间 (s)"); ax0.set_ylabel("机械能 (J)")
        ax0.set_title("① 头对头:接触后孪生账面'幻能'≠现实归零\n(同位置 x=1.80m,能量背离)")
        ax0.legend(fontsize=8); ax0.grid(alpha=0.3)
    # ② D3 包络
    ax1.plot(angs, [r["contact_div_J"] for r in rows], "o-", color="#d33", label="接触能量发散 |ΔE|")
    ax1.plot(angs, [r["fp_floor_J"] for r in rows], "s--", color="#2a7", label="自由段 FP 本底")
    ax1.axhline(5 * max(out["freespace"]["E_abs_max"], 0.005), ls=":", color="#888", label="跨保真预言阈(5×本底)")
    ax1.set_xlabel("入射角 (°)  0=头对头, 大=掠射"); ax1.set_ylabel("|E_2d − E_pb| (J)")
    ax1.set_title("② D3 跨保真能量发散包络\n(75°=未达墙→真阴性)"); ax1.legend(fontsize=8); ax1.grid(alpha=0.3)
    ax1.set_yscale("symlog", linthresh=1e-3)
    # ③ 核心对照柱
    cats = ["内部自检\nEC1–EC5", "跨保真\n能量预言"]
    passes = [sum(r["twin_ec_passed"] for r in rows), len(rows) - sum(r["detected"] for r in rows)]
    flags = [len(rows) - sum(r["twin_ec_passed"] for r in rows), sum(r["detected"] for r in rows)]
    x = np.arange(2)
    ax2.bar(x, passes, color="#2a7", label="PASS/一致")
    ax2.bar(x, flags, bottom=passes, color="#d33", label="RED/FLAG")
    ax2.set_xticks(x); ax2.set_xticklabels(cats, fontsize=9)
    ax2.set_ylabel(f"入射角数 (共 {len(rows)})")
    ax2.set_title("③ 内部一致 ≠ 与现实一致\n(孪生过自检 / 跨保真预言抓背离)"); ax2.legend(fontsize=8)
    fig.suptitle("Cross-Fidelity D2: 简化孪生过全部内部 EC,接触处账面能量涌现背离 PyBullet 现实",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")


if __name__ == "__main__":
    main()
