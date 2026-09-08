# 论文图表复现脚本(paper_figures)

复现论文《面向具身智能的系统审计素养培养实践》(《计算机教育》已录用，待刊)的全部统计图表及图 6 合成图。

## 产物与论文对应关系(五项,对齐论文 v1_2)

| 输出文件 | 论文编号 | 内容 |
|---|---|---|
| `fig4_ppo_eval.png` | 图 4 | PPO 导航策略量化评测(25 张随机地图,成功/碰撞/超时条形图) |
| `fig5_cpu_compare.png` | 图 5 | 同等 SLAM 建图与导航任务下教学终端 CPU 占用对比 |
| `fig6_composite.jpeg` | 图 6 | (a) 部署实拍 + (b) SLAM/Nav2 截图组 纵向合成 |
| `fig7_attainment.png` | 图 7 | 三届×三学期达成度分组柱状图(含 0.65 合格阈值线)【v1_2 更正版】 |
| `fig8_dimensions.png` | 图 8 | GR5.2×2 / GR9.2 / GR10.2 四维度黑白折线【v1_2 更正版】 |

**v1_2 更正说明**:图 7 由"转置折线"更正为"三届×三学期"分组柱状(黑白纹理区分学期);图 8 补齐此前遗漏的 GR10.2 系列,共四条黑白折线,数值按原图像素标定复核(误差 ≤0.002);图内一律不再嵌入"图N"编号,编号仅由正文题注承载。

(论文图 2 由 `audit/make_audit_figure.py --paper` 生成,图 3 由 `diagnostics/record_fork.py --paper` 生成,不在本脚本范围内。)

## 用法

```bash
python tools/paper_figures/make_paper_figures.py                 # 默认输出到 ./figs_out,dpi=200
python tools/paper_figures/make_paper_figures.py --dpi 300       # 论文投稿建议 300
python tools/paper_figures/make_paper_figures.py --outdir /tmp/figs
python tools/paper_figures/make_paper_figures.py --eval-json audit/eval_summary.json
python tools/paper_figures/make_paper_figures.py --audit-json audit_summary.json
```

- `--eval-json`:传入 `audit/run_action1.py` 评测后导出的 `eval_summary.json`,图 4 将从平台实测数据生成,与论文数值形成可复现闭环;不提供时使用脚本内嵌的论文常量。
- `--audit-json`:传入 `tools/audit_tools/analyze_packs.py` 汇总审计包后导出的 `audit_summary.json`,额外生成过程性证据系列 `figA_detection_table.png`(注入-检出结果表)、`figA_latency_dist.png`(检出时延分布)与 `figA_coding_dist.png`(证伪编码等级分布,**仅当 JSON 含人工双评 `coding` 键时生成**);均为黑白印刷友好,论文图号确定后统一改名。
- 中文字体按平台自动探测(回退链:Noto Sans CJK SC → Source Han Sans SC → Microsoft YaHei → PingFang SC → Noto Sans CJK JP);找不到中文字体时打印警告,不报错。

## 数据来源与更新方式

图 4/图 5/图 7/图 8 的统计数据全部取自论文正文与表 2(图 8 数值另经原图像素标定复核),**内嵌于脚本顶部的【数据常量区】**(`FIG4_EVAL`、`FIG5_*`、`FIG7_*`、`FIG8_DIMENSIONS`)。更新教学数据(如新增一届达成度)时只需修改常量区,重新运行即可再生图表;图 4 亦可直接用 `--eval-json` 挂接平台最新评测结果。

图 6 为照片合成,不含统计数据:需要本目录 `assets/` 下两张源图 —— `photo_deploy.png`(部署实拍)与 `slam_nav_montage.jpeg`(SLAM/Nav2 截图组),缺图时跳过并提示,不影响其余四图。合成用 Pillow 完成(matplotlib 的既有依赖,无需额外安装)。

生成的 PNG/JPEG 为可复现产物,不入库(见根目录 `.gitignore` 的 `figs_out/`)。
