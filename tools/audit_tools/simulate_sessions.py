# -*- coding: utf-8 -*-
"""
simulate_sessions.py —— 教师自测：5 个模拟会话端到端跑通实验模式（FORGE-004 卡 B 随卡入仓）
============================================================================================
对真服务端走完「连接 → 证伪动作 → 平台截图 → 判定 → 导出审计包」全流程，产出的包交给
verify_pack.py / analyze_packs.py 校验与汇总——验的是**平台产生侧**。
（离线验校验器：selftest.py；离线验产生器语义、票据、限额与边界口径：exp_selftest.py。）

前置（教师机，另一终端）：
    export AUDIT_TEACHER_KEY=<自拟一次性口令>      # 只认环境变量；不要写进命令行参数或 URL
    AUDIT_EXP=1 python inference_server.py          # 或 python inference_server.py --audit-exp

本脚本同样从环境变量 AUDIT_TEACHER_KEY 读口令，经请求头 X-Audit-Teacher-Key 发送，做五轮定向会话；
截图与导出凭握手时下发的会话票据。未设口令时服务端会忽略定向参数，故本脚本直接退出。

用法：
    python tools/audit_tools/simulate_sessions.py [--server 127.0.0.1:8000]
                                                  [--outdir audit_packs_selftest] [--verify]

预期（加 --verify 时自动核对，任一不符退出码 1）：
    T01 健康轮、判「健康」            → 误报 否
    T02 注入 C1、判 C1                → 命中 是，定位正确 是
    T03 注入 C2、故意判 C3            → 命中 是，定位正确 否（检验定位准确率口径）
    T04 注入 C1、起爆前即导出         → incomplete 是，命中 否（汇总剔除，不被当成健康轮）
    T05 注入 C2、起爆前抢先判 C2      → 判定早于起爆 是，命中 否
    另核：错票据导出与截图均被拒（404）；汇总剔除未完成会话 1 个
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import audit_chain  # noqa: E402

try:
    import websockets
except ImportError:
    print("需要 websockets 库（平台核心依赖，pip install websockets）")
    sys.exit(2)

KEY_ENV = "AUDIT_TEACHER_KEY"
KEY_HEADER = "X-Audit-Teacher-Key"
# 1x1 红色 PNG（模拟平台截图上传；服务端校验 PNG、先查尺寸再解码并烧入水印）
TINY_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
                "nGP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

PLAN = [  # (uid, 定向条件, 起爆秒, 判定, 理由, 判定时机)
    ("T01", "healthy", 2, "healthy", "三项自检均无异常", "late"),
    ("T02", "C1", 2, "C1", "slip 归零后仍 odom≡truth，判假", "late"),
    ("T03", "C2", 2, "C3", "数据疑似冻结（故意误定位）", "late"),
    ("T04", "C1", 600, "C1", "起爆前即导出（未完成会话）", "late"),
    ("T05", "C2", 4, "C2", "起爆前抢先判定", "early"),
]
EXPECT = {
    "T01": {"condition": "healthy", "false_alarm": False, "incomplete": False},
    "T02": {"condition": "C1", "hit": True, "localization_correct": True},
    "T03": {"condition": "C2", "hit": True, "localization_correct": False},
    "T04": {"condition": "C1", "incomplete": True, "hit": False},
    "T05": {"condition": "C2", "verdict_before_onset": True, "hit": False},
}
AUTH_CHECKS: dict[str, bool] = {}


def _connect(url, headers):
    major = int(str(getattr(websockets, "__version__", "0")).split(".")[0] or 0)
    if major >= 14:
        return websockets.connect(url, additional_headers=headers)
    return websockets.connect(url, extra_headers=headers)          # websockets < 14 的旧参数名


def post_json(url, obj):
    req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(obj).encode("utf-8"))
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read()


def post_status(url, obj):
    try:
        return post_json(url, obj)[0]
    except urllib.error.HTTPError as e:
        return e.code


async def run_session(host, key, uid, force, onset_s, verdict, note, when, outdir):
    url = f"ws://{host}/ws?exp=1&uid={uid}&force={force}&onset={onset_s}"
    async with _connect(url, {KEY_HEADER: key}) as ws:
        session_id = ticket = None
        while session_id is None:                     # 握手可能晚于若干广播帧到达，逐条扫描
            d = json.loads(await ws.recv())
            if "exp_session" in d:
                session_id, ticket = d["exp_session"]["session_id"], d["exp_session"].get("ticket")
        print(f"[{uid}] 会话 {session_id} 定向条件={force} onset={onset_s}s 判定时机={when}")

        async def drain(seconds):
            """持续消费下行帧（C3/断流期间无帧，靠超时推进）。"""
            loop = asyncio.get_event_loop()
            end = loop.time() + seconds
            while loop.time() < end:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

        async def send_verdict():
            await ws.send(json.dumps({"student_verdict": {"choice": verdict, "note": note}}))

        if when == "early":
            await drain(0.5)
            await send_verdict()                                    # 起爆前抢先判定
        await drain(1.5)                                             # 起爆前的基线观察
        await ws.send(json.dumps({"self_test": {"action": "seq_probe"}}))
        await ws.send(json.dumps({"self_test": {"action": "slip_zero"}}))
        await drain(1.0)
        await ws.send(json.dumps({"self_test": {"action": "slip_restore"}}))
        await drain(3.5)                                             # 越过 onset，观察注入表现

        base = f"http://{host}"
        shot = {"session_id": session_id, "ticket": ticket, "panel": {"seq": 1, "feed_age_s": 0.1},
                "image": "data:image/png;base64," + TINY_PNG_B64}
        status, body = post_json(f"{base}/screenshot", shot)
        print(f"[{uid}] 截图存证: {json.loads(body).get('filename')}")
        if uid == "T01":                                             # 票据授权：只知道会话号不能操作
            AUTH_CHECKS["错票据截图被拒"] = post_status(f"{base}/screenshot", dict(shot, ticket="wrong")) == 404
            AUTH_CHECKS["错票据导出被拒"] = post_status(f"{base}/export_pack/{session_id}", {"ticket": "wrong"}) == 404
            AUTH_CHECKS["无票据导出被拒"] = post_status(f"{base}/export_pack/{session_id}", {}) == 404
        if when == "late":
            await send_verdict()
            await drain(0.5)

    status, data = post_json(f"http://{host}/export_pack/{session_id}", {"ticket": ticket})   # 导出即结束会话
    path = os.path.join(outdir, f"{uid}_{session_id}.zip")
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"[{uid}] 审计包已导出: {path} ({len(data)} bytes)")
    return uid, path


def verify(paths):
    """逐包 verify_pack 判绿；按 EXPECT 核对复算结论；核票据授权；核汇总剔除。返回是否全部符合。"""
    ok = True
    rc = subprocess.run([sys.executable, os.path.join(HERE, "verify_pack.py"), *paths.values()]).returncode
    print(f"verify_pack 退出码 {rc}（期望 0）")
    ok &= rc == 0
    records = []
    for uid, path in paths.items():
        with zipfile.ZipFile(path) as z:
            s = audit_chain.derive_summary(audit_chain.parse_events(z.read("audit_log.jsonl").decode("utf-8")))
        records.append(s)
        bad = {k: (s.get(k), v) for k, v in EXPECT[uid].items() if s.get(k) != v}
        print(f"  {'✓' if not bad else '✗'} {uid} " + ("复算结论与预期一致" if not bad else f"不符（实得, 期望）: {bad}"))
        ok &= not bad
    for name, passed in AUTH_CHECKS.items():
        print(f"  {'✓' if passed else '✗'} {name}")
        ok &= passed
    import analyze_packs
    agg = analyze_packs.aggregate(records)
    good = agg["n_incomplete_excluded"] == 1 and agg["checkpoints"]["C1"]["n"] == 1
    print(f"  {'✓' if good else '✗'} 汇总剔除未完成会话 {agg['n_incomplete_excluded']} 个，C1 计入 {agg['checkpoints']['C1']['n']} 个（期望 1、1）")
    return ok and good


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="127.0.0.1:8000")
    ap.add_argument("--outdir", default="audit_packs_selftest")
    ap.add_argument("--verify", action="store_true", help="导出后自动 verify_pack 并核对预期")
    args = ap.parse_args()
    key = os.environ.get(KEY_ENV, "")
    if not key:
        print(f"未设环境变量 {KEY_ENV}：定向注入不会生效，教师自测无从核对。请与服务端设同一口令后重跑。")
        sys.exit(2)
    os.makedirs(args.outdir, exist_ok=True)
    paths = {}
    for uid, force, onset_s, verdict, note, when in PLAN:
        uid, path = await run_session(args.server, key, uid, force, onset_s, verdict, note, when, args.outdir)
        paths[uid] = path

    print(f"\n{len(PLAN)} 个模拟会话完成。")
    if args.verify:
        good = verify(paths)
        print("端到端自测通过 ✅" if good else "端到端自测未通过 ❌")
        sys.exit(0 if good else 1)
    print(f"下一步：python tools/audit_tools/verify_pack.py {args.outdir}")
    print(f"        python tools/audit_tools/analyze_packs.py {args.outdir}")


if __name__ == "__main__":
    asyncio.run(main())
