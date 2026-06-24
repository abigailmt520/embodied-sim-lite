# -*- coding: utf-8 -*-
"""
integrity_audit.py  ——  动作1 · 防自欺完整性审计（Anti-Self-Deception Integrity Audit）
=========================================================================================
本模块是「审计仪」本身：输入一段运行时状态流（session，逐帧契约 + 监控客户端的采样时间与
链路状态声明），输出一组检查项的 红(RED)/绿(GREEN) + 定位信息。

设计原则（论文 §4.3/4.4 的灵魂，见 PRD）：
    审计自身必须先被证明"能抓假"。一个永远显绿的审计就是波将金村。
    因此每个检查都针对一类**真实的自欺信号**，且能在被故意注入对应假仪表时**确实变红并定位**。

三类核心检查（对应验收门 1 的 1-A / 1-B / 1-C）：
    C1  TRUTH_ODOM_FORK   —— Truth 与 Odom 是否真分叉。抓"把 Odom 接回真值"的假仪表（ox=robot.x）。
    C2  SEQ_INTEGRITY     —— 帧序号是否与"数据在更新"自洽。抓"数据在动但帧序号冻结/倒退"。
    C3  FEED_LIVENESS     —— 断流是否即冻结并标 OFFLINE。抓"feed 中断却仍声明 online/运行中"。

session 帧记录契约（list[dict]）：
    {
      "recv_t": float,                      # 监控客户端采样该帧的墙钟时间 (s)
      "seq": int,                           # 契约帧序号（embodied_env 全局单调）
      "truth": {"x","y","theta"},           # 真值位姿（= 契约 robot）
      "odom":  {"x","y","theta"},           # 里程计位姿（= 契约 odom）
      "step": int, "terminated": bool, "truncated": bool,
      "link_status": "online" | "offline",  # 系统/前端对链路活性的声明（健康系统断流→offline）
    }

纯 stdlib + numpy，无 env/torch 依赖；可独立对任意 session（含离线 json）运行。
"""

import math

# ---- 判定阈值（保守、物理可解释；非为凑结果而调，见 INV-2）----
EPS_FORK = 1e-4        # Truth–Odom 视为"无分叉"的误差上限 (m)：健康系统打滑后远超此值
MIN_MOTION = 0.5       # C1 生效所需的最小真值累计行程 (m)：行程不足则判 N/A 而非误报
EPS_MOVE = 1e-9        # 判定"位姿发生移动"的最小欧氏增量 (m)
STALE_TOL = 2          # C3 容忍的连续陈旧帧数：超过即认定 feed 停更（容忍 1 帧抖动）


def _xy(p):
    return (p["x"], p["y"])


def _dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _moved(prev, cur):
    """真值位姿在两帧间是否发生移动（位置或朝向）。"""
    return (_dist(prev["truth"], cur["truth"]) > EPS_MOVE
            or abs(prev["truth"]["theta"] - cur["truth"]["theta"]) > EPS_MOVE)


def _result(name, desc, ok, detail, locator=None):
    return {
        "check": name,
        "desc": desc,
        "status": "GREEN" if ok else "RED",
        "ok": bool(ok),
        "detail": detail,
        "locator": locator,
    }


# ====================================================================
# C1 · Truth–Odom 真分叉
# ====================================================================
def check_truth_odom_fork(session):
    """抓"假仪表"：Odom 被接回真值（误差链路死掉，Truth≡Odom）。

    仅在 online 帧上评估。统计真值累计行程 L 与 Truth–Odom 最大误差 E_max：
        - 行程不足（L<MIN_MOTION）：N/A（不误报）；
        - 行程充足但 E_max≈0：判红"无分叉/疑似抄真值"，并定位发生处。
    """
    online = [f for f in session if f.get("link_status", "online") == "online"]
    if len(online) < 2:
        return _result("C1_TRUTH_ODOM_FORK", "Truth 与 Odom 是否真分叉",
                       True, "online 帧不足，N/A")

    L = 0.0
    e_max, e_max_seq = 0.0, None
    for i in range(1, len(online)):
        L += _dist(online[i - 1]["truth"], online[i]["truth"])
    for f in online:
        e = _dist(f["truth"], f["odom"])
        if e > e_max:
            e_max, e_max_seq = e, f["seq"]

    if L < MIN_MOTION:
        return _result("C1_TRUTH_ODOM_FORK", "Truth 与 Odom 是否真分叉",
                       True, f"真值累计行程 L={L:.3f}m < {MIN_MOTION}m，运动不足，N/A")

    if e_max < EPS_FORK:
        return _result(
            "C1_TRUTH_ODOM_FORK", "Truth 与 Odom 是否真分叉", False,
            f"行程 L={L:.2f}m 内 Truth–Odom 最大误差仅 {e_max:.2e}m (<{EPS_FORK:.0e}) —— "
            f"里程计无漂移/疑似抄真值（假仪表）",
            locator={"max_err_m": e_max, "truth_path_len_m": round(L, 3),
                     "n_online_frames": len(online)})
    return _result(
        "C1_TRUTH_ODOM_FORK", "Truth 与 Odom 是否真分叉", True,
        f"行程 L={L:.2f}m 内 Truth–Odom 最大误差 {e_max:.3f}m @seq={e_max_seq}（真分叉）",
        locator={"max_err_m": round(e_max, 4), "truth_path_len_m": round(L, 3)})


