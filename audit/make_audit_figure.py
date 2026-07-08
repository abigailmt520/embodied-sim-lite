# -*- coding: utf-8 -*-
"""
make_audit_figure.py  ——  动作1 · 红/绿对照证据图（论文 §4.3 配图）
====================================================================
加载已存档的 4 段 session（healthy + 注入 1-A/1-B/1-C），**重新真实运行审计**，
把判定矩阵渲染成一张"红/绿对照"图：
    行 = 三项检查 C1 / C2 / C3
    列 = 健康系统(门2) | 注入1-A | 注入1-B | 注入1-C  (门1)
    每格 = 绿底 ✓PASS / 红底 ✗FAIL + 真实定位信息（帧号/seq/误差/recv_t）

图中所有红/绿与定位文本均来自 `audit_session()` 的真实返回，非 hardcode（INV-2）。

运行：python audit/make_audit_figure.py   （先跑过 run_action1.py 生成 sessions/*.json）
产物：audit/audit_redgreen_matrix.png
"""

import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from integrity_audit import audit_session  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SESS = os.path.join(HERE, "sessions")

# ---- 注册 CJK 字体（matplotlib 默认字体无中文）----
for cand in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
             "/Library/Fonts/Arial Unicode.ttf",
             "/System/Library/Fonts/Hiragino Sans GB.ttc"):
    if os.path.exists(cand):
        font_manager.fontManager.addfont(cand)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=cand).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

GREEN_FILL, GREEN_EDGE, GREEN_TXT = "#d7f3e3", "#2faa6a", "#11623b"
RED_FILL, RED_EDGE, RED_TXT = "#fbd9d9", "#d84141", "#8a1c1c"
HEAD_FILL, HEAD_TXT = "#2b2f3a", "#ffffff"

# 行名与论文 v1.1 图 2 逐字一致(论文 v1.1 术语);内部 CHECK_ID 标识符保持不变
ROWS = [("C1", "C1 真值-里程计真分叉\nTRUTH_ODOM_FORK"),
        ("C2", "C2 帧序号单调\nSEQ_INTEGRITY"),
        ("C3", "C3 断流冻结\nFEED_LIVENESS")]

COLS = [("healthy", "健康系统 (门2)\nHealthy"),
        ("1-A_truth_copy", "注入 1-A\nodom ← truth"),
        ("1-B_seq_freeze", "注入 1-B\nseq frozen"),
        ("1-C_stall_running", "注入 1-C\nstall→online")]

CHECK_ID = {"C1": "C1_TRUTH_ODOM_FORK", "C2": "C2_SEQ_INTEGRITY",
            "C3": "C3_FEED_LIVENESS"}


def load_audit(col_key):
    if col_key == "healthy":
        path = os.path.join(SESS, "healthy.json")
    else:
        path = os.path.join(SESS, f"injected_{col_key}.json")
    with open(path) as fh:
        sess = json.load(fh)
    res = audit_session(sess)
    return {c["check"]: c for c in res["checks"]}


def cell_text(row_key, chk):
    """把真实审计结果压成简短可读的格子文案。"""
    loc = chk.get("locator") or {}
    if chk["ok"]:
        head = "✓ PASS"
        if row_key == "C1":
            body = f"max err={loc.get('max_err_m','?')} m\nL={loc.get('truth_path_len_m','?')} m (真分叉)"
        elif row_key == "C2":
            body = "seq 随数据单调自增"
        else:
            body = "陈旧帧已标 OFFLINE"
    else:
        head = "✗ FAIL"
        if row_key == "C1":
            body = (f"max err={loc.get('max_err_m','?')} m ≈ 0\n"
                    f"L={loc.get('truth_path_len_m','?')} m → 无分叉/抄真值")
        elif row_key == "C2":
            if "frozen_seq" in loc:
                body = f"seq 冻结@{loc['frozen_seq']}\nframe {loc.get('frame_index')}, t={loc.get('recv_t')}s"
            else:
                body = f"seq 倒退 {loc.get('prev_seq')}→{loc.get('seq')}\nframe {loc.get('frame_index')}"
        else:
            span = loc.get("recv_t_span")
            body = (f"stale@seq{loc.get('frozen_seq')} 但 link=online\n"
                    f"t={span}s → 断流却运行中")
    return head, body


