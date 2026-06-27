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
from energy_audit import audit_session as energy_audit                   # noqa: E402
from integrity_audit import (check_truth_odom_fork, check_seq_integrity,  # noqa: E402
                             check_feed_liveness)
from leakage_audit import ci_audit                                       # noqa: E402
from joint_audit import coupling_verdict, traj_vs_map                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WALLS = EmbodiedNavEnv.MAZE_WALLS
RADIUS = EmbodiedNavEnv.ROBOT_RADIUS
PHANTOM_IDX = 4          # 幽灵掉的墙：死亡长廊左墙 (28,29,5,33)


def _energy_row(env):
    st = env.get_render_state(); e = st["energy"]
    return {"step": st["step"], "seq": st["seq"], "E_kin": e["E_kin"], "dE": e["dE"],
            "W_act": e["W_act"], "D_damp": e["D_damp"],
            "E_contact_decl": e["E_contact_decl"], "E_contact_act": e["E_contact_act"],
            "penetration": e["penetration"], "v_act": st["v_act"], "w_act": st["w_act"]}


def _c1c2c3_session(truth, odom):
    return [{"recv_t": float(i), "seq": i, "step": i,
             "truth": {"x": float(truth[i][0]), "y": float(truth[i][1]), "theta": 0.0},
             "odom": {"x": float(odom[i][0]), "y": float(odom[i][1]), "theta": 0.0},
             "terminated": False, "truncated": False, "link_status": "online"}
            for i in range(len(truth))]


def run_layers(truth, odom, eledger, slip, tag):
    """三层独立审计 + 联合判定，返回各层 verdict。"""
    # 物理层 EC1-EC5
    phys = energy_audit(eledger, v_max=EmbodiedNavEnv.V_PHYS_MAX,
                        w_max=EmbodiedNavEnv.W_PHYS_MAX, with_collision=True)
    # 契约层 C1/C2/C3 + CI
    sess = _c1c2c3_session(truth, odom)
    c1 = check_truth_odom_fork(sess); c2 = check_seq_integrity(sess); c3 = check_feed_liveness(sess)
    ci = ci_audit(np.asarray(truth), np.asarray(odom), slip)
    contract_ok = c1["ok"] and c2["ok"] and c3["ok"] and ci["ok"]
    # 联合 report×physics
    tv, ov, verdict = coupling_verdict(truth, odom, WALLS, RADIUS)
    print(f"\n{'='*78}\n  {tag}\n{'='*78}")
    print(f"  物理层 EC1-EC5      : {'🟢 全过' if phys['passed'] else '🔴 有红'}"
          + ("" if phys["passed"] else "  " + ",".join(c["check"] for c in phys["checks"] if not c["ok"])))
    print(f"  契约层 C1/C2/C3+CI  : {'🟢 全过' if contract_ok else '🔴 有红'}"
          f"  (C1 {'🟢' if c1['ok'] else '🔴'} C2 {'🟢' if c2['ok'] else '🔴'} "
          f"C3 {'🟢' if c3['ok'] else '🔴'} CI {'🟢' if ci['ok'] else '🔴'})")
    print(f"  联合 truth_vs_map   : {'🟢 真值合法' if tv['ok'] else '🔴 真值穿墙'}")
    print(f"  联合 odom_vs_map    : {'🟢 上报合法' if ov['ok'] else '🔴 上报穿墙'}")
    print(f"  ── 联合判定 ──────► {verdict}")
    return {"physics_passed": phys["passed"], "contract_passed": contract_ok,
            "truth_vs_map_ok": tv["ok"], "odom_vs_map_ok": ov["ok"], "verdict": verdict,
            "truth_pen_locator": tv["locator"], "odom_pen_locator": ov["locator"]}


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


def main():
    print("Phase4 · 双态耦合压测（report × physics）—— 反自欺纪律压测核心论点")
    ta, oa, la_led = scenario_a()
    rA = run_layers(ta, oa, la_led, 0.05, "场景 A · 字面穿墙幽灵（真值真穿墙）")
    if rA["verdict"] == "PHYSICS_INTERNAL":
        print("  ► 如实判定：**非真耦合**。truth_vs_map 红 = 真值真穿墙 → 物理内(真值 vs 声称地图)独力可抓；")
        print("    当前 EC5 漏它仅因「信任账本 penetration（幽灵墙不在碰撞系统→报0）」= EC5 实现缺口，非耦合。")

    tb, ob, lb_led = scenario_b()
    rB = run_layers(tb, ob, lb_led, 0.05, "场景 B · 真耦合变体（真值诚实，odom 伪造穿墙）")
    if rB["verdict"] == "TRUE_COUPLING":
        print("  ► 如实判定：**真耦合**。truth_vs_map 绿（真值合法）+ 物理层过 + 契约层过，")
        print("    唯 odom_vs_map(report×physics) 红 → 既非物理内、也非契约自洽可抓，唯联合可抓。")

    print(f"\n{'='*78}\n  结论\n{'='*78}")
    print(f"  场景A 判定: {rA['verdict']}  (物理过={rA['physics_passed']}, 契约过={rA['contract_passed']})")
    print(f"  场景B 判定: {rB['verdict']}  (物理过={rB['physics_passed']}, 契约过={rB['contract_passed']})")
    true_coupling_exists = (rB["verdict"] == "TRUE_COUPLING")
    print(f"\n  「两层各自过、唯联合抓」的真耦合自欺：{'✅ 可构造（场景B）' if true_coupling_exists else '⚠️ 未能构造'}")
    print( "  「字面穿墙幽灵」：物理内(truth_vs_map)可抓 → 非真耦合（EC5 缺口），如实标注、未硬凑。")

    json.dump({"scenario_A": rA, "scenario_B": rB,
               "true_coupling_constructible": bool(true_coupling_exists)},
              open(os.path.join(HERE, "coupling_summary.json"), "w"), indent=2, ensure_ascii=False)
    return true_coupling_exists


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
