# Table 4 支撑数据（Paper 87 修订稿 §4.6 "Ablations and Sensitivity"）

Table 4 汇集五项检查，全部由冻结基准运行与归档日志导出，**无新增数据采集**。下表逐行给出数字来源；层序同论文 Table 2：1.5B / 3B / Fallback 2 / Teacher。

| 行 | 数字 | 来源（本包内可复算者标 ✔） |
|---|---|---|
| Interface：shared-prefix → prefix-free 动作集（1.5B，S1） | 12/24 → 24/24 | 开发期冒烟跑（论文 Table 1）；原始冒烟日志在论文工作区归档，**不在本包**（非正典批次） |
| Model tier：同一提示词/schema/温度 | 60.0 / 73.3 / 96.7 / 97.5 % | ✔ `logs/table1_{edge,edge3b,fallback2,cloud}_sanitized.jsonl` 的 `score` 字段；`eval/s4_datapack.md` 表7 |
| Decoding：temperature 0 + 预注册确定性闸 | 四模型闸门检查零变异；一候选教师模型被闸门排除 | `benchmark/FROZEN.md`：协议附录条文二（闸门定义）、「Table 1第三/四列正典登记」（3B/Fallback 2 两跑 24 条逐字节零差异）、「全量归档登记」门2日志哈希（教师 3 条字段+字节双等价）、「教师型号拍板/重拍板」节（候选模型确定性 JSON 截断记录）；闸门日志本身不在本包，以哈希登记为凭 |
| Safety layers：须拒子集 n=14 | 模型层 0 / 7 / 14 / 14；词法屏净增 9 / 0 / 0 / 0 | ✔ `eval/s4_datapack.md` 表3/表8；日志 S5 层 `parsed.action` 与 `system_action` 对照 |
| Whitelist：raw targets 白名单外 | 0 / 0 / 0 / 0（各 120） | ✔ `eval/count_oov_targets.py`（SHA256 a83707e7…）+ `eval/run_count_oov_targets.sh`；机制：边缘两模型 ollama `format=schema` 语法约束解码（by construction），云端两模型自由 JSON + 解析器校验（empirical）；见 FROZEN「R1描述性计数注记（D4）」与「核1注记」 |
