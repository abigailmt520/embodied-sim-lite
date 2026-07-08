# -*- coding: utf-8 -*-
"""
record_fork.py  ——  阶段 0 · DoD-1 真分叉证据记录器（instrumentation，非功能代码）
=================================================================================
目的：以 headless 方式驱动 embodied_env 一个回合长度（500 步）的轨迹，分别在
      slip=0（before / 对照）与 slip=SLIP_FACTOR（after / 真打滑）下，逐帧记录
      真值(Truth) 与 里程计(Odom) 位姿，计算累积位置误差，导出 CSV 并绘制 before/after
      误差-时间曲线。

方法学（为何可复现、为何不是 hardcode 假曲线，对应 INV-2）：
  - 控制器：开环「定曲率」动作 [v=0.6, w=0.25]，全程恒定 → 真值轨迹为一个有界圆，
    可复现且与策略无关（漂移特性刻画的标准做法：驱动已知轨迹、比较真值 vs 航迹推算）。
  - 贯穿固定 500 步、**不因 terminated/truncated 提前复位**：复位会把里程计重新标定、
    误差归零，无法呈现连续累积曲线；定曲率真值有界，不会因忽略碰撞而跑飞。
  - before/after 用**同一随机种子 + 同一控制器**，唯一变量是 slip 系数（一次只动一个变量）。
  - 误差全部来自 env 内部真实的打滑积分过程（带种子的 self.np_random），本脚本不注入任何数字。

产物：
  diagnostics/fork_before.csv      slip=0 逐帧数据（误差恒 0.000000）
  diagnostics/fork_after.csv       slip=0.05 逐帧数据（误差非零、随时间增长）
  diagnostics/fork_error_curve.png before/after 误差-时间对照曲线

运行：python diagnostics/record_fork.py
"""

import csv
import os
import sys

import numpy as np

# 允许从 diagnostics/ 子目录直接运行（把仓库根加入 import 路径）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from embodied_env import EmbodiedNavEnv  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 7

# —— 论文截图模式(--paper)的中文字体:按平台自动探测,找不到只警告(与 tools/paper_figures 一致)——
CJK_FONT_FILES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
]
CJK_FONT_NAMES = ["Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei",
                  "PingFang SC", "Noto Sans CJK JP", "Hiragino Sans GB", "Arial Unicode MS"]


