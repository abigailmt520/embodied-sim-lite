#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ready_check.py —— 三不可变面守卫 / CI 三道门（CSO-028 平台保护令）

三道门（任一失败 exit 1；用法/环境错误 exit 2）：
  --selfcheck  门1 三门自检（旧）：实跑 audit/run_action1.py，门1/门2/门3 三行判定须全 ✅
  --course     门2 课程一致性：course_manifest.yaml → tag → commit 三点一致；契约版本一致；
               golden 自身 MANIFEST 完整；旧入口在 HEAD 树与 course tag 树**同机复跑**产物逐字节一致（A/B）；
               HEAD 产物再对照 golden 基准输出集（策略 golden.policy：bench-strict / strict / report）
  --paper      门3 论文复现：artifacts/HASHES.lock 只增不改（含新基准命名规则）；冻结基准子集派生复跑
               （parsed.action + parsed.targets 字段等价，数值指标逐位一致）；S5 派生脚本输出逐字节复现；
               D4 白名单外计数四列复现；平台论文数字（PPO 25 回合计数 / 真分叉 ATE）复现
  --all        三门顺序全跑

维护子命令（只在基准机上、由人显式执行；均拒绝静默覆盖）：
  --record-golden [--force]      自 course tag 树录制 golden 基准输出集到 manifest 指定目录
  --lock-artifacts [--append]    自 paper tag 生成 artifacts/HASHES.lock（--append 只添新路径，旧行不动）
  --write-frozen-subset [--force] 自四份正典脱敏日志 + 平台实跑生成 artifacts/eval/ci_frozen_subset.json

攻击语料隔离：本脚本只以 benchmark id 引用条目，任何输出不含 instruction 文本。
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "course_manifest.yaml"
DUMP_DIR = None  # --dump DIR：把 HEAD 归一化产物落盘（CI 上传，供跨平台差异度量）
LOCK_PATH = ROOT / "artifacts" / "HASHES.lock"
FROZEN_SUBSET_PATH = ROOT / "artifacts" / "eval" / "ci_frozen_subset.json"
S5_SCRIPT = ROOT / "artifacts" / "eval" / "derive_s5_attribution.py"
S5_OUT = ROOT / "artifacts" / "eval" / "s5_attribution.md"
OOV_SH = ROOT / "artifacts" / "eval" / "run_count_oov_targets.sh"
OOV_SCRIPT_SHA = "a83707e7bda9d784b41ec51e607d4011dd105055d610952cbe275cc7d6950a5c"  # FROZEN「R1描述性计数注记（D4）」
LOGS = {  # 与 derive_s5_attribution.py 公开包布局一致
    "1.5B": "table1_edge_sanitized.jsonl",
    "3B": "table1_edge3b_sanitized.jsonl",
    "Fallback 2": "table1_fallback2_sanitized.jsonl",
    "Teacher": "table1_cloud_sanitized.jsonl",
}


# ---------------------------------------------------------------- 基础工具
def sh(cmd, cwd=ROOT, check=True, env=None, binary=False):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=not binary, env=env)
    if check and r.returncode != 0:
        err = r.stderr if not binary else r.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"命令失败 {' '.join(map(str, cmd))}: {err.strip()}")
    return r


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    return sha256_bytes(Path(p).read_bytes())


def rev(ref):
    r = sh(["git", "rev-parse", "-q", "--verify", ref], check=False)
    return r.stdout.strip() if r.returncode == 0 else None


class Report:
    """逐条 PASS/FAIL/INFO 记录；任一 FAIL 即门红。"""

    def __init__(self, title):
        self.title, self.lines, self.fails = title, [], 0
        print(f"\n== {title} ==")

    def ok(self, msg):
        self.lines.append(("PASS", msg)); print(f"  [PASS] {msg}")

    def fail(self, msg):
        self.lines.append(("FAIL", msg)); self.fails += 1; print(f"  [FAIL] {msg}")

    def info(self, msg):
        self.lines.append(("INFO", msg)); print(f"  [INFO] {msg}")

    def check(self, cond, msg_ok, msg_fail=None):
        (self.ok if cond else self.fail)(msg_ok if cond else (msg_fail or msg_ok))
        return bool(cond)

    @property
    def passed(self):
        return self.fails == 0


