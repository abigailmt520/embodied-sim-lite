#!/usr/bin/env bash
# 公开仓推送的唯一入口：自测 → 待推引用全树审计 → 推送。任一环节非零即停，不推。
# 用法：tools/publish.sh [--tags] [branch] [remote ...]
#   branch 默认=当前分支；remote 默认=全部远端。--tags 同时推送 tags。
# 冻结分支（论文态，不再提交）：paper-sync-v1.1 —— 拒绝推送。
set -uo pipefail
FROZEN_BRANCHES="paper-sync-v1.1"
TAGS=""; [ "${1:-}" = "--tags" ] && { TAGS="--tags"; shift; }
ROOT="$(git rev-parse --show-toplevel)" || exit 2; cd "$ROOT"
BRANCH="${1:-$(git branch --show-current)}"; shift || true
REMOTES="${*:-$(git remote)}"
for f in $FROZEN_BRANCHES; do [ "$BRANCH" = "$f" ] && { echo "publish: 分支 $BRANCH 已冻结为论文态，拒绝推送" >&2; exit 3; }; done
git rev-parse --verify -q "refs/heads/$BRANCH" >/dev/null || { echo "publish: 本地分支不存在: $BRANCH" >&2; exit 2; }
echo "== [1/3] 审计自测 =="
python3 tools/audit_secrets.py --self-test || { echo "publish: 自测未过，停止" >&2; exit 1; }
echo "== [2/3] 全树审计 refs/heads/$BRANCH =="
python3 tools/audit_secrets.py --ref "refs/heads/$BRANCH" || { echo "publish: 审计命中，停止，不推" >&2; exit 1; }
echo "== [3/3] 推送 $BRANCH -> $REMOTES $TAGS =="
status=0
for r in $REMOTES; do
  git push "$r" "$BRANCH:$BRANCH" $TAGS || { echo "publish: 推送 $r 失败" >&2; status=1; }
done
exit $status
