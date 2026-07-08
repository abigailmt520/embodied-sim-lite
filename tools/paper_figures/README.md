# 论文图表复现脚本(paper_figures)

复现论文《面向具身智能的系统审计素养培养实践》(v1.1,拟刊发于《计算机教育》)的全部统计图表。

## 图表与论文对应关系

| 输出文件 | 论文编号 | 内容 |
|---|---|---|
| `fig4_ppo_eval.png` | 图 4 | PPO 导航策略量化评测(25 张随机地图,成功/碰撞/超时条形图) |
| `fig5_cpu_compare.png` | 图 5 | 同等 SLAM 建图与导航任务下教学终端 CPU 占用对比 |
| `fig7_attainment_trend.png` | 图 7 | 前三届三学期课程达成度趋势(含 0.65 合格阈值线) |
| `fig8_dimension_compare.png` | 图 8 | GR5.2(工具运用)跨届稳定 vs GR9.2(团队协作)波动对比 |

(论文图 2 由 `audit/make_audit_figure.py` 生成,图 3 由 `diagnostics/record_fork.py` 生成,不在本脚本范围内。)

## 用法

```bash
python tools/paper_figures/make_paper_figures.py                 # 默认输出到 ./figs_out,dpi=200
python tools/paper_figures/make_paper_figures.py --dpi 300       # 论文投稿建议 300
python tools/paper_figures/make_paper_figures.py --outdir /tmp/figs
python tools/paper_figures/make_paper_figures.py --eval-json audit/eval_summary.json
```

- `--eval-json`:传入 `audit/run_action1.py` 评测后导出的 `eval_summary.json`,图 4 将从平台实测数据生成,与论文数值形成可复现闭环;不提供时使用脚本内嵌的论文常量。
- 中文字体按平台自动探测(回退链:Noto Sans CJK SC → Source Han Sans SC → Microsoft YaHei → PingFang SC → Noto Sans CJK JP);找不到中文字体时打印警告,不报错。

## 数据来源与更新方式

四幅图的数据全部取自论文正文与表 2,**内嵌于脚本顶部的【数据常量区】**(`FIG4_EVAL`、`FIG5_*`、`FIG7_*`、`FIG8_*`)。更新教学数据(如新增一届达成度)时只需修改常量区,重新运行即可再生图表;图 4 亦可直接用 `--eval-json` 挂接平台最新评测结果。

生成的 PNG 为可复现产物,不入库(见根目录 `.gitignore` 的 `figs_out/`)。