def load_manifest():
    if not MANIFEST_PATH.exists():
        sys.exit(f"缺 course_manifest.yaml（{MANIFEST_PATH}）")
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def machine_fingerprint():
    """基准机指纹：golden 逐字节对照只在同指纹机器上强制。"""
    hw = ""
    try:
        if platform.system() == "Darwin":
            hw = sh(["sysctl", "-n", "hw.model"]).stdout.strip()
        elif platform.system() == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith("model name"):
                    hw = line.split(":", 1)[1].strip(); break
    except Exception:
        pass
    vers = {}
    for m in ("numpy", "torch", "matplotlib", "stable_baselines3", "gymnasium"):
        try:
            vers[m] = __import__(m).__version__
        except Exception:
            vers[m] = None
    return {"system": platform.system(), "machine": platform.machine(), "hw_model": hw,
            "python": platform.python_version(), **vers}


FP_KEYS = ("system", "machine", "hw_model", "python", "numpy", "torch", "matplotlib")


def run_env(manifest):
    env = dict(os.environ)
    env.update({k: str(v) for k, v in (manifest.get("golden", {}).get("env") or {}).items()})
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return env


# ---------------------------------------------------------------- 入口复跑与归一化
def normalize(data: bytes, rules, ctx) -> bytes:
    for rule in rules or []:
        if rule == "json_drop_keys":
            obj = json.loads(data.decode("utf-8"))
            for k in ctx.get("drop_keys", []):
                obj.pop(k, None)
            data = (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        elif rule == "json_round":
            # 定点化（CSO-028-R1 裁定②）：浮点统一舍入到 round_digits 位，跨 BLAS 末位差归零；
            # 施加在归一化层而非旧入口写出时，保证 course tag 旧入口本身逐字节不动（A/B 门仍对原始产物成立）
            nd = int(ctx.get("round_digits", 6))
            def _rnd(v):
                if isinstance(v, float):
                    r = round(v, nd)
                    return 0.0 if r == 0 else r          # 消 -0.0
                if isinstance(v, list):
                    return [_rnd(x) for x in v]
                if isinstance(v, dict):
                    return {k: _rnd(x) for k, x in v.items()}
                return v
            obj = _rnd(json.loads(data.decode("utf-8")))
            data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        elif rule == "strip_root":
            text = data.decode("utf-8", "replace")
            for path, tag in ctx.get("paths", []):
                text = text.replace(path, tag)
            data = text.encode("utf-8")
        else:
            raise ValueError(f"未知归一化规则 {rule}")
    return data


def run_entry(tree: Path, entry, env) -> dict:
    """在 tree 目录下执行一个入口命令，返回 {golden相对路径: 归一化后字节}。"""
    tmp = Path(tempfile.mkdtemp(prefix="rc_tmp_"))
    try:
        cmd = [c.replace("{tmp}", str(tmp)) for c in entry["cmd"]]
        r = subprocess.run(cmd, cwd=str(tree), env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"入口 {entry['id']} 退出码 {r.returncode}\n{r.stderr[-2000:]}")
        # 路径归一化：同时替换原始路径与 realpath（macOS 的 /var → /private/var 符号链接；脚本内 abspath 取 getcwd 已解析形）
        ctx = {"paths": sorted({(str(Path(tree).resolve()), "<ROOT>"), (str(tree), "<ROOT>"),
                                (str(tmp.resolve()), "<TMP>"), (str(tmp), "<TMP>")}, key=lambda x: -len(x[0]))}
        outs = {}
        for o in entry.get("outputs", []):
            src = Path(o["path"].replace("{tmp}", str(tmp)))
            if not src.is_absolute():
                src = tree / src
            if not src.exists():
                raise RuntimeError(f"入口 {entry['id']} 未产出 {o['path']}")
            key = o.get("as", o["path"])
            outs[key] = normalize(src.read_bytes(), o.get("normalize"),
                                  {**ctx, "drop_keys": o.get("drop_keys", []), "round_digits": o.get("round_digits", 6)})
        so = entry.get("stdout")
        if so:
            outs[so["path"]] = normalize(r.stdout.encode("utf-8"), so.get("normalize"), ctx)
        return outs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_all_entries(tree: Path, manifest, env, only=None):
    outs = {}
    for e in manifest["entries"]:
        if only and e["id"] not in only:
            continue
        outs.update(run_entry(tree, e, env))
    return outs


class TagWorktree:
    """临时 worktree（分离 HEAD 指向 tag），退出即删。"""

    def __init__(self, ref):
        self.ref, self.path = ref, None

    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix="rc_wt_"))
        sh(["git", "worktree", "add", "--detach", str(self.path), self.ref])
        return self.path

    def __exit__(self, *a):
        sh(["git", "worktree", "remove", "--force", str(self.path)], check=False)
        shutil.rmtree(self.path, ignore_errors=True)


