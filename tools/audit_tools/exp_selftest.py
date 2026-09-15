# -*- coding: utf-8 -*-
"""
exp_selftest.py —— 实验模式产生侧离线红测（FORGE-004 卡 B；不需服务端、不需 torch；截图用例需 Pillow）
================================================================================================
卡 A 的 selftest.py 证明「校验器能红」；本脚本证明「产生器按规范产包，且隔离、票据、限额与边界口径成立」：

     1. 密钥纪律：无密钥或密钥不符时 force/onset 不生效，SESSION_START 如实记「请求过」；日志不含密钥与票据
     2. 注入语义：C1 起爆后下发 odom ≡ truth；C2 起爆后 seq 冻结；C3 起爆后停发
     3. 会话隔离：证伪动作只改本会话 slip，全局 env.slip_factor 与其他会话不变；slip 归零后航向差恒定
     4. 停发自检与回合复位
     5. 票据：握手下发票据；只凭会话号不可操作
     6. 截图：合法 PNG 存证留 sha256 与面板读数；非 PNG／坏 base64／无法解码／超尺寸（先查尺寸）／超配额／未知会话分别拒绝
     7. 资源：日志即开即关（批量会话后文件描述符不增长）；写盘失败时链头不动；上行消息令牌桶限流并计数
     8. 边界口径：起爆前导出 → incomplete、汇总剔除；起爆前判定 → 不计命中
     9. 产包：导出包全部被 verify_pack 判绿，复算结论符合预期；导出后会话封闭；篡改一行即判红
    10. 分发：会话渲染异常时关闭该连接（1011），普通连接照常收广播
    11. 首页注入：锚点恰好一次才构建；缺锚点即报错

用法:  python tools/audit_tools/exp_selftest.py [--keep]
退出码: 全过 0，任一未达预期 1。
"""
import argparse
import asyncio
import base64
import contextlib
import io
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import audit_chain  # noqa: E402
import experiment_mode as em  # noqa: E402
import verify_pack  # noqa: E402
import analyze_packs  # noqa: E402

KEY = "selftest-key-7f3a"
TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
                            "nGP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
TICK = 1.0 / 60.0
FAILS: list[str] = []


def check(ok, name):
    print(f"  {'✓' if ok else '✗'} {name}")
    if not ok:
        FAILS.append(name)


class StubEnv:
    """只提供实验模式读取的两个量；若被写入即暴露在 slip_factor 上。"""
    SLIP_FACTOR = 0.05
    DT = 0.1

    def __init__(self):
        self.slip_factor = 0.05


class FakeClock:
    """平台时钟替身：随模拟 tick 推进，使事件 ts 与调度时刻一致。"""

    def __init__(self):
        self.now = 0.0
        self.base = datetime(2026, 9, 15, 10, 0, 0).astimezone()

    def __call__(self):
        return (self.base + timedelta(seconds=self.now)).isoformat(timespec="milliseconds")


class FakeWS:
    def __init__(self, qp=None, headers=None):
        self.sent, self.closed_code = [], None
        self.query_params, self.headers = qp or {}, headers or {}

    async def send_text(self, text):
        self.sent.append(text)

    async def close(self, code=1000):
        self.closed_code = code


class FakeManager:
    def __init__(self, conns):
        self.active = set(conns)

    def disconnect(self, ws):
        self.active.discard(ws)


def states(n, reset_at=None, v=0.6, w=0.25, dt=0.1):
    """合成孪生状态流（每 tick 一步 env.step）：真值走定曲率，全局 odom 带固定漂移。"""
    x, y, th = 2.0, 2.0, 0.3
    ox, oy, oth = x, y, th
    seq, step = 100, 0
    for i in range(n):
        if reset_at is not None and i == reset_at:
            x, y, th = 7.0, 3.0, -1.0
            ox, oy, oth = x, y, th
            step = 0
        th = em._wrap(th + w * dt)
        x += v * math.cos(th) * dt
        y += v * math.sin(th) * dt
        oth = em._wrap(oth + w * 1.05 * dt)
        ox += v * 1.05 * math.cos(oth) * dt
        oy += v * 1.05 * math.sin(oth) * dt
        seq += 1
        step += 1
        yield {"robot": {"x": x, "y": y, "theta": th, "radius": 0.2},
               "odom": {"x": ox, "y": oy, "theta": oth},
               "seq": seq, "step": step, "control_mode": "rl"}


