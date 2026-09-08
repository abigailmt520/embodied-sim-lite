# -*- coding: utf-8 -*-
"""
audit_chain.py —— 审计日志哈希链与 summary 复算(共享规范,纯标准库)
====================================================================
被两侧共同引用,保证「写入」与「校验」用同一套字节级规范:
    - inference_server.py    实验模式写 JSONL 审计日志(任务六)
    - tools/audit_tools/     verify_pack.py / analyze_packs.py 独立复算

哈希链规范(docs/audit_pack_spec.md §2):
    core       = {ts, session_id, uid, event, payload} 五字段
    core_json  = json.dumps(core, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"))          # 规范化序列化
    line_hash  = SHA256(prev_hash + core_json) 的十六进制
    存盘行     = core 五字段 + prev_hash + line_hash(同一规范化序列化)
    创世 prev_hash = 64 个 '0'
"""
import hashlib
import json
from datetime import datetime

GENESIS = "0" * 64
CORE_FIELDS = ("ts", "session_id", "uid", "event", "payload")


def canonical_json(core: dict) -> str:
    """core 五字段的规范化序列化(哈希的唯一输入形式)。"""
    return json.dumps({k: core[k] for k in CORE_FIELDS},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def line_hash(prev_hash: str, core: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(core)).encode("utf-8")).hexdigest()


def make_line(core: dict, prev_hash: str) -> tuple[str, str]:
    """构造一条存盘行。返回 (行文本, 本行 line_hash 即下一行的 prev_hash)。"""
    h = line_hash(prev_hash, core)
    rec = dict(core)
    rec["prev_hash"] = prev_hash
    rec["line_hash"] = h
    return json.dumps(rec, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")), h


def verify_chain(jsonl_text: str) -> tuple[bool, int, str, list[str]]:
    """逐行校验哈希链。返回 (是否通过, 行数, 末行哈希, 错误列表)。"""
    errors: list[str] = []
    prev = GENESIS
    n = 0
    last = GENESIS
    for i, raw in enumerate(jsonl_text.splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        n += 1
        try:
            rec = json.loads(raw)
        except ValueError:
            errors.append(f"第 {i} 行:JSON 解析失败")
            continue
        if rec.get("prev_hash") != prev:
            errors.append(f"第 {i} 行:prev_hash 断链(期望 {prev[:12]}…,实际 "
                          f"{str(rec.get('prev_hash'))[:12]}…)")
        try:
            expect = line_hash(rec.get("prev_hash", ""), rec)
        except KeyError as e:
            errors.append(f"第 {i} 行:缺少字段 {e}")
            continue
        if rec.get("line_hash") != expect:
            errors.append(f"第 {i} 行:line_hash 不匹配(内容被改动?)")
        prev = rec.get("line_hash", "")
        last = prev
    return (not errors), n, last, errors


def parse_events(jsonl_text: str) -> list[dict]:
    """解析 JSONL 为事件列表(含 core 五字段;不做哈希校验)。"""
    events = []
    for raw in jsonl_text.splitlines():
        raw = raw.strip()
        if raw:
            events.append(json.loads(raw))
    return events


def _ts_ms(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp() * 1000.0


def derive_summary(events: list[dict]) -> dict:
    """从事件流独立复算会话 summary(检出率/时延不采信自报,由日志重算)。

    口径(docs/audit_pack_spec.md §4):
        condition   : 日志中有 INJECT 即为该注入类型;无 INJECT 视为健康轮
        final 判定  : 以最后一次 STUDENT_VERDICT 为准
        hit         : 注入轮且 final 判定为 abnormal
        定位正确    : hit 且 checkpoint 与注入类型一致
        false_alarm : 健康轮且 final 判定为 abnormal
        检出时延    : final 判定时刻 − INJECT 时刻(仅命中轮)
    """
    start = next((e for e in events if e["event"] == "SESSION_START"), None)
    inject = next((e for e in events if e["event"] == "INJECT"), None)
    verdicts = [e for e in events if e["event"] == "STUDENT_VERDICT"]
    final = verdicts[-1] if verdicts else None
    shots = [e for e in events if e["event"] == "SCREENSHOT"]
    self_tests = [e["payload"].get("action") for e in events if e["event"] == "SELF_TEST"]

    condition = inject["payload"]["type"] if inject else "healthy"
    fv = final["payload"] if final else None
    hit = bool(inject and fv and fv.get("verdict") == "abnormal")
    latency = _ts_ms(final["ts"]) - _ts_ms(inject["ts"]) if hit else None
    return {
        "uid": events[0]["uid"] if events else None,
        "session_id": events[0]["session_id"] if events else None,
        "seed": start["payload"].get("seed") if start else None,
        "condition": condition,
        "onset_ms": inject["payload"].get("onset_ms") if inject else None,
        "final_verdict": ({"verdict": fv.get("verdict"),
                           "checkpoint": fv.get("checkpoint"),
                           "note": fv.get("note"),
                           "ts": final["ts"]} if final else None),
        "hit": hit,
        "localization_correct": bool(hit and fv.get("checkpoint") == condition),
        "false_alarm": bool(inject is None and fv and fv.get("verdict") == "abnormal"),
        "detect_latency_ms": (round(latency, 1) if latency is not None else None),
        "self_tests": self_tests,
        "n_screenshots": len(shots),
        "n_events": len(events),
    }