def golden_policy(manifest, rep):
    """解析 golden 对照策略：strict / report。bench-strict = 与录制指纹同机则 strict，否则 report。"""
    override = os.environ.get("READY_CHECK_GOLDEN")
    pol = override or manifest.get("golden", {}).get("policy", "bench-strict")
    if pol == "bench-strict":
        rec = ROOT / manifest["golden"]["dir"] / "RECORD.json"
        if rec.exists():
            recorded = json.loads(rec.read_text(encoding="utf-8")).get("fingerprint", {})
            here = machine_fingerprint()
            same = all(recorded.get(k) == here.get(k) for k in FP_KEYS)
            pol = "strict" if same else "report"
            rep.info(f"golden 策略 bench-strict → 本机{'＝' if same else '≠'}录制机（{here['hw_model'] or here['machine']}，"
                     f"torch {here['torch']} / numpy {here['numpy']} / mpl {here['matplotlib']}）→ {pol}")
        else:
            pol = "report"
    else:
        rep.info(f"golden 策略 = {pol}{'（环境变量覆盖）' if override else ''}")
    return pol


# ---------------------------------------------------------------- 门1
def gate_selfcheck(manifest):
    rep = Report("门1 三门自检（旧）：audit/run_action1.py")
    env = run_env(manifest)
    r = subprocess.run([sys.executable, "audit/run_action1.py"], cwd=str(ROOT), env=env, capture_output=True, text=True)
    rep.check(r.returncode == 0, f"run_action1.py 退出码 {r.returncode}")
    for label in ("门 1（审计抓假·红）: ✅", "门 2（放行健康·绿）: ✅", "门 3（基础评测）   : ✅"):
        rep.check(label in r.stdout, f"判定行在案：{label.strip()}", f"判定行缺失/非✅：{label.strip()}")
    m = re.search(r"成功率 success_rate\s*:\s*([\d.]+)%", r.stdout)
    if m:
        rep.info(f"PPO 成功率 {m.group(1)}%（N=25，固定种子）")
    return rep


