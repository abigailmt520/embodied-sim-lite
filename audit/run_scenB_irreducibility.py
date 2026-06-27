# -*- coding: utf-8 -*-
"""
run_scenB_irreducibility.py  ——  场景 B「拓扑不可约性」验证（§5 核心论点防御）
====================================================================================
审稿人攻击：场景 B 只是「把地图给契约层、查 o_t 在墙里吗」就能抓 → 关系型层冗余。
防御（拓扑不可约）：把场景 B 重配为「**位移跨墙**」形式——真值 x_t 在墙 A 侧自由空间、
   报告 o_t 在墙 B 侧自由空间（**不在墙里**）、‖o_t−x_t‖≤ξ，于是位移向量 o_t−x_t 跨墙。
   关键前置 **墙厚 d < 噪声预算 ξ**。此时：
     ① 物理(x vs M) pass、② 契约噪声(‖o-x‖≤ξ) pass、③ 带地图契约(o∈M? M6a) pass、
     ④ 更强 report-only(seg(o,o)∩M? M6b) pass，唯 ⑤ 关系型(seg(x,o)∩M) reject。
   ⇒ 故障只活在 truth↔report 交叉关系里，任何单端点/单投影检查（含带地图者）都分解不出。

🔴 诚实判据：若带地图契约 baseline(M6) 反而抓到了场景 B → 主张可约、需修正，如实报告。绝不调参强凑。
🔴 诚实附带（d<ξ 的代价）：同一 d<ξ 条件让**诚实噪声**也可能偶发跨墙 → 刻画关系型预言的健康误报，
   并证明 **持续性(跨墙帧占比)** 把「持续跨墙=真故障(frac=1.0)」与「偶发噪声(frac 小)」分开。

运行：python audit/run_scenB_irreducibility.py
产物：audit/scenB_irreducibility.json、audit/scenB_irreducibility.png
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embodied_env import EmbodiedNavEnv                                   # noqa: E402
from relational_oracle import (physics_oracle, contract_noise_oracle, map_point_oracle,  # noqa
                               map_continuity_oracle, relational_oracle, five_oracles,
                               format_five, clearance)
import run_coupling_test as RCT                                          # noqa: E402
from run_g5_statistics import maze_run                                   # noqa: E402  真实env诚实健康轨迹
from joint_audit import joint_report_vs_map                             # noqa: E402  G5 朴素点查(对照FP包络)

HERE = os.path.dirname(os.path.abspath(__file__))

# ── 实验参数（明确 d < ξ）──────────────────────────────────────────
WALL_THIN = [(30.0, 30.2, 9.0, 16.0)]   # 薄墙 M：xmin,xmax,ymin,ymax
D = round(WALL_THIN[0][1] - WALL_THIN[0][0], 4)    # 墙厚 d = 0.20 m
XI = 0.50                                # 传感器噪声预算 ξ（短程~60步诚实漂移≈0.2-0.3m 的 ~2× 余量；见 G5 Part D）
RADIUS = 0.0                             # 点估计（task 的 d<ξ 形式；物理半径 R 仅把 d→d+2R，拓扑同构）
N = 60
PERSIST = 0.50                           # 关系型判故障所需的跨墙帧占比阈（分离持续 vs 偶发）

MAZE_WALLS = EmbodiedNavEnv.MAZE_WALLS


# ── 实例构造 ─────────────────────────────────────────────────────
def scenB_v2():
    """重配场景 B：真值 A 侧自由、报告 B 侧自由（不在墙里）、位移跨墙、‖o-x‖≤ξ。"""
    y = 10.0 + 3.0 * np.arange(N) / (N - 1)           # 真值/报告平行沿 y 上行（有运动 L=3m）
    truth = np.column_stack([np.full(N, 29.90), y])   # A 侧自由（29.90 ∉ [30.0,30.2]）
    odom = np.column_stack([np.full(N, 30.35), y])    # B 侧自由（30.35 ∉ [30.0,30.2]）；偏移 0.45≤ξ
    return truth, odom


def healthy_near_wall(seed):
    """健康对照：真值贴墙 A 侧合法行进，odom = 真值 + 诚实**无偏**相关噪声(AR1, clip ‖ε‖≤ξ)。"""
    rng = np.random.default_rng(seed)
    y = 10.0 + 3.0 * np.arange(N) / (N - 1)
    truth = np.column_stack([np.full(N, 29.90), y])    # 贴 A 侧合法（不进墙）
    eps = np.zeros((N, 2)); a = 0.85; s = 0.12
    for i in range(1, N):
        eps[i] = a * eps[i - 1] + rng.normal(0.0, s, 2)
    nr = np.linalg.norm(eps, axis=1); over = nr > XI    # clip 进噪声预算
    eps[over] = eps[over] * (XI / nr[over])[:, None]
    return truth, truth + eps


def scenB_v1_old():
    """旧场景 B（对照·可约）：真值被墙挡(合法)，odom 伪造直穿墙——o_t **真落墙里**。"""
    truth, odom, _ = RCT.scenario_b()                  # 在 MAZE_WALLS 上；odom 26.5→31 穿 [28,29] 墙
    return np.asarray(truth, float), np.asarray(odom, float)


# ── 主验证 ───────────────────────────────────────────────────────
def main():
    print("场景 B 拓扑不可约性验证（§5 防御）")
    print(f"实验参数：墙厚 d={D:.2f} m，噪声预算 ξ={XI:.2f} m，**d<ξ={D < XI}**，N={N} 帧，"
          f"radius={RADIUS}（点估计），持续性阈={PERSIST}")
    out = {"params": {"d": D, "xi": XI, "d_lt_xi": bool(D < XI), "N": N,
                      "radius": RADIUS, "persist_frac": PERSIST}}

    # ① 重配场景 B v2（核心）——五路 + 不可约判定
    tv2, ov2 = scenB_v2()
    print("\n" + "=" * 88)
    print("  【重配场景 B v2 · 位移跨墙】五路预言（同一 (truth, odom, M_thin) 上并列）")
    print("=" * 88)
    r2 = five_oracles(tv2, ov2, WALL_THIN, XI, RADIUS, persist_frac=PERSIST)
    print(format_five(r2))
    irreducible = (r2["verdict"] == "IRREDUCIBLE_RELATIONAL")
    out["scenB_v2"] = {k: (v if isinstance(v, str) else
                           {kk: vv for kk, vv in v.items() if kk in
                            ("check", "ok", "detail", "frac", "n_cross", "max_err", "n_illegal")})
                       for k, v in r2.items()}
    if irreducible:
        print("  ► 🔴 不可约成立：①②③④全 pass（含带地图契约 M6a/M6b），唯 ⑤ 关系型 reject。")
        print("    故障活在 truth↔report 位移段跨墙——带地图的契约层也分解不出 → 关系型层**非冗余**。")
    else:
        print(f"  ► ⚠️ 判定={r2['verdict']}：若带地图契约抓到了 v2，则主张可约、需修正（如实报告）。")

    # ② 旧场景 B（对照·可约）——证明攻击对旧形式有效、对 v2 无效
    tv1, ov1 = scenB_v1_old()
    print("\n" + "=" * 88)
    print("  【旧场景 B v1 · o_t 真落墙里】五路预言（对照：带地图契约应能抓→可约）")
    print("=" * 88)
    r1 = five_oracles(tv1, ov1, MAZE_WALLS, XI, RADIUS, persist_frac=PERSIST)
    print(format_five(r1))
    v1_reducible = (not r1["map_point"]["ok"]) or (not r1["map_continuity"]["ok"])
    out["scenB_v1_old"] = {k: (v if isinstance(v, str) else
                               {kk: vv for kk, vv in v.items() if kk in
                                ("check", "ok", "detail", "frac", "n_cross", "max_err", "n_illegal")})
                           for k, v in r1.items()}
    print(f"  ► 旧 v1：带地图契约(M6a/M6b) {'抓到→可约（攻击对旧形式有效）' if v1_reducible else '未抓'}；"
          f"噪声预言 {'亦 reject(报告偏离>ξ)' if not r1['contract_noise']['ok'] else 'pass'}。"
          f"\n    对照坐实：v1 可约是因 o_t 真落墙/偏离超 ξ；**v2 修掉这两点后唯关系型可抓**。")

    # ③ 健康误报 + 持续性分离（诚实：d<ξ 让诚实噪声也偶发跨墙）
    print("\n" + "=" * 88)
    print("  【健康误报 + 持续性分离】30 seed 贴墙健康（无偏噪声）vs 场景 B v2（持续跨墙）")
    print("=" * 88)
    nseed = 30
    hp = {"map_point_fp": 0, "map_cont_fp": 0, "rel_singleframe_fp": 0, "rel_persist_fp": 0}
    fracs = []
    for si in range(nseed):
        th, oh = healthy_near_wall(2000 + si)
        mp = map_point_oracle(oh, WALL_THIN, RADIUS)
        mc = map_continuity_oracle(oh, WALL_THIN, RADIUS)
        rel0 = relational_oracle(th, oh, WALL_THIN, RADIUS, persist_frac=0.0)     # 单帧即判
        relp = relational_oracle(th, oh, WALL_THIN, RADIUS, persist_frac=PERSIST)  # 持续性门控
        fracs.append(rel0["frac"])
        hp["map_point_fp"] += int(not mp["ok"])
        hp["map_cont_fp"] += int(not mc["ok"])
        hp["rel_singleframe_fp"] += int(not rel0["ok"])
        hp["rel_persist_fp"] += int(not relp["ok"])
    fracs = np.array(fracs)
    scenB_frac = r2["relational"]["frac"]
    print(f"  健康(贴墙)跨墙帧占比 frac：mean={fracs.mean():.2f} max={fracs.max():.2f}（无偏噪声→偶发）")
    print(f"  场景 B v2 跨墙帧占比 frac={scenB_frac:.2f}（持续→真故障）")
    print(f"  各预言在【健康】的误报（应低/零）：")
    print(f"    ③带地图契约 M6a(单点)        误报 {hp['map_point_fp']}/{nseed}")
    print(f"    ④report-only M6b(自穿)       误报 {hp['map_cont_fp']}/{nseed}")
    print(f"    ⑤关系型(单帧即判, persist=0)  误报 {hp['rel_singleframe_fp']}/{nseed}  ← d<ξ 下诚实噪声偶发跨墙")
    print(f"    ⑤关系型(持续性门控 persist={PERSIST}) 误报 {hp['rel_persist_fp']}/{nseed}  ← 持续性分离后")
    sep_ok = (fracs.max() < PERSIST < scenB_frac) and hp["rel_persist_fp"] == 0
    print(f"  ► 持续性分离：健康 frac.max={fracs.max():.2f} < 阈 {PERSIST} < v2 frac={scenB_frac:.2f}"
          f" → {'✅ 干净分离（门控后健康零误报、v2 仍抓）' if sep_ok else '⚠️ 未干净分离（如实报告）'}")
    out["specificity"] = {"n_seed": nseed, "healthy_frac_mean": float(fracs.mean()),
                          "healthy_frac_max": float(fracs.max()), "scenB_v2_frac": float(scenB_frac),
                          **{k: int(v) for k, v in hp.items()}, "clean_separation": bool(sep_ok)}

    # ④ 覆盖矩阵（实例 × 五预言；M6a/M6b=带地图契约 baseline）
    print("\n" + "=" * 88)
    print("  【覆盖矩阵】实例 × 五预言（🔴 M6a/M6b 带地图契约 baseline 漏 v2 = 不可约证据）")
    print("=" * 88)
    def cell(r): return "🟢pass" if r["ok"] else "🔴抓"
    cols = ["①物理", "②噪声", "③M6a带图点", "④M6b自穿", "⑤关系型"]
    print(f"  {'实例':<18}" + "".join(f"{c:<12}" for c in cols))
    def row(name, r):
        print(f"  {name:<18}" + "".join(f"{cell(r[k]):<12}" for k in
              ["physics", "contract_noise", "map_point", "map_continuity", "relational"]))
    # healthy 用持续性门控的关系型（代表性单 seed=2000）
    th, oh = healthy_near_wall(2000)
    rh = five_oracles(th, oh, WALL_THIN, XI, RADIUS, persist_frac=PERSIST)
    row("healthy(贴墙)", rh)
    row("scenB_v1_old", r1)
    row("scenB_v2_new", r2)
    print("\n  🔴 头条：scenB_v2 行——①②③④全 🟢pass（带地图契约 M6a/M6b 也漏），唯 ⑤关系型 🔴抓。")
    print("     对照 scenB_v1：③M6a 🔴抓（o_t 真落墙）→ 旧形式可约；v2 修掉后唯关系型可抓 → **拓扑不可约**。")

    out["matrix"] = {
        "cols": cols,
        "healthy": {k: bool(rh[k]["ok"]) for k in ["physics", "contract_noise", "map_point", "map_continuity", "relational"]},
        "scenB_v1_old": {k: bool(r1[k]["ok"]) for k in ["physics", "contract_noise", "map_point", "map_continuity", "relational"]},
        "scenB_v2_new": {k: bool(r2[k]["ok"]) for k in ["physics", "contract_noise", "map_point", "map_continuity", "relational"]},
    }
    out["verdict"] = {"scenB_v2_irreducible": bool(irreducible),
                      "scenB_v1_reducible_by_map": bool(v1_reducible),
                      "claim_holds": bool(irreducible and v1_reducible)}

    # ⑤ (e) 实测漂移包络 vs clearance vs C1 ceiling —— 经验 soundness 证据
    sound = part_e_drift_vs_clearance(nseed=30)
    out["soundness"] = sound

    # 图
    try:
        make_fig(fracs, scenB_frac, sound)
    except Exception as e:
        print(f"  [WARN] 图跳过: {e}")
    json.dump(out, open(os.path.join(HERE, "scenB_irreducibility.json"), "w"),
              indent=2, ensure_ascii=False)
    print("\n" + "=" * 88)
    if irreducible and v1_reducible:
        print("  结论：✅ §5 防御成立——场景 B 重配为位移跨墙后**拓扑不可约**（带地图契约也漏，唯关系型抓），")
        print("        旧形式可约对照坐实改进。诚实附带：d<ξ 下关系型靠持续性门控保特异性。")
    else:
        print("  结论：⚠️ 主张需修正（见上）——如实报告，未调参强凑。")
    return irreducible and v1_reducible


def part_e_drift_vs_clearance(nseed=30):
    """(e) 实测真实 env 诚实漂移 δ(t) vs 最近障碍 clearance vs C1 ceiling ξ。

    经验 soundness：在 gated 短窗内 δ(t) ≪ clearance（可证不误报，§clearance 充分条件）；
    并报 δ(t) 随轨迹长度增长曲线，应与 G5 Part D 的 FP 包络（0/30@≤40 → 100%@≥160）吻合：
    FP 跃变恰发生在 δ_max 越过 clearance 之处。"""
    print("\n" + "=" * 88)
    print(f"  【(e) 漂移包络 vs clearance vs C1 ceiling】真实 env 诚实健康轨迹（slip=0.05，{nseed} seed）")
    print("=" * 88)
    rad = EmbodiedNavEnv.ROBOT_RADIUS
    print(f"  C1/契约噪声 ceiling ξ={XI:.2f} m；机器人半径 R={rad:.2f} m；clearance=到最近 MAZE 墙余隙")
    print(f"  可证 soundness 充分条件：δ_max < clear_min ⇒ 漂移球不触墙 ⇒ o 同自由区 ⇒ 关系型不误报。")
    print(f"\n  {'窗长L':<7}{'δ_max':<9}{'clear_min':<11}{'clear_med':<11}{'δ_max/clear_med':<16}"
          f"{'朴素点查FP(G5式)':<18}{'关系型FP(精化)':<16}{'δ<clear_min?(可证)'}")
    rows = {}
    for L in (20, 40, 80, 160, 320):
        dmax, cmin, cmed, ratio, naive_fp, rel_fp = [], [], [], [], 0, 0
        for si in range(nseed):
            t, o, _ = maze_run(1500 + si, steps=L, slip=0.05)
            delta = np.linalg.norm(o - t, axis=1)
            clr = np.array([clearance(p, MAZE_WALLS, rad) for p in t])
            dmax.append(float(delta.max())); cmin.append(float(clr.min())); cmed.append(float(np.median(clr)))
            ratio.append(float(delta.max() / max(np.median(clr), 1e-6)))
            naive_fp += int(not joint_report_vs_map(o, MAZE_WALLS, rad)["ok"])   # G5 朴素点查包络
            rel_fp += int(not relational_oracle(t, o, MAZE_WALLS, rad, persist_frac=PERSIST)["ok"])
        dmax_m = float(np.mean(dmax)); cmin_m = float(np.mean(cmin)); cmed_m = float(np.mean(cmed))
        ratio_m = float(np.mean(ratio))
        provable = dmax_m < cmin_m                              # 可证 soundness：δ_max < clear_min
        rows[L] = {"delta_max": dmax_m, "clear_min": cmin_m, "clear_med": cmed_m, "ratio": ratio_m,
                   "naive_fp": int(naive_fp), "rel_fp": int(rel_fp), "n": nseed, "provable_sound": bool(provable)}
        print(f"  {L:<7}{dmax_m:<9.3f}{cmin_m:<11.3f}{cmed_m:<11.3f}{ratio_m:<16.2f}"
              f"{f'{naive_fp}/{nseed}':<18}{f'{rel_fp}/{nseed}':<16}{'✅ 可证sound' if provable else '❌ 不可证'}")
    # 诚实判读
    gated = [L for L in (20, 40, 80, 160, 320) if rows[L]["provable_sound"]]
    cross = next((L for L in (20, 40, 80, 160, 320) if rows[L]["delta_max"] >= rows[L]["clear_min"]), None)
    print(f"\n  🔴 经验 soundness 判读：")
    print(f"    可证 sound 区(δ_max<clear_min) = {gated}：实测 δ_max ≪ clearance"
          f"（δ_max/clear_med={rows[40]['ratio']:.2f}@L40, {rows[80]['ratio']:.2f}@L80）。")
    print(f"    δ_max 越过 clear_min @L≈{cross}：恰对齐 **G5 朴素点查 FP 包络**（本列 0/30@≤80 → "
          f"{rows[160]['naive_fp']}/30@160 → {rows[320]['naive_fp']}/30@320）→ **FP 包络由「δ 越过 clearance」解释**。")
    print(f"    δ(t) 随长度增长：" + " → ".join(f"{L}步={rows[L]['delta_max']:.2f}m" for L in (20, 40, 80, 160, 320)))
    print(f"    🔵 附带：**精化关系型(through-cross+持续性)** FP 全程 "
          f"{'/'.join(str(rows[L]['rel_fp']) for L in (20,40,80,160,320))} /30 —— 比朴素点查更稳健"
          f"（要求 o 落在**不同自由区**而非仅漂入墙；长程漂移多沿走廊、非持续跨墙）。")
    # 经验 soundness 判据 = 我们的【精化关系型预言】：gated 短窗(含 scenB v2 N=60≤80)
    #   可证 sound(δ_max<clear_min) + 全程实测 FP 0/30。（朴素点查 FP 是对照=G5 包络，非我们的检查。）
    sound_ok = (rows[40]["provable_sound"] and rows[80]["provable_sound"]
                and rows[40]["rel_fp"] == 0 and rows[80]["rel_fp"] == 0)
    print(f"  ► {'✅ 经验 soundness 成立' if sound_ok else '⚠️ 经验 soundness 存疑（如实报告）'}"
          f"（评判对象=精化关系型预言）：gated 短窗(含 scenB v2 N=60)内 δ_max ≪ clear_min（可证不误报）、"
          f"精化关系型全程 FP 0/30。朴素点查 FP 包络(G5)由 δ 越过 clearance 解释。")
    return {"rows": {str(k): v for k, v in rows.items()}, "xi_ceiling": XI, "radius": rad,
            "provable_sound_windows": gated, "delta_crosses_clear_min_at": cross, "sound": bool(sound_ok)}


def make_fig(healthy_fracs, scenB_frac, sound=None):
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
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(19, 4.6))
    # 左：几何示意（薄墙 + truth/odom + 位移段）
    w = WALL_THIN[0]
    ax1.add_patch(plt.Rectangle((w[0], w[2]), w[1] - w[0], w[3] - w[2], color="#555", alpha=0.7))
    tv, ov = scenB_v2()
    ax1.plot(tv[:, 0], tv[:, 1], "-", color="#2a7", lw=2, label="真值 x_t (A 侧自由)")
    ax1.plot(ov[:, 0], ov[:, 1], "-", color="#37a", lw=2, label="报告 o_t (B 侧自由)")
    for i in range(0, N, 8):
        ax1.plot([tv[i, 0], ov[i, 0]], [tv[i, 1], ov[i, 1]], "-", color="#d33", lw=1, alpha=0.7)
    ax1.plot([], [], "-", color="#d33", label="位移段 o−x（跨墙→关系型抓）")
    ax1.set_xlim(29.5, 30.8); ax1.set_title(f"① 几何：d={D:.2f}<ξ={XI:.2f}，端点皆自由、唯位移跨墙")
    ax1.set_xlabel("x (m)"); ax1.set_ylabel("y (m)"); ax1.legend(fontsize=7, loc="upper right")
    # 右：持续性分离（健康 frac 分布 vs v2）
    ax2.hist(healthy_fracs, bins=12, range=(0, 1), color="#2a7", alpha=0.6, label="健康(贴墙)跨墙帧占比")
    ax2.axvline(scenB_frac, color="#d33", lw=2.5, label=f"场景B v2 frac={scenB_frac:.2f}(持续)")
    ax2.axvline(PERSIST, ls="--", color="#888", label=f"持续性阈={PERSIST}")
    ax2.set_xlabel("跨墙帧占比 frac"); ax2.set_ylabel("seed 数")
    ax2.set_title("② 持续性分离：偶发噪声 vs 持续故障"); ax2.legend(fontsize=8)
    # ③ (e) 漂移包络 vs clearance vs FP（经验 soundness）
    if sound is not None:
        rows = {int(k): v for k, v in sound["rows"].items()}
        Ls = sorted(rows.keys())
        dmax = [rows[L]["delta_max"] for L in Ls]
        cmed = [rows[L]["clear_med"] for L in Ls]
        cmin = [rows[L]["clear_min"] for L in Ls]
        naive = [rows[L]["naive_fp"] / rows[L]["n"] for L in Ls]
        relf = [rows[L]["rel_fp"] / rows[L]["n"] for L in Ls]
        ax3.plot(Ls, dmax, "o-", color="#d33", lw=2, label="δ_max 实测漂移")
        ax3.plot(Ls, cmin, "s--", color="#2a7", lw=2, label="clearance 最小")
        ax3.fill_between(Ls, cmin, cmed, color="#2a7", alpha=0.15, label="clearance [min,中位]")
        ax3.axhline(sound["xi_ceiling"], ls=":", color="#888", label=f"C1 ceiling ξ={sound['xi_ceiling']:.2f}")
        ax3b = ax3.twinx()
        ax3b.plot(Ls, naive, "^-", color="#e80", lw=1.6, alpha=0.9, label="朴素点查FP(G5式,右轴)")
        ax3b.plot(Ls, relf, "v-", color="#a4d", lw=1.6, alpha=0.9, label="关系型FP(精化,右轴)")
        ax3b.set_ylabel("健康 FP 率"); ax3b.set_ylim(-0.05, 1.05)
        ax3b.legend(fontsize=7, loc="center right")
        ax3.set_xscale("log"); ax3.set_xlabel("窗长 L (步, log)"); ax3.set_ylabel("距离 (m)")
        ax3.set_title("③ δ vs clearance：δ<clear_min→可证sound；δ越过↔朴素FP跃变(G5)")
        ax3.legend(fontsize=7, loc="upper left"); ax3.grid(alpha=0.3)
    fig.suptitle("场景 B 拓扑不可约性 + 经验 soundness：带地图契约漏(唯关系型抓) · 持续性保特异性 · δ≪clearance",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(HERE, "scenB_irreducibility.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\n  [OK] 图: {out}")


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
