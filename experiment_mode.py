# -*- coding: utf-8 -*-
"""
experiment_mode.py —— 过程性证据采集·平台侧：实验模式（FORGE-004 任务六卡 B；加法＋默认关闭）
==================================================================================================
本模块是审计包的**产生侧**；校验与汇总侧是 audit_chain.py 与 tools/audit_tools/（卡 A）。
包格式、哈希链与复算口径以 docs/audit_pack_spec.md 为准（§9 专述本模块）。

一、开关与隔离（ITERATION.md §2「加法＋开关」）
    - 总开关在 inference_server.py：命令行 `--audit-exp` 或环境变量 `AUDIT_EXP=1`。
      未开启时 inference_server.py **不导入本模块**、不注册新路由、首页与 /health 原样，
      即开关关闭态与本模块引入前逐字节一致。
    - 开启后，只有 WebSocket URL 带 `?exp=1` 的连接才建立实验会话；普通观测窗与 ROS 2 桥接
      照旧收统一广播，字节不变。
    - 会话内的一切改写（注入、证伪动作、里程计）只作用于**该连接的下发文本**；
      本模块从不写全局孪生 env 的任何属性——多名学生同时做 slip 归零也互不干扰。

二、双盲与密钥
    - 注入类型与起爆时刻由会话种子决定（os.urandom 生成），INJECT 事件只落盘、不下发。
    - 教师自测的定向注入（URL 参数 force / onset）只在请求头 `X-Audit-Teacher-Key`
      与环境变量 `AUDIT_TEACHER_KEY` 一致时生效；密钥只认环境变量，不写日志、不打印。
      学生自带 force 参数不会生效，但「请求过定向注入」会如实记入 SESSION_START。
    - 部署前提：服务端运行在教师机，学生只经浏览器连入，审计目录对学生不可读；
      学生本机自跑服务端时可直接读到 INJECT 落盘，双盲不成立。

三、环境变量（全部可选）
    AUDIT_DIR               会话目录根，默认 audit_sessions（运行产物，已 gitignore）
    AUDIT_INJECT            1（默认）开注入调度；0 只留痕不注入（全部为健康轮）
    AUDIT_HEALTHY_WEIGHT    健康轮权重，默认 0.25，取值 [0, 1]
    AUDIT_ONSET_MIN_S / AUDIT_ONSET_MAX_S   起爆时刻均匀分布区间，默认 30 / 180 秒
    AUDIT_TEACHER_KEY       教师自测密钥；不设则定向注入一律不生效
    AUDIT_PLATFORM_VERSION  写入 MANIFEST 的平台版本；不设则取 git describe

四、资源与完整性（FORGE-004 复核修复）
    - 会话票据：握手下发一次性票据（不显示），截图与导出端点凭票据授权；只知道会话号不能结束或导出他人会话。
    - 限额：请求体按流读取封顶；每会话截图 ≤60 张；图片边长 ≤4096、像素 ≤16,777,216，先查尺寸再解码；无法烧水印的图拒收；
      上行消息令牌桶 10 条/秒、突发 20 条，超出丢弃并计数；水印与打包移到工作线程，不阻塞心跳。
    - 日志即开即关，不长期占用文件句柄；写盘成功后才推进哈希链头。
    - 未起爆即结束的会话，`SESSION_END` 记下分配条件与计划起爆时刻，复算时标 incomplete、汇总剔除。

依赖：标准库 ＋ audit_chain；截图水印需要 Pillow（缺失时截图端点返回 503，不存无水印的图）。
"""
import asyncio
import base64
import binascii
import hashlib
import hmac
import io
import json
import math
import os
import random
import re
# 随机源统一用 os.urandom（系统密码学随机源），见 ExperimentSession.__init__
import subprocess
import sys
import time
import zipfile
from datetime import datetime

import audit_chain

INJECT_TYPES = ("C1", "C2", "C3")          # 与 audit/integrity_audit.py 三检查点一一对应
FEED_CUT_S = 3.0                           # feed_cut 自检：本会话停发时长（秒）
TELEMETRY_PERIOD_S = 1.0                   # TELEMETRY 抽稀周期（秒）
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024     # 单张截图上限（解码后字节）
TEACHER_KEY_HEADER = "x-audit-teacher-key"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_SCREENSHOTS_PER_SESSION = 60           # 每会话截图张数上限
MAX_IMAGE_SIDE = 4096                      # 截图单边像素上限
MAX_IMAGE_PIXELS = 4096 * 4096             # 截图像素总数上限（先查尺寸再解码）
MAX_BODY_BYTES = (MAX_SCREENSHOT_BYTES * 4) // 3 + 64 * 1024   # 请求体按流读取的封顶字节数
MSG_RATE_PER_S = 10.0                      # 上行消息令牌桶：每秒补充
MSG_BURST = 20.0                           # 上行消息令牌桶：突发上限
_UID_RE = re.compile(r"[^A-Za-z0-9_-]")
_OFF_WORDS = ("0", "false", "no", "off")


def platform_ts() -> str:
    """平台时钟（审计包唯一时间源）：本地时区 ISO 8601，毫秒精度。"""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def sanitize_uid(raw) -> str:
    """匿名代号只保留字母、数字、下划线、连字符，最长 32；为空则 anon。代号不得是真实姓名或学号。"""
    return _UID_RE.sub("", str(raw or ""))[:32] or "anon"


