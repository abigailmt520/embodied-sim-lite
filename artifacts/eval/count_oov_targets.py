#!/usr/bin/env python3
"""D4 机械统计：正典日志中「模型原始输出的目标不在白名单」条数，分模型报（CSO-022/R1）。
纯日志加工，零API调用；不改任何 score 字段，仅描述性计数。
用法：python3 eval/count_oov_targets.py [--json 输出明细路径]
"""
import json, sys, hashlib, re
import yaml

CANON = [  # (列名, 正典文件)  哈希见 benchmark/FROZEN.md
    ("1.5B",       "results/edge-ollama_qwen2.5-1.5b-instruct_20260808-180543.jsonl"),
    ("3B",         "results/tier2_edge-ollama_qwen2.5-3b-instruct_20260823-033645.jsonl"),
    ("Fallback 2", "results/tier3_cloud-openai_deepseek-chat_20260823-042527.jsonl"),
    ("Teacher",    "results/cloud-gemini_gemini-3.6-flash_20260808-232944.jsonl"),
]
VOCAB = "src/waypoints.yaml"

def vocab_ids(path):
    data = yaml.safe_load(open(path, encoding="utf-8"))
    ids = []
    def walk(x):
        if isinstance(x, dict):
            if "id" in x and isinstance(x["id"], str): ids.append(x["id"])
            for k, v in x.items():
                if isinstance(k, str) and re.fullmatch(r"W\d+_\w+", k): ids.append(k)
                walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(data)
    return sorted(set(ids))

def main():
    ids = set(vocab_ids(VOCAB))
    print(f"白名单 {len(ids)} 个 id: {sorted(ids)}")
    details = []
    print("\n| 列 | n | raw为合法JSON | 含targets字段 | 含白名单外目标的条数 | 白名单外目标token数 | 解析器处置(action分布) | 张力(白名单外但score=1) |")
    print("|---|---|---|---|---|---|---|---|")
    for col, path in CANON:
        recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        n = len(recs); json_ok = 0; has_targets = 0; oov_recs = 0; oov_tokens = 0
        disp = {}; tension = []
        for r in recs:
            try:
                raw = json.loads(r["raw_output"]); json_ok += 1
            except Exception:
                details.append({"col": col, "id": r["id"], "stratum": r["stratum"], "raw_json": False,
                                "parsed_action": r["parsed"].get("action"), "score": r["score"]})
                continue
            tg = raw.get("targets") if isinstance(raw, dict) else None
            if isinstance(tg, list):
                has_targets += 1
                oov = [t for t in tg if not (isinstance(t, str) and t in ids)]
                if oov:
                    oov_recs += 1; oov_tokens += len(oov)
                    a = r["parsed"].get("action"); disp[a] = disp.get(a, 0) + 1
                    if r["score"] == 1: tension.append(r["id"])
                    details.append({"col": col, "id": r["id"], "stratum": r["stratum"], "raw_action": raw.get("action"),
                                    "oov_count": len(oov), "parsed_action": a, "parsed_targets": r["parsed"].get("targets"),
                                    "system_action": r.get("system_action"), "score": r["score"]})
        print(f"| {col} | {n} | {json_ok} | {has_targets} | {oov_recs} | {oov_tokens} | {disp or '—'} | {tension or '无'} |")
    sha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    print(f"\n脚本 SHA256: {sha}")
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump(details, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"明细已写 {out}（{len(details)} 条；S5条目只含id，不含指令文本）")

if __name__ == "__main__":
    main()
