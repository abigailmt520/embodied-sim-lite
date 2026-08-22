#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真值出图（make_gt_map.py）：固定 seed 复现布局 → map_gt.pgm(P5) + map_gt.yaml。

map 帧原点 = (0,0,0) = 仿真世界帧：rviz2 里点到的坐标即世界真值坐标。
与 nav_gateway.py 以同一 --seed 使用（同一世界）。用途：跳过 SLAM，直接为
Nav2（map_server/AMCL 或 slam 免用）提供已知世界的干净占据栅格——本平台
无 SLAM 贡献主张，sim 供真图属标准做法。障碍按原始半径落图不膨胀（膨胀交给
Nav2 costmap）。

用法：python3 make_gt_map.py [--simdir .] [--seed 42] [--out .] [--res 0.05]
"""

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simdir", default=str(Path(__file__).resolve().parent),
                    help="embodied_env.py所在目录（默认=本脚本目录）")
    ap.add_argument("--seed", type=int, default=42, help="世界种子（与nav_gateway一致）")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument("--res", type=float, default=0.05, help="栅格分辨率 m/px")
    ap.add_argument("--wall", type=float, default=0.10, help="场界墙厚 m")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(args.simdir).expanduser().resolve()))
    from embodied_env import EmbodiedNavEnv
    env = EmbodiedNavEnv(seed=args.seed, slip=0.0)

    W, H, res = float(env.ARENA_W), float(env.ARENA_H), args.res
    wpx, hpx = int(round(W / res)), int(round(H / res))
    grid = np.full((hpx, wpx), 254, dtype=np.uint8)   # 254=自由（trinary惯例）

    # 场界墙（物理边界，lidar/碰撞可感）
    wall_px = max(1, int(round(args.wall / res)))
    grid[:wall_px, :] = 0
    grid[-wall_px:, :] = 0
    grid[:, :wall_px] = 0
    grid[:, -wall_px:] = 0

    # 圆障碍（像素中心世界坐标判归属；PGM行0=顶=世界y最大）
    ys, xs = np.mgrid[0:hpx, 0:wpx]
    cx_w = (xs + 0.5) * res
    cy_w = (hpx - ys - 0.5) * res
    for ox, oy, orr in env.obstacles:
        grid[(cx_w - ox) ** 2 + (cy_w - oy) ** 2 <= orr ** 2] = 0

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    pgm = out / "map_gt.pgm"
    with pgm.open("wb") as f:
        f.write(b"P5\n# gt map seed=%d\n%d %d\n255\n" % (args.seed, wpx, hpx))
        f.write(grid.tobytes())
    (out / "map_gt.yaml").write_text(
        f"image: map_gt.pgm\nmode: trinary\nresolution: {res}\n"
        f"origin: [0.0, 0.0, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n",
        encoding="utf-8")

    sha = hashlib.sha256(pgm.read_bytes()).hexdigest()
    print(f"[真值出图] seed={args.seed} {wpx}x{hpx}px res={res}m → {pgm}")
    print("[障碍表] " + "; ".join(f"({o[0]:.2f},{o[1]:.2f},r{o[2]:.2f})" for o in env.obstacles))
    print(f"[起点真值] ({env.pos[0]:.2f},{env.pos[1]:.2f}) yaw={np.degrees(env.theta):.0f}°"
          f"（rviz初始位姿按此设）")
    print(f"[map_gt.pgm SHA256] {sha}")
    print("[下一步] Nav2 bringup map:=~/sim_ops/map_gt.yaml；标定 --map map_gt.yaml")


if __name__ == "__main__":
    main()