def _wrap(a: float) -> float:
    """角度归一化到 [-π, π)，与 embodied_env.EmbodiedNavEnv._wrap_angle 同式。"""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _detect_platform_version() -> str:
    """平台版本（仅写入 MANIFEST 作附注，不参与复算比对）：git describe，失败即 unknown。"""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        p = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=here,
                           capture_output=True, text=True, timeout=3)
        v = p.stdout.strip()
        return v if p.returncode == 0 and v else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# ====================================================================
# 配置：全部读自环境变量（密钥只认环境变量）
# ====================================================================
class ExperimentConfig:
    """实验模式参数。越界或非法值回落默认，并记入 notes（启动时打印，便于教师发现配置错）。"""

    def __init__(self, environ=None):
        e = os.environ if environ is None else environ
        self.notes: list[str] = []
        self.audit_dir = (e.get("AUDIT_DIR") or "").strip() or "audit_sessions"
        self.inject_enabled = (e.get("AUDIT_INJECT") or "1").strip().lower() not in _OFF_WORDS
        self.healthy_weight = self._float(e, "AUDIT_HEALTHY_WEIGHT", 0.25, 0.0, 1.0)
        self.onset_min_s = self._float(e, "AUDIT_ONSET_MIN_S", 30.0, 0.0, None)
        self.onset_max_s = self._float(e, "AUDIT_ONSET_MAX_S", 180.0, 0.0, None)
        if self.onset_max_s < self.onset_min_s:
            self.notes.append(f"AUDIT_ONSET_MIN_S={self.onset_min_s:g} 大于 AUDIT_ONSET_MAX_S="
                              f"{self.onset_max_s:g}，已回落默认 30–180 s")
            self.onset_min_s, self.onset_max_s = 30.0, 180.0
        self.teacher_key = e.get("AUDIT_TEACHER_KEY") or ""          # 不打印、不落盘
        self.platform_version = ((e.get("AUDIT_PLATFORM_VERSION") or "").strip()
                                 or _detect_platform_version())

    def _float(self, e, name, default, lo, hi):
        raw = (e.get(name) or "").strip()
        if not raw:
            return default
        try:
            v = float(raw)
        except ValueError:
            self.notes.append(f"{name} 不是数值，已用默认 {default:g}")
            return default
        if not math.isfinite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
            self.notes.append(f"{name}={v:g} 越界，已用默认 {default:g}")
            return default
        return v


# ====================================================================
# 审计日志：一行一事件，行间哈希链（规范唯一实现在 audit_chain.py）
# ====================================================================
class AuditLogger:
    """每次写入即开即关（不长期占用文件句柄）；写盘成功后才推进哈希链头，写失败时链头不动。"""

    def __init__(self, root: str, uid: str, session_id: str, clock):
        self.dir = os.path.join(root, f"{uid}_{session_id}")
        self.shots_dir = os.path.join(self.dir, "screenshots")
        os.makedirs(self.shots_dir, exist_ok=True)
        self.path = os.path.join(self.dir, "audit_log.jsonl")
        self.uid, self.session_id, self._clock = uid, session_id, clock
        self.prev_hash = audit_chain.GENESIS
        self.n_lines = 0
        self.closed = False
        with open(self.path, "x", encoding="utf-8"):     # x：同名日志已存在即报错，绝不续写他人日志
            pass

    def log(self, event: str, payload: dict | None = None):
        if self.closed:
            return
        core = {"ts": self._clock(), "session_id": self.session_id, "uid": self.uid,
                "event": event, "payload": payload or {}}
        line, new_hash = audit_chain.make_line(core, self.prev_hash)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self.prev_hash = new_hash                           # 写盘成功之后才推进
        self.n_lines += 1

    def close(self):
        self.closed = True


# ====================================================================
# 会话自有里程计：证伪动作只改本会话，不碰全局孪生
# ====================================================================
class SessionOdometry:
    """与 embodied_env.EmbodiedNavEnv._integrate_odom 同一模型，按会话独立积分。

        v_odom = v(1+slip) + N(0, slip)·|v|      w_odom = w(1+slip) + N(0, slip)·|w|

    (v, w) 由相邻两帧真值位姿反解：真值积分为半隐式 unicycle（先转向后平移），故
    w = wrap(θ' − θ)/DT、v = |Δpos|/DT 恰为该步施加的真实速度。噪声取会话自有 RNG（由会话种子派生，
    可复现）。回合复位（step 归零后重计）时按 env.reset 口径把里程计对齐真值。
    """

    def __init__(self, slip: float, dt: float, rng: random.Random):
        self.slip = float(slip)
        self.dt = float(dt)
        self._rng = rng
        self._prev = None                  # (x, y, θ, seq, step)
        self.x = self.y = self.theta = 0.0

    def update(self, state: dict) -> dict:
        r = state["robot"]
        x, y, th = float(r["x"]), float(r["y"]), float(r["theta"])
        seq, step = int(state.get("seq", 0)), int(state.get("step", 0))
        if self._prev is None:
            o = state.get("odom") or r      # 首帧承接全局里程计，与普通观测窗所见连续
            self.x, self.y, self.theta = float(o["x"]), float(o["y"]), float(o["theta"])
        elif step <= self._prev[4] or seq <= self._prev[3]:
            self.x, self.y, self.theta = x, y, th          # 回合复位：对齐真值（与 env.reset 同口径）
        else:
            n = max(1, seq - self._prev[3])                # 正常为 1；漏帧时按帧数均摊
            w = _wrap(th - self._prev[2]) / (n * self.dt)
            v = math.hypot(x - self._prev[0], y - self._prev[1]) / (n * self.dt)
            for _ in range(n):
                self._integrate(v, w)
        self._prev = (x, y, th, seq, step)
        return {"x": self.x, "y": self.y, "theta": self.theta}

    def _integrate(self, v: float, w: float):
        s = self.slip
        if s <= 0.0:
            vo, wo = v, w                                  # 退化档：与真值同式，不抽随机数
        else:
            vo = v * (1.0 + s) + self._rng.gauss(0.0, s) * abs(v)
            wo = w * (1.0 + s) + self._rng.gauss(0.0, s) * abs(w)
        self.theta = _wrap(self.theta + wo * self.dt)
        self.x += vo * math.cos(self.theta) * self.dt
        self.y += vo * math.sin(self.theta) * self.dt