# ---------------------------------------------------------------- 门2
def gate_course(manifest, cache):
    rep = Report("门2 课程一致性：course_manifest.yaml ↔ tag ↔ commit ↔ 旧入口产物")
    c = manifest["course"]
    tag, pinned = c["tag"], c["pinned_commit"]
    tag_obj = rev(f"refs/tags/{tag}")
    if not rep.check(tag_obj is not None, f"tag {tag} 存在", f"tag {tag} 不存在（CI 需 fetch-tags）"):
        return rep
    kind = sh(["git", "cat-file", "-t", tag]).stdout.strip()
    rep.check(kind == "tag", f"tag {tag} 为附注 tag", f"tag {tag} 非附注 tag（{kind}）")
    commit = rev(f"{tag}^{{commit}}")
    rep.check(commit == pinned, f"tag {tag} → {commit[:7]} = manifest pinned_commit", f"tag {tag} → {commit} ≠ manifest pinned_commit {pinned}")
    same_as = c.get("same_as")
    if same_as:
        other = rev(f"refs/heads/{same_as}") or rev(f"refs/remotes/origin/{same_as}") or rev(f"refs/tags/{same_as}")
        if other:
            rep.check(other == commit, f"same_as {same_as} → {other[:7]} 与 tag 同点", f"same_as {same_as} → {other[:7]} ≠ tag {commit[:7]}")
        else:
            rep.info(f"same_as {same_as} 引用本地不可见，跳过（非失败）")
    # 契约版本
    api = ROOT / c["contract"]["path"]
    want = str(c["contract"]["version"])
    if rep.check(api.exists(), f"契约文件 {c['contract']['path']} 存在", f"契约文件 {c['contract']['path']} 缺失"):
        m = re.search(r"契约版本[:：]\s*v?(\d+\.\d+\.\d+)", api.read_text(encoding="utf-8"))
        rep.check(m and m.group(1) == want, f"契约版本 v{want} 与 manifest 一致", f"契约版本头 {m.group(1) if m else '缺失'} ≠ manifest {want}")
    # golden 自身完整性
    gdir = ROOT / manifest["golden"]["dir"]
    mf = gdir / "MANIFEST.sha256"
    golden = {}
    if rep.check(mf.exists(), f"golden 清单 {mf.relative_to(ROOT)} 存在", "golden 清单缺失（先在基准机 --record-golden）"):
        bad = 0
        for line in mf.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            h, rel = line.split("  ", 1)
            p = gdir / rel
            if not p.exists() or sha256_file(p) != h:
                bad += 1; rep.fail(f"golden 文件被改/缺失：{rel}")
            else:
                golden[rel] = p.read_bytes()
        rep.check(bad == 0, f"golden {len(golden)} 件与清单哈希一致")
    # A/B 同机复跑
    env = run_env(manifest)
    try:
        with TagWorktree(tag) as wt:
            outs_a = run_all_entries(wt, manifest, env)
        outs_b = run_all_entries(ROOT, manifest, env)
    except RuntimeError as e:
        rep.fail(f"入口复跑失败：{e}")
        return rep
    cache["head_outputs"] = outs_b
    if DUMP_DIR:
        for k, v in outs_b.items():
            dp = Path(DUMP_DIR) / k; dp.parent.mkdir(parents=True, exist_ok=True); dp.write_bytes(v)
        rep.info(f"HEAD 归一化产物已落盘 {len(outs_b)} 件 → {DUMP_DIR}")
    rep.check(set(outs_a) == set(outs_b), f"A/B 产物集合一致（{len(outs_b)} 件）")
    diff = [k for k in sorted(outs_b) if outs_a.get(k) != outs_b.get(k)]
    rep.check(not diff, f"A/B 逐字节一致：HEAD 旧入口产物 = course tag 产物（{len(outs_b)} 件）", f"A/B 不一致：{diff}")
    # golden 对照
    pol = golden_policy(manifest, rep)
    if golden:
        gd = [k for k in sorted(outs_b) if golden.get(k) != outs_b[k]]
        missing = [k for k in sorted(outs_b) if k not in golden]
        if pol == "strict":
            rep.check(not gd and not missing, f"HEAD 产物与 golden 逐字节一致（{len(outs_b)} 件）", f"与 golden 不一致：{gd + missing}")
        else:
            rep.info(f"golden 对照（report）：一致 {len(outs_b) - len(gd) - len(missing)} / 不一致 {len(gd)} / golden 缺 {len(missing)}"
                     + (f"；不一致件：{gd}" if gd else ""))
    return rep


# ---------------------------------------------------------------- 门3
def parse_lock():
    """返回 (anchor(tag, commit), {path: sha256}, append_only:set)。
    `# append-only: p1 p2 …` 指令行列出的路径按「锚点内容为当前内容前缀」校验（台账/索引只增不改），其余按哈希不变。"""
    anchor, entries, append_only = None, {}, set()
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("# anchor:"):
            parts = line.split()          # "# anchor: tag <name> <sha>"
            anchor = (parts[3], parts[4])
        elif line.startswith("# append-only:"):
            append_only.update(line.split(":", 1)[1].split())
        elif line.strip() and not line.startswith("#"):
            h, p = line.split("  ", 1)
            entries[p] = h
    return anchor, entries, append_only


NEW_BENCH_RE = re.compile(r"^artifacts/benchmark/v(?!1(?:[^0-9]|$))\d+[A-Za-z0-9._-]*/")


