#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ros_bridge.py
=============
Embodied-SimLite ROS 2 桥接层（重构自旧版 sim_ros2_bridgeV1.0.py）。

第一性原理（彻底解耦）下的职责边界：
    - 物理推演与 AI 决策完全收敛进 inference_server.py（PPO + embodied_env.py）；
    - 本桥接器只做「协议翻译」：把孪生状态广播翻成 ROS 2 话题，把 ROS 2 控制翻成
      推理网关可识别的人工覆盖指令。

数据流：
    下行(订阅)  : 推理网关 /ws 广播 get_render_state() 新版嵌套契约
                  → 发布 /odom、/scan，并广播 tf（odom→base_footprint→base_link/laser_frame）。
    上行(发布)  : 订阅 /cmd_vel(_nav) → 通过 /ws 下发 {"cmd_vel":{...}} 触发 2s 人工覆盖。

契约对齐（关键变更）：
    旧版读取扁平字段 data["ox"]/data["oyaw"]/data["lidar"]；
    新版改读嵌套字段：里程计取 data["odom"]（带真打滑漂移，与平台「真分叉里程计」一致），
    LiDAR 取 data["lidar"]（真实测距 m）。
    ⚠ /odom 必须发布「里程计」data["odom"] 而非「真值」data["robot"]——若误发真值，
    会在 ROS 层复活「里程计≡真值」的假仪表，与平台真分叉里程计自相矛盾。