# ====================================================================
# 单个实验会话：注入调度 + 学生可见状态改写 + 事件留痕
# ====================================================================
class ExperimentSession:
    def __init__(self, ctx, uid: str, force=None, onset=None, override_ok: bool = False):
        cfg = ctx.cfg
        self.ctx = ctx
        self.uid = uid
        self.session_id = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(4).hex()
        self.seed = int.from_bytes(os.urandom(4), "big")
        rng = random.Random(self.seed)
        # 抽签顺序固定（不论是否定向）：事后可凭日志里的 seed 独立复算本会话的条件与起爆时刻
        u, k, onset_draw = rng.random(), rng.randrange(3), rng.uniform(cfg.onset_min_s, cfg.onset_max_s)
        requested = force not in (None, "") or onset not in (None, "")
        self.forced = False

        if override_ok and (force in INJECT_TYPES or force == "healthy"):
            self.condition, self.forced = force, True
        elif not cfg.inject_enabled:
            self.condition = "healthy"
        else:
            self.condition = "healthy" if u < cfg.healthy_weight else INJECT_TYPES[k]

        self.onset_s = onset_draw
        if override_ok and onset not in (None, ""):
            try:
                v = float(onset)
                if math.isfinite(v) and v >= 0.0:
                    self.onset_s, self.forced = v, True
            except (TypeError, ValueError):
                pass

        self.odometry = SessionOdometry(ctx.default_slip, ctx.dt, random.Random(f"odom-{self.seed}"))
        self.logger = AuditLogger(cfg.audit_dir, uid, self.session_id, ctx.clock)
        self.t0 = None
        self.injected = False
        self.frozen_seq = None
        self.last_sent: dict | None = None
        self.last_send_t: float | None = None
        self.suppress_until = 0.0
        self.last_telemetry_t: float | None = None
        self.slip_backup: float | None = None
        self.ended = False
        self.ticket = os.urandom(16).hex()                  # 会话票据：只在握手中下发一次，不显示、不落盘
        self.n_shots = 0
        self.dropped_messages = 0
        self._bucket = MSG_BURST
        self._bucket_t: float | None = None
        self.logger.log("SESSION_START", {
            "mode": "exp", "seed": self.seed, "uid": uid,
            "inject_enabled": cfg.inject_enabled,
            "healthy_weight": cfg.healthy_weight,
            "onset_window_s": [cfg.onset_min_s, cfg.onset_max_s],
            "slip": self.odometry.slip,
            "platform_version": cfg.platform_version,
            "override_requested": bool(requested),
            "forced": self.forced,
        })

    # ---- 每 tick：会话里程计 → 注入起爆 → 状态改写 → 1Hz 遥测 → 返回下发文本（None＝本 tick 停发）----
    def render_for_student(self, state: dict, now: float) -> str | None:
        if self.ended:
            return None
        if self.t0 is None:
            self.t0 = now
        elapsed = now - self.t0
        view = dict(state)
        view["odom"] = self.odometry.update(state)          # 停发期间也照常积分

        if (not self.injected) and self.condition != "healthy" and elapsed >= self.onset_s:
            self.injected = True
            self.frozen_seq = state.get("seq")
            self.logger.log("INJECT", {"type": self.condition,
                                       "onset_ms": int(elapsed * 1000),
                                       "scheduled_onset_ms": int(self.onset_s * 1000),
                                       "params": self._inject_params()})

        out: dict | None = view
        if self.injected:
            if self.condition == "C1":                      # 里程计接回真值：真分叉链路被杀死
                out = dict(view)
                r = state["robot"]
                out["odom"] = {"x": r["x"], "y": r["y"], "theta": r["theta"]}
            elif self.condition == "C2":                    # 帧序号冻结：数据在动，seq 停在起爆时刻
                out = dict(view)
                out["seq"] = self.frozen_seq
            else:                                           # C3 断流：整流停发，连接仍在（前端仍称在线）
                out = None
        if out is not None and now < self.suppress_until:
            out = None                                      # feed_cut 自检窗口内停发

        if self.last_telemetry_t is None or now - self.last_telemetry_t >= TELEMETRY_PERIOD_S:
            self.last_telemetry_t = now
            src = out if out is not None else (self.last_sent or view)
            base_t = self.last_send_t if self.last_send_t is not None else self.t0
            self.logger.log("TELEMETRY", {
                "truth_xy": [round(src["robot"]["x"], 3), round(src["robot"]["y"], 3)],
                "odom_xy": [round(src["odom"]["x"], 3), round(src["odom"]["y"], 3)],
                "seq": src.get("seq"),
                "feed_age_ms": 0 if out is not None else int((now - base_t) * 1000),
                "slip": self.odometry.slip,
            })

        if out is None:
            return None
        self.last_sent = out
        self.last_send_t = now
        return json.dumps(out, separators=(",", ":"))

    def check_ticket(self, value) -> bool:
        return isinstance(value, str) and hmac.compare_digest(value.encode("utf-8"), self.ticket.encode("utf-8"))

    def allow_message(self, now: float) -> bool:
        """上行消息令牌桶：超出速率的消息丢弃并计数（计数在 SESSION_END 落盘）。"""
        if self._bucket_t is None:
            self._bucket_t = now
        self._bucket = min(MSG_BURST, self._bucket + max(0.0, now - self._bucket_t) * MSG_RATE_PER_S)
        self._bucket_t = now
        if self._bucket >= 1.0:
            self._bucket -= 1.0
            return True
        self.dropped_messages += 1
        return False

    def _inject_params(self) -> dict:
        if self.condition == "C1":
            return {"fake": "odom_rewired_to_truth"}
        if self.condition == "C2":
            return {"fake": "seq_frozen", "frozen_seq": self.frozen_seq}
        return {"fake": "feed_stalled_while_claiming_online"}

    # ---- 三个标准自检动作（spec §6），只作用于本会话 ----
    def handle_self_test(self, action: str, now: float):
        if self.ended:
            return
        if action == "slip_zero":
            if self.slip_backup is None:
                self.slip_backup = self.odometry.slip
            self.odometry.slip = 0.0
            payload = {"action": "slip_zero", "scope": "session",
                       "slip_before": self.slip_backup, "slip_after": 0.0}
        elif action == "slip_restore":
            restored = self.slip_backup if self.slip_backup is not None else self.ctx.default_slip
            self.odometry.slip = restored
            self.slip_backup = None
            payload = {"action": "slip_restore", "scope": "session", "slip_after": restored}
        elif action == "feed_cut":
            self.suppress_until = now + FEED_CUT_S
            payload = {"action": "feed_cut", "scope": "session", "duration_ms": int(FEED_CUT_S * 1000)}
        elif action == "seq_probe":
            s = self.last_sent or {}
            payload = {"action": "seq_probe", "scope": "session", "seq": s.get("seq"), "step": s.get("step")}
        else:
            return
        self.logger.log("SELF_TEST", payload)

    def handle_verdict(self, choice: str, note: str):
        if self.ended:
            return
        choice = choice if choice in ("healthy",) + INJECT_TYPES else "healthy"
        self.logger.log("STUDENT_VERDICT", {
            "verdict": "healthy" if choice == "healthy" else "abnormal",
            "checkpoint": None if choice == "healthy" else choice,
            "note": (note or "")[:300],
        })

    def finalize(self, reason: str):
        """幂等：补记 SESSION_END 并封闭日志；此后本会话不再下发、不再接受判定。"""
        if self.ended:
            return
        self.ended = True
        # 记下分配条件与计划起爆时刻：未起爆即结束的会话，复算时据此标 incomplete，不会被当成健康轮
        self.logger.log("SESSION_END", {"reason": reason, "assigned_condition": self.condition,
                                        "scheduled_onset_ms": int(self.onset_s * 1000),
                                        "injected": self.injected,
                                        "dropped_messages": self.dropped_messages})
        self.logger.close()


