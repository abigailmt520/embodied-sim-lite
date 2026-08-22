#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成静态世界导航模式的Nav2调优参数（配合README 5.9）——从系统默认参数出发叠加改写：

  1. AMCL预置初始位姿（seed=42世界起点8.08/6.24/yaw1.536）——启动即定位，
     根治"无初始位姿→map帧缺失→导航侧活化死锁"（seed=42默认世界的出生点；换seed请同步改POSE）
  2. MPPI禁倒车 vx_min=0（本车v∈[0,1]，平台§5.7硬约束）
  3. v4：边距实验整体撤销（v2冻住/v3超时实测——防穿模全权交由跑间守卫承担），
     costmap/CostCritic全部回默认；新增MPPI提速 vx_max 0.5→0.9（120s预算内到达率杠杆，
     上限仍低于env的1.0）

改写逐项防御式定位（键不存在则报告跳过，不硬炸）；输出SHA256供FROZEN封存。
【VM零外网禁令】依赖仅PyYAML+stdlib。
用法：python3 make_nav2_params_p4.py [--out ~/sim_ops/nav2_params_p4.yaml]
"""
import argparse
import hashlib
from pathlib import Path

import yaml

SRC = "/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml"
POSE = {"x": 8.08, "y": 6.24, "z": 0.0, "yaw": 1.536}


def dig(d, *keys):
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return None
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="nav2_params_navmode.yaml")
    args = ap.parse_args()
    d = yaml.safe_load(Path(SRC).read_text(encoding="utf-8"))
    done, skipped = [], []

    a = dig(d, "amcl", "ros__parameters")
    if a is not None:
        a["set_initial_pose"] = True
        a["initial_pose"] = dict(POSE)
        done.append("amcl预置位姿(8.08,6.24,yaw1.536)")
    else:
        skipped.append("amcl")

    cs = dig(d, "controller_server", "ros__parameters")
    if cs is not None and "FollowPath" in cs:
        # v6：MPPI整体换RPP（README §5.8预案：MPPI在odom反馈健康下仍输出~0.014m/s
        # 爬行，2026-08-22实测三轮定案；RPP不依赖速度反馈，结构最简）
        cs["FollowPath"] = {
            "plugin": "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController",
            "desired_linear_vel": 0.8,
            "lookahead_dist": 0.6, "min_lookahead_dist": 0.3, "max_lookahead_dist": 0.9,
            "use_velocity_scaled_lookahead_dist": True,
            "transform_tolerance": 0.2,
            "use_collision_detection": True,
            "max_allowed_time_to_collision_up_to_carrot": 1.0,
            "use_regulated_linear_velocity_scaling": True,
            "use_cost_regulated_linear_velocity_scaling": False,
            "regulated_linear_scaling_min_radius": 0.9,
            "regulated_linear_scaling_min_speed": 0.25,
            "allow_reversing": False,
            "use_rotate_to_heading": True,
            "rotate_to_heading_angular_vel": 1.2,
            "rotate_to_heading_min_angle": 0.785,
            "max_angular_accel": 3.2,
            "max_robot_pose_search_dist": 10.0,
        }
        done.append("FollowPath整体换RPP(v6:desired_vel0.8/禁倒车/rotate_to_heading)")
    else:
        skipped.append("FollowPath")

    gc = dig(d, "controller_server", "ros__parameters", "general_goal_checker")
    if gc is not None:
        gc["xy_goal_tolerance"] = 0.15
        done.append("goal容差0.25→0.15(v5:停点须显著紧于0.30冻结复测容差)")
    else:
        skipped.append("general_goal_checker")

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print("[改写完成] " + "；".join(done))
    if skipped:
        print("[键缺失跳过·须回报] " + "；".join(skipped))
    print(f"[输出] {out}\n[SHA256] {sha}（批量前入FROZEN封存）")


if __name__ == "__main__":
    main()
