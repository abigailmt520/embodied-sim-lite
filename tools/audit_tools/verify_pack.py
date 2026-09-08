# -*- coding: utf-8 -*-
"""
verify_pack.py —— 审计包逐包校验(任务六.6)
============================================
包格式与口径见 docs/audit_pack_spec.md。对每个 {uid}_{session_id}.zip:
    1. 逐行校验 audit_log.jsonl 的 SHA-256 哈希链(规范见仓库根 audit_chain.py);
    2. 核对 MANIFEST.json 的行数与总哈希;
    3. 由日志独立复算 summary,与包内 summary.json 逐字段比对(不采信自报)。

用法:
    python tools/audit_tools/verify_pack.py 包1.zip [包2.zip ...]
    python tools/audit_tools/verify_pack.py 包目录/          # 校验目录下全部 *.zip

退出码:全部通过 0,任一失败 1。
"""
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import audit_chain  # noqa: E402

# summary 中由日志复算、必须一致的字段(platform_version 等附注字段不参与比对)
CHECK_FIELDS = ("uid", "session_id", "seed", "condition", "onset_ms", "final_verdict",
                "hit", "localization_correct", "false_alarm", "detect_latency_ms",
                "self_tests", "n_screenshots", "n_events")


def verify_one(path: str) -> bool:
    problems = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for need in ("audit_log.jsonl", "summary.json", "MANIFEST.json"):
            if need not in names:
                problems.append(f"缺少 {need}")
        if problems:
            _report(path, problems)
            return False
        jsonl_text = z.read("audit_log.jsonl").decode("utf-8")
        summary = json.loads(z.read("summary.json"))
        manifest = json.loads(z.read("MANIFEST.json"))
        shots_in_zip = sorted(n.split("/", 1)[1] for n in names
                              if n.startswith("screenshots/") and not n.endswith("/"))

    # 1) 哈希链
    ok, n_lines, total_hash, errors = audit_chain.verify_chain(jsonl_text)
    problems += errors

    # 2) MANIFEST
    if manifest.get("lines") != n_lines:
        problems.append(f"MANIFEST.lines={manifest.get('lines')} 与实际行数 {n_lines} 不符")
    if manifest.get("total_hash") != total_hash:
        problems.append("MANIFEST.total_hash 与末行哈希不符")

    # 3) summary 复算比对
    events = audit_chain.parse_events(jsonl_text)
    derived = audit_chain.derive_summary(events)
    for k in CHECK_FIELDS:
        if summary.get(k) != derived.get(k):
            problems.append(f"summary.{k} 自报={summary.get(k)!r} 复算={derived.get(k)!r}")

    # 4) SCREENSHOT 事件与包内截图逐一对应
    logged_shots = sorted(e["payload"].get("filename") for e in events
                          if e["event"] == "SCREENSHOT")
    if logged_shots != shots_in_zip:
        problems.append(f"截图与日志不符:日志 {logged_shots} vs 包内 {shots_in_zip}")

    _report(path, problems, n_lines=n_lines,
            condition=derived.get("condition"), hit=derived.get("hit"))
    return not problems


def _report(path, problems, n_lines=None, condition=None, hit=None):
    name = os.path.basename(path)
    if not problems:
        print(f"✓ PASS  {name}  (行数={n_lines}, 条件={condition}, "
              f"命中={'是' if hit else '否'})")
    else:
        print(f"✗ FAIL  {name}")
        for p in problems:
            print(f"        - {p}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)
    packs = []
    for a in args:
        if os.path.isdir(a):
            packs += sorted(os.path.join(a, f) for f in os.listdir(a) if f.endswith(".zip"))
        else:
            packs.append(a)
    if not packs:
        print("未找到任何 .zip 审计包")
        sys.exit(2)
    results = [verify_one(p) for p in packs]
    n_ok = sum(results)
    print(f"\n共 {len(packs)} 包:通过 {n_ok},失败 {len(packs) - n_ok}")
    sys.exit(0 if n_ok == len(packs) else 1)


if __name__ == "__main__":
    main()
