# -*- coding: utf-8 -*-
"""
fault_injection.py  ——  动作1 · 假仪表注入器（仅供审计自证抓假，绝不进生产路径）
================================================================================
向一段 *健康* session 注入三类真实的"自欺/假仪表"，用于验证审计确实能抓假（验收门 1）。

注入是对状态流的**真实破坏**（复刻历史上真实出现过的缺陷），不是写"演示用红色输出"：
    1-A truth_copy     —— 把 Odom 逐帧接回真值（复刻 V3 重构期 ox=robot.x 的波将金村）。
    1-B seq_freeze     —— 数据仍在更新，却把帧序号冻结（帧序号撒谎）。
    1-C stall_running  —— 把"断流冻结段"的链路声明从 offline 改回 online（断流却显示运行中）。

每个注入器接收健康 session 的深拷贝、返回被破坏的 session；健康原件不被修改（一键复原 =
不施加注入 / 重新用健康 session）。
"""

import copy


def inject_truth_copy(session):
    """1-A：Odom ← Truth（逐帧抄真值）。模拟"误差链路死掉、里程计=真值"的假仪表。"""
    s = copy.deepcopy(session)
    for f in s:
        f["odom"] = {"x": f["truth"]["x"], "y": f["truth"]["y"],
                     "theta": f["truth"]["theta"]}
    return s


def inject_seq_freeze(session, start_frac=0.3, span=12):
    """1-B：在一段 online、数据仍在更新的窗口内冻结帧序号（数据动而 seq 不动）。"""
    s = copy.deepcopy(session)
    online_idx = [i for i, f in enumerate(s) if f.get("link_status") == "online"]
    if not online_idx:
        return s
    a = online_idx[int(len(online_idx) * start_frac)]
    frozen = s[a]["seq"]
    for i in range(a, min(a + span, len(s))):
        if s[i].get("link_status") == "online":
            s[i]["seq"] = frozen     # 帧序号钉死；真值/里程计照常推进（数据鲜活）
    return s


def inject_stall_running(session):
    """1-C：把健康 session 的"断流冻结段"（offline）改回 online，制造"断流却显示运行中"。"""
    s = copy.deepcopy(session)
    flipped = 0
    for f in s:
        if f.get("link_status") == "offline":
            f["link_status"] = "online"   # 数据仍冻结，却谎称在线/运行中
            flipped += 1
    if flipped == 0:
        # 健康 session 未含断流段时，兜底：在尾部制造一段冻结却 online 的陈旧帧
        last = copy.deepcopy(s[-1])
        t = last["recv_t"]
        for k in range(1, 11):
            fr = copy.deepcopy(last)
            fr["recv_t"] = round(t + k * 0.1, 3)   # 墙钟推进
            fr["link_status"] = "online"           # 数据冻结却声明在线
            s.append(fr)
    return s


INJECTORS = {
    "1-A_truth_copy": inject_truth_copy,
    "1-B_seq_freeze": inject_seq_freeze,
    "1-C_stall_running": inject_stall_running,
}

DESCRIPTIONS = {
    "1-A_truth_copy": "把 Odom 逐帧接回真值（odom←truth），复刻 ox=robot.x 波将金村",
    "1-B_seq_freeze": "数据仍在更新却冻结帧序号（帧序号撒谎）",
    "1-C_stall_running": "把断流冻结段的链路声明从 offline 改回 online（断流却显示运行中）",
}
