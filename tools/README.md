# tools/

- `paper_figures/`：《计算机教育》论文图表复现（见其 README）。
- `audit_secrets.py` + `audit_allowlist.txt`：凭证级词表审计（`--self-test` 自测 / `--ref <ref>` 扫某引用全树 / 无参扫工作树）；任一剩余命中 exit 1。
- `publish.sh`：公开仓推送唯一入口——自测 → 待推分支全树审计 → 推送，任一环节非零即停；冻结分支 `paper-sync-v1.1`、`paper2-embodied-simlite` 默认拒推（镜像同步须显式 `--allow-frozen`，仍经审计）。用法 `tools/publish.sh [--tags] [--allow-frozen] [branch] [remote ...]`。
- `install_hooks.sh`：一键把 `hooks/pre-push`（推送前审计硬门）安装到本地克隆的 `.git/hooks/`；新克隆先跑一次。
