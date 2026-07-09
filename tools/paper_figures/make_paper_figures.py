# -*- coding: utf-8 -*-
"""
make_paper_figures.py  ——  论文《面向具身智能的系统审计素养培养实践》图表复现脚本
==================================================================================
一键复现论文 v1_2 的五项插图产物(与论文编号一一对应):
    图4  fig4_ppo_eval.png       PPO 导航策略量化评测(25 张随机地图)
    图5  fig5_cpu_compare.png    同等 SLAM/导航任务下教学终端 CPU 占用对比
    图6  fig6_composite.jpeg     (a) 部署实拍 + (b) SLAM/Nav2 截图组 纵向合成
    图7  fig7_attainment.png     三届×三学期达成度分组柱状图【v1_2 更正版】
    图8  fig8_dimensions.png     四维度黑白折线·含 GR10.2【v1_2 更正版】

v1_2 更正说明:
    图7 由"转置折线"更正为"三届×三学期"分组柱状(黑白纹理区分学期);
    图8 补齐此前遗漏的 GR10.2 系列,共四条黑白折线,数值按原图像素标定
        复核(误差 ≤0.002);图内一律不再嵌入"图N"编号,编号仅由正文题注承载。

数据来源:图4/图5 = 正文 3.3 节;图7 = 表 2;图8 = 正文 4.2 节数值 + 像素标定。
统计数据集中在下方【数据常量区】;更新教学数据时只改常量即可再生图表。
图6 为照片合成,需本目录 assets/ 下两张源图(photo_deploy.png、slam_nav_montage.jpeg)。

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
import numpy as np

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# ============================================================
# 数据常量区(全部取自论文 v1_2 正文与表 2,更新数据只改这里)
# ============================================================
# 图4:PPO 策略 25 张随机地图评测(论文 3.3;可被 --eval-json 实测数据覆盖)
FIG4_EVAL = {"n_maps": 25, "episodes_per_map": 1,
             "counts": {"success": 21, "collision": 3, "timeout": 1}}

# 图5:同等 SLAM 建图与导航任务下教学终端 CPU 占用(论文 1.3/3.1 实测)
FIG5_GAZEBO_CPU = (75, 100)     # Gazebo 三维方案实测区间 %
FIG5_SIMLITE_CPU = 3            # 本平台约 3%

# 图7:三届×三学期达成度(论文表 2;行=届别、列=学期,与表 2 布局一致)
FIG7_GRADES = ["G1", "G2", "G3"]
FIG7_SEMESTER_LABELS = ["第一学期·硬件本体", "第二学期·仿真验证", "第三学期·具身进阶"]
FIG7_ATTAINMENT = {"G1": [0.915, 0.872, 0.905],
                   "G2": [0.890, 0.918, 0.873],
                   "G3": [0.914, 0.896, 0.896]}
FIG7_THRESHOLD = 0.65           # 合格阈值

# 图8:四维度达成度折线(论文 4.2 节数值 + 原图像素标定,误差 ≤0.002)
FIG8_DIMENSIONS = [
    ("GR5.2 使用现代工具(第二学期)",   [0.915, 0.927, 0.922]),
    ("GR5.2 使用现代工具(第三学期)",   [0.882, 0.908, 0.910]),
    ("GR9.2 团队协作与文档(第二学期)", [0.745, 0.915, 0.800]),
    ("GR10.2 沟通答辩(第三学期)",      [0.908, 0.786, 0.882]),
]

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
# 图7  三届×三学期达成度分组柱状图【v1_2 更正版】(数据=表2)
#      黑白纹理区分学期系列;纵轴 0.60 起截断,合格阈值 0.65
#      以黑色虚线显式画出;纵横比与论文原图 (2262x1256) 一致
# ============================================================
def fig7(outdir, dpi):
    x = np.arange(3)
    w = 0.26
    # 学期主序:把"届别×学期"的表 2 数据按学期转置成三条系列
    sem_values = list(zip(*[FIG7_ATTAINMENT[g] for g in FIG7_GRADES]))
    styles = [("white", "///"), ("0.78", None), ("0.40", None)]
    fig, ax = plt.subplots(figsize=(11.31, 6.28), dpi=dpi)
    for k, (lab, d, (fc, ht)) in enumerate(zip(FIG7_SEMESTER_LABELS, sem_values, styles)):
        b = ax.bar(x + (k-1)*w, d, w, label=lab, facecolor=fc, hatch=ht,
                   edgecolor="black", linewidth=1.2)
        for r, v in zip(b, d):
            ax.text(r.get_x() + r.get_width()/2, v + 0.004, f"{v:.3f}",
                    ha="center", va="bottom", fontsize=12.5)
    ax.axhline(FIG7_THRESHOLD, color="black", ls=(0, (6, 4)), lw=1.6)
    ax.text(2.42, FIG7_THRESHOLD + 0.003, f"合格阈值 {FIG7_THRESHOLD}",
            fontsize=12.5, ha="right", va="bottom")
    ax.set_ylim(0.60, 0.97)
    ax.set_yticks(np.arange(0.60, 0.96, 0.05))
    ax.set_xticks(x)
    ax.set_xticklabels(FIG7_GRADES, fontsize=14)
    ax.set_xlabel("年级(按入学先后,G3 为平台引入年级)", fontsize=14)
    ax.set_ylabel("毕业要求指标点达成度", fontsize=14)
    ax.tick_params(labelsize=13)
    ax.grid(axis="y", color="0.85", lw=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper center", ncol=3, fontsize=12.5, frameon=False,
              bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout()
    fig.savefig(f"{outdir}/fig7_attainment.png")
    plt.close(fig)


# ============================================================
# 图8  四维度黑白折线【v1_2 更正版】(GR5.2×2 + GR9.2 + GR10.2)
#      线型/标记区分系列,黑白印刷可辨;逐点标值;
#      纵横比与论文原图 (1650x1080) 一致
# ============================================================
def fig8(outdir, dpi):
    x = np.arange(3)
    styles = [dict(color="black", ls="-",  marker="o", mfc="black", mec="black"),
              dict(color="black", ls="--", marker="s", mfc="white", mec="black"),
              dict(color="0.42",  ls="-.", marker="^", mfc="0.42",  mec="0.42"),
              dict(color="0.42",  ls=":",  marker="D", mfc="white", mec="0.42")]
    fig, ax = plt.subplots(figsize=(8.25, 5.40), dpi=dpi)
    for (lab, d), st in zip(FIG8_DIMENSIONS, styles):
        ax.plot(x, d, label=lab, lw=2.2, ms=9, **st)
    # 逐点标值的偏移表 (x索引, 系列索引) -> (dx, dy),避免数值标签互相遮挡
    off = {(0, 0): (0, 8),  (0, 1): (0, -15), (0, 2): (0, 8),   (0, 3): (0, -15),
           (1, 0): (0, 8),  (1, 1): (0, -15), (1, 2): (0, 8),   (1, 3): (0, -15),
           (2, 0): (0, 8),  (2, 1): (0, -15), (2, 2): (0, -15), (2, 3): (0, 8)}
    for si, ((lab, d), st) in enumerate(zip(FIG8_DIMENSIONS, styles)):
        for xi, v in enumerate(d):
            dx, dy = off[(xi, si)]
            ax.annotate(f"{v:.3f}", (xi, v), textcoords="offset points",
                        xytext=(dx, dy), ha="center", fontsize=11,
                        color="black" if st["color"] == "black" else "0.30")
    ax.text(0.02, 0.965, "GR5.2 两学期均稳定于 0.91 上下",
            transform=ax.transAxes, fontsize=12)
    ax.set_ylim(0.70, 0.965)
    ax.set_yticks(np.arange(0.70, 0.96, 0.05))
    ax.set_xticks(x)
    ax.set_xticklabels(FIG7_GRADES, fontsize=14)
    ax.set_xlim(-0.25, 2.25)
    ax.set_xlabel("年级(按入学先后)", fontsize=14)
    ax.set_ylabel("毕业要求指标点达成度", fontsize=14)
    ax.tick_params(labelsize=13)
    ax.grid(axis="y", color="0.85", lw=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2,
              fontsize=12, frameon=False)
    fig.subplots_adjust(left=0.11, right=0.97, top=0.97, bottom=0.24)
    fig.savefig(f"{outdir}/fig8_dimensions.png")
    plt.close(fig)


# ============================================================
# 图6  (a) 部署实拍 + (b) SLAM/Nav2 截图组 纵向合成
#      源图在本目录 assets/ 下;像素合成,不受 --dpi 影响
# ============================================================
def fig6_composite(outdir):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[跳过] 图6合成: 未安装 Pillow(pip install pillow)")
        return
    pa = os.path.join(ASSETS_DIR, "photo_deploy.png")
    pb = os.path.join(ASSETS_DIR, "slam_nav_montage.jpeg")
    if not (os.path.exists(pa) and os.path.exists(pb)):
        print(f"[跳过] 图6合成: 缺少 assets 源图({pa} / {pb})")
        return
    a = Image.open(pa).convert("RGB")
    b = Image.open(pb).convert("RGB")
    W = 1248
    b2 = b.resize((W, round(b.height * W / b.width)), Image.LANCZOS)
    fnt = None
    for path in KNOWN_FONT_FILES:          # (a)(b) 标注复用字体探测列表
        if os.path.exists(path):
            try:
                fnt = ImageFont.truetype(path, 36)
                break
            except Exception:
                continue
    if fnt is None:
        fnt = ImageFont.load_default()
    lab_h, pad = 52, 10
    H = pad + a.height + lab_h + pad + b2.height + lab_h
    canvas = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(canvas)
    y = pad
    canvas.paste(a, (0, y))
    y += a.height
    d.text((W//2, y + lab_h//2), "(a)", font=fnt, fill="black", anchor="mm")
    y += lab_h + pad
    canvas.paste(b2, (0, y))
    y += b2.height
    d.text((W//2, y + lab_h//2), "(b)", font=fnt, fill="black", anchor="mm")
    canvas.save(f"{outdir}/fig6_composite.jpeg", quality=90)


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
    ap = argparse.ArgumentParser(description="复现论文 v1_2 图4/图5/图6/图7/图8")
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
    fig6_composite(args.outdir)
    print(f"figures written to {args.outdir} (dpi={args.dpi})")


if __name__ == "__main__":
    main()
