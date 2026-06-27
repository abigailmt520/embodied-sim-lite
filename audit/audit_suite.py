# -*- coding: utf-8 -*-
"""
audit_suite.py  ——  常驻三层审计套件（契约 / 物理 / 联合）
==========================================================
把各层审计固化为并列的常驻套件，供运行时统一调用：

  契约层 (report 自洽)         : C1 真分叉 / C2 帧序单调 / C3 断流即冻结 / CI 互信息泄漏
  物理层 (physics 自洽)        : EC1 能量预算 / EC2 无凭空能量 / EC3 执行器上限 /
                                 EC4 碰撞非负 / EC5 非穿透(账本) / **EC5' 真值-vs-地图(物理内几何重算)**
  联合层 (report×physics 跨态) : JOINT odom-vs-声称地图（上报轨迹对照物理地图）

层职责分离（Phase4 + 本次 EC5' 收尾）：
  - EC5'（物理内）抓「真值真穿墙」——含碰撞检测剔除墙（幽灵墙）使账本 penetration=0 的 EC5 缺口。
  - JOINT（跨态）抓「真值合法但 odom 伪造穿墙」——真耦合，物理内/契约自洽皆不可抓。
  判据分离：truth_vs_map(EC5') 红 ⇒ 物理内单层可抓（非耦合）；EC5' 绿 ∧ JOINT 红 ⇒ 真耦合。
"""

import numpy as np

from energy_audit import audit_session as _energy_audit
from integrity_audit import (check_truth_odom_fork, check_seq_integrity, check_feed_liveness)
from leakage_audit import ci_audit
from joint_audit import ec5_prime, joint_report_vs_map


def _c1c2c3_session(truth, odom):
    return [{"recv_t": float(i), "seq": i, "step": i,
             "truth": {"x": float(truth[i][0]), "y": float(truth[i][1]), "theta": 0.0},
             "odom": {"x": float(odom[i][0]), "y": float(odom[i][1]), "theta": 0.0},
             "terminated": False, "truncated": False, "link_status": "online"}
            for i in range(len(truth))]


def run_suite(truth_traj, odom_traj, ledger, walls, radius, slip,
              v_max, w_max, run_ci=True):
    """跑常驻三层套件，返回 {contract, physics, joint} 各层结果 + 总判定。

    ledger: 逐帧能量/碰撞账本（供 EC1-EC5）。walls/radius: 声称地图几何（供 EC5'/JOINT）。
    """
    truth = np.asarray(truth_traj, dtype=np.float64)
    odom = np.asarray(odom_traj, dtype=np.float64)

    # —— 契约层 ——
    sess = _c1c2c3_session(truth, odom)
    contract_checks = [check_truth_odom_fork(sess), check_seq_integrity(sess),
                       check_feed_liveness(sess)]
    if run_ci:
        contract_checks.append(ci_audit(truth, odom, slip))
    contract_ok = all(c["ok"] for c in contract_checks)

    # —— 物理层：EC1-EC5（账本）+ EC5'（物理内真值-vs-地图几何）——
    ec15 = _energy_audit(ledger, v_max=v_max, w_max=w_max, with_collision=True)
    ec5p = ec5_prime(truth, walls, radius)
    physics_checks = ec15["checks"] + [ec5p]
    physics_ok = ec15["passed"] and ec5p["ok"]

    # —— 联合层：odom-vs-声称地图 ——
    joint = joint_report_vs_map(odom, walls, radius)
    joint_ok = joint["ok"]

    return {
        "contract": {"ok": contract_ok, "checks": contract_checks},
        "physics": {"ok": physics_ok, "checks": physics_checks,
                    "ec5_prime_ok": ec5p["ok"], "ec5_prime": ec5p},
        "joint": {"ok": joint_ok, "check": joint},
    }


def format_suite(res, title=""):
    lines = [title] if title else []
    def layer(tag, ok):
        return f"  {tag:<26}: {'🟢 全过' if ok else '🔴 有红'}"
    lines.append(layer("契约层 C1/C2/C3+CI", res["contract"]["ok"]))
    for c in res["contract"]["checks"]:
        lines.append(f"      [{'🟢' if c['ok'] else '🔴'}] {c['check']}")
    lines.append(layer("物理层 EC1-EC5+EC5'", res["physics"]["ok"]))
    for c in res["physics"]["checks"]:
        mk = '🟢' if c['ok'] else '🔴'
        lines.append(f"      [{mk}] {c['check']}"
                     + ("" if c["ok"] else f"  └ {c['detail']}"))
    j = res["joint"]["check"]
    lines.append(layer("联合层 JOINT odom-vs-map", res["joint"]["ok"])
                 + ("" if res["joint"]["ok"] else f"  └ {j['detail']}"))
    return "\n".join(lines)


def coupling_label(res):
    """据三层结果给耦合判定。EC5' 红=物理内可抓(非耦合); EC5'绿∧JOINT红=真耦合。"""
    ec5p_ok = res["physics"]["ec5_prime_ok"]
    joint_ok = res["joint"]["ok"]
    if not ec5p_ok:
        return "PHYSICS_INTERNAL"     # 真值真穿墙：物理内 EC5' 单层可抓 → 非真耦合
    if not joint_ok:
        return "TRUE_COUPLING"        # 真值合法、唯上报非法 → 唯联合可抓 → 真耦合
    return "NO_VIOLATION"