"""

import os
import json
import math
import time
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy
import websocket
from geometry_msgs.msg import Twist, TransformStamped, TwistStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_ros import TransformBroadcaster

# 推理网关 WebSocket 地址（统一端点 /ws，取代旧版 /ws/simulation）
GATEWAY_WS_URL = os.environ.get("SIM_GATEWAY_WS", "ws://127.0.0.1:8000/ws")


def get_quaternion_from_euler(yaw):
    return [0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)]


class EmbodiedRos2Bridge(Node):
    def __init__(self):
        super().__init__('embodied_sim_bridge')

        # —— 控制下行：订阅 Nav2 / 遥控的速度指令 ——
        self.create_subscription(TwistStamped, '/cmd_vel_nav', self.cmd_stamped_callback, 10)
        self.create_subscription(Twist, '/cmd_vel', self.cmd_twist_callback, 10)

        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)

        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
            depth=10
        )
        self.scan_pub = self.create_publisher(LaserScan, '/scan', sensor_qos)

        self.tf_broadcaster = TransformBroadcaster(self)

        self.robot_base_frame = "base_footprint"
        self._twist_prev = None   # (t_mono, x, y, yaw) 有限差分算twist用

        self.ws = None
        self.log_counter = 0
        self.last_step = -1   # 以 render_state 的 step 去重，避免重复发布同一帧
        self.reconnect_attempts = 0

        # —— 先声明后发布（FORGE-002 任务七）：启动即打印话题/frame/QoS 契约概要，
        #    供学生用 `ros2 topic info --verbose` 逐条核实（契约见 docs/teaching_api.md §3）——
        self.get_logger().info(
            "📋 桥接契约声明（先声明后发布）：\n"
            "    发布 /odom     nav_msgs/Odometry      QoS RELIABLE/VOLATILE depth=10  "
            "frame odom→base_footprint（漂移里程计，位姿＋有限差分 twist）\n"
            "    发布 /scan     sensor_msgs/LaserScan  QoS BEST_EFFORT/VOLATILE depth=10  "
            "frame laser_frame（24 线 360°，量程取契约 lidar_range）\n"
            "    广播 tf        odom→base_footprint→base_link 及 base_footprint→laser_frame\n"
            "    订阅 /cmd_vel  geometry_msgs/Twist · /cmd_vel_nav geometry_msgs/TwistStamped "
            "→ 推理网关 2s 人工覆盖\n"
            "    断线行为：自动重连（3 秒间隔，无限次）；连接/断开/重连均有带时间戳日志")

        self.connect_websocket()

    # ------------------------------------------------------------------
    # WebSocket 连接管理
    # ------------------------------------------------------------------
    def connect_websocket(self):
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(GATEWAY_WS_URL,
                                         on_open=self.on_open,
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close)
        wst = threading.Thread(target=self.ws_thread)
        wst.daemon = True
        wst.start()
        self.get_logger().info(f"🔗 ROS 2 桥接器启动中，正在连接推理网关 {GATEWAY_WS_URL} ...")

    def ws_thread(self):
        while True:
            self.ws.run_forever()
            self.reconnect_attempts += 1
            self.get_logger().error(
                f"❌ 与推理网关连接中断/失败，3 秒后发起第 {self.reconnect_attempts} 次自动重连 "
                f"→ {GATEWAY_WS_URL}")
            time.sleep(3)

    def on_open(self, ws):
        self.get_logger().info(
            f"✅ 已成功连接到推理网关！（生命周期：CONNECTED，此前重连尝试 "
            f"{self.reconnect_attempts} 次）")
        self.reconnect_attempts = 0
        self.last_step = -1

    def on_close(self, ws, close_status_code, close_msg):
        self.get_logger().warn(
            f"⚠️ WebSocket 连接已断开！（生命周期：DISCONNECTED，code={close_status_code}）；"
            "将自动重连，无需手动重启")

    # ------------------------------------------------------------------
    # 控制下行：/cmd_vel → 人工覆盖指令（推理网关侧负责换算到归一化动作并抢占 RL）
    # ------------------------------------------------------------------
    def cmd_twist_callback(self, msg):
        self.process_cmd(msg.linear.x, msg.angular.z)

    def cmd_stamped_callback(self, msg):
        self.process_cmd(msg.twist.linear.x, msg.twist.angular.z)

    def process_cmd(self, v_x, w_z):
        if abs(v_x) > 0.01 or abs(w_z) > 0.01:
            self.log_counter += 1
            if self.log_counter % 5 == 0:
                self.get_logger().info(
                    f"🕹️ [人工覆盖下发] 线速度: {v_x:.2f} m/s, 角速度: {w_z:.2f} rad/s")
        try:
            # 透传真实物理量；归一化与 2s 覆盖窗口由推理网关 OverrideController 处理
            self.ws.send(json.dumps({"cmd_vel": {"linear": float(v_x), "angular": float(w_z)}}))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 状态上行：解析新版嵌套契约 → 发布 /odom、/scan、tf
    # ------------------------------------------------------------------
    def on_message(self, ws, message):
        data = json.loads(message)
        current_time = self.get_clock().now().to_msg()

        # —— 里程计 + tf：读取新版 data["odom"]（带真打滑漂移；旧契约无 odom 时回退 robot）——
        odom_src = data.get("odom") or data.get("robot")
        if odom_src is not None:
            ox = float(odom_src["x"])    # 里程计（含漂移），非真值——与平台真分叉里程计一致
            oy = float(odom_src["y"])
            oyaw = float(odom_src["theta"])

            odom = Odometry()
            odom.header.stamp = current_time
            odom.header.frame_id = "odom"
            odom.child_frame_id = self.robot_base_frame
            odom.pose.pose.position.x = ox
            odom.pose.pose.position.y = oy
            q = get_quaternion_from_euler(oyaw)
            odom.pose.pose.orientation.x = q[0]
            odom.pose.pose.orientation.y = q[1]
            odom.pose.pose.orientation.z = q[2]
            odom.pose.pose.orientation.w = q[3]
            # —— twist有限差分（2026-08-22实测定案：twist恒0令MPPI每周期从静止
            #    重起步，输出被压至~0.014m/s爬行→60s位移0judged假死；差分速度物理诚实）——
            import time as _time
            _now_m = _time.monotonic()
            if self._twist_prev is not None:
                _pt, _px, _py, _pyaw = self._twist_prev
                _dt = _now_m - _pt
                if 0.0 < _dt < 1.0:
                    _dx, _dy = ox - _px, oy - _py
                    # 线速度带符号：位移在车头方向的投影（本车无倒车，通常≥0）
                    odom.twist.twist.linear.x = (_dx * math.cos(oyaw) + _dy * math.sin(oyaw)) / _dt
                    _dyaw = math.atan2(math.sin(oyaw - _pyaw), math.cos(oyaw - _pyaw))
                    odom.twist.twist.angular.z = _dyaw / _dt
            self._twist_prev = (_now_m, ox, oy, oyaw)
            self.odom_pub.publish(odom)

            t0 = TransformStamped()
            t0.header.stamp = current_time
            t0.header.frame_id = "odom"
            t0.child_frame_id = self.robot_base_frame
            t0.transform.translation.x = ox
            t0.transform.translation.y = oy
            t0.transform.translation.z = 0.15
            t0.transform.rotation.x = q[0]
            t0.transform.rotation.y = q[1]
            t0.transform.rotation.z = q[2]
            t0.transform.rotation.w = q[3]

            t1 = TransformStamped()
            t1.header.stamp = current_time
            t1.header.frame_id = self.robot_base_frame
            t1.child_frame_id = "base_link"
            t1.transform.rotation.w = 1.0

            t2 = TransformStamped()
            t2.header.stamp = current_time
            t2.header.frame_id = self.robot_base_frame
            t2.child_frame_id = "laser_frame"
            t2.transform.translation.z = 0.5
            t2.transform.rotation.w = 1.0

            self.tf_broadcaster.sendTransform([t0, t1, t2])

        # —— 激光雷达：读取新版 data["lidar"]（真实测距 m）+ data["lidar_range"] ——
        lidar = data.get("lidar")
        step = data.get("step", None)
        if lidar and step != self.last_step:
            self.last_step = step
            n = len(lidar)

            scan = LaserScan()
            scan.header.stamp = current_time
            scan.header.frame_id = "laser_frame"
            # env 射线偏移 linspace(-π, π, N, endpoint=False)：angle_min=-π, increment=2π/N
            scan.angle_min = -math.pi
            scan.angle_increment = (2.0 * math.pi) / n
            scan.angle_max = scan.angle_min + scan.angle_increment * (n - 1)
            scan.range_min = 0.0
            scan.range_max = float(data.get("lidar_range", 5.0))
            scan.ranges = [float(r) for r in lidar]

            self.scan_pub.publish(scan)

    def on_error(self, ws, error):
        pass


def main(args=None):
    rclpy.init(args=args)
    bridge = EmbodiedRos2Bridge()
    try:
        rclpy.spin(bridge)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