# ====================================================================
# 截图存证与审计包导出（HTTP 端点与离线自测共用）
# ====================================================================
def sanitize_panel(obj) -> dict | None:
    """页面面板读数（学生端上报，属页面自述，只作截图旁注，不参与复算）。"""
    if not isinstance(obj, dict):
        return None
    out = {}
    seq, age = obj.get("seq"), obj.get("feed_age_s")
    if isinstance(seq, int) and not isinstance(seq, bool):
        out["seq"] = seq
    if isinstance(age, (int, float)) and not isinstance(age, bool) and math.isfinite(age):
        out["feed_age_s"] = round(float(age), 2)
    return out or None


def watermark_lines(sess: ExperimentSession, panel: dict | None) -> tuple[str, str]:
    line1 = (f"EXP {sess.uid} | {sess.session_id} | {sess.ctx.clock()} | "
             f"Embodied-SimLite {sess.ctx.cfg.platform_version}")
    line2 = ("page panel: seq=%s feed_age=%ss" % (panel.get("seq", "-"), panel.get("feed_age_s", "-"))
             if panel else "page panel: -")
    return line1, line2


def prepare_screenshot(image_field, lines: tuple[str, str]) -> tuple[int, dict | None, bytes | None]:
    """纯计算、可在工作线程执行：解码 → 校验 PNG → 先查尺寸 → 解码并烧水印。返回 (状态码, 错误响应体, 输出字节)。"""
    b64 = str(image_field or "")
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    if len(b64) > (MAX_SCREENSHOT_BYTES * 4) // 3 + 16:
        return 413, {"ok": False, "error": "image too large"}, None
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return 400, {"ok": False, "error": "bad image data"}, None
    if not raw.startswith(PNG_MAGIC):
        return 400, {"ok": False, "error": "not a PNG image"}, None
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return 503, {"ok": False, "error": "server cannot watermark screenshots (Pillow missing)"}, None
    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if w <= 0 or h <= 0 or w > MAX_IMAGE_SIDE or h > MAX_IMAGE_SIDE or w * h > MAX_IMAGE_PIXELS:
            return 413, {"ok": False, "error": "image dimensions too large"}, None
        img = img.convert("RGB")                             # 真正解码在此，尺寸已先行核过
        bar_h = 40
        canvas = Image.new("RGB", (w, h + bar_h), "black")
        canvas.paste(img, (0, bar_h))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 4), lines[0], fill="#ffd54a")
        draw.text((8, 22), lines[1], fill="#9fd3ff")
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return 200, None, buf.getvalue()
    except Exception:
        return 400, {"ok": False, "error": "image cannot be decoded for watermarking"}, None


