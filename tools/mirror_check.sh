#!/usr/bin/env bash
# 双远端引用漂移巡检（CSO-028-R1 裁定③）：比对 Gitee 与 GitHub 上受保护 tag 与关键分支的对象哈希。
# 只读，不推不改。任一受保护引用 缺失/哈希不同 → exit 1（报警）；远端不可达 → exit 2。
# 用法：tools/mirror_check.sh [gitee_url] [github_url]   （CI 与 publish.sh 调用；本地亦可直接跑）
set -uo pipefail
G1="${1:-https://gitee.com/yfeng620/embodied-sim-lite}"
G2="${2:-https://github.com/abigailmt520/embodied-sim-lite.git}"
TAG_RE='^refs/tags/(course-|paper[^[:space:]]*-|p5-|v[0-9]+\.[0-9]+\.[0-9]+)'   # 受保护 tag：与 publish.sh 白名单同构（v* 版本 tag 自 FORGE-004 纳入；GitHub ruleset 只护 course-*／paper*-*）
HEAD_RE='^refs/heads/(master|release/.+|paper-sync-v1\.1|paper2-embodied-simlite)$'
a=$(git ls-remote --tags --heads "$G1" 2>/dev/null) || { echo "mirror: 无法访问 $G1" >&2; exit 2; }
b=$(git ls-remote --tags --heads "$G2" 2>/dev/null) || { echo "mirror: 无法访问 $G2" >&2; exit 2; }
# 挂账豁免（只报不红；每条须附原因，解除时删行并记 FROZEN-CI）：
#   refs/heads/paper2-embodied-simlite —— e2b6474 树命中凭证审计误报（embodied_env.py:398 注释中的一个副词，dream-os DECISIONS 09-05 判误报，
#   词根收紧待「第三分支处置令」），推送前硬门拒推故暂不能镜像；tag paper2-final（4f111ad）审计零命中已镜像。
#   refs/tags/v1.0.0 —— 历史版本 tag（2026-05-03，b3b0cd6）只在 Gitee：GitHub 镜像建立时只带 Paper-87 相关引用；
#   FORGE-004 把 v* 纳入巡检时发现，是否补镜像待令（补推须先过推送前审计），在此之前只报不红。
WAIVED='^refs/heads/paper2-embodied-simlite$|^refs/tags/v1\.0\.0$'
refs=$( { echo "$a"; echo "$b"; } | awk '{print $2}' | grep -v '\^{}$' | grep -E "$TAG_RE|$HEAD_RE" | sort -u)
status=0; n=0
printf '%-40s %-9s %-9s %s\n' "ref" "gitee" "github" "状态"
for r in $refs; do
  ha=$(echo "$a" | awk -v r="$r" '$2==r{print substr($1,1,7)}'); hb=$(echo "$b" | awk -v r="$r" '$2==r{print substr($1,1,7)}')
  if [ -z "$ha" ]; then st="ONLY-GITHUB"; elif [ -z "$hb" ]; then st="ONLY-GITEE"; elif [ "$ha" = "$hb" ]; then st="SAME"; else st="DIFF"; fi
  if [ "$st" != "SAME" ] && echo "$r" | grep -qE "$WAIVED"; then st="$st(挂账豁免)"; fi
  case "$st" in SAME|*挂账豁免*) ;; *) status=1 ;; esac
  n=$((n+1)); printf '%-40s %-9s %-9s %s\n' "$r" "${ha:--}" "${hb:--}" "$st"
done
echo "mirror: 比对 $n 条受保护引用 → $([ $status = 0 ] && echo '全同 ✅' || echo '漂移 🔴（需人工核查：以 publish.sh 双推纠正，禁止单边改锚）')"
exit $status
