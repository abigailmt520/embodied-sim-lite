# -*- coding: utf-8 -*-
"""
capture_offline.py  ——  动作1 · 1-C 真实浏览器 OFFLINE 截图（headless Chrome via CDP）
======================================================================================
驱动**真实**的 inference_server 前端，复现"WS 断流 → 前端冻结并显示 OFFLINE"并截图：
    1) 启动真实 inference_server（不改一行前端代码）；
    2) headless Chrome 打开页面，等待 WS 连上、画面渲染、状态=在线；
    3) **杀掉服务端**制造真实断流 → 触发前端 ws.onclose → setOffline() 冻结遮罩；
    4) 截图保存。

这是对真实前端真实断流行为的捕获，非伪造页面（守 INV-2）。
依赖：仅需系统 Chrome + 标准库 + websockets（CDP 通信），无需 selenium/playwright。

运行：python audit/capture_offline.py
产物：audit/offline_screenshot.png
"""

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SERVER_PORT = 8000
CDP_PORT = 9222
URL = f"http://localhost:{SERVER_PORT}/"
OUT = os.path.join(HERE, "offline_screenshot.png")


def _wait_http(url, timeout=25):
    for _ in range(int(timeout * 2)):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def cmd(self, method, **params):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} error: {msg['error']}")
                return msg.get("result", {})

    async def eval_js(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr, returnByValue=True)
        return r.get("result", {}).get("value")


async def drive(server_proc):
    # 取页面 target 的 CDP ws 地址
    targets = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{CDP_PORT}/json").read().decode())
    page = next((t for t in targets if t.get("type") == "page"), targets[0])
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=None) as ws:
        cdp = CDP(ws)
        await cdp.cmd("Page.enable")
        await cdp.cmd("Runtime.enable")
        await cdp.cmd("Emulation.setDeviceMetricsOverride",
                      width=1600, height=900, deviceScaleFactor=1, mobile=False)
        await cdp.cmd("Page.navigate", url=URL)

        # 等待 WS 连上、画面在线（wsStatus 含"在线"）
        online = False
        for _ in range(30):
            await asyncio.sleep(0.5)
            txt = await cdp.eval_js(
                "(document.getElementById('wsStatus')||{}).innerText || ''")
            if txt and ("在线" in txt or "online" in txt.lower()):
                online = True
                break
        print(f"  [chrome] 连接状态文本: online={online}")
        await asyncio.sleep(1.5)   # 多收几帧，机器人/雷达渲染稳定

        # —— 制造真实断流：杀掉服务端 ——
        print("  [server] 杀掉服务端，制造真实 WS 断流…")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except Exception:
            server_proc.kill()

        # 等待前端 onclose → OFFLINE 遮罩出现
        offline = False
        for _ in range(20):
            await asyncio.sleep(0.4)
            disp = await cdp.eval_js(
                "(document.getElementById('offline-overlay')||{}).style?"
                ".display || ''")
            status = await cdp.eval_js(
                "(document.getElementById('wsStatus')||{}).innerText || ''")
            epi = await cdp.eval_js(
                "(document.getElementById('epi_status')||{}).innerText || ''")
            if disp == "flex" or "OFFLINE" in (status or "") or "OFFLINE" in (epi or ""):
                offline = True
                print(f"  [chrome] OFFLINE 已触发: overlay.display={disp!r} "
                      f"status={status!r} epi={epi!r}")
                break
        if not offline:
            print("  [warn] 未检测到 OFFLINE 状态（仍截图当前画面以供检查）")
        await asyncio.sleep(0.8)

        shot = await cdp.cmd("Page.captureScreenshot", format="png",
                             captureBeyondViewport=False)
        with open(OUT, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print(f"  [OK] 截图已保存: {OUT}")
        return offline


def main():
    if not os.path.exists(CHROME):
        print(f"[ERR] 未找到 Chrome: {CHROME}")
        sys.exit(1)

    # 1) 启动真实服务端
    print("[1/3] 启动真实 inference_server …")
    server = subprocess.Popen([sys.executable, "inference_server.py"], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _wait_http(f"http://127.0.0.1:{SERVER_PORT}/health"):
        server.kill()
        print("[ERR] 服务端未就绪")
        sys.exit(1)
    print("      服务端就绪。")

    # 2) 启动 headless Chrome（独立 user-data-dir，开远程调试）
    print("[2/3] 启动 headless Chrome …")
    profile = tempfile.mkdtemp(prefix="cdp_chrome_")
    chrome = subprocess.Popen([
        CHROME, "--headless=new", f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}", "--window-size=1600,900",
        "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
        "--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _wait_http(f"http://127.0.0.1:{CDP_PORT}/json/version"):
        chrome.kill(); server.kill(); shutil.rmtree(profile, ignore_errors=True)
        print("[ERR] Chrome CDP 未就绪")
        sys.exit(1)

    # 3) 驱动 + 截图
    print("[3/3] 驱动页面、断流、截图 …")
    ok = False
    try:
        ok = asyncio.run(drive(server))
    finally:
        for p in (server, chrome):
            try:
                p.terminate(); p.wait(timeout=3)
            except Exception:
                p.kill()
        shutil.rmtree(profile, ignore_errors=True)
    print(f"\n结果：OFFLINE 截图{'成功' if ok else '已生成(请人工核对 OFFLINE 是否可见)'} → {OUT}")


if __name__ == "__main__":
    main()
