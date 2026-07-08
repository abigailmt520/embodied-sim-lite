# -*- coding: utf-8 -*-
"""
make_paper_figures.py  ——  论文《面向具身智能的系统审计素养培养实践》图表复现脚本
==================================================================================
一键复现论文 v1.1 的四幅统计图(与论文编号一一对应):
    图4  fig4_ppo_eval.png          PPO 导航策略量化评测(25 张随机地图)
    图5  fig5_cpu_compare.png       同等 SLAM/导航任务下教学终端 CPU 占用对比
    图7  fig7_attainment_trend.png  前三届三学期课程达成度趋势
    图8  fig8_dimension_compare.png GR5.2/GR9.2 维度对比(跨届稳定性 vs 波动)

所有数据取自论文正文与表 2,集中在下方【数据常量区】;更新教学数据时只改常量即可再生图表。

用法:
    python tools/paper_figures/make_paper_figures.py [--outdir DIR] [--dpi N] [--eval-json FILE]
    --outdir     输出目录,默认 ./figs_out
    --dpi        输出分辨率,默认 200(论文投稿建议 300)
    --eval-json  评测汇总 JSON(audit/run_action1.py 产出的 eval_summary.json);
                 提供时图 4 从实测数据生成,不提供时使用下方内嵌常量
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ============================================================
# 数据常量区(全部取自论文 v1.1 正文与表 2,更新数据只改这里)
# ============================================================
# 图4:PPO 策略 25 张随机地图评测(论文 3.3;可被 --eval-json 实测数据覆盖)
FIG4_EVAL = {"n_maps": 25, "episodes_per_map": 1,
             "counts": {"success": 21, "collision": 3, "timeout": 1}}

# 图5:同等 SLAM 建图与导航任务下教学终端 CPU 占用(论文 1.3/3.1 实测)
FIG5_GAZEBO_CPU = (75, 100)     # Gazebo 三维方案实测区间 %
FIG5_SIMLITE_CPU = 3            # 本平台约 3%

# 图7:前三届三学期达成度趋势(论文表 2)
FIG7_SEMESTERS = ["第一学期\n(硬件本体)", "第二学期\n(仿真验证)", "第三学期\n(具身进阶)"]
FIG7_ATTAINMENT = {"G1": [0.915, 0.872, 0.905],
                   "G2": [0.890, 0.918, 0.873],
                   "G3": [0.914, 0.896, 0.896]}
FIG7_THRESHOLD = 0.65           # 合格阈值

# 图8:GR5.2(工具运用)跨届稳定 vs GR9.2(团队协作)波动显著(论文 4.2)
FIG8_GROUPS = ["第二学期\nGR5.2(工具)", "第三学期\nGR5.2(工具)", "第二学期\nGR9.2(协作)"]
FIG8_VALUES = {"G1": [0.915, 0.905, 0.745],
               "G2": [0.927, 0.913, 0.915],
               "G3": [0.922, 0.878, 0.860]}

# ============================================================
# 中文字体:按平台自动探测的回退链,找不到时警告而非报错
# ============================================================
FONT_FALLBACK_CHAIN = ["Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei",
                       "PingFang SC", "Noto Sans CJK JP"]
# 各平台常见中文字体文件,先注册再按名探测(macOS 额外兜底 Hiragino/Arial Unicode)
KNOWN_FONT_FILES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",       # Linux (Noto)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",                           # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",                                    # Windows 微软雅黑
]
EXTRA_FALLBACKS = ["Hiragino Sans GB", "Arial Unicode MS"]


def setup_cjk_font():
    for path in KNOWN_FONT_FILES:
        if os.path.exists(path):
            try:
                font_manager.fontManager.addfont(path)
            except Exception:
                pass
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = [n for n in FONT_FALLBACK_CHAIN + EXTRA_FALLBACKS if n in available]
    if chosen:
        print(f"[字体] 使用中文字体: {chosen[0]}")
    else:
        print("[警告] 未找到可用中文字体(回退链: "
              f"{', '.join(FONT_FALLBACK_CHAIN)}),图中中文可能显示为方框。")
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = chosen + plt.rcParams["font.sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.size"] = 13


# 色盲友好且黑白印刷可辨(配合线型/填充图案)
C_G1, C_G2, C_G3 = "#4477AA", "#EE7733", "#777777"


# ============================================================
# 图4  PPO 导航策略量化评测(水平条形图,黑白印刷友好)
#      画布纵横比与论文原图 (779x647) 一致
# ============================================================
def fig4(outdir, dpi, eval_data):
    n = eval_data["n_maps"] * eval_data["episodes_per_map"]
    cnt = eval_data["counts"]
    cats = ["超时", "碰撞", "成功"]
    keys = ["timeout", "collision", "success"]
    vals = [cnt[k] / n * 100 for k in keys]
    counts = [f"{cnt[k]}/{n}" for k in keys]
    colors = ["#BBBBBB", "#EE7733", "#4477AA"]
    hatch = ["..", "//", ""]
    fig, ax = plt.subplots(figsize=(7.0, 5.81), dpi=dpi)
    bars = ax.barh(cats, vals, color=colors, edgecolor="black", height=0.55)
    for b, h in zip(bars, hatch):
        b.set_hatch(h)
    for b, v, c in zip(bars, vals, counts):
        ax.text(v + 1.5, b.get_y() + b.get_height()/2,
                f"{v:.0f}%  ({c})", va="center", fontsize=14)
    ax.set_xlim(0, 100)
    ax.set_xlabel("占比 / %", fontsize=14)
    ax.set_title(f"PPO 策略 {eval_data['n_maps']} 张随机地图评测结果"
                 f"(每图 {eval_data['episodes_per_map']} 回合,N={n})",
                 fontsize=14, pad=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", ls=":", alpha=0.5)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(f"{outdir}/fig4_ppo_eval.png")
    plt.close(fig)


# ============================================================
# 图5  同等 SLAM 建图与导航任务下教学终端 CPU 占用对比
#      纵横比与论文原图 (1248x723) 一致
# ============================================================
def fig5(outdir, dpi):
    fig, ax = plt.subplots(figsize=(7.5, 4.34), dpi=dpi)
    x = [0, 1]
    # Gazebo: 用区间中点作柱高,误差线标出实测区间
    gz_lo, gz_hi = FIG5_GAZEBO_CPU
    gz_mid = (gz_lo + gz_hi) / 2
    ax.bar(0, gz_mid, width=0.45, color="#EE7733", edgecolor="black",
           yerr=[[gz_mid-gz_lo], [gz_hi-gz_mid]], capsize=8,
           error_kw=dict(lw=1.5))
    ax.bar(1, FIG5_SIMLITE_CPU, width=0.45, color="#4477AA", edgecolor="black")
    ax.text(0, gz_hi + 3, f"{gz_lo}%~{gz_hi}%\n(常伴卡顿)", ha="center", fontsize=13)
    ax.text(1, FIG5_SIMLITE_CPU + 3, f"约 {FIG5_SIMLITE_CPU}%", ha="center", fontsize=13)
    ax.set_xticks(x)
    ax.set_xticklabels(["Ubuntu+ROS 2+Gazebo\n三维方案", "Embodied-SimLite\n(本平台)"],
                       fontsize=13)
    ax.set_ylabel("CPU 占用率 / %", fontsize=14)
    ax.set_ylim(0, 115)
    ax.set_title("同等 SLAM 建图与自主导航任务·普通教学终端实测", fontsize=14, pad=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", ls=":", alpha=0.5)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(f"{outdir}/fig5_cpu_compare.png")
    plt.close(fig)


# ============================================================
# 图7  前三届三学期课程达成度趋势(数据=表2)
#      纵轴 0.60 起并标注,合格阈值 0.65 以虚线显式画出,
#      规避截断纵轴夸大波动的问题;纵横比与论文原图 (1131x628) 一致
# ============================================================
def fig7(outdir, dpi):
    styles = {"G1": (C_G1, "o", "-"), "G2": (C_G2, "s", "--"), "G3": (C_G3, "^", "-.")}
    fig, ax = plt.subplots(figsize=(7.9, 4.39), dpi=dpi)
    for name, ys in FIG7_ATTAINMENT.items():
        c, m, ls = styles[name]
        ax.plot(FIG7_SEMESTERS, ys, marker=m, ls=ls, color=c, lw=2, ms=8, label=name)
        for xi, y in zip(range(3), ys):
            dy = 0.012 if name != "G1" else -0.022
            ax.annotate(f"{y:.3f}", (xi, y), textcoords="offset points",
                        xytext=(0, 14 if dy > 0 else -20),
                        ha="center", fontsize=11, color=c)
    ax.axhline(FIG7_THRESHOLD, color="#CC3311", ls=":", lw=2)
    ax.text(2.02, FIG7_THRESHOLD + 0.005, f"合格阈值 {FIG7_THRESHOLD}",
            color="#CC3311", fontsize=12, ha="right", va="bottom")
    ax.set_ylim(0.60, 1.00)
    ax.set_ylabel("毕业要求指标点达成度", fontsize=14)
    ax.legend(title="届别", loc="lower left", fontsize=12, framealpha=0.9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", ls=":", alpha=0.5)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(f"{outdir}/fig7_attainment_trend.png")
    plt.close(fig)


# ============================================================
# 图8  GR5.2(工具运用)跨届稳定 vs GR9.2(团队协作)波动显著
#      纵轴 0 起满量程 + 逐柱标值;纵横比与论文原图 (825x474) 一致
# ============================================================
def fig8(outdir, dpi):
    import numpy as np
    x = np.arange(3)
    w = 0.25
    fig, ax = plt.subplots(figsize=(7.5, 4.31), dpi=dpi)
    for off, name, c, h in [(-w, "G1", C_G1, ""), (0, "G2", C_G2, "//"),
                            (w, "G3", C_G3, "..")]:
        ys = FIG8_VALUES[name]
        bars = ax.bar(x + off, ys, w, color=c, edgecolor="black",
                      label=name, hatch=h)
        for b, v in zip(bars, ys):
            ax.text(b.get_x() + b.get_width()/2, v + 0.012, f"{v:.3f}",
                    ha="center", fontsize=10.5)
    ax.axhline(FIG7_THRESHOLD, color="#CC3311", ls=":", lw=1.8)
    ax.text(2.45, FIG7_THRESHOLD + 0.007, f"合格阈值 {FIG7_THRESHOLD}",
            color="#CC3311", fontsize=11, ha="right", va="bottom")
    ax.set_xticks(x)
    ax.set_xticklabels(FIG8_GROUPS, fontsize=12)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("指标点达成度", fontsize=13)
    ax.legend(title="届别", ncols=3, loc="lower right", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", ls=":", alpha=0.5)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(f"{outdir}/fig8_dimension_compare.png")
    plt.close(fig)


def load_eval_json(path):
    """读取 audit/run_action1.py 导出的 eval_summary.json,归一为图 4 所需结构。"""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    try:
        return {"n_maps": d["n_maps"],
                "episodes_per_map": d["episodes_per_map"],
                "counts": {k: d["counts"][k] for k in ("success", "collision", "timeout")}}
    except KeyError as e:
        print(f"[错误] {path} 缺少字段 {e},请用最新 audit/run_action1.py 重新生成。")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="复现论文 v1.1 图4/图5/图7/图8")
    ap.add_argument("--outdir", default="./figs_out", help="输出目录(默认 ./figs_out)")
    ap.add_argument("--dpi", type=int, default=200, help="输出 DPI(默认 200,投稿建议 300)")
    ap.add_argument("--eval-json", default=None,
                    help="评测汇总 JSON(eval_summary.json);提供时图 4 用实测数据")
    args = ap.parse_args()

    setup_cjk_font()
    os.makedirs(args.outdir, exist_ok=True)

    if args.eval_json:
        eval_data = load_eval_json(args.eval_json)
        print(f"[图4] 使用实测评测数据: {args.eval_json}")
    else:
        eval_data = FIG4_EVAL
        print("[图4] 使用论文内嵌常量(可用 --eval-json 换成实测数据)")

    fig4(args.outdir, args.dpi, eval_data)
    fig5(args.outdir, args.dpi)
    fig7(args.outdir, args.dpi)
    fig8(args.outdir, args.dpi)
    print(f"figures written to {args.outdir} (dpi={args.dpi})")


if __name__ == "__main__":
    main()