def main():
    audits = {ck: load_audit(ck) for ck, _ in COLS}

    nrow, ncol = len(ROWS), len(COLS)
    fig, ax = plt.subplots(figsize=(15.5, 7.6))
    ax.set_xlim(0, ncol + 1.15)
    ax.set_ylim(0, nrow + 1.4)
    ax.axis("off")

    cw, ch = 1.0, 1.0
    x0, y0 = 1.15, 0.25
    rh = 0.95

    def box(x, y, w, h, fill, edge, rad=0.06):
        ax.add_patch(FancyBboxPatch((x + 0.04, y + 0.04), w - 0.08, h - 0.08,
                     boxstyle=f"round,pad=0.0,rounding_size={rad}",
                     fc=fill, ec=edge, lw=1.6))

    # 列表头
    for j, (_, label) in enumerate(COLS):
        x = x0 + j * cw
        box(x, y0 + nrow * rh, cw, rh * 0.95, HEAD_FILL, HEAD_FILL)
        ax.text(x + cw / 2, y0 + nrow * rh + rh * 0.48, label, ha="center", va="center",
                color=HEAD_TXT, fontsize=11, fontweight="bold")
    # 行表头
    for i, (_, label) in enumerate(ROWS):
        y = y0 + (nrow - 1 - i) * rh
        box(0.06, y, 1.05, rh, HEAD_FILL, HEAD_FILL)
        ax.text(0.06 + 1.05 / 2, y + rh / 2, label, ha="center", va="center",
                color=HEAD_TXT, fontsize=10.5, fontweight="bold")

    # 单元格
    for i, (rk, _) in enumerate(ROWS):
        y = y0 + (nrow - 1 - i) * rh
        for j, (ck, _) in enumerate(COLS):
            x = x0 + j * cw
            chk = audits[ck][CHECK_ID[rk]]
            if chk["ok"]:
                box(x, y, cw, rh, GREEN_FILL, GREEN_EDGE)
                hc, bc = GREEN_TXT, GREEN_TXT
            else:
                box(x, y, cw, rh, RED_FILL, RED_EDGE)
                hc, bc = RED_TXT, RED_TXT
            head, body = cell_text(rk, chk)
            ax.text(x + cw / 2, y + rh * 0.74, head, ha="center", va="center",
                    color=hc, fontsize=12.5, fontweight="bold")
            ax.text(x + cw / 2, y + rh * 0.34, body, ha="center", va="center",
                    color=bc, fontsize=8.2)

    fig.suptitle("Embodied-SimLite · 完整性审计 红/绿对照证据 (Integrity Audit RED/GREEN)",
                 fontsize=15, fontweight="bold", y=0.985)
    ax.text((ncol + 1.15) / 2, 0.04,
            "门2：健康系统三项全绿、零误报   |   门1：1-A/1-B/1-C 三类注入各被对应检查判红并定位   "
            "——审计自身已被证明「能抓假」，非永远显绿的波将金村",
            ha="center", va="center", fontsize=9.5, color="#333")

    out = os.path.join(HERE, "audit_redgreen_matrix.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"[OK] 红/绿对照图已保存: {out}")
    # 顺带核验：第一列应全绿，后三列对角线应红
    ok = (all(audits["healthy"][CHECK_ID[r]]["ok"] for r, _ in ROWS)
          and not audits["1-A_truth_copy"]["C1_TRUTH_ODOM_FORK"]["ok"]
          and not audits["1-B_seq_freeze"]["C2_SEQ_INTEGRITY"]["ok"]
          and not audits["1-C_stall_running"]["C3_FEED_LIVENESS"]["ok"])
    print(f"[CHECK] 健康全绿 + 三注入对角线判红: {'通过' if ok else '不符'}")


if __name__ == "__main__":
    main()
