# -*- coding: utf-8 -*-
"""
run_coupling_test.py  ——  Phase4 · 双态耦合压测（用反自欺纪律压测论文核心论点本身）
====================================================================================
目标：构造一个自欺，使 (a) 契约层审计单独跑=过、(b) 物理层审计单独跑=过、
      但 (c) report×physics 联合交叉核对=抓住。这才证明「双态耦合」，而非两个并排审计。

🔴 诚实判别（最重要）：一个穿墙自欺是否构成**真耦合**，由 truth_vs_map 判别：
    - truth_vs_map 红 → 真值真穿墙 → **物理内（真值 vs 地图）独力可抓** → **非真耦合**（仅 EC5 实现缺口）。
    - truth_vs_map 绿 且 odom_vs_map 红 → 真值合法、唯上报非法 → 既非物理内、也非契约自洽可抓 → **真耦合**。

两场景：
  场景A「字面穿墙幽灵」：碰撞检测剔除一面墙 → **真值真穿墙**。预期物理/契约各自过，但 truth_vs_map 红
        → 如实判「非真耦合，物理内可抓（EC5 缺口）」。绝不调参硬凑成耦合。
  场景B「真耦合变体」：**真值诚实（被墙挡、合法）**，但 odom 被伪造成一条穿墙的自洽航迹。
        预期 truth_vs_map 绿、odom_vs_map 红 → 真耦合（唯 report×物理地图 可抓）。

运行：python audit/run_coupling_test.py
产物：audit/coupling_summary.json
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embodied_env import EmbodiedNavEnv                                   # noqa: E402
from audit_suite import run_suite, format_suite, coupling_label          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WALLS = EmbodiedNavEnv.MAZE_WALLS
RADIUS = EmbodiedNavEnv.ROBOT_RADIUS
PHANTOM_IDX = 4          # 幽灵掉的墙：死亡长廊左墙 (28,29,5,33)
THIN_WALL = [(30.0, 30.2, 9.0, 16.0)]   # 薄墙 d=0.20 < ξ（场景 B2 位移跨墙·拓扑不可约接入回归用）


def _energy_row(env):
    st = env.get_render_state(); e = st["energy"]
    return {"step": st["step"], "seq": st["seq"], "E_kin": e["E_kin"], "dE": e["dE"],
            "W_act": e["W_act"], "D_damp": e["D_damp"],
            "E_contact_decl": e["E_contact_decl"], "E_contact_act": e["E_contact_act"],
            "penetration": e["penetration"], "v_act": st["v_act"], "w_act": st["w_act"]}


def run_layers(truth, odom, eledger, slip, tag):
    """跑常驻三层套件（含物理层 EC5'），返回各层 verdict + 耦合判定。"""
    res = run_suite(truth, odom, eledger, WALLS, RADIUS, slip,
                    EmbodiedNavEnv.V_PHYS_MAX, EmbodiedNavEnv.W_PHYS_MAX)
    verdict = coupling_label(res)
    print(f"\n{'='*78}\n  {tag}\n{'='*78}")
    print(format_suite(res))
    print(f"  ── 耦合判定 ──────► {verdict}")
    return {"physics_passed": res["physics"]["ok"], "contract_passed": res["contract"]["ok"],
            "ec5_prime_ok": res["physics"]["ec5_prime_ok"], "joint_ok": res["joint"]["ok"],
            "verdict": verdict}


# ====================================================================
# 场景 A：字面「穿墙幽灵」——真值真穿墙
# ====================================================================
def scenario_a():
    env = EmbodiedNavEnv(slip=0.05, control_mode="A", map_type="maze")
    env.reset(seed=11)
    env.pos = np.array([26.5, 20.0]); env.theta = 0.0; env.v_act = 0.0; env.w_act = 0.0
    env.odom_pos = env.pos.copy(); env.odom_theta = 0.0
    env.physics_fault = {"phantom_walls": [PHANTOM_IDX]}   # 碰撞检测剔除死亡长廊左墙
    truth, odom, eledger = [env.pos.copy()], [env.odom_pos.copy()], []
    for _ in range(40):
        env.step(np.array([1.0, 0.0], dtype=np.float32))   # 直冲 +x，穿过 [28,29] 那面墙
        truth.append(env.pos.copy()); odom.append(env.odom_pos.copy()); eledger.append(_energy_row(env))
    return np.array(truth), np.array(odom), eledger


