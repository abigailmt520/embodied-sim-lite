#!/usr/bin/env bash
# 公开仓推送的唯一入口：自测 → 待推引用全树审计 → 推送。任一环节非零即停，不推。
# 用法：tools/publish.sh [--tags] [--allow-frozen] [branch] [remote ...]
#   branch 默认=当前分支；remote 默认=全部远端。--tags 同时推送 tags。
# 冻结分支（论文态/独立快照，不再提交）：paper-sync-v1.1、paper2-embodied-simlite —— 默认拒绝推送；
#   仅镜像同步（内容不变地推到另一远端）可用 --allow-frozen 显式放行，仍经审计。
set -uo pipefail
FROZEN_BRANCHES="paper-sync-v1.1 paper2-embodied-simlite"
TAGS=""; ALLOW_FROZEN=0
while [ "${1:-}" = "--tags" ] || [ "${1:-}" = "--allow-frozen" ]; do
  [ "$1" = "--tags" ] && TAGS="--tags"; [ "$1" = "--allow-frozen" ] && ALLOW_FROZEN=1; shift
done
ROOT="$(git rev-parse --show-toplevel)" || exit 2; cd "$ROOT"
BRANCH="${1:-$(git branch --show-current)}"; shift || true
REMOTES="${*:-$(git remote)}"
for f in $FROZEN_BRANCHES; do
  if [ "$BRANCH" = "$f" ]; then
    [ "$ALLOW_FROZEN" = "1" ] && echo "publish: 警告——$BRANCH 为冻结分支，--allow-frozen 仅用于镜像同步（内容不变）" >&2 || { echo "publish: 分支 $BRANCH 已冻结（论文态/独立快照），拒绝推送；镜像同步请显式加 --allow-frozen" >&2; exit 3; }
  fi
done
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
