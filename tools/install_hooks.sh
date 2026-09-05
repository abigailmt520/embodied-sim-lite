#!/usr/bin/env bash
# 一键安装本仓 git 钩子（其他克隆重装用）：把 tools/hooks/* 复制到 .git/hooks/ 并加执行位。
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"; HOOKS="$(git -C "$ROOT" rev-parse --git-path hooks)"
mkdir -p "$HOOKS"
for h in "$ROOT"/tools/hooks/*; do
  cp "$h" "$HOOKS/$(basename "$h")"; chmod +x "$HOOKS/$(basename "$h")"
  echo "installed: $HOOKS/$(basename "$h")"
done
