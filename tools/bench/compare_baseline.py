#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_baseline.py —— 性能预算比对（CSO-028-R1 裁定④）

主口径：整机占比（gateway 1 客户端 pct_of_machine_mean）≤ 10%  —— 绝对门，管课堂体验（与论文图5口径自洽）
并记口径：单核占用（ps %cpu 单核基准）—— 负载本身的可移植度量，只登记不设绝对门
相对回归预算：任一层合并后，单核口径各读数对 baseline 劣化 ≤ 20%（相对值）—— 防温水

用法：python3 tools/bench/compare_baseline.py --new result.json [--baseline tools/bench/baseline_course-2026A.json]
                                             [--abs-machine 10] [--rel 0.20]
result.json 由 tools/bench/cpu_usage.py --mode both --out 生成（须在基准机上跑：指纹不同即判「不可比」exit 2）。
退出码：0 通过｜1 超预算｜2 不可比/用法错误。
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = ROOT / "tools" / "bench" / "baseline_course-2026A.json"
FP_KEYS = ("hw_model", "ncpu", "machine", "system")


def pick(d, *ks):
    for k in ks:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return None
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", required=True); ap.add_argument("--baseline", default=str(DEFAULT_BASE))
    ap.add_argument("--abs-machine", type=float, default=10.0, help="主口径绝对门：整机占比上限 %%")
    ap.add_argument("--rel", type=float, default=0.20, help="相对回归预算（单核口径），默认 0.20")
    a = ap.parse_args()
    base = json.loads(Path(a.baseline).read_text(encoding="utf-8")); new = json.loads(Path(a.new).read_text(encoding="utf-8"))
    mb, mn = base.get("machine", {}), new.get("machine", {})
    diff_fp = [k for k in FP_KEYS if mb.get(k) != mn.get(k)]
    if diff_fp:
        print(f"不可比：机器指纹不同 {diff_fp}（baseline {mb.get('hw_model')} / {mb.get('ncpu')}核 vs new {mn.get('hw_model')} / {mn.get('ncpu')}核）——只能同机比较"); sys.exit(2)
    fails = []
    print(f"{'读数':<44}{'baseline':>12}{'new':>12}{'相对变化':>10}  判定")
    # 主口径：整机占比绝对门
    gk = "gateway_1client" if "gateway_1client" in new else "gateway"
    v = pick(new, gk, "pct_of_machine_mean")
    if v is not None:
        ok = v <= a.abs_machine
        print(f"{'主口径 整机占比（gateway 1客户端，%）':<44}{pick(base,'gateway_1client','pct_of_machine_mean') or float('nan'):>12.3f}{v:>12.3f}{'':>10}  {'✅' if ok else '🔴'} ≤{a.abs_machine}%")
        if not ok: fails.append("整机占比超绝对门")
    # 相对回归：单核口径
    rows = [("kernel 每步CPU ms（单核）", ("kernel", "cpu_ms_per_step")),
            ("gateway 空载 单核%均值", ("gateway_idle_0client", "pct_one_core", "mean")),
            ("gateway 1客户端 单核%均值", ("gateway_1client", "pct_one_core", "mean")),
            ("nav_gateway 1客户端 单核%均值", ("nav_gateway_1client", "pct_one_core", "mean"))]
    for label, path in rows:
        b, n = pick(base, *path), pick(new, *path)
        if b is None or n is None:
            print(f"{label:<44}{'—':>12}{'—':>12}{'':>10}  （缺读数，跳过）"); continue
        rel = (n - b) / b if b else float("inf")
        ok = rel <= a.rel
        print(f"{label:<44}{b:>12.3f}{n:>12.3f}{rel*100:>+9.1f}%  {'✅' if ok else '🔴'} 相对≤{a.rel*100:.0f}%")
        if not ok: fails.append(f"{label} 劣化 {rel*100:+.1f}%")
    print("\n结论：" + ("通过 ✅" if not fails else "超预算 🔴 — " + "；".join(fails)))
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