def commit_screenshot(sess: ExperimentSession, out: bytes, panel: dict | None) -> tuple[int, dict]:
    """在事件循环线程落盘并留 SCREENSHOT 事件（审计日志只在此线程写）。"""
    if sess.ended:
        return 404, {"ok": False, "error": "unknown or ended session"}
    if sess.n_shots >= MAX_SCREENSHOTS_PER_SESSION:
        return 429, {"ok": False, "error": "screenshot quota reached"}
    sess.n_shots += 1
    fname = f"shot_{sess.n_shots:02d}_{time.strftime('%H%M%S')}.png"
    with open(os.path.join(sess.logger.shots_dir, fname), "xb") as fh:
        fh.write(out)
    sess.logger.log("SCREENSHOT", {"filename": fname, "bytes": len(out),
                                   "sha256": hashlib.sha256(out).hexdigest(),
                                   "watermark": True, "page_panel": panel})
    return 200, {"ok": True, "filename": fname}


def save_screenshot(sess: ExperimentSession | None, image_field, panel=None) -> tuple[int, dict]:
    """同步版（离线自测用）：配额 → 计算 → 落盘。HTTP 端点走线程化的同一套函数。"""
    if sess is None or sess.ended:
        return 404, {"ok": False, "error": "unknown or ended session"}
    if sess.n_shots >= MAX_SCREENSHOTS_PER_SESSION:
        return 429, {"ok": False, "error": "screenshot quota reached"}
    p = sanitize_panel(panel)
    code, body, out = prepare_screenshot(image_field, watermark_lines(sess, p))
    if out is None:
        return code, body
    return commit_screenshot(sess, out, p)


