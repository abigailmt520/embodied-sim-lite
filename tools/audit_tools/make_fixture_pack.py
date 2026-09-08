# -*- coding: utf-8 -*-
"""
make_fixture_pack.py —— 离线造审计包(卡A自测夹具,纯标准库,不需服务端)
==========================================================================
按 docs/audit_pack_spec.md 的规范直接调 audit_chain 造包,用途只有一个:
**给 verify_pack.py 一个可判绿的合法包与一批可判红的篡改包**,让红测能红。

与 tools/audit_tools/simulate_sessions.py 的分工(后者属卡B,尚未入仓):
    simulate_sessions.py  端到端跑真服务端的实验模式(?exp=1),验的是**平台**;
    make_fixture_pack.py  离线按规范造字节,验的是**校验器自身**——
                          校验器的测试不该依赖被它校验的那个系统。

用法:
    python tools/audit_tools/make_fixture_pack.py --outdir <目录>
        [--uid T01] [--condition C1|C2|C3|healthy] [--verdict abnormal|healthy]
        [--checkpoint C1|C2|C3] [--onset-ms 2000] [--latency-ms 4000]
        [--tamper none|event|line_hash|prev_hash|manifest_lines|summary]

--tamper 说明(合法包外的五种篡改面,逐面都应被 verify_pack.py 判红):
    event          改一条事件的 payload 内容(哈希不再匹配)
    line_hash      只改末行 line_hash
    prev_hash      断链:改中间一行的 prev_hash
    manifest_lines MANIFEST.lines 与实际行数不符
    summary        summary.json 自报值与日志复算不符(自报命中,日志是健康轮)
"""
import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import audit_chain  # noqa: E402

PLATFORM_VERSION = "fixture-1.0.0"
# 1x1 红色 PNG(占位截图;内容不参与校验,只核文件名与日志对账)
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c636062f8cf00000583020079d9c1a30000000049454e44ae426082")


def _iso(base: datetime, ms: int) -> str:
    return (base + timedelta(milliseconds=ms)).isoformat(timespec="milliseconds")


def build_events(uid, session_id, condition, verdict, checkpoint, onset_ms, latency_ms):
    """按 spec §2 事件序列造一个会话的 core 事件流(未加哈希)。"""
    t0 = datetime(2026, 9, 8, 10, 0, 0)
    shot = f"{uid}_{session_id}_001.png"
    ev = []

    def add(ms, event, payload):
        ev.append({"ts": _iso(t0, ms), "session_id": session_id, "uid": uid,
                   "event": event, "payload": payload})

    add(0, "SESSION_START", {"seed": 4242, "platform_version": PLATFORM_VERSION})
    add(500, "SELF_TEST", {"action": "seq_probe"})
    add(900, "SELF_TEST", {"action": "slip_zero"})
    add(1400, "SELF_TEST", {"action": "slip_restore"})
    if condition != "healthy":
        add(onset_ms, "INJECT", {"type": condition, "onset_ms": onset_ms})
    add(onset_ms + 300, "TELEMETRY", {"step": 42, "seq": 42})
    add(onset_ms + latency_ms - 200, "SCREENSHOT", {"filename": shot})
    add(onset_ms + latency_ms, "STUDENT_VERDICT",
        {"verdict": verdict, "checkpoint": checkpoint,
         "note": "夹具会话(离线生成,仅供校验器红测)"})
    add(onset_ms + latency_ms + 500, "SESSION_END", {"reason": "fixture"})
    return ev, shot


def chain_lines(events):
    """把 core 事件流串成带哈希的存盘行。返回 (行列表, 末行哈希)。"""
    prev = audit_chain.GENESIS
    lines = []
    for core in events:
        line, prev = audit_chain.make_line(core, prev)
        lines.append(line)
    return lines, prev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--uid", default="T01")
    ap.add_argument("--session-id", default="fixture0001")
    ap.add_argument("--condition", default="C1", choices=["C1", "C2", "C3", "healthy"])
    ap.add_argument("--verdict", default="abnormal", choices=["abnormal", "healthy"])
    ap.add_argument("--checkpoint", default=None, help="判定点名;默认与 condition 一致")
    ap.add_argument("--onset-ms", type=int, default=2000)
    ap.add_argument("--latency-ms", type=int, default=4000)
    ap.add_argument("--tamper", default="none",
                    choices=["none", "event", "line_hash", "prev_hash",
                             "manifest_lines", "summary"])
    args = ap.parse_args()

    checkpoint = args.checkpoint if args.checkpoint is not None else (
        args.condition if args.condition != "healthy" else None)
    events, shot = build_events(args.uid, args.session_id, args.condition,
                                args.verdict, checkpoint,
                                args.onset_ms, args.latency_ms)

    # summary 与 MANIFEST 一律由**同一套复算**产出——合法包按定义自洽
    lines, total_hash = chain_lines(events)
    summary = audit_chain.derive_summary(events)
    summary["platform_version"] = PLATFORM_VERSION
    manifest = {"total_hash": total_hash, "lines": len(lines),
                "chain_ok_at_export": True, "platform_version": PLATFORM_VERSION,
                "clock_basis": "fixture fixed clock, ISO8601 ms",
                "generated_at": _iso(datetime(2026, 9, 8, 10, 0, 0), 9999)}

    # ---- 篡改面(每一种都应被 verify_pack.py 判红)----
    if args.tamper == "event":
        rec = json.loads(lines[-2])                       # 改 STUDENT_VERDICT 的理由
        rec["payload"] = dict(rec["payload"], note="被改过的理由")
        lines[-2] = json.dumps(rec, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
    elif args.tamper == "line_hash":
        rec = json.loads(lines[-1])
        rec["line_hash"] = "0" * 64
        lines[-1] = json.dumps(rec, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
    elif args.tamper == "prev_hash":
        rec = json.loads(lines[2])
        rec["prev_hash"] = "f" * 64
        lines[2] = json.dumps(rec, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
    elif args.tamper == "manifest_lines":
        manifest["lines"] = len(lines) + 1
    elif args.tamper == "summary":
        summary["hit"] = not summary["hit"]

    os.makedirs(args.outdir, exist_ok=True)
    path = os.path.join(args.outdir, f"{args.uid}_{args.session_id}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("audit_log.jsonl", "\n".join(lines) + "\n")
        z.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        z.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr(f"screenshots/{shot}", TINY_PNG)
    print(f"夹具包已生成: {path}  (篡改面={args.tamper}, 条件={args.condition}, "
          f"行数={len(lines)})")


if __name__ == "__main__":
    main()
