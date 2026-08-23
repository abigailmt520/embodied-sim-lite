# 压测报告（ROS2口径）｜ 20260822-155610 ｜ 模式=正式50

- 判据=FROZEN冻结值（到达≤0.3m仅位置/超时120s/假死无进度60s）；崩溃+假死≥3即回退
- 计数：到达0 ｜ 未到达50 ｜ 崩溃0 ｜ 假死0 ｜ 人工中止0
- 判定：**PASS（崩溃假死0/50＜3）**：sim主线放行，续走08-16闭环

| 跑 | 航点 | 结果 | 归因 | 详情 |
|---|---|---|---|---|
| 1 | W3_podium | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 3.746, "duration_s": 30.6, "note": "nav2_aborted"} |
| 2 | W1_door | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.844, "duration_s": 31.5, "note": "nav2_aborted"} |
| 3 | W4_shelf | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.123, "duration_s": 30.5, "note": "nav2_aborted"} |
| 4 | W4_shelf | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.086, "duration_s": 31.5, "note": "nav2_aborted"} |
| 5 | W5_window | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 7.476, "duration_s": 30.5, "note": "nav2_aborted"} |
| 6 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.234, "duration_s": 31.5, "note": "nav2_aborted"} |
| 7 | W6_bench | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 9.538, "duration_s": 30.5, "note": "nav2_aborted"} |
| 8 | W4_shelf | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.144, "duration_s": 31.5, "note": "nav2_aborted"} |
| 9 | W8_home | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 6.004, "duration_s": 30.5, "note": "nav2_aborted"} |
| 10 | W1_door | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.864, "duration_s": 31.6, "note": "nav2_aborted"} |
| 11 | W8_home | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.935, "duration_s": 31.5, "note": "nav2_aborted"} |
| 12 | W8_home | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.907, "duration_s": 30.5, "note": "nav2_aborted"} |
| 13 | W5_window | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 7.396, "duration_s": 31.5, "note": "nav2_aborted"} |
| 14 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.167, "duration_s": 30.5, "note": "nav2_aborted"} |
| 15 | W4_shelf | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.151, "duration_s": 31.6, "note": "nav2_aborted"} |
| 16 | W6_bench | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 9.548, "duration_s": 30.5, "note": "nav2_aborted"} |
| 17 | W7_trash | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 6.048, "duration_s": 31.5, "note": "nav2_aborted"} |
| 18 | W3_podium | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 3.719, "duration_s": 30.5, "note": "nav2_aborted"} |
| 19 | W1_door | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.86, "duration_s": 31.6, "note": "nav2_aborted"} |
| 20 | W3_podium | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 3.717, "duration_s": 30.5, "note": "nav2_aborted"} |
| 21 | W3_podium | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 3.639, "duration_s": 31.5, "note": "nav2_aborted"} |
| 22 | W3_podium | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 3.663, "duration_s": 30.5, "note": "nav2_aborted"} |
| 23 | W5_window | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 7.482, "duration_s": 31.5, "note": "nav2_aborted"} |
| 24 | W7_trash | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 6.115, "duration_s": 30.5, "note": "nav2_aborted"} |
| 25 | W7_trash | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 6.112, "duration_s": 31.5, "note": "nav2_aborted"} |
| 26 | W4_shelf | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.159, "duration_s": 30.5, "note": "nav2_aborted"} |
| 27 | W8_home | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.886, "duration_s": 31.5, "note": "nav2_aborted"} |
| 28 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.118, "duration_s": 30.5, "note": "nav2_aborted"} |
| 29 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.149, "duration_s": 31.5, "note": "nav2_aborted"} |
| 30 | W5_window | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 7.462, "duration_s": 30.5, "note": "nav2_aborted"} |
| 31 | W1_door | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.854, "duration_s": 31.5, "note": "nav2_aborted"} |
| 32 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.199, "duration_s": 30.5, "note": "nav2_aborted"} |
| 33 | W3_podium | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 3.719, "duration_s": 31.5, "note": "nav2_aborted"} |
| 34 | W6_bench | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 9.583, "duration_s": 30.5, "note": "nav2_aborted"} |
| 35 | W6_bench | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 9.639, "duration_s": 31.5, "note": "nav2_aborted"} |
| 36 | W6_bench | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 9.624, "duration_s": 30.5, "note": "nav2_aborted"} |
| 37 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.18, "duration_s": 31.6, "note": "nav2_aborted"} |
| 38 | W7_trash | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 6.053, "duration_s": 30.5, "note": "nav2_aborted"} |
| 39 | W4_shelf | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.059, "duration_s": 31.6, "note": "nav2_aborted"} |
| 40 | W8_home | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.934, "duration_s": 30.5, "note": "nav2_aborted"} |
| 41 | W7_trash | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 6.063, "duration_s": 31.5, "note": "nav2_aborted"} |
| 42 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.173, "duration_s": 31.5, "note": "nav2_aborted"} |
| 43 | W1_door | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.862, "duration_s": 31.5, "note": "nav2_aborted"} |
| 44 | W7_trash | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 6.068, "duration_s": 31.5, "note": "nav2_aborted"} |
| 45 | W5_window | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 7.452, "duration_s": 31.5, "note": "nav2_aborted"} |
| 46 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.158, "duration_s": 31.5, "note": "nav2_aborted"} |
| 47 | W6_bench | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 9.534, "duration_s": 30.5, "note": "nav2_aborted"} |
| 48 | W6_bench | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 9.613, "duration_s": 31.6, "note": "nav2_aborted"} |
| 49 | W2_charge | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 1.186, "duration_s": 30.5, "note": "nav2_aborted"} |
| 50 | W8_home | not_reached | nav2_timeout | {"nav2_status": 6, "final_dist_m": 5.905, "duration_s": 31.5, "note": "nav2_aborted"} |

> 埋点=Table2归因四路同款；口径见 benchmark/FROZEN.md。回传：本报告+jsonl拷回信箱inbox/。
