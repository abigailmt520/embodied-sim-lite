# -*- coding: utf-8 -*-
"""
selftest.py —— 审计工具链红测(卡A验收项 A2;纯标准库,不需服务端)
====================================================================
一个永远显绿的审计,正是它自己反对的东西。本测试证明校验器**能红**:

    绿:合法包 → verify_pack.py 退出码 0
    红:五种篡改面(改事件/改 line_hash/断 prev_hash/改 MANIFEST.lines/改 summary 自报)
        → verify_pack.py 退出码 1,且报错文字点到该面

再加一项汇总冒烟:analyze_packs.py 能对夹具包出 audit_summary.json 与 receipts.csv。

用法:  python tools/audit_tools/selftest.py [--keep]
退出码:全过 0,任一未达预期 1。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PY = sys.executable

# (篡改面, 期望退出码, 报错文字须命中的关键词)
CASES = [
    ("none",           0, None),
    ("event",          1, "line_hash 不匹配"),
    ("line_hash",      1, "line_hash 不匹配"),
    ("prev_hash",      1, "prev_hash 断链"),
    ("manifest_lines", 1, "MANIFEST.lines"),
    ("summary",        1, "summary.hit"),
]


def run(cmd, cwd=ROOT):
    p = subprocess.run([PY] + cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留临时目录便于排查")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="audit_selftest_")
    failures = []
    try:
        for tamper, want_rc, want_text in CASES:
            d = os.path.join(tmp, tamper)
            rc, out = run(["tools/audit_tools/make_fixture_pack.py", "--outdir", d,
                           "--uid", "T01", "--session-id", "s" + tamper,
                           "--tamper", tamper])
            if rc != 0:
                failures.append(f"[{tamper}] 造包失败:\n{out}")
                continue
            rc, out = run(["tools/audit_tools/verify_pack.py", d])
            ok = (rc == want_rc) and (want_text is None or want_text in out)
            mark = "✓" if ok else "✗"
            print(f"  {mark} 篡改面={tamper:<15} 退出码={rc}(期望 {want_rc})"
                  + (f" 命中「{want_text}」={'是' if want_text in out else '否'}"
                     if want_text else ""))
            if not ok:
                failures.append(f"[{tamper}] 期望退出码 {want_rc} 命中「{want_text}」,"
                                f"实得 {rc}:\n{out}")

        # 汇总冒烟:合法包目录 → audit_summary.json + receipts.csv
        good = os.path.join(tmp, "none")
        outj = os.path.join(tmp, "audit_summary.json")
        outc = os.path.join(tmp, "receipts.csv")
        rc, out = run(["tools/audit_tools/analyze_packs.py", good,
                       "--out", outj, "--csv", outc])
        ok = rc == 0 and os.path.exists(outj) and os.path.exists(outc)
        print(f"  {'✓' if ok else '✗'} 汇总冒烟 analyze_packs → "
              f"audit_summary.json / receipts.csv")
        if not ok:
            failures.append(f"[analyze] 退出码 {rc}:\n{out}")
        elif os.path.exists(outj):
            with open(outj, encoding="utf-8") as fh:
                s = json.load(fh)
            print(f"      n_packs={s.get('n_packs')} "
                  f"C1.n={s.get('checkpoints', {}).get('C1', {}).get('n')}")
    finally:
        if args.keep:
            print(f"\n临时目录保留:{tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"红测未通过({len(failures)} 项):")
        for f in failures:
            print("  - " + f)
        sys.exit(1)
    print(f"红测通过 ✅（{len(CASES)} 个篡改面 + 1 项汇总冒烟）")


if __name__ == "__main__":
    main()