def _setup_cjk_font(plt, font_manager):
    for path in CJK_FONT_FILES:
        if os.path.exists(path):
            try:
                font_manager.fontManager.addfont(path)
            except Exception:
                pass
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = [n for n in CJK_FONT_NAMES if n in available]
    if not chosen:
        print("  [WARN] 未找到中文字体,论文模式图中中文可能显示为方框。")
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = chosen + plt.rcParams["font.sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
STEPS = EmbodiedNavEnv.MAX_STEPS          # 一个回合长度 = 500 步
ACTION = np.array([0.6, 0.25], dtype=np.float32)  # 开环定曲率：真实 v=0.6 m/s, w=0.375 rad/s


def record(slip):
    """跑一个 STEPS 步的固定轨迹，返回逐帧记录 list[dict]。"""
    env = EmbodiedNavEnv(slip=slip)
    env.reset(seed=SEED)
    rows = []
    for i in range(STEPS):
        env.step(ACTION)
        err_xy = float(np.linalg.norm(env.pos - env.odom_pos))
        dyaw = (env.theta - env.odom_theta + np.pi) % (2 * np.pi) - np.pi
        rows.append({
            "step": env.step_count,
            "t_s": round(env.step_count * env.DT, 3),
            "truth_x": round(float(env.pos[0]), 6),
            "truth_y": round(float(env.pos[1]), 6),
            "truth_theta": round(float(env.theta), 6),
            "odom_x": round(float(env.odom_pos[0]), 6),
            "odom_y": round(float(env.odom_pos[1]), 6),
            "odom_theta": round(float(env.odom_theta), 6),
            "err_xy": round(err_xy, 6),
            "err_yaw_deg": round(float(np.degrees(dyaw)), 4),
        })
    return rows


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def metrics(rows):
    err = np.array([r["err_xy"] for r in rows])
    return {
        "ATE_RMSE": float(np.sqrt(np.mean(err ** 2))),
        "final_err": float(err[-1]),
        "max_err": float(err.max()),
        "mean_err": float(err.mean()),
        "final_yaw_drift_deg": float(rows[-1]["err_yaw_deg"]),
    }


def main(paper=False):
    before = record(slip=0.0)
    after = record(slip=EmbodiedNavEnv.SLIP_FACTOR)

    write_csv(before, os.path.join(HERE, "fork_before.csv"))
    write_csv(after, os.path.join(HERE, "fork_after.csv"))

    mb, ma = metrics(before), metrics(after)
    print("=" * 68)
    print(f"  真分叉记录 · 种子={SEED} · 步数={STEPS} · 动作={ACTION.tolist()} (开环定曲率)")
    print("=" * 68)
    print(f"  {'指标':<22}{'before(slip=0)':>20}{'after(slip=0.05)':>22}")
    print(f"  {'ATE_RMSE (m)':<22}{mb['ATE_RMSE']:>20.6f}{ma['ATE_RMSE']:>22.6f}")
    print(f"  {'最终位置误差 (m)':<20}{mb['final_err']:>20.6f}{ma['final_err']:>22.6f}")
    print(f"  {'最大位置误差 (m)':<20}{mb['max_err']:>20.6f}{ma['max_err']:>22.6f}")
    print(f"  {'最终朝向漂移 (deg)':<19}{mb['final_yaw_drift_deg']:>20.4f}{ma['final_yaw_drift_deg']:>22.4f}")
    print("=" * 68)
    # 抽样几帧，肉眼可见 after 的 err_xy 单调增长、before 恒 0
    print("  采样帧 (step | before.err_xy | after.err_xy):")
    for k in (50, 100, 200, 300, 400, 500):
        b = before[k - 1]["err_xy"]
        a = after[k - 1]["err_xy"]
        print(f"    step {k:>4} | {b:>12.6f} | {a:>12.6f}")

    # ---- 绘图 ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        tb = [r["t_s"] for r in before]
        eb = [r["err_xy"] for r in before]
        ta = [r["t_s"] for r in after]
        ea = [r["err_xy"] for r in after]

        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(tb, eb, label="before  (slip=0.00) — Truth ≡ Odom, err ≡ 0", color="#2c7", lw=2)
        ax.plot(ta, ea, label="after   (slip=0.05) — real drift, err grows", color="#d33", lw=2)
        ax.set_xlabel("time (s)")
        ax.set_ylabel("cumulative position error |Truth - Odom|  (m)")
        ax.set_title("Embodied-SimLite | Stage-0 Truth-vs-Odom true fork (DoD-1)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left")
        out = os.path.join(HERE, "fork_error_curve.png")
        fig.tight_layout()
        fig.savefig(out, dpi=130)
        print(f"\n  [OK] 误差曲线已保存: {out}")

        # ---- 论文截图模式(--paper):大字号中文版,供论文图 3(期刊单栏约 8cm 印刷)----
        #      加粗线宽、放大坐标轴/图例字号,并标注两条要点(论文 v1.1 图 3 题注口径)
        if paper:
            _setup_cjk_font(plt, matplotlib.font_manager)
            figp, axp = plt.subplots(figsize=(8, 5))
            axp.plot(tb, eb, label="slip = 0(对照)", color="#2c7", lw=3.5)
            axp.plot(ta, ea, label="slip = 0.05(真打滑)", color="#d33", lw=3.5)
            axp.set_xlabel("时间 / s", fontsize=17)
            axp.set_ylabel("累积位置误差 |Truth − Odom| / m", fontsize=17)
            axp.tick_params(labelsize=14)
            axp.grid(True, alpha=0.3)
            axp.legend(loc="center left", fontsize=15)
            axp.annotate("slip=0 退化为真值(误差恒为 0)",
                         xy=(ta[len(ta)//2], 0), xytext=(ta[len(ta)//6], max(ea)*0.18),
                         fontsize=15, color="#1a7a50",
                         arrowprops=dict(arrowstyle="->", color="#1a7a50", lw=1.8))
            axp.annotate("slip>0 误差随真实行程增长",
                         xy=(ta[int(len(ta)*0.8)], ea[int(len(ea)*0.8)]),
                         xytext=(ta[int(len(ta)*0.3)], max(ea)*0.82),
                         fontsize=15, color="#a02020",
                         arrowprops=dict(arrowstyle="->", color="#a02020", lw=1.8))
            outp = os.path.join(HERE, "fork_error_curve_paper.png")
            figp.tight_layout()
            figp.savefig(outp, dpi=300)
            print(f"  [OK] 论文图 3(大字号中文版)已保存: {outp}")
    except Exception as e:  # matplotlib 缺失时降级为仅 CSV（PRD 允许 PNG 或可绘图 CSV）
        print(f"\n  [WARN] 绘图跳过（{e}）；CSV 已生成，可自行绘图。")

    print(f"  [OK] CSV: {os.path.join(HERE, 'fork_before.csv')}")
    print(f"  [OK] CSV: {os.path.join(HERE, 'fork_after.csv')}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="真分叉记录器(before/after 误差曲线)")
    ap.add_argument("--paper", action="store_true",
                    help="论文截图模式:额外输出大字号中文版 fork_error_curve_paper.png(论文图 3)")
    main(paper=ap.parse_args().paper)