def _write_atomic(path: str, text: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def pack_bytes(sess: ExperimentSession) -> tuple[str, bytes]:
    """读日志与截图、复算 summary、写留档、打 zip。不写审计日志，可在工作线程执行；调用前须已 finalize。"""
    with open(sess.logger.path, encoding="utf-8") as fh:
        jsonl_text = fh.read()
    ok, n_lines, total_hash, _errors = audit_chain.verify_chain(jsonl_text)
    version = sess.ctx.cfg.platform_version
    summary = audit_chain.derive_summary(audit_chain.parse_events(jsonl_text))
    summary["platform_version"] = version
    manifest = {"total_hash": total_hash, "lines": n_lines, "chain_ok_at_export": ok,
                "platform_version": version,
                "clock_basis": "platform server wall clock, ISO 8601 ms, local timezone",
                "generated_at": sess.ctx.clock()}
    summary_text = json.dumps(summary, ensure_ascii=False, indent=2)
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    for name, text in (("summary.json", summary_text), ("MANIFEST.json", manifest_text)):
        _write_atomic(os.path.join(sess.logger.dir, name), text)   # 服务端留档，与包内逐字节相同
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("audit_log.jsonl", jsonl_text)
        z.writestr("summary.json", summary_text)
        z.writestr("MANIFEST.json", manifest_text)
        for shot in sorted(os.listdir(sess.logger.shots_dir)):
            z.write(os.path.join(sess.logger.shots_dir, shot), f"screenshots/{shot}")
    return f"{sess.uid}_{sess.session_id}.zip", buf.getvalue()


def build_pack(sess: ExperimentSession) -> tuple[str, bytes]:
    """审计包 {uid}_{session_id}.zip ＝ audit_log.jsonl + screenshots/ + summary.json + MANIFEST.json。

    导出即结束会话（先 finalize 再读日志）：学生看到包内 INJECT 真值之后，本会话不能再改判定。
    summary 由 audit_chain.derive_summary 从日志复算，与 verify_pack.py 同一函数（spec §4）。
    """
    sess.finalize("export")
    return pack_bytes(sess)


# ====================================================================
# 首页注入片段：只在开关打开时拼进首页（首页常量 HTML_CONTENT 本身一字不改）
# ====================================================================
EXP_HEAD_HTML = """
<!-- ===== 实验模式（experiment_mode.py）：仅服务端 --audit-exp 开启时注入本段；页面未带 ?exp=1 时本段立即返回 ===== -->
<script>
(function () {
    "use strict";
    var q = new URLSearchParams(window.location.search);
    if (q.get("exp") !== "1") { return; }
    var uid = (q.get("uid") || "anon").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 32) || "anon";
    var S = { session: null, ticket: null, ws: null, lastFeedMs: Date.now(), lastSeq: null };

    function setText(id, t) { var el = document.getElementById(id); if (el) { el.textContent = t; } }
    function flash(t) {
        setText("exp_msg", t);
        setTimeout(function () { var el = document.getElementById("exp_msg"); if (el && el.textContent === t) { el.textContent = ""; } }, 4000);
    }
    function updateBanner() {
        setText("exp-banner", "实验模式 EXP | uid: " + uid + " | session: " + (S.session || "连接中…") +
            " | 页面时钟: " + new Date().toISOString() + "（截图水印以平台时钟为准）");
    }

    // ① 取证截图需保留 WebGL 绘制缓冲：仅本页、仅 webgl 上下文强制 preserveDrawingBuffer
    var nativeGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type, attrs) {
        if (type === "webgl" || type === "webgl2" || type === "experimental-webgl") {
            attrs = Object.assign({}, attrs || {}, { preserveDrawingBuffer: true });
        }
        return nativeGetContext.call(this, type, attrs);
    };

    // ② 页面自建的 /ws 连接自动带上 exp=1&uid=…；握手消息由本段消费，其余帧原样交给页面
    var NativeWS = window.WebSocket;
    var ExpWS = function (url, protocols) {
        var u = new URL(url, window.location.href);
        var isGateway = (u.pathname === "/ws");
        if (isGateway) { u.searchParams.set("exp", "1"); u.searchParams.set("uid", uid); }
        var ws = (protocols === undefined) ? new NativeWS(u.toString()) : new NativeWS(u.toString(), protocols);
        if (!isGateway) { return ws; }
        var pageHandler = null;
        Object.defineProperty(ws, "onmessage", {
            configurable: true,
            get: function () { return pageHandler; },
            set: function (fn) { pageHandler = fn; }
        });
        ws.addEventListener("message", function (e) {
            var d = null;
            try { d = JSON.parse(e.data); } catch (err) { d = null; }
            if (d && d.exp_session) { S.session = d.exp_session.session_id; S.ticket = d.exp_session.ticket || null; updateBanner(); return; }
            S.lastFeedMs = Date.now();
            if (d && d.seq !== undefined && d.seq !== null) { S.lastSeq = d.seq; setText("exp_seq", String(d.seq)); }
            if (typeof pageHandler === "function") { pageHandler.call(ws, e); }
        });
        S.ws = ws;
        return ws;
    };
    ExpWS.prototype = NativeWS.prototype;
    ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach(function (k) { ExpWS[k] = NativeWS[k]; });
    window.WebSocket = ExpWS;

    // ③ 操作台动作：全部经服务端留痕；判定可多次提交，以最后一次为准
    function send(obj) {
        if (S.ws && S.ws.readyState === 1) { S.ws.send(JSON.stringify(obj)); return true; }
        return false;
    }
    window.expSelfTest = function (action) {
        flash(send({ self_test: { action: action } }) ? ("已执行证伪动作并留痕: " + action) : "未连接，动作未发送");
    };
    window.expVerdict = function () {
        var ok = send({ student_verdict: {
            choice: document.getElementById("exp_verdict").value,
            note: document.getElementById("exp_note").value } });
        flash(ok ? "判定已提交并留痕" : "未连接，判定未发送");
    };
    window.expScreenshot = function () {
        var c = document.querySelector("#canvas-container canvas");
        if (!S.session || !S.ticket || !c) { flash("会话未就绪，无法截图"); return; }
        var age = Math.round((Date.now() - S.lastFeedMs) / 100) / 10;
        fetch("/screenshot", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: S.session, ticket: S.ticket, image: c.toDataURL("image/png"),
                                   panel: { seq: S.lastSeq, feed_age_s: age } }) })
            .then(function (r) { return r.json(); })
            .then(function (j) { flash(j.ok ? ("截图已存证: " + j.filename) : ("截图失败: " + (j.error || ""))); })
            .catch(function () { flash("截图失败"); });
    };
    window.expExport = function () {
        if (!S.session || !S.ticket) { flash("会话未就绪"); return; }
        if (!window.confirm("导出即结束本次会话（此后不能再改判定），确定导出？")) { return; }
        fetch("/export_pack/" + encodeURIComponent(S.session), { method: "POST",
            headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticket: S.ticket }) })
            .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.blob(); })
            .then(function (blob) {
                var a = document.createElement("a");
                a.href = URL.createObjectURL(blob); a.download = uid + "_" + S.session + ".zip";
                document.body.appendChild(a); a.click();
                setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
                flash("审计包已导出，本次会话已结束");
            })
            .catch(function (e) { flash("导出失败: " + e.message); });
    };

    window.addEventListener("load", function () {
        document.body.classList.add("screenshot-mode");        // 实验模式强制截图友好样式
        setText("c3-term", "完整性检查点：C3 断流冻结");
        document.getElementById("exp-banner").style.display = "block";
        document.getElementById("exp-panel").style.display = "block";
        updateBanner();
        setInterval(function () {
            updateBanner();
            var age = (Date.now() - S.lastFeedMs) / 1000;
            var el = document.getElementById("exp_age");
            if (el) {
                el.textContent = age.toFixed(1) + " s" + (age > 2 ? " ⚠ 疑似断流/冻结" : "");
                el.style.color = age > 2 ? "#ff4444" : "#00ffcc";
            }
        }, 250);
    });
})();
</script>
"""

EXP_BODY_HTML = """
    <!-- ===== 实验模式：顶栏水印 + 审计操作台（默认隐藏，由上方脚本在 ?exp=1 时显示）===== -->
    <div id="exp-banner" style="display:none; position:fixed; top:0; left:0; right:0; z-index:3000;
         background:rgba(0,0,0,0.88); color:#ffd54a; font-family:monospace; font-size:15px;
         text-align:center; padding:6px 0; border-bottom:1px solid #665500;"></div>
    <div id="exp-panel" style="display:none; position:fixed; left:12px; bottom:12px; z-index:3000;
         background:rgba(0,0,0,0.88); border:1px solid #665500; border-radius:8px;
         padding:12px 14px; font-family:monospace; font-size:13px; color:#eee; min-width:320px;">
        <div style="color:#ffd54a; font-weight:bold; margin-bottom:6px;">实验模式 · 审计操作台</div>
        <div class="tel-row"><span>帧序号 seq:</span><span id="exp_seq">—</span></div>
        <div class="tel-row"><span>数据新鲜度 feed age:</span><span id="exp_age">—</span></div>
        <div style="margin:8px 0 4px; color:#aaa;">标准证伪动作（全程留痕，只作用于本会话）:</div>
        <div>
            <button onclick="expSelfTest('slip_zero')">slip 归零</button>
            <button onclick="expSelfTest('slip_restore')">恢复 slip</button>
            <button onclick="expSelfTest('feed_cut')">断流自检 3s</button>
            <button onclick="expSelfTest('seq_probe')">帧序探针</button>
        </div>
        <div style="margin:10px 0 4px; color:#aaa;">审计判定（可多次提交，以最后一次为准）:</div>
        <div>
            <select id="exp_verdict">
                <option value="healthy">健康（无注入）</option>
                <option value="C1">C1 真值-里程计真分叉</option>
                <option value="C2">C2 帧序号单调</option>
                <option value="C3">C3 断流冻结</option>
            </select>
            <input id="exp_note" placeholder="一句话理由" style="width:120px;">
            <button onclick="expVerdict()">提交判定</button>
        </div>
        <div style="margin-top:10px;">
            <button onclick="expScreenshot()">平台截图</button>
            <button onclick="expExport()">导出审计包</button>
            <span id="exp_msg" style="color:#88ff88;"></span>
        </div>
    </div>
"""


def build_exp_html(base_html: str) -> str:
    """把实验模式片段拼进首页：</head> 前放脚本、</body> 前放操作台。锚点须各恰好出现一次，否则拒绝构建。"""
    for anchor in ("</head>", "</body>"):
        n = base_html.count(anchor)
        if n != 1:
            raise ValueError(f"首页 HTML 锚点 {anchor} 出现 {n} 次（须恰好 1 次），拒绝注入实验模式前端")
    return (base_html.replace("</head>", EXP_HEAD_HTML + "</head>", 1)
                     .replace("</body>", EXP_BODY_HTML + "</body>", 1))


# ====================================================================
# inference_server.py 与实验模式之间的唯一接口（开关打开时才被构造）
# ====================================================================
class ExperimentContext:
    def __init__(self, env, cfg: ExperimentConfig | None = None, clock=None):
        # env 只读：取默认 slip 与积分步长；本模块不写 env 的任何属性
        self.cfg = cfg if cfg is not None else ExperimentConfig()
        self.clock = clock or platform_ts
        self.default_slip = float(getattr(env, "slip_factor", getattr(env, "SLIP_FACTOR", 0.05)))
        self.dt = float(getattr(env, "DT", 0.1))
        self.sessions: dict[str, ExperimentSession] = {}   # session_id → 会话（导出后仍保留，供重复下载）
        self.by_ws: dict = {}                                # WebSocket → 会话（断开即移除，会话本身不结束）
        self._html_cache: str | None = None

    # ---- 启动与健康检查 ----
    def startup_line(self, base_html: str) -> str:
        self.html(base_html)          # 预构建首页：锚点缺失在启动时即报错，不留到学生打开页面时
        cfg = self.cfg
        inj = (f"开（健康权重 {cfg.healthy_weight:g}，起爆 {cfg.onset_min_s:g}–{cfg.onset_max_s:g} s）"
               if cfg.inject_enabled else "关（AUDIT_INJECT=0：只留痕不注入）")
        key = ("已启用（请求头 X-Audit-Teacher-Key；密钥只认环境变量 AUDIT_TEACHER_KEY）"
               if cfg.teacher_key else "未启用（未设 AUDIT_TEACHER_KEY）")
        line = (f">>> [实验模式] 已开启（--audit-exp / AUDIT_EXP）：审计目录 {cfg.audit_dir}/；"
                f"注入调度 {inj}；教师定向注入 {key}；平台版本 {cfg.platform_version}")
        if cfg.notes:
            line += "\n>>> [实验模式] 参数告警：" + "；".join(cfg.notes)
        return line

    def health_extra(self) -> dict:
        return {"audit_exp": True}

    def html(self, base_html: str) -> str:
        if self._html_cache is None:
            self._html_cache = build_exp_html(base_html)
        return self._html_cache

    def shutdown(self):
        for s in list(self.sessions.values()):
            s.finalize("shutdown")

    # ---- 会话 ----
    def create_session(self, uid, force=None, onset=None, teacher_key=None) -> ExperimentSession:
        key = self.cfg.teacher_key
        override_ok = (bool(key) and isinstance(teacher_key, str)
                       and hmac.compare_digest(teacher_key.encode("utf-8"), key.encode("utf-8")))
        sess = ExperimentSession(self, sanitize_uid(uid), force=force, onset=onset, override_ok=override_ok)
        self.sessions[sess.session_id] = sess
        return sess

    async def open_session(self, ws):
        """WebSocket 已 accept 后调用：URL 带 ?exp=1 才建会话并下发握手；否则返回 None（普通连接）。"""
        qp = ws.query_params
        if qp.get("exp") != "1":
            return None
        sess = self.create_session(qp.get("uid", ""), force=qp.get("force"), onset=qp.get("onset"),
                                   teacher_key=ws.headers.get(TEACHER_KEY_HEADER))
        self.by_ws[ws] = sess
        await ws.send_text(json.dumps({"exp_session": {
            "session_id": sess.session_id, "uid": sess.uid, "ticket": sess.ticket,
            "platform_version": self.cfg.platform_version}}, separators=(",", ":")))
        return sess

    def on_disconnect(self, ws):
        self.by_ws.pop(ws, None)

    def handle_client_message(self, sess: ExperimentSession, data: dict, now: float):
        if not (isinstance(data.get("self_test"), dict) or isinstance(data.get("student_verdict"), dict)):
            return
        if not sess.allow_message(now):
            return
        st = data.get("self_test")
        if isinstance(st, dict):
            sess.handle_self_test(str(st.get("action", "")), now)
        sv = data.get("student_verdict")
        if isinstance(sv, dict):
            sess.handle_verdict(str(sv.get("choice", "")), str(sv.get("note", "")))

    async def distribute(self, manager, state: dict, base_json: str, now: float):
        """普通连接收统一广播（与 manager.broadcast 同字节）；实验会话收按注入调度改写后的专属状态。

        会话渲染异常时显式关闭该连接（1011），避免学生端静默冻结、形似 C3；发送失败的连接照常清理。
        """
        dead, broken = [], []
        for ws in list(manager.active):
            sess = self.by_ws.get(ws)
            if sess is None:
                text = base_json
            else:
                try:
                    text = sess.render_for_student(state, now)
                except Exception as exc:
                    print(f"[实验模式] 会话 {sess.session_id} 渲染异常 {exc!r}：关闭该连接", file=sys.stderr)
                    broken.append(ws)
                    continue
                if text is None:
                    continue
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in broken:
            try:
                await ws.close(code=1011)
            except Exception:
                pass
        for ws in dead + broken:
            manager.disconnect(ws)
            self.on_disconnect(ws)

    # ---- HTTP 端点（只在开关打开时注册）----
    def register_routes(self, app):
        from fastapi import Request
        from fastapi.responses import JSONResponse, Response
        ctx = self

        async def read_json_capped(req):
            """按流读取请求体并封顶（不依赖 Content-Length，分块上传同样受限）。返回 (dict 或 None, 状态码)。"""
            total, chunks = 0, []
            async for chunk in req.stream():
                total += len(chunk)
                if total > MAX_BODY_BYTES:
                    return None, 413
                chunks.append(chunk)
            try:
                data = json.loads(b"".join(chunks) or b"null")
            except ValueError:
                return None, 400
            return (data, 200) if isinstance(data, dict) else (None, 400)

        def authorized(session_id, data):
            sess = ctx.sessions.get(str(session_id or ""))
            if sess is None or data is None or not sess.check_ticket(data.get("ticket")):
                return None
            return sess

        @app.post("/screenshot")
        async def exp_screenshot(req: Request):
            """实验模式平台截图：凭会话票据；服务端烧入水印后存证并留 SCREENSHOT 事件。平台外截图无水印无日志，一律无效。"""
            data, code = await read_json_capped(req)
            if data is None:
                return JSONResponse({"ok": False, "error": "image too large" if code == 413 else "bad request"},
                                    status_code=code)
            sess = authorized(data.get("session_id"), data)
            if sess is None or sess.ended:                   # 不区分「会话不存在」与「票据不符」，不留探测面
                return JSONResponse({"ok": False, "error": "unknown or ended session"}, status_code=404)
            if sess.n_shots >= MAX_SCREENSHOTS_PER_SESSION:
                return JSONResponse({"ok": False, "error": "screenshot quota reached"}, status_code=429)
            panel = sanitize_panel(data.get("panel"))
            code, body, out = await asyncio.to_thread(prepare_screenshot, data.get("image"),
                                                      watermark_lines(sess, panel))
            if out is None:
                return JSONResponse(body, status_code=code)
            code, body = commit_screenshot(sess, out, panel)
            return JSONResponse(body, status_code=code)

        @app.post("/export_pack/{session_id}")
        async def exp_export_pack(session_id: str, req: Request):
            """审计包导出（凭会话票据；导出即结束会话；打包在工作线程执行，不阻塞心跳）。"""
            data, code = await read_json_capped(req)
            if data is None:                                 # 超限或非 JSON 对象：先于授权判定返回，不泄露会话是否存在
                return JSONResponse({"error": "request too large" if code == 413 else "bad request"},
                                    status_code=code)
            sess = authorized(session_id, data)
            if sess is None:
                return JSONResponse({"error": "unknown session"}, status_code=404)
            sess.finalize("export")                          # 事件循环线程内补记 SESSION_END
            fname, blob = await asyncio.to_thread(pack_bytes, sess)
            return Response(blob, media_type="application/zip",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"'})
