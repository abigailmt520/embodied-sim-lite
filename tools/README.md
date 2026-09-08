# tools/

- `paper_figures/`：《计算机教育》论文图表复现（见其 README）。
- `audit_secrets.py` + `audit_allowlist.txt`：凭证级词表审计（`--self-test` 自测 / `--ref <ref>` 扫某引用全树 / 无参扫工作树）；任一剩余命中 exit 1。
- `publish.sh`：公开仓推送唯一入口——自测 → 待推分支全树审计 → 推送，任一环节非零即停；冻结分支 `paper-sync-v1.1`、`paper2-embodied-simlite` 默认拒推（镜像同步须显式 `--allow-frozen`，仍经审计）。用法 `tools/publish.sh [--tag NAME ...] [--allow-frozen] [branch] [remote ...]`；只推显式指定且匹配前缀白名单（`paper*-*`、`p5-*`、`course-*`）的 tag，其余拒推；不提供全量 --tags。
- `install_hooks.sh`：一键把 `hooks/pre-push`（推送前审计硬门）安装到本地克隆的 `.git/hooks/`；新克隆先跑一次。
- `ready_check.py`：三不可变面守卫 / CI 三道门（CSO-028）——`--selfcheck` 门1 三门自检｜`--course` 门2 课程一致性（manifest↔tag↔commit、A/B 同机复跑、golden 对照）｜`--paper` 门3 论文复现（HASHES.lock 只增不改、冻结子集派生复跑）｜`--all`；维护子命令 `--record-golden` / `--lock-artifacts` / `--write-frozen-subset` 默认拒绝覆盖。定义与容差见根目录 `FROZEN-CI.md`，纪律见 `ITERATION.md`。
- `bench/cpu_usage.py`：教学终端 CPU 占用测量（kernel 折算 / gateway `ps %cpu` 两口径）；基准机与基线 `bench/BENCH-MACHINE.md`、`bench/baseline_course-2026A.json`。