def gate_paper(manifest, cache):
    rep = Report("门3 论文复现：artifacts 只增不改 + 冻结子集派生复跑 + 平台论文数字")
    p = manifest["paper"]
    # 1) HASHES.lock
    if rep.check(LOCK_PATH.exists(), "artifacts/HASHES.lock 存在", "artifacts/HASHES.lock 缺失（--lock-artifacts）"):
        anchor, locked, append_only = parse_lock()
        tag_commit = rev(f"{p['p4_tag']}^{{commit}}")
        rep.check(anchor and anchor[0] == p["p4_tag"] and anchor[1] == tag_commit,
                  f"锁锚点 = tag {p['p4_tag']} @ {tag_commit[:7] if tag_commit else '?'}",
                  f"锁锚点 {anchor} ≠ tag {p['p4_tag']} @ {tag_commit}")
        changed, not_prefix = [], []
        for rel, h in locked.items():
            f = ROOT / rel
            if not f.exists():
                changed.append(rel); continue
            if rel in append_only:
                base = sh(["git", "cat-file", "-p", f"{anchor[1]}:{rel}"], binary=True).stdout
                if not f.read_bytes().startswith(base):
                    not_prefix.append(rel)
            elif sha256_file(f) != h:
                changed.append(rel)
        n_frozen = len(locked) - len(append_only)
        rep.check(not changed, f"冻结路径 {n_frozen} 件哈希不变", f"冻结路径被改/删：{changed}")
        rep.check(not not_prefix, f"只增路径 {len(append_only)} 件以锚点内容为前缀（{sorted(append_only)}）", f"只增路径被改写/删行：{not_prefix}")
        tracked = sh(["git", "ls-files", "--", "artifacts"]).stdout.split()
        new = [t for t in tracked if t not in locked]
        bad_new = [t for t in new if t.startswith("artifacts/benchmark/") and not NEW_BENCH_RE.match(t)]
        rep.check(not bad_new, f"新增 {len(new)} 件（benchmark/ 下新增须落 v2+ 新目录）", f"benchmark/ 下新增未按「新目录+新版本号」：{bad_new}")
    # 2) 冻结子集派生复跑
    if rep.check(FROZEN_SUBSET_PATH.exists(), "冻结子集期望文件存在", "缺 artifacts/eval/ci_frozen_subset.json（--write-frozen-subset）"):
        exp = json.loads(FROZEN_SUBSET_PATH.read_text(encoding="utf-8"))
        derived = derive_subset()
        for model in LOGS:
            e, d = exp["models"][model], derived["models"][model]
            mism = [i for i in e["subset"] if e["subset"][i] != d["subset"].get(i)]
            rep.check(not mism, f"{model}：S5 须拒子集 {len(e['subset'])} 条 action+targets+system_action+score 逐条等价", f"{model}：字段不等价 id={mism}")
            rep.check(e["totals"] == d["totals"], f"{model}：n={d['totals']['n']} score_sum={d['totals']['score_sum']} 分层={d['totals']['by_stratum']} 逐位一致",
                      f"{model}：数值指标不一致 期望{e['totals']} 实得{d['totals']}")
        rep.check(exp["table2"] == derived["table2"], f"Table 2：n={derived['table2']['n']} reached={derived['table2']['reached']} 一致", f"Table 2 不一致 {exp['table2']} vs {derived['table2']}")
        rep.check(exp["stress"] == derived["stress"], f"压测第四轮：n={derived['stress']['n']} results={derived['stress']['results']} 一致", f"压测不一致 {exp['stress']} vs {derived['stress']}")
        rep.check(exp["subset_ids"] == derived["subset_ids"], f"须拒子集 id 集合一致（{len(derived['subset_ids'])} 条，只引 id）")
    else:
        exp = None
    # 3) S5 派生脚本逐字节
    tmp = Path(tempfile.mkdtemp(prefix="rc_s5_"))
    try:
        r = subprocess.run([sys.executable, str(S5_SCRIPT), "--out", str(tmp / "s5.md")], cwd=str(ROOT), capture_output=True, text=True)
        rep.check(r.returncode == 0, "derive_s5_attribution.py 内置断言 PASS（Table 5 + §5.1）", f"derive_s5_attribution.py 退出码 {r.returncode}")
        rep.check((tmp / "s5.md").exists() and (tmp / "s5.md").read_bytes() == S5_OUT.read_bytes(), "s5_attribution.md 复跑输出逐字节一致", "s5_attribution.md 复跑输出与库内不一致")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 4) D4 计数
    r = subprocess.run(["bash", str(OOV_SH)], cwd=str(ROOT), capture_output=True, text=True)
    rep.check(r.returncode == 0, "run_count_oov_targets.sh 退出码 0", f"run_count_oov_targets.sh 退出码 {r.returncode}")
    for col in LOGS:
        rep.check(f"| {col} | 120 | 120 | 120 | 0 | 0 | — | 无 |" in r.stdout, f"D4 {col}：0/120 白名单外", f"D4 {col} 行不符")
    rep.check(f"脚本 SHA256: {OOV_SCRIPT_SHA}" in r.stdout, "count_oov_targets.py SHA256 = FROZEN 登记值")
    # 5) 平台论文数字（PPO 计数受 golden 策略；真分叉 ATE 纯 numpy，一律 strict）
    if exp and "platform_paper" in exp:
        outs = cache.get("head_outputs")
        if outs is None:
            try:
                outs = run_all_entries(ROOT, manifest, run_env(manifest), only={"selfcheck3", "fork"})
            except RuntimeError as e:
                rep.fail(f"平台入口复跑失败：{e}"); outs = {}
        got = platform_numbers(outs)
        pp = exp["platform_paper"]
        pol = golden_policy(manifest, rep)
        (rep.check if pol == "strict" else (lambda c, a, b=None: rep.info(a if c else f"（report）{b}")))(
            got.get("ppo") == pp["ppo"], f"PPO 25 回合计数 {got.get('ppo')} = 论文（84%/12%/4%，均步 {pp['ppo']['avg_steps_success']}）", f"PPO 计数不一致：期望 {pp['ppo']} 实得 {got.get('ppo')}")
        rep.check(got.get("fork") == pp["fork"], f"真分叉 ATE_RMSE {got.get('fork', {}).get('ATE_RMSE')} m 等 4 项逐位一致", f"真分叉指标不一致：期望 {pp['fork']} 实得 {got.get('fork')}")
    return rep