# ====================================================================
# C2 · 帧序号自洽（抓"数据在动但帧序号冻结/倒退"）
# ====================================================================
def check_seq_integrity(session):
    """帧序号必须与"数据在更新"自洽：

    对相邻 online 帧：
        - seq 倒退（seq[i] < seq[i-1]）→ 判红；
        - 真值在移动但 seq 未自增（数据鲜活而帧序号撒谎）→ 判红。
    （真值与 seq 同时冻结属"陈旧/断流"，交给 C3 判定，不在此误判。）
    """
    prev = None
    for i, f in enumerate(session):
        if f.get("link_status", "online") != "online":
            prev = None  # 跨越 offline 段后不做跨段比较
            continue
        if prev is not None:
            ps, cs = prev["seq"], f["seq"]
            if cs < ps:
                return _result("C2_SEQ_INTEGRITY", "帧序号是否单调自洽", False,
                               f"帧序号倒退：seq {ps} → {cs}",
                               locator={"frame_index": i, "prev_seq": ps, "seq": cs,
                                        "recv_t": f["recv_t"]})
            if _moved(prev, f) and cs == ps:
                return _result("C2_SEQ_INTEGRITY", "帧序号是否单调自洽", False,
                               f"数据在更新（真值移动 {_dist(prev['truth'], f['truth']):.3f}m）"
                               f"但帧序号冻结于 seq={cs}",
                               locator={"frame_index": i, "frozen_seq": cs,
                                        "recv_t": f["recv_t"]})
        prev = f
    return _result("C2_SEQ_INTEGRITY", "帧序号是否单调自洽", True,
                   "所有 online 帧的帧序号随数据更新单调自增")


# ====================================================================
# C3 · 断流即冻结（抓"feed 中断却仍声明 online/运行中"）
# ====================================================================
def check_feed_liveness(session):
    """断流即冻结并标 OFFLINE：

    "陈旧帧" = 真值与 seq 均未变化但 recv_t 在推进（墙钟在走、数据冻结）。
    若连续陈旧帧数 ≥ STALE_TOL 期间链路仍声明 online → 判红（断流却显示运行中）。
    健康系统在断流段会把 link_status 置 offline，故陈旧帧被豁免 → 绿。
    """
    prev = None
    stale_run = 0
    run_start = None
    for i, f in enumerate(session):
        online = f.get("link_status", "online") == "online"
        if prev is not None and online:
            stale = (not _moved(prev, f)) and (f["seq"] == prev["seq"]) \
                    and (f["recv_t"] > prev["recv_t"])
            if stale:
                if stale_run == 0:
                    run_start = i
                stale_run += 1
                if stale_run >= STALE_TOL:
                    return _result(
                        "C3_FEED_LIVENESS", "断流是否即冻结并标 OFFLINE", False,
                        f"feed 已停更（自 seq={f['seq']} 起连续 {stale_run} 帧数据冻结、"
                        f"墙钟仍在推进）但链路仍声明 online —— 断流却显示运行中",
                        locator={"stale_from_frame": run_start, "frozen_seq": f["seq"],
                                 "recv_t_span": [session[run_start]["recv_t"], f["recv_t"]],
                                 "link_status": "online"})
            else:
                stale_run = 0
        else:
            stale_run = 0
        prev = f
    return _result("C3_FEED_LIVENESS", "断流是否即冻结并标 OFFLINE", True,
                   "无'断流却显示运行中'：陈旧帧均已正确标记 OFFLINE 冻结")


CHECKS = [check_truth_odom_fork, check_seq_integrity, check_feed_liveness]


def audit_session(session):
    """对一段 session 运行全部检查，返回汇总结果。"""
    results = [c(session) for c in CHECKS]
    passed = all(r["ok"] for r in results)
    return {"passed": passed, "verdict": "GREEN" if passed else "RED", "checks": results}


def format_report(audit, title=""):
    """渲染为可回贴的文本报告。"""
    lines = []
    if title:
        lines.append(title)
    overall = "🟢 全绿通过 (GREEN)" if audit["passed"] else "🔴 检出自欺 (RED)"
    lines.append(f"  审计总判定：{overall}")
    for r in audit["checks"]:
        mark = "🟢 GREEN" if r["ok"] else "🔴 RED  "
        lines.append(f"    [{mark}] {r['check']:<22} {r['desc']}")
        lines.append(f"             └─ {r['detail']}")
        if not r["ok"] and r["locator"]:
            lines.append(f"             └─ 定位: {r['locator']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("用法: python integrity_audit.py <session.json>")
        sys.exit(1)
    with open(sys.argv[1]) as fh:
        sess = json.load(fh)
    res = audit_session(sess)
    print(format_report(res, title=f"== 审计 {sys.argv[1]} =="))
    sys.exit(0 if res["passed"] else 2)
