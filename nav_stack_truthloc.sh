#!/bin/bash
# 真值定位模式导航栈——配合 README 5.9 静态世界导航模式使用。
# 原理：map帧≡世界帧（make_gt_map真值图origin=0）且 odom≡真值（nav_gateway slip=0），
# 故 map→odom=恒等静态变换即数学精确定位；AMCL在24束稀疏扫描下漂移大（实测
# 单腿0.2~0.5m），做导航量化实验建议直接用本模式。
# 用法：bash nav_stack_truthloc.sh [map_gt.yaml] [nav2_params.yaml]
#   参数②可省（用Nav2默认参数）；建议用 make_nav2_params_navmode.py 生成的调优版
#  （含RPP控制器——Jazzy默认MPPI在本桥接下实测持续低速爬行，见README 5.8）。
set -e
MAP="${1:-map_gt.yaml}"
PARAMS="${2:-}"
source /opt/ros/jazzy/setup.bash
trap 'kill 0' EXIT
ros2 run tf2_ros static_transform_publisher --x 0 --y 0 --z 0 --qx 0 --qy 0 --qz 0 --qw 1 \
     --frame-id map --child-frame-id odom &
ros2 run nav2_map_server map_server --ros-args -p yaml_filename:="$(realpath "$MAP")" &
sleep 3
ros2 lifecycle set /map_server configure
ros2 lifecycle set /map_server activate
echo "===== 真值定位就绪（map→odom恒等），起导航栈 ====="
if [ -n "$PARAMS" ]; then
  exec ros2 launch nav2_bringup navigation_launch.py params_file:="$(realpath "$PARAMS")"
else
  exec ros2 launch nav2_bringup navigation_launch.py
fi
