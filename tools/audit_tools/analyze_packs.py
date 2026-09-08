# -*- coding: utf-8 -*-
"""
analyze_packs.py —— 审计包批量汇总(任务六.6)
==============================================
汇总目录内全部 {uid}_{session_id}.zip,输出:
    audit_summary.json  各检查点发现率/定位准确率/误报率/时延分布
                        (可直接喂给 make_paper_figures.py --audit-json)
    receipts.csv        每人每会话回执(uid/条件/判定/命中/时延/证伪动作)

指标口径(docs/audit_pack_spec.md §5,先于数据定稿):
    发现率      = 注入轮中报告异常的比例
    定位准确率  = 报异常的注入轮中检查点点名正确的比例
    误报率      = 健康轮中报告异常的比例
    检出时延    = 判定时刻 − 注入 onset,仅命中轮,报中位数[四分位距]
    比例的 95% 置信区间一律 Clopper–Pearson 精确区间(纯 Python 实现,无 scipy 依赖)

用法:
    python tools/audit_tools/analyze_packs.py 包目录/ [--out audit_summary.json]
                                              [--csv receipts.csv] [--skip-verify]
默认先逐包校验哈希链,校验失败的包被剔除并告警(--skip-verify 跳过校验)。
"""
import argparse
import csv
import json
import math
import os
import sys
import zipfile
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import audit_chain  # noqa: E402


# ------------------------------------------------------------------
# Clopper–Pearson 精确置信区间(正则不完全 Beta 函数 + 二分求逆,纯标准库)
# ------------------------------------------------------------------
def _betacf(a, b, x, eps=3e-12, max_iter=300):
    """I_x(a,b) 的连分式(Numerical Recipes 6.4)。"""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    return h


def _betai(a, b, x):
    """正则不完全 Beta 函数 I_x(a,b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(q, a, b, tol=1e-10):
    """Beta 分布分位数(对 I_x(a,b)=q 二分求逆)。"""
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _betai(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


def clopper_pearson(k, n, alpha=0.05):
    """比例 k/n 的 Clopper–Pearson 精确 95% 置信区间。n=0 时返回 None。"""
    if n == 0:
        return None
    lo = 0.0 if k == 0 else _beta_ppf(alpha / 2.0, k, n - k + 1)
    hi = 1.0 if k == n else _beta_ppf(1.0 - alpha / 2.0, k + 1, n - k)
    return [round(lo, 4), round(hi, 4)]


def _median_iqr(values):
    if not values:
        return None
    v = sorted(values)

    def q(p):
        idx = p * (len(v) - 1)
        lo_i = int(math.floor(idx))
        hi_i = int(math.ceil(idx))
        return v[lo_i] + (v[hi_i] - v[lo_i]) * (idx - lo_i)

    return {"median": round(q(0.5), 1), "iqr": [round(q(0.25), 1), round(q(0.75), 1)],
            "n": len(v), "values": [round(x, 1) for x in v]}


# ------------------------------------------------------------------
# 汇总
# ------------------------------------------------------------------
def load_pack(path, skip_verify=False):
    with zipfile.ZipFile(path) as z:
        jsonl_text = z.read("audit_log.jsonl").decode("utf-8")
    if not skip_verify:
        ok, _, _, errors = audit_chain.verify_chain(jsonl_text)
        if not ok:
            print(f"[剔除] {os.path.basename(path)}:哈希链校验失败 "
                  f"({errors[0] if errors else ''})")
            return None
    # 一律由日志独立复算,不采信包内自报 summary
    return audit_chain.derive_summary(audit_chain.parse_events(jsonl_text))


def aggregate(records):
    out = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "n_packs": len(records), "metrics_spec": "docs/audit_pack_spec.md §5",
           "checkpoints": {}, "healthy": {}, "sessions": records}
    for cp in ("C1", "C2", "C3"):
        rs = [r for r in records if r["condition"] == cp]
        det = [r for r in records if r["condition"] == cp and r["hit"]]
        loc = [r for r in det if r["localization_correct"]]
        lat = [r["detect_latency_ms"] for r in det if r["detect_latency_ms"] is not None]
        out["checkpoints"][cp] = {
            "n": len(rs), "detected": len(det),
            "detection_rate": round(len(det) / len(rs), 4) if rs else None,
            "detection_ci95": clopper_pearson(len(det), len(rs)),
            "loc_correct": len(loc),
            "localization_accuracy": round(len(loc) / len(det), 4) if det else None,
            "latency_ms": _median_iqr(lat),
        }
    hs = [r for r in records if r["condition"] == "healthy"]
    fa = [r for r in hs if r["false_alarm"]]
    out["healthy"] = {"n": len(hs), "false_alarms": len(fa),
                      "false_alarm_rate": round(len(fa) / len(hs), 4) if hs else None,
                      "false_alarm_ci95": clopper_pearson(len(fa), len(hs))}
    return out


def write_receipts(records, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["uid", "session_id", "condition", "verdict", "checkpoint",
                    "hit_or_correct_rejection", "localization_correct",
                    "detect_latency_ms", "self_tests", "n_screenshots"])
        for r in sorted(records, key=lambda x: (x["uid"] or "", x["session_id"] or "")):
            fv = r["final_verdict"] or {}
            correct = (r["hit"] if r["condition"] != "healthy"
                       else (fv.get("verdict") == "healthy"))
            w.writerow([r["uid"], r["session_id"], r["condition"],
                        fv.get("verdict"), fv.get("checkpoint"),
                        int(bool(correct)), int(bool(r["localization_correct"])),
                        r["detect_latency_ms"],
                        "|".join(r["self_tests"]), r["n_screenshots"]])


def main():
    ap = argparse.ArgumentParser(description="汇总审计包目录 → audit_summary.json + 回执 CSV")
    ap.add_argument("packs_dir", help="审计包目录(内含 *.zip)")
    ap.add_argument("--out", default="audit_summary.json")
    ap.add_argument("--csv", default="receipts.csv")
    ap.add_argument("--skip-verify", action="store_true", help="跳过哈希链校验(不建议)")
    args = ap.parse_args()

    zips = sorted(os.path.join(args.packs_dir, f)
                  for f in os.listdir(args.packs_dir) if f.endswith(".zip"))
    if not zips:
        print(f"目录 {args.packs_dir} 下没有 .zip 审计包")
        sys.exit(2)
    records = [r for r in (load_pack(p, args.skip_verify) for p in zips) if r is not None]
    summary = aggregate(records)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    write_receipts(records, args.csv)

    print(f"共汇总 {len(records)}/{len(zips)} 包 → {args.out} / {args.csv}")
    for cp, m in summary["checkpoints"].items():
        lat = m["latency_ms"]
        lat_s = (f"{lat['median']/1000:.1f}s [{lat['iqr'][0]/1000:.1f},"
                 f"{lat['iqr'][1]/1000:.1f}]" if lat else "—")
        print(f"  {cp}: n={m['n']} 发现率={m['detection_rate']} CI95={m['detection_ci95']} "
              f"定位准确率={m['localization_accuracy']} 时延中位[IQR]={lat_s}")
    h = summary["healthy"]
    print(f"  健康: n={h['n']} 误报率={h['false_alarm_rate']} CI95={h['false_alarm_ci95']}")


if __name__ == "__main__":
    main()