# ====================================================================
# 场景 B：真耦合变体——真值诚实（被墙挡），odom 伪造成穿墙自洽航迹
# ====================================================================
def scenario_b():
    # 真值：诚实跑（撞墙回弹、合法），记录真值轨迹与其诚实能量账本
    env = EmbodiedNavEnv(slip=0.05, control_mode="A", map_type="maze")
    env.reset(seed=11)
    env.pos = np.array([26.5, 20.0]); env.theta = 0.0; env.v_act = 0.0; env.w_act = 0.0
    env.odom_pos = env.pos.copy(); env.odom_theta = 0.0
    # 不注入幽灵 → 真值被 [28,29] 墙挡住（合法）
    truth, eledger = [env.pos.copy()], []
    for _ in range(40):
        env.step(np.array([1.0, 0.0], dtype=np.float32))
        truth.append(env.pos.copy()); eledger.append(_energy_row(env))
    truth = np.array(truth)
    # odom：伪造一条「直穿墙」的自洽航迹（恒定 +x 增量，越过 [28,29] 墙）。
    #   内部自洽 dead-reckoning（匀速直线）→ 契约 C1-3/CI 看不出；但越过声称墙 → odom_vs_map 红。
    n = len(truth)
    odom = np.array([[26.5 + i * 0.12, 20.0] for i in range(n)])   # 从 26.5 直穿到 ~31
    return truth, odom, eledger


# ====================================================================
# 场景 B2：重配「位移跨墙」真耦合（拓扑不可约）——朴素点查漏、关系型抓
#   真值 A 侧自由、odom B 侧自由（**不落墙**）、‖o-x‖≤ξ，唯位移段穿薄墙(d=0.20<ξ)。
#   见 docs/ScenB-Irreducibility.md。验「不可约性已接入常驻 audit_suite」。
# ====================================================================
def scenario_b2():
    # 取一段健康 env 行程作**干净能量账本**（物理层 EC1-EC5 绿）；几何为合成（点估计 radius=0）。
    env = EmbodiedNavEnv(slip=0.05, control_mode="A", map_type="maze")
    env.reset(seed=7)
    env.pos = np.array([20.0, 20.0]); env.theta = 0.0; env.v_act = 0.0; env.w_act = 0.0
    env.odom_pos = env.pos.copy(); env.odom_theta = 0.0
    rng = np.random.default_rng(7)
    eledger = []
    for _ in range(60):
        env.step(np.array([0.8, (rng.random() - 0.5) * 0.6], dtype=np.float32))
        eledger.append(_energy_row(env))
    n = len(eledger) + 1
    y = 10.0 + 3.0 * np.arange(n) / (n - 1)
    truth = np.column_stack([np.full(n, 29.90), y]) + np.random.default_rng(2).normal(0, 0.02, (n, 2))  # A 侧自由(诚实)
    odom = np.column_stack([np.full(n, 30.35), y]) + np.random.default_rng(3).normal(0, 0.03, (n, 2))   # B 侧自由(不落墙)
    return truth, odom, eledger


