#!/usr/bin/env bash
# 复现 Table 4「Whitelist」行：在脱敏日志上运行 count_oov_targets.py（脚本原样，SHA256 a83707e7…；见 benchmark/FROZEN.md「R1描述性计数注记（D4）」）。
# 脚本按论文工作区的正典文件名读取，这里用符号链接把 logs/ 下的脱敏日志映射成同名文件，脚本本身零改动。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; LOGS="$HERE/../logs"; T="$(mktemp -d)"
mkdir -p "$T/results" "$T/src" "$T/eval"
ln -s "$LOGS/table1_edge_sanitized.jsonl"      "$T/results/edge-ollama_qwen2.5-1.5b-instruct_20260808-180543.jsonl"
ln -s "$LOGS/table1_edge3b_sanitized.jsonl"    "$T/results/tier2_edge-ollama_qwen2.5-3b-instruct_20260823-033645.jsonl"
ln -s "$LOGS/table1_fallback2_sanitized.jsonl" "$T/results/tier3_cloud-openai_deepseek-chat_20260823-042527.jsonl"
ln -s "$LOGS/table1_cloud_sanitized.jsonl"     "$T/results/cloud-gemini_gemini-3.6-flash_20260808-232944.jsonl"
cp "$HERE/waypoints.yaml" "$T/src/waypoints.yaml"; cp "$HERE/count_oov_targets.py" "$T/eval/"
( cd "$T" && python3 eval/count_oov_targets.py )   # 预期：四列均 0/120，脚本 SHA256 a83707e7…
rm -rf "$T"
