#!/usr/bin/env python3
"""凭证级词表审计（推送前硬门）。

用法：
  python3 tools/audit_secrets.py                 # 扫描工作树：已跟踪 + 未忽略的未跟踪文件
  python3 tools/audit_secrets.py --ref <ref>     # 扫描某提交/分支的已跟踪文件（pre-push 钩子对待推引用调用）
  python3 tools/audit_secrets.py --self-test     # 注入假密钥自测：必须拦截；自测结束即删临时文件
退出码：0 = 零剩余命中（可推）；1 = 有剩余命中（拒绝推送）；2 = 用法错误 / 自测失败。

allowlist：tools/audit_allowlist.txt，每行「路径glob<TAB>行正则」，命中行仅当路径与行正则同时匹配才排除
（用于排除“审计词表说明句”自身等已人工复核的文本）。本脚本与 allowlist 文件本身也经由 allowlist 排除。
"""
import fnmatch, os, re, subprocess, sys, tempfile

# 词表：原审计清单（AIza*/api_key/GEMINI_API_KEY/Bearer/sk-*/authorization/x-goog/secret/password/token赋值）+ 常见密钥形态
PATTERN = re.compile(
    r"AIza[0-9A-Za-z_\-]{10,}"                 # Google API key 形态
    r"|(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{6,}"  # OpenAI/DeepSeek 风格 key
    r"|(?<![A-Za-z0-9_])AKIA[0-9A-Z]{12,}"      # AWS access key id
    r"|(?<![A-Za-z0-9_])ghp_[A-Za-z0-9]{10,}"   # GitHub token
    r"|api_key|GEMINI_API_KEY|OPENAI_API_KEY|DEEPSEEK_API_KEY"
    r"|Bearer\s+[A-Za-z0-9._\-]{10,}"
    r"|authorization|x-goog|secret|password|token\s*="
    r"|BEGIN [A-Z ]*PRIVATE KEY",
    re.IGNORECASE)
ALLOWLIST = "tools/audit_allowlist.txt"

def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout

def load_allowlist():
    rules = []
    if os.path.exists(ALLOWLIST):
        for line in open(ALLOWLIST, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "\t" not in line:
                continue
            glob, rx = line.split("\t", 1)
            rules.append((glob.strip(), re.compile(rx)))
    return rules

def allowed(path, line, rules):
    return any(fnmatch.fnmatch(path, g) and rx.search(line) for g, rx in rules)

def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]

def scan_blob(path, data, rules, hits):
    if is_binary(data):
        return
    for i, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        if PATTERN.search(line) and not allowed(path, line, rules):
            hits.append((path, i, line.strip()[:120]))

def scan_ref(ref, rules):
    hits = []
    for entry in sh("git", "ls-tree", "-r", "-z", ref).split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        blob = meta.split()[2]
        data = subprocess.run(["git", "cat-file", "blob", blob], capture_output=True, check=True).stdout
        scan_blob(path, data, rules, hits)
    return hits

def scan_worktree(rules):
    hits = []
    files = sh("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    for path in files:
        if not path or not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            scan_blob(path, f.read(), rules, hits)
    return hits

def report(hits, label):
    if hits:
        print(f"AUDIT FAIL — {len(hits)} 处剩余命中（{label}），拒绝推送：")
        for p, i, l in hits[:50]:
            print(f"  {p}:{i}: {l}")
        return 1
    print(f"AUDIT PASS — 零剩余命中（{label}）")
    return 0

def self_test(rules):
    """注入假密钥形态的临时文件（未跟踪），①直接扫该文件必须命中≥4行；②工作树扫描必须把它列为命中；
    随后删除临时文件，再扫必须回到基线。任一不满足→exit 2。"""
    base = scan_worktree(rules)
    fd, tmp_abs = tempfile.mkstemp(prefix=".audit_selftest_", suffix=".txt", dir="tools", text=True)
    tmp = os.path.relpath(tmp_abs, os.getcwd()).replace(os.sep, "/")   # 与 git ls-files 的相对路径口径一致
    try:
        with os.fdopen(fd, "w") as f:
            f.write("fake1 = sk-test-abcdefghijklmnopqrstuvwxyz0123\n")
            f.write("fake2 = AKIAABCDEFGHIJKLMNOP\n")
            f.write("GEMINI_API_KEY=AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE\n")
            f.write("Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n")
        direct = []
        with open(tmp, "rb") as f:
            scan_blob(tmp, f.read(), rules, direct)
        with_tmp = scan_worktree(rules)
        injected = [h for h in with_tmp if h[0] == tmp]
        ok_direct, ok_wt = len(direct) >= 4, len(injected) >= 4
        print(f"self-test: 注入 {tmp} 4 行假密钥 → 直接扫描命中 {len(direct)} 行 {'✔' if ok_direct else '✘'}；工作树扫描命中 {len(injected)} 行 {'✔' if ok_wt else '✘（未跟踪文件被忽略或路径口径不一致）'}")
    finally:
        os.remove(tmp)
    after = scan_worktree(rules)
    clean = (after == base) and not os.path.exists(tmp)
    print(f"self-test: 删除临时文件后命中恢复基线（{len(base)} 处）{'✔' if clean else '✘'}；临时文件已删除：{not os.path.exists(tmp)}")
    passed = ok_direct and ok_wt and clean
    print("self-test:", "PASS" if passed else "FAIL")
    return 0 if passed else 2

def main(argv):
    os.chdir(sh("git", "rev-parse", "--show-toplevel").strip())
    rules = load_allowlist()
    if argv[:1] == ["--self-test"]:
        return self_test(rules)
    if argv[:1] == ["--ref"] and len(argv) == 2:
        return report(scan_ref(argv[1], rules), f"ref {argv[1][:12]}")
    if not argv:
        return report(scan_worktree(rules), "worktree")
    print(__doc__); return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