def main():
    print("Phase4b · 双态耦合压测（含物理层 EC5' + 常驻联合层）—— 判据分离收尾")
    ta, oa, la_led = scenario_a()
    rA = run_layers(ta, oa, la_led, 0.05, "场景 A · 字面穿墙幽灵（真值真穿墙）")
    a_ok = (rA["verdict"] == "PHYSICS_INTERNAL") and (not rA["ec5_prime_ok"]) and (not rA["physics_passed"])
    if a_ok:
        print("  ► 如实判定：**非真耦合**。EC5'(物理内真值-vs-声称地图)单层判红 → 物理层独力可抓，")
        print("    不需 joint。坐实「场景A=单层缺口（已由 EC5' 补上）、非耦合」。")

    tb, ob, lb_led = scenario_b()
    rB = run_layers(tb, ob, lb_led, 0.05, "场景 B · 真耦合变体（真值诚实，odom 伪造穿墙）")
    # 真耦合充要：物理层(含EC5')过 + 契约层过 + EC5' 绿(没替 joint 充数) + 唯 joint 红
    b_ok = (rB["verdict"] == "TRUE_COUPLING" and rB["physics_passed"] and rB["contract_passed"]
            and rB["ec5_prime_ok"] and (not rB["joint_ok"]))
    if b_ok:
        print("  ► 如实判定：**真耦合**。物理层(含 EC5')🟢 + 契约层 🟢 + **EC5' 绿（真值合法、未替 joint 充数）**，")
        print("    唯 joint(report×physics) 红 → 唯联合可抓。坐实「场景B=真耦合、唯 joint 抓」。")

    # —— 场景 B2：位移跨墙真耦合（拓扑不可约）—— 验「不可约性已接入常驻 audit_suite」——
    #   CI(slip-噪声 MI 通道)对此合成几何构造不适用 → run_ci=False；契约层取 C1/C2/C3。
    tb2, ob2, lb2 = scenario_b2()
    res2 = run_suite(tb2, ob2, lb2, THIN_WALL, 0.0, 0.05,
                     EmbodiedNavEnv.V_PHYS_MAX, EmbodiedNavEnv.W_PHYS_MAX, run_ci=False)
    v2 = coupling_label(res2)
    jp2 = res2["joint"]["check"]["ok"]; jr2 = res2["joint"]["relational"]["ok"]
    print(f"\n{'='*78}\n  场景 B2 · 位移跨墙真耦合（拓扑不可约，d=0.20<ξ）—— 不可约性接入常驻套件回归\n{'='*78}")
    print(format_suite(res2))
    print(f"  ── 耦合判定 ──────► {v2}")
    b2_ok = (v2 == "TRUE_COUPLING" and res2["physics"]["ok"] and res2["contract"]["ok"]
             and res2["physics"]["ec5_prime_ok"] and jp2 and (not jr2))
    if b2_ok:
        print("  ► 接入坐实：物理🟢+契约🟢+EC5'🟢+**朴素点查🟢(漏 o_t 在自由空间)**，唯**关系型🔴抓** → TRUE_COUPLING。")
        print("    常驻 audit_suite 现已覆盖『位移跨墙』拓扑不可约自欺（带地图朴素点查漏、关系型补）。")
    else:
        print(f"  ► ⚠️ 接入异常（如实报告）：verdict={v2} 朴素点查ok={jp2} 关系型ok={jr2}")

    print(f"\n{'='*78}\n  结论（判据分离、各司其职 + 不可约接入）\n{'='*78}")
    print(f"  场景A : {rA['verdict']}  EC5'={'🔴' if not rA['ec5_prime_ok'] else '🟢'} joint={'🔴' if not rA['joint_ok'] else '🟢'}"
          f"  → 物理层 EC5' 单层抓（非耦合）")
    print(f"  场景B : {rB['verdict']}  EC5'={'🟢' if rB['ec5_prime_ok'] else '🔴'} joint={'🔴' if not rB['joint_ok'] else '🟢'}"
          f"  → joint 朴素点查抓（o_t 落墙·可约形式）")
    print(f"  场景B2: {v2}  EC5'={'🟢' if res2['physics']['ec5_prime_ok'] else '🔴'} "
          f"朴素点查={'🟢漏' if jp2 else '🔴'} 关系型={'🔴抓' if not jr2 else '🟢'}"
          f"  → 唯关系型抓（位移跨墙·拓扑不可约）")
    clean = a_ok and b_ok and b2_ok
    print(f"\n  判据分离干净 + 不可约接入：{'✅ A=EC5'+chr(39)+'单层 / B=joint点查 / B2=唯关系型' if clean else '⚠️ 见上分析'}")

    json.dump({"scenario_A": rA, "scenario_B": rB,
               "scenario_B2": {"verdict": v2, "naive_point_ok": bool(jp2), "relational_ok": bool(jr2),
                               "physics_ok": bool(res2["physics"]["ok"]), "contract_ok": bool(res2["contract"]["ok"]),
                               "ec5_prime_ok": bool(res2["physics"]["ec5_prime_ok"]), "irreducible_integrated": bool(b2_ok)},
               "criteria_separated": bool(clean)},
              open(os.path.join(HERE, "coupling_summary.json"), "w"), indent=2, ensure_ascii=False)
    return clean


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