def png_claiming(w, h):
    """把 1x1 PNG 的 IHDR 改写成声称 w×h（重算 CRC），用于「先查尺寸再解码」的红测。"""
    b = bytearray(TINY_PNG)
    assert bytes(b[12:16]) == b"IHDR"
    b[16:20], b[20:24] = struct.pack(">I", w), struct.pack(">I", h)
    b[29:33] = struct.pack(">I", zlib.crc32(bytes(b[12:29])) & 0xFFFFFFFF)
    return bytes(b)


def data_url(raw):
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def last_event(sess):
    return json.loads(open(sess.logger.path, encoding="utf-8").read().splitlines()[-1])


def open_fds():
    return len(os.listdir("/dev/fd"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留临时目录便于排查")
    args = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="exp_selftest_")
    try:
        run(tmp)
    finally:
        if args.keep:
            print(f"\n临时目录保留：{tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"实验模式离线红测未通过（{len(FAILS)} 项）：")
        for f in FAILS:
            print("  - " + f)
        sys.exit(1)
    print(f"实验模式离线红测通过 ✅（{CHECKS[0]} 项）")


CHECKS = [0]
_orig_check = check


def check(ok, name):  # noqa: F811  计数包装
    CHECKS[0] += 1
    _orig_check(ok, name)


def run(tmp):
    env = StubEnv()
    clock = FakeClock()
    cfg = em.ExperimentConfig(environ={"AUDIT_DIR": os.path.join(tmp, "sessions"),
                                       "AUDIT_TEACHER_KEY": KEY, "AUDIT_PLATFORM_VERSION": "selftest"})
    ctx = em.ExperimentContext(env, cfg=cfg, clock=clock)

    print("[1 密钥纪律]")
    t01 = ctx.create_session("T01", force="healthy", onset="0.5", teacher_key=KEY)
    t02 = ctx.create_session("T02", force="C1", onset="0.5", teacher_key=KEY)
    t03 = ctx.create_session("T03", force="C2", onset="0.5", teacher_key=KEY)
    t04 = ctx.create_session("T04", force="C3", onset="0.5", teacher_key=KEY)
    t05 = ctx.create_session("T05", force="C1", onset="0.5", teacher_key=None)
    t06 = ctx.create_session("T06", force="C1", onset="0.5", teacher_key="wrong-key")
    check(t02.forced and t02.condition == "C1" and abs(t02.onset_s - 0.5) < 1e-12, "密钥一致：定向 C1、onset=0.5 生效")
    check((not t05.forced) and t05.onset_s >= 30.0, "无密钥：定向参数不生效（onset 仍在 30–180 s 抽签）")
    check((not t06.forced) and t06.onset_s >= 30.0, "密钥不符：定向参数不生效")
    nokey_ctx = em.ExperimentContext(env, cfg=em.ExperimentConfig(environ={
        "AUDIT_DIR": os.path.join(tmp, "sessions_nokey"), "AUDIT_PLATFORM_VERSION": "selftest"}), clock=clock)
    check(not nokey_ctx.create_session("N01", force="C1", onset="0.5", teacher_key="").forced, "服务端未设密钥：空密钥请求头也不能定向")
    start05 = json.loads(open(t05.logger.path, encoding="utf-8").readline())["payload"]
    check(start05["override_requested"] is True and start05["forced"] is False, "SESSION_START 如实记录「请求过定向但未生效」")
    check(em.sanitize_uid("S07<script>") == "S07script" and em.sanitize_uid("") == "anon", "uid 净化")

    print("[2–3 注入语义与会话隔离]")
    sessions = [t01, t02, t03, t04]
    outs = {s.uid: [] for s in sessions}
    heading_err_after_zero = []
    for i, st in enumerate(states(240)):
        clock.now = i * TICK
        if i == 60:
            t01.handle_self_test("slip_zero", clock.now)
        for s in sessions:
            text = s.render_for_student(st, clock.now)
            outs[s.uid].append((clock.now, st, None if text is None else json.loads(text)))
        if i > 61:
            o = outs["T01"][-1][2]
            heading_err_after_zero.append(em._wrap(o["odom"]["theta"] - st["robot"]["theta"]))
    post = lambda uid: [(st, o) for (t, st, o) in outs[uid] if t >= 0.5 + TICK]          # noqa: E731
    pre = lambda uid: [(st, o) for (t, st, o) in outs[uid] if t < 0.5]                    # noqa: E731
    check(all(o is not None and o["odom"]["x"] == st["robot"]["x"] and o["odom"]["y"] == st["robot"]["y"]
              and o["odom"]["theta"] == st["robot"]["theta"] for st, o in post("T02")), "C1 起爆后下发 odom ≡ truth（逐位）")
    check(any(abs(o["odom"]["x"] - st["robot"]["x"]) > 1e-6 for st, o in pre("T02")), "C1 起爆前 odom 与真值确有分叉")
    check(len({o["seq"] for st, o in post("T03")}) == 1 and all(o["seq"] != st["seq"] for st, o in post("T03")[1:]), "C2 起爆后 seq 冻结")
    check(all(o is None for st, o in post("T04")) and all(o is not None for st, o in pre("T04")), "C3 起爆后停发、起爆前正常下发")
    check(not any(o is None for st, o in post("T01")), "健康轮不注入、不停发")
    check(env.slip_factor == 0.05, "证伪动作后全局 env.slip_factor 未被改写（0.05）")
    check(t01.odometry.slip == 0.0 and t02.odometry.slip == 0.05, "slip 归零只作用于本会话（T01=0，T02 仍 0.05）")
    spread = max(heading_err_after_zero) - min(heading_err_after_zero)
    check(spread < 1e-9, f"slip 归零后航向差恒定（波动 {spread:.2e} rad）")
    t01.handle_self_test("slip_restore", clock.now)
    check(t01.odometry.slip == 0.05, "slip_restore 恢复本会话默认值")

    print("[4 停发自检与回合复位]")
    t07 = ctx.create_session("T07", force="healthy", onset="0", teacher_key=KEY)
    got = []
    for i, st in enumerate(states(400, reset_at=300)):
        clock.now = 10.0 + i * TICK
        if i == 10:
            t07.handle_self_test("feed_cut", clock.now)
        text = t07.render_for_student(st, clock.now)
        got.append((i, st, None if text is None else json.loads(text)))
    check(all(o is None for i, st, o in got if 11 <= i < 10 + int(3.0 / TICK)) and got[10 + int(3.0 / TICK) + 2][2] is not None,
          "feed_cut 本会话停发 3 s 后恢复")
    _, st_r, o_r = got[300]
    check(o_r is not None and o_r["odom"]["x"] == st_r["robot"]["x"] and o_r["odom"]["y"] == st_r["robot"]["y"], "回合复位帧：会话里程计对齐真值")

    print("[5 票据]")
    ws_h = FakeWS(qp={"exp": "1", "uid": "H01"})
    s_h = asyncio.run(ctx.open_session(ws_h))
    shake = json.loads(ws_h.sent[0])["exp_session"]
    check(s_h is not None and shake.get("ticket") == s_h.ticket and len(s_h.ticket) == 32, "握手下发 32 位票据")
    check(asyncio.run(ctx.open_session(FakeWS(qp={}))) is None, "不带 ?exp=1 的连接不建会话、不发握手")
    check(s_h.check_ticket(s_h.ticket) and not s_h.check_ticket("wrong") and not s_h.check_ticket(None), "票据比对：对的通过，错的与缺失的拒绝")

    print("[6 截图]")
    code, body = em.save_screenshot(t02, data_url(TINY_PNG), panel={"seq": 7, "feed_age_s": 0.44, "junk": "x"})
    ev = last_event(t02)
    check(code == 200 and body["ok"] and ev["event"] == "SCREENSHOT" and len(ev["payload"].get("sha256", "")) == 64
          and ev["payload"].get("watermark") is True, "合法 PNG 存证 200，事件含 sha256 且已烧水印")
    check(ev["payload"].get("page_panel") == {"seq": 7, "feed_age_s": 0.44}, "截图事件附页面面板读数（净化后）")
    check(em.save_screenshot(t02, base64.b64encode(b"GIF89a....").decode())[0] == 400, "非 PNG 拒绝 400")
    check(em.save_screenshot(t02, "@@not-base64@@")[0] == 400, "坏 base64 拒绝 400")
    check(em.save_screenshot(t02, data_url(em.PNG_MAGIC + b"garbage-garbage"))[0] == 400, "PNG 头加垃圾字节：无法解码加水印，拒绝 400")
    check(em.save_screenshot(t02, data_url(png_claiming(5000, 5000)))[0] == 413, "声称 5000×5000：先查尺寸即拒绝 413（不解码）")
    check(em.save_screenshot(t02, data_url(png_claiming(4097, 10)))[0] == 413, "单边超 4096：拒绝 413")
    saved = t02.n_shots
    t02.n_shots = em.MAX_SCREENSHOTS_PER_SESSION
    check(em.save_screenshot(t02, data_url(TINY_PNG))[0] == 429, f"超每会话 {em.MAX_SCREENSHOTS_PER_SESSION} 张配额：拒绝 429")
    t02.n_shots = saved
    check(em.save_screenshot(None, "x")[0] == 404, "未知会话拒绝 404")

    print("[7 资源]")
    before = open_fds()
    bulk_ctx = em.ExperimentContext(env, cfg=em.ExperimentConfig(environ={
        "AUDIT_DIR": os.path.join(tmp, "bulk"), "AUDIT_PLATFORM_VERSION": "selftest"}), clock=clock)
    for k in range(40):
        s = bulk_ctx.create_session(f"B{k:02d}")
        for j in range(5):
            s.logger.log("TELEMETRY", {"j": j})
    after = open_fds()
    check(after - before <= 2, f"40 个会话各写 6 行后文件描述符增长 {after - before}（日志即开即关，期望 ≤2）")
    probe = bulk_ctx.create_session("P01")
    prev, n0 = probe.logger.prev_hash, probe.logger.n_lines

    def failing_open(*a, **k):
        raise OSError("模拟写盘失败")
    em.open = failing_open
    try:
        try:
            probe.logger.log("TELEMETRY", {"x": 1})
            raised = False
        except OSError:
            raised = True
    finally:
        del em.open
    check(raised and probe.logger.prev_hash == prev and probe.logger.n_lines == n0, "写盘失败：异常上抛，链头与行数不动")
    probe.logger.log("TELEMETRY", {"x": 2})
    ok_chain = audit_chain.verify_chain(open(probe.logger.path, encoding="utf-8").read())[0]
    check(ok_chain, "写盘失败之后再写：哈希链仍完整")
    rl = bulk_ctx.create_session("R01")
    for _ in range(100):
        bulk_ctx.handle_client_message(rl, {"self_test": {"action": "seq_probe"}}, 5.0)
    n_tests = sum(1 for line in open(rl.logger.path, encoding="utf-8") if '"SELF_TEST"' in line)
    check(n_tests == int(em.MSG_BURST) and rl.dropped_messages == 100 - int(em.MSG_BURST), f"同一瞬间 100 条上行：放行 {n_tests}（突发上限 {int(em.MSG_BURST)}），丢弃 {rl.dropped_messages}")
    bulk_ctx.handle_client_message(rl, {"self_test": {"action": "seq_probe"}}, 6.0)
    rl.finalize("export")
    check(last_event(rl)["payload"].get("dropped_messages") == 100 - int(em.MSG_BURST), "丢弃计数记入 SESSION_END")
    check(bulk_ctx.handle_client_message(rl, {"cmd_vel": {}}, 7.0) is None and rl.dropped_messages == 100 - int(em.MSG_BURST), "非实验消息不占令牌、不计丢弃")

    print("[8 边界口径]")
    t08 = ctx.create_session("T08", force="C1", onset="100", teacher_key=KEY)
    for i, st in enumerate(states(30)):
        clock.now = 20.0 + i * TICK
        t08.render_for_student(st, clock.now)
    t08.handle_verdict("C1", "起爆前就导出")
    t09 = ctx.create_session("T09", force="C2", onset="1.0", teacher_key=KEY)
    for i, st in enumerate(states(120)):
        clock.now = 30.0 + i * TICK
        if i == 15:
            t09.handle_verdict("C2", "起爆前抢先判定")
        t09.render_for_student(st, clock.now)

    print("[9 判定、导出与复算]")
    for s, choice in ((t01, "healthy"), (t02, "C1"), (t03, "C3"), (t04, "C3"), (t05, "healthy")):
        s.handle_verdict(choice, "自测判定")
    packs = os.path.join(tmp, "packs")
    os.makedirs(packs)
    paths = {}
    for s in (t01, t02, t03, t04, t05, t08, t09):
        fname, data = em.build_pack(s)
        paths[s.uid] = os.path.join(packs, fname)
        with open(paths[s.uid], "wb") as fh:
            fh.write(data)
    with contextlib.redirect_stdout(io.StringIO()):
        results = {uid: verify_pack.verify_one(p) for uid, p in paths.items()}
    check(all(results.values()), f"导出包全部被 verify_pack 判绿（{sum(results.values())}/{len(results)}）")
    expect = {"T01": {"condition": "healthy", "false_alarm": False, "incomplete": False},
              "T02": {"condition": "C1", "hit": True, "localization_correct": True, "n_screenshots": 1},
              "T03": {"condition": "C2", "hit": True, "localization_correct": False},
              "T04": {"condition": "C3", "hit": True, "localization_correct": True},
              "T08": {"condition": "C1", "incomplete": True, "hit": False, "false_alarm": False},
              "T09": {"condition": "C2", "verdict_before_onset": True, "hit": False, "detect_latency_ms": None}}
    summaries = {}
    for uid, exp in expect.items():
        with zipfile.ZipFile(paths[uid]) as z:
            summ = json.loads(z.read("summary.json"))
        summaries[uid] = summ
        bad = {k: (summ.get(k), v) for k, v in exp.items() if summ.get(k) != v}
        check(not bad, f"{uid} 复算结论符合预期" + (f"：{bad}" if bad else ""))
    end08 = json.loads(open(t08.logger.path, encoding="utf-8").read().splitlines()[-1])["payload"]
    check(end08.get("assigned_condition") == "C1" and end08.get("injected") is False and end08.get("scheduled_onset_ms") == 100000,
          "起爆前导出：SESSION_END 记下分配条件、未起爆、计划起爆时刻")
    agg = analyze_packs.aggregate([summaries[u] for u in ("T01", "T02", "T03", "T04", "T08", "T09")])
    check(agg["n_incomplete_excluded"] == 1 and agg["checkpoints"]["C1"]["n"] == 1 and agg["checkpoints"]["C2"]["n"] == 2
          and agg["checkpoints"]["C2"]["detected"] == 1 and agg["n_verdict_before_onset"] == 1,
          "汇总：剔除未完成会话 1 个；判定早于起爆计入分母不计命中")
    n_before = t02.logger.n_lines
    t02.handle_verdict("healthy", "导出后试图改判")
    check(t02.ended and t02.logger.n_lines == n_before and t02.render_for_student(st_r, 99.0) is None, "导出即结束会话：不再下发、不再接受判定")
    all_logs = b"".join(open(os.path.join(r, f), "rb").read() for r, _, fs in os.walk(os.path.join(tmp, "sessions")) for f in fs if f.endswith(".jsonl"))
    check(KEY.encode() not in all_logs and t02.ticket.encode() not in all_logs, "审计日志不含教师密钥与会话票据")
    bad_path = os.path.join(packs, "tampered.zip")
    with zipfile.ZipFile(paths["T02"]) as zin, zipfile.ZipFile(bad_path, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "audit_log.jsonl":
                lines = data.decode("utf-8").splitlines()
                rec = json.loads(lines[1])
                rec["payload"] = dict(rec["payload"], action="tampered")
                lines[1] = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                data = ("\n".join(lines) + "\n").encode("utf-8")
            zout.writestr(item, data)
    with contextlib.redirect_stdout(io.StringIO()):
        tampered_ok = verify_pack.verify_one(bad_path)
    check(tampered_ok is False, "篡改一行日志 → verify_pack 判红")

    print("[10 分发]")
    s_bad = ctx.create_session("T11", force="healthy", onset="0", teacher_key=KEY)
    ws_bad, ws_plain = FakeWS(), FakeWS()
    ctx.by_ws[ws_bad] = s_bad

    def boom(state, now):
        raise RuntimeError("模拟渲染异常")
    s_bad.render_for_student = boom
    mgr = FakeManager([ws_bad, ws_plain])
    with contextlib.redirect_stderr(io.StringIO()):
        asyncio.run(ctx.distribute(mgr, next(states(1)), "BASE", 0.0))
    check(ws_plain.sent == ["BASE"], "普通连接照常收统一广播")
    check(ws_bad.closed_code == 1011 and ws_bad not in mgr.active and ws_bad not in ctx.by_ws, "渲染异常的实验连接被关闭（1011）并移出广播与会话映射")

    print("[11 首页注入]")
    built = em.build_exp_html("<html><head><title>x</title></head><body><p>x</p></body></html>")
    check(built.count("exp-panel") >= 1 and built.count("</head>") == 1 and built.count("</body>") == 1, "锚点恰好一次：构建成功且锚点不重复")
    try:
        em.build_exp_html("<html><body></body></html>")
        check(False, "缺 </head> 锚点应报错")
    except ValueError:
        check(True, "缺 </head> 锚点即报错")


if __name__ == "__main__":
    main()
