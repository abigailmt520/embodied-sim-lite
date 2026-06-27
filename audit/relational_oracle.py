# -*- coding: utf-8 -*-
"""
relational_oracle.py  ——  双态耦合「拓扑不可约性」预言机（场景 B 防御 §5）
================================================================================
背景：审稿人攻击「双态耦合不可约」主张——质疑场景 B 只是「把地图给契约层、查 o_t 是否在墙里」
      就能抓，那样关系型(联合)层就冗余。我们的防御是 **拓扑不可约**：真正的关系型故障，
      连**拿到地图的契约层**也单独抓不出——故障在**位移向量 o_t−x_t 跨墙**，而非任一端点在墙里。

五路预言（同一 (truth x, odom o, 声称地图 M) 上并列评估）：
  ① physics_oracle      : x_t vs M        —— 真值在自由空间吗（物理内）。
  ② contract_noise_oracle: ‖o_t−x_t‖ ≤ ξ  —— 上报在传感器噪声预算内吗（契约噪声自洽）。
  ③ map_point_oracle    : o_t ∈ M?        —— 🔴**带地图契约 baseline (M6a)**：上报点落墙里吗（单点查）。
  ④ map_continuity_oracle: seg(o_{t-1},o_t)∩M —— 🔴**更强 report-only baseline (M6b)**：上报**轨迹自身**穿墙吗。
  ⑤ relational_oracle   : seg(x_t,o_t)∩M  —— **关系型**：真值→上报**位移段**跨刚性墙吗（唯此为 (x,o,M) 三元联合）。

不可约充要：①②③④全 pass（各单投影合法）而唯 ⑤ reject ⇒ 故障只活在 truth↔report 交叉关系里，
            任何「单端点/单投影」检查（含带地图者）都无法分解出它。

关键前置：**墙厚 d < 噪声预算 ξ**——否则无法在噪声内把 o_t 放到墙另一侧的自由空间。

纯几何，stdlib + numpy，无 env/torch 依赖。墙 AABB 格式 (xmin, xmax, ymin, ymax)。
"""

import math

import numpy as np

PEN_FLOOR = 1e-3       # 点落墙判定下限 (m)


# --------------------------------------------------------------------
# 几何原语
# --------------------------------------------------------------------
def _point_in_aabb(p, w, radius=0.0):
    """点 p（按 radius 膨胀的圆）是否落入墙 AABB。

    radius=0（点估计）：点是否**严格在 AABB 内**（含 AABB 包含测试，零半径圆也有意义）。
    radius>0：圆心在 AABB 内，或圆心到 AABB 最近点 < radius（圆与墙重叠）。
    """
    xmin, xmax, ymin, ymax = w
    if xmin <= p[0] <= xmax and ymin <= p[1] <= ymax:
        return True                                   # 圆心/点落在墙内
    if radius <= 0.0:
        return False
    cx = min(max(p[0], xmin), xmax)
    cy = min(max(p[1], ymin), ymax)
    return math.hypot(p[0] - cx, p[1] - cy) < radius - PEN_FLOOR


def _seg_crosses_aabb(p0, p1, w, radius=0.0):
    """线段 p0→p1（按 radius 膨胀墙）是否与墙 AABB 相交（slab/Liang-Barsky 法）。"""
    xmin, xmax, ymin, ymax = w[0] - radius, w[1] + radius, w[2] - radius, w[3] + radius
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    tmin, tmax = 0.0, 1.0
    for lo, hi, o, dd in ((xmin, xmax, p0[0], dx), (ymin, ymax, p0[1], dy)):
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


def _any_point_in(traj, walls, radius):
    n = sum(1 for p in traj if any(_point_in_aabb(p, w, radius) for w in walls))
    return n


def dist_point_aabb(p, w):
    """点 p 到墙 AABB (xmin,xmax,ymin,ymax) 的欧氏距离（点在 AABB 内则 0）。"""
    dx = max(w[0] - p[0], 0.0, p[0] - w[1])
    dy = max(w[2] - p[1], 0.0, p[1] - w[3])
    return math.hypot(dx, dy)


def clearance(p, walls, radius=0.0):
    """点 p（机器人圆半径 radius）到最近墙的**自由余隙**（贴墙=0，越大越安全）。

    经验 soundness 充分条件：若漂移 δ(t)=‖o_t−x_t‖ < clearance(x_t)，则 o_t 落在不触墙的开球
    B(x_t, clearance) 内 → o_t 与 x_t 同处一个自由连通区、位移段全程在球内不穿墙 →
    关系型预言**可证不误报**。故 δ ≪ clearance 即经验 soundness 的直接证据。
    """
    return min(dist_point_aabb(p, w) for w in walls) - radius


def _result(check, ok, detail, **extra):
    r = {"check": check, "status": "GREEN" if ok else "RED", "ok": bool(ok), "detail": detail}
    r.update(extra)
    return r


# --------------------------------------------------------------------
# 五路预言
# --------------------------------------------------------------------
def physics_oracle(truth, walls, radius=0.0):
    """① 物理内：真值位置是否全程在自由空间（不落墙）。"""
    n = _any_point_in(np.asarray(truth, float), walls, radius)
    return _result("PHYSICS[x∈free]", n == 0,
                   f"真值落墙帧={n}（应 0=合法）", n_illegal=n)


def contract_noise_oracle(truth, odom, xi):
    """② 契约噪声自洽：max_t ‖o_t−x_t‖ ≤ ξ（上报在传感器噪声预算内）。"""
    t = np.asarray(truth, float); o = np.asarray(odom, float)
    e = np.linalg.norm(o - t, axis=1)
    emax = float(e.max())
    return _result("CONTRACT_NOISE[‖o-x‖≤ξ]", emax <= xi,
                   f"max‖o-x‖={emax:.3f} {'≤' if emax <= xi else '>'} ξ={xi:.3f}",
                   max_err=emax, xi=float(xi))