def derive_subset():
    """从四份脱敏日志派生冻结子集事实（只引 id；不触碰 instruction 文本）。"""
    out = {"models": {}, "subset_ids": None}
    logs_dir = ROOT / "artifacts" / "logs"
    for model, fname in LOGS.items():
        recs = [json.loads(l) for l in (logs_dir / fname).open(encoding="utf-8") if l.strip()]
        subset = {r["id"]: {"action": r["parsed"]["action"], "targets": list(r["parsed"].get("targets") or []),
                            "system_action": r["system_action"], "score": r["score"]}
                  for r in recs if r["stratum"] == "S5" and r["expected_action"] == "reject"}
        by_s = {}
        for r in recs:
            by_s[r["stratum"]] = by_s.get(r["stratum"], 0) + int(r["score"])
        out["models"][model] = {"subset": subset,
                                "totals": {"n": len(recs), "score_sum": sum(int(r["score"]) for r in recs),
                                           "by_stratum": dict(sorted(by_s.items()))}}
        ids = sorted(subset)
        out["subset_ids"] = ids if out["subset_ids"] is None else out["subset_ids"]
    t2 = [json.loads(l) for l in (logs_dir / "table2_canonical_sanitized.jsonl").open(encoding="utf-8") if l.strip()]
    out["table2"] = {"n": len(t2), "reached": sum(1 for r in t2 if r.get("item_reached") in (True, 1, "true", "True"))}
    st = [json.loads(l) for l in (logs_dir / "stress_round4_sanitized.jsonl").open(encoding="utf-8") if l.strip()]
    out["stress"] = {"n": len(st), "results": dict(sorted(Counter(str(r.get("result")) for r in st).items()))}
    return out


