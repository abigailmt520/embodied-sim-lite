#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轨迹记录器：10Hz记录/odom位姿到CSV，Ctrl+C收尾写盘。

用途：录制一段行驶轨迹（教学实验报告配图/轨迹分析）；slip=0时/odom≡真值。
用法：python3 traj_logger.py [--out traj.csv]
"""
import argparse
import csv
import math
from pathlib import Path

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="traj.csv")
    args = ap.parse_args()
    rows = []

    class L(Node):
        def __init__(self):
            super().__init__("traj_logger")
            self.create_subscription(Odometry, "/odom", self.cb, 10)
            self.n = 0

        def cb(self, m):
            p, q = m.pose.pose.position, m.pose.pose.orientation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            rows.append((self.get_clock().now().nanoseconds / 1e9, p.x, p.y, yaw))
            self.n += 1
            if self.n % 50 == 0:
                print(f"\r已记录{self.n}帧 当前({p.x:.2f},{p.y:.2f})", end="", flush=True)

    rclpy.init()
    node = L()
    print("[轨迹记录] 开始（Ctrl+C 收尾写盘）")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        out = Path(args.out).expanduser()
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "x", "y", "yaw"])
            w.writerows(rows)
        print(f"\n[轨迹记录] {len(rows)}帧 → {out}")
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