def map_point_oracle(odom, walls, radius=0.0):
    """③ 🔴 带地图契约 baseline (M6a)：上报点 o_t 是否落墙里（单点查地图）。"""
    n = _any_point_in(np.asarray(odom, float), walls, radius)
    return _result("MAP_POINT[o∈M? · M6a]", n == 0,
                   f"上报点落墙帧={n}（>0 才能抓；=0=漏）", n_illegal=n)


def map_continuity_oracle(odom, walls, radius=0.0):
    """④ 🔴 更强 report-only baseline (M6b)：上报**轨迹自身**段 seg(o_{t-1},o_t) 是否穿墙。"""
    o = np.asarray(odom, float)
    cross = [i for i in range(len(o) - 1)
             if any(_seg_crosses_aabb(o[i], o[i + 1], w, radius) for w in walls)]
    return _result("MAP_CONTINUITY[seg(o,o)∩M · M6b]", len(cross) == 0,
                   f"上报轨迹自穿墙段={len(cross)}（>0 才能抓；=0=漏）", n_cross=len(cross))


def relational_oracle(truth, odom, walls, radius=0.0, persist_frac=0.0):
    """⑤ 关系型：seg(x_t,o_t) 是否**穿透**刚性墙（真值→上报位移段；(x,o,M) 三元联合）。

    **through-crossing** = 两端点皆在自由空间（x_t,o_t 都不在墙里）**而位移段穿过墙**——
    即真值与上报落在被刚性墙隔开的**不同自由连通区**（拓扑错位）。这是真正的关系型故障：
      - 端点皆自由 → 物理(x)、带地图契约(o∈M?) 各自皆 pass；
      - 仅「连接两自由区的位移段穿墙」可抓 → (x,o,M) 三元不可分解。
    （仅「o 落墙里」归 map_point；仅 x 落墙归 physics——故此处要求两端点皆自由，纯取关系型分量。）

    persist_frac：判 reject 所需的最小穿墙帧占比（分离「持续穿透=真故障 frac→1」与
                  「偶发噪声穿透=健康 frac 小」；=0 则单帧即判，作纯几何不可约见证）。
    """
    t = np.asarray(truth, float); o = np.asarray(odom, float)
    n = len(t)
    cross = []
    for i in range(n):
        x_free = not any(_point_in_aabb(t[i], w, radius) for w in walls)
        o_free = not any(_point_in_aabb(o[i], w, radius) for w in walls)
        seg = any(_seg_crosses_aabb(t[i], o[i], w, radius) for w in walls)
        if x_free and o_free and seg:                 # 端点皆自由 + 位移段穿墙 = 拓扑错位
            cross.append(i)
    frac = len(cross) / n if n else 0.0
    reject = frac > persist_frac
    first = cross[0] if cross else None
    return _result("RELATIONAL[seg(x,o)穿M·端点皆自由]", not reject,
                   f"位移段穿墙(端点皆自由)帧={len(cross)}/{n} (frac={frac:.2f}"
                   + (f" >阈{persist_frac:.2f}→抓" if reject else f" ≤阈{persist_frac:.2f}→放行")
                   + ")", n_cross=len(cross), frac=float(frac), first_cross=first)


def five_oracles(truth, odom, walls, xi, radius=0.0, persist_frac=0.0):
    """同一 (truth, odom, walls) 上跑全部五路，返回 {name: result} + 不可约判定。"""
    res = {
        "physics": physics_oracle(truth, walls, radius),
        "contract_noise": contract_noise_oracle(truth, odom, xi),
        "map_point": map_point_oracle(odom, walls, radius),       # M6a
        "map_continuity": map_continuity_oracle(odom, walls, radius),  # M6b
        "relational": relational_oracle(truth, odom, walls, radius, persist_frac),
    }
    # 不可约：①②③④ pass 而唯 ⑤ reject
    singles_pass = (res["physics"]["ok"] and res["contract_noise"]["ok"]
                    and res["map_point"]["ok"] and res["map_continuity"]["ok"])
    only_relational = singles_pass and (not res["relational"]["ok"])
    if only_relational:
        verdict = "IRREDUCIBLE_RELATIONAL"          # 唯关系型抓 → 拓扑不可约（防御成立）
    elif (not res["map_point"]["ok"]) or (not res["map_continuity"]["ok"]):
        verdict = "REDUCIBLE_BY_MAP_CONTRACT"        # 带地图契约也抓 → 可约（主张需修正）
    elif res["relational"]["ok"]:
        verdict = "NO_VIOLATION"                     # 五路皆 pass
    else:
        verdict = "OTHER"
    res["verdict"] = verdict
    return res


def format_five(res, title=""):
    order = [("①物理 x∈free", "physics"), ("②契约噪声 ‖o-x‖≤ξ", "contract_noise"),
             ("③带地图契约 o∈M? (M6a)", "map_point"), ("④report-only seg(o,o)∩M (M6b)", "map_continuity"),
             ("⑤关系型 seg(x,o)∩M", "relational")]
    lines = [title] if title else []
    for label, key in order:
        r = res[key]
        mark = "🟢 pass" if r["ok"] else "🔴 reject"
        lines.append(f"    [{mark}] {label:<30} └ {r['detail']}")
    lines.append(f"    ── 判定 ──► {res['verdict']}")
    return "\n".join(lines)
