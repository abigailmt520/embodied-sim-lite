#!/usr/bin/env bash
# 公开仓推送的唯一入口：自测 → 待推引用全树审计 → 推送 → 双远端漂移巡检。任一环节非零即停，不推。
# 用法：tools/publish.sh [--tag NAME ...] [--allow-frozen] [branch] [remote ...]
#   --tag NAME 只推送指定 tag（可重复），且 NAME 须匹配前缀白名单 paper*-*、p5-* 或 course-*，其余拒推（exit 4）；
#   不再提供 --tags（推送全部本地 tag 曾把无关 tag 带入审计并拒推）。
#   branch 默认=当前分支；remote 默认=全部远端。--tags 同时推送 tags。
# 冻结分支（论文态/独立快照，不再提交）：paper-sync-v1.1、paper2-embodied-simlite —— 默认拒绝推送；
#   仅镜像同步（内容不变地推到另一远端）可用 --allow-frozen 显式放行，仍经审计。
set -uo pipefail
FROZEN_BRANCHES="paper-sync-v1.1 paper2-embodied-simlite"
TAGS=""; ALLOW_FROZEN=0
while [ "${1:-}" = "--tag" ] || [ "${1:-}" = "--allow-frozen" ]; do
  if [ "$1" = "--tag" ]; then
    case "$2" in paper*-*|p5-*|course-*) TAGS="$TAGS refs/tags/$2" ;; *) echo "publish: tag $2 不在前缀白名单（paper*-* / p5-* / course-*），拒推" >&2; exit 4 ;; esac
    shift 2
  else ALLOW_FROZEN=1; shift; fi
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
echo "== [3/3] 推送 $BRANCH${TAGS:+ + tags:$TAGS} -> $(echo $REMOTES | tr "\n" " ")=="
status=0
for r in $REMOTES; do
  git push "$r" "$BRANCH:$BRANCH" $TAGS || { echo "publish: 推送 $r 失败" >&2; status=1; }   # $TAGS 为 refs/tags/NAME 列表，逐个显式推送
done
# [4/4] 双远端漂移巡检（CSO-028-R1 裁定③）：只在推送到全部远端时有意义；单远端推送后本就预期不一致，跳过
if [ "$(echo $REMOTES | wc -w)" -ge 2 ] && [ "$status" = 0 ]; then
  echo "== [4/4] 双远端漂移巡检 =="
  bash tools/mirror_check.sh || { echo "publish: 双远端受保护引用漂移，需人工核查" >&2; status=1; }
else
  echo "== [4/4] 单远端推送，跳过双远端巡检（完成双推后请跑 tools/mirror_check.sh）=="
fi
exit $status
