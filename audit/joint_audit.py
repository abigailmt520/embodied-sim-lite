# -*- coding: utf-8 -*-
"""
joint_audit.py  ——  Phase4 · report×physics 联合交叉核对（轨迹 vs 声称物理地图）
==================================================================================
不变量（跨态）：一条上报轨迹上的每个位置，都必须在**声称物理地图**里合法可达——
        机器人圆不得落入任何声称墙体的 AABB 内。违反 = 上报了「物理上不可能到达」的位置。

🔴 关键判别（本模块为耦合压测服务，诚实第一）：
    本检查可作用于两种轨迹，二者区分「真耦合」与「仅 EC5 实现缺口」：
      - truth_vs_map（真值轨迹 vs 地图）：纯**物理内**检查（真值与地图都在物理侧），
        不需上报通道。若它判红，则该自欺**物理层独力可抓**（应属一个完善的 EC5），
        **不构成 report×physics 真耦合**。
      - odom_vs_map（上报轨迹 vs 地图）：**report×physics 跨态**检查（odom 来自契约、地图来自物理）。
    真耦合的充要刻画：**truth_vs_map 绿（物理真值合法）而 odom_vs_map 红（上报非法）**——
    此时既非物理内可抓、也非契约自洽可抓，唯 report×物理地图 联合可抓。

纯几何，无 env/torch 依赖；消费 (轨迹 positions, 声称 walls AABB, 半径)。
"""

import math

PEN_FLOOR = 1e-3       # 轨迹-地图穿透判红下限 (m)：超过即「落在墙内」


def _circle_aabb_pen(pos, walls, radius):
    """圆心 pos 对 walls 的最大穿透深度（落在墙内为正）。"""
    max_pen = 0.0
    for wx1, wx2, wy1, wy2 in walls:
        cx = min(max(pos[0], wx1), wx2)
        cy = min(max(pos[1], wy1), wy2)
        d = math.hypot(pos[0] - cx, pos[1] - cy)
        if d < radius:
            max_pen = max(max_pen, radius - d)
    return max_pen


def traj_vs_map(traj, walls, radius, label="traj"):
    """对一条轨迹跑「轨迹-地图非穿透」检查，返回 result。"""
    worst, worst_i = 0.0, None
    n_illegal = 0
    for i, p in enumerate(traj):
        pen = _circle_aabb_pen(p, walls, radius)
        if pen > PEN_FLOOR:
            n_illegal += 1
            if pen > worst:
                worst, worst_i = pen, i
    name = f"JOINT_TRAJ_VS_MAP[{label}]"
    desc = f"{label} 轨迹是否全程在声称地图内合法可达"
    if worst_i is not None:
        return {"check": name, "desc": desc, "status": "RED", "ok": False,
                "detail": f"{label} 上报位置落入声称墙内：{n_illegal} 帧非法，最深穿透 "
                          f"{worst:.3f} m @帧{worst_i}（物理上不可能合法到达）",
                "locator": {"first_illegal_frame": worst_i, "n_illegal_frames": n_illegal,
                            "max_penetration_m": round(worst, 4),
                            "pos": [round(float(traj[worst_i][0]), 3), round(float(traj[worst_i][1]), 3)]}}
    return {"check": name, "desc": desc, "status": "GREEN", "ok": True,
            "detail": f"{label} 轨迹全程在声称地图内合法（无落墙）", "locator": None}


def ec5_prime(truth_traj, walls, radius):
    """EC5'（物理层）：物理内「真值-vs-声称地图几何」重算非穿透。

    **不信任账本的 penetration 字段**——直接用真值位置对照**声称全地图**几何独立判定。
    故能抓「碰撞检测剔除墙（幽灵墙）使账本 penetration=0」的 EC5 缺口（真值真在墙内）。
    纯物理内检查（真值与地图皆物理侧），不需上报通道。
    """
    r = traj_vs_map(truth_traj, walls, radius, "truth")
    r["check"] = "EC5P_TRUTH_MAP"
    r["desc"] = "EC5'：真值位置是否未落入声称地图墙内（物理内几何重算，不信任账本）"
    return r


def joint_report_vs_map(odom_traj, walls, radius):
    """联合层（report×physics）：上报轨迹（odom）-vs-声称地图几何 非穿透。

    odom 来自契约、地图来自物理 → 跨态检查。抓「真值合法但上报伪造穿墙航迹」的真耦合
    （此类既非物理内（真值合法 EC5' 绿）、也非契约自洽（odom 自洽 C1-3/CI 绿）可抓）。
    """
    r = traj_vs_map(odom_traj, walls, radius, "odom")
    r["check"] = "JOINT_ODOM_MAP"
    r["desc"] = "联合：上报(odom)位置是否未落入声称地图墙内（report×physics 跨态）"
    return r


def coupling_verdict(truth_traj, odom_traj, walls, radius):
    """耦合压测核心判定：返回 (truth_vs_map, odom_vs_map, verdict_str)。

    verdict：
      'TRUE_COUPLING'  —— truth_vs_map 绿 且 odom_vs_map 红：唯 report×physics 联合可抓（真耦合）。
      'PHYSICS_INTERNAL' —— truth_vs_map 红：物理内（真值vs地图）独力可抓 → 非真耦合（EC5 缺口）。
      'NO_VIOLATION'   —— 二者皆绿：无穿墙违反。
    """
    tv = traj_vs_map(truth_traj, walls, radius, "truth")
    ov = traj_vs_map(odom_traj, walls, radius, "odom")
    if not tv["ok"]:
        verdict = "PHYSICS_INTERNAL"
    elif not ov["ok"]:
        verdict = "TRUE_COUPLING"
    else:
        verdict = "NO_VIOLATION"
    return tv, ov, verdict