def platform_numbers(outs):
    """从入口产物（归一化字节）提取平台论文数字。"""
    got = {}
    ep = outs.get("audit/eval_episodes.csv")
    if ep:
        import csv, io
        rows = list(csv.DictReader(io.StringIO(ep.decode("utf-8"))))
        succ = [r for r in rows if r["success"] == "1"]
        got["ppo"] = {"n": len(rows), "success": len(succ), "collision": sum(r["collision"] == "1" for r in rows),
                      "timeout": sum(r["outcome"] == "timeout" for r in rows),
                      "avg_steps_success": round(sum(int(r["steps"]) for r in succ) / len(succ), 1) if succ else None}
    fa = outs.get("diagnostics/fork_after.csv")
    if fa:
        import csv, io, math
        rows = list(csv.DictReader(io.StringIO(fa.decode("utf-8"))))
        err = [float(r["err_xy"]) for r in rows]
        got["fork"] = {"ATE_RMSE": round(math.sqrt(sum(e * e for e in err) / len(err)), 6), "final_err": round(err[-1], 6),
                       "max_err": round(max(err), 6), "final_yaw_drift_deg": round(float(rows[-1]["err_yaw_deg"]), 4)}
    return got


# ---------------------------------------------------------------- 维护子命令
def record_golden(manifest, force):
    gdir = ROOT / manifest["golden"]["dir"]
    if gdir.exists() and any(gdir.iterdir()) and not force:
        sys.exit(f"golden 目录已存在（{gdir}），拒绝覆盖；确需重录加 --force（须同时在 FROZEN-CI.md 追加记录）")
    tag = manifest["course"]["tag"]
    env = run_env(manifest)
    rec_path = gdir / "RECORD.json"
    prev_json = rec_path.read_text(encoding="utf-8") if rec_path.exists() else None
    with TagWorktree(tag) as wt:
        outs = run_all_entries(wt, manifest, env)
    if gdir.exists():
        shutil.rmtree(gdir)
    gdir.mkdir(parents=True, exist_ok=True)
    if prev_json is not None:
        rec_path.write_text(prev_json, encoding="utf-8")   # 先放回旧 RECORD 供 history 续写
    for rel, data in outs.items():
        p = gdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    lines = [f"# golden 基准输出集 ｜ course tag {tag} @ {rev(tag + '^{commit}')} ｜ 录制 {datetime.date.today().isoformat()}",
             "# 格式：sha256  相对路径（归一化后字节；归一化规则见 course_manifest.yaml entries[].outputs[].normalize）"]
    lines += [f"{sha256_bytes(outs[k])}  {k}" for k in sorted(outs)]
    (gdir / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    prev = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
    history = prev.get("history", [])
    reason = os.environ.get("GOLDEN_RERECORD_REASON")
    if force and not reason:
        sys.exit("重录须给出原因：环境变量 GOLDEN_RERECORD_REASON=…（入 RECORD.json history）")
    if force:
        history.append({"at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "reason": reason,
                        "prev_recorded": prev.get("recorded"), "prev_files": prev.get("files")})
    rec = {"tag": tag, "commit": rev(tag + "^{commit}"), "recorded": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "fingerprint": machine_fingerprint(), "env": manifest["golden"].get("env") or {},
           "entries": [e["id"] for e in manifest["entries"]], "files": len(outs),
           "normalization": {e["id"]: [(o.get("as", o["path"]), o.get("normalize"), o.get("round_digits")) for o in e.get("outputs", []) if o.get("normalize")]
                             for e in manifest["entries"]},
           "history": history}
    (gdir / "RECORD.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"golden 已录制：{len(outs)} 件 → {gdir}（指纹 {rec['fingerprint']['hw_model']} / torch {rec['fingerprint']['torch']}）")


def lock_artifacts(manifest, append):
    tag = manifest["paper"]["p4_tag"]
    commit = rev(f"{tag}^{{commit}}")
    if not commit:
        sys.exit(f"tag {tag} 不存在")
    existing = {}
    if LOCK_PATH.exists():
        if not append:
            sys.exit("artifacts/HASHES.lock 已存在；只允许 --append 添新路径（旧行不动）")
        _, existing = parse_lock()
    listing = sh(["git", "ls-tree", "-r", "--full-tree", f"{tag}^{{commit}}", "--", "artifacts/"]).stdout.splitlines()
    new = {}
    for line in listing:
        meta, path = line.split("\t", 1)
        blob = meta.split()[2]
        if path in existing or path == "artifacts/HASHES.lock":
            continue
        data = sh(["git", "cat-file", "-p", blob], binary=True).stdout
        new[path] = sha256_bytes(data)
    if append:
        # 追加模式：新路径取自当前工作树（新基准/新版本），而非锚点 tag
        tracked = sh(["git", "ls-files", "--", "artifacts"]).stdout.split()
        new = {t: sha256_file(ROOT / t) for t in tracked if t not in existing and t != "artifacts/HASHES.lock"}
        body = LOCK_PATH.read_text(encoding="utf-8").rstrip("\n") + "\n"
        body += f"# appended {datetime.date.today().isoformat()} @ {rev('HEAD')[:7]}\n"
    else:
        ao = " ".join(manifest["paper"].get("append_only", []))
        body = (f"# anchor: tag {tag} {commit}\n"
                f"# artifacts 只增不改守卫：下列历史路径的内容哈希不得改变；新增文件另起新路径（benchmark/ 下须 v2+ 新目录）\n"
                f"# append-only: {ao}\n")
    body += "".join(f"{h}  {p}\n" for p, h in sorted(new.items()))
    LOCK_PATH.write_text(body, encoding="utf-8")
    print(f"HASHES.lock：{'追加' if append else '生成'} {len(new)} 条（锚点 {tag} @ {commit[:7]}）")


def write_frozen_subset(manifest, force):
    if FROZEN_SUBSET_PATH.exists() and not force:
        sys.exit("ci_frozen_subset.json 已存在，拒绝覆盖（改动＝新版本文件 + FROZEN-CI.md 追加）")
    d = derive_subset()
    outs = run_all_entries(ROOT, manifest, run_env(manifest), only={"selfcheck3", "fork"})
    d["platform_paper"] = platform_numbers(outs)
    d["_meta"] = {"written": datetime.date.today().isoformat(), "head": rev("HEAD"), "note": "只引 benchmark id；不含 instruction 文本"}
    FROZEN_SUBSET_PATH.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for m, v in d["models"].items():
        print(f"{m}: n={v['totals']['n']} score_sum={v['totals']['score_sum']} by_stratum={v['totals']['by_stratum']} 子集={len(v['subset'])}")
    print(f"table2={d['table2']} stress={d['stress']} platform={d['platform_paper']}")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selfcheck", action="store_true"); ap.add_argument("--course", action="store_true")
    ap.add_argument("--paper", action="store_true"); ap.add_argument("--all", action="store_true")
    ap.add_argument("--record-golden", action="store_true"); ap.add_argument("--lock-artifacts", action="store_true")
    ap.add_argument("--write-frozen-subset", action="store_true")
    ap.add_argument("--append", action="store_true"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", help="机器可读结果输出路径")
    ap.add_argument("--dump", help="把 HEAD 归一化产物落盘到目录（CI 上传供跨平台差异度量）")
    a = ap.parse_args()
    global DUMP_DIR
    DUMP_DIR = a.dump
    manifest = load_manifest()
    if a.record_golden:
        return record_golden(manifest, a.force)
    if a.lock_artifacts:
        return lock_artifacts(manifest, a.append)
    if a.write_frozen_subset:
        return write_frozen_subset(manifest, a.force)
    gates = []
    if a.all or a.selfcheck: gates.append("selfcheck")
    if a.all or a.course: gates.append("course")
    if a.all or a.paper: gates.append("paper")
    if not gates:
        ap.print_help(); sys.exit(2)
    cache, reports = {}, []
    for g in gates:
        reports.append({"selfcheck": gate_selfcheck, "course": lambda m: gate_course(m, cache), "paper": lambda m: gate_paper(m, cache)}[g](manifest))
    print("\n== 汇总 ==")
    for r in reports:
        print(f"  {'🟢 GREEN' if r.passed else '🔴 RED  '}  {r.title}")
    if a.json:
        Path(a.json).write_text(json.dumps([{"gate": r.title, "passed": r.passed, "lines": r.lines} for r in reports], indent=1, ensure_ascii=False), encoding="utf-8")
    sys.exit(0 if all(r.passed for r in reports) else 1)


if __name__ == "__main__":
    main()
