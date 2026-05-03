#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy
import json
import math
import time
import threading
import websocket
from geometry_msgs.msg import Twist, TransformStamped, TwistStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_ros import TransformBroadcaster

def get_quaternion_from_euler(yaw):
    return [0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)]

class EmbodiedRos2Bridge(Node):
    def __init__(self):
        super().__init__('embodied_sim_bridge')
        
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
        
        self.ws = None
        self.log_counter = 0
        self.last_lidar_stamp = 0 
        
        self.connect_websocket()

    def connect_websocket(self):
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp("ws://192.168.1.149:8000/ws/simulation",
                                         on_open=self.on_open,
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close)
        wst = threading.Thread(target=self.ws_thread)
        wst.daemon = True
        wst.start()
        self.get_logger().info("🔗 ROS 2 桥接器启动中，正在寻找 Web 引擎...")

    def ws_thread(self):
        while True:
            self.ws.run_forever()
            self.get_logger().error("❌ 未连接到 Web 引擎，3秒后重试...")
            time.sleep(3)

    def on_open(self, ws):
        self.get_logger().info("✅ 完美！已成功连接到 Web 物理引擎！")
        self.last_lidar_stamp = 0

    def on_close(self, ws, close_status_code, close_msg):
        self.get_logger().warn("⚠️ WebSocket 连接已断开！")

    def cmd_twist_callback(self, msg):
        self.process_cmd(msg.linear.x, msg.angular.z)

    def cmd_stamped_callback(self, msg):
        self.process_cmd(msg.twist.linear.x, msg.twist.angular.z)

    def process_cmd(self, v_x, w_z):
        v = v_x * 3.0
        w = w_z * 1.5
        
        if abs(v_x) > 0.01 or abs(w_z) > 0.01:
            self.log_counter += 1
            if self.log_counter % 5 == 0:
                self.get_logger().info(f"🚀 [控制指令下发] 线速度: {v_x:.2f}, 角速度: {w_z:.2f}")

        try:
            self.ws.send(json.dumps({"left": v - w, "right": v + w}))
        except Exception:
            pass 

    def on_message(self, ws, message):
        data = json.loads(message)
        current_time = self.get_clock().now().to_msg()

        if "ox" in data:
            odom = Odometry()
            odom.header.stamp = current_time
            odom.header.frame_id = "odom"
            odom.child_frame_id = self.robot_base_frame
            odom.pose.pose.position.x = data["ox"]
            odom.pose.pose.position.y = data["oy"]
            q = get_quaternion_from_euler(data["oyaw"])
            odom.pose.pose.orientation.x = q[0]
            odom.pose.pose.orientation.y = q[1]
            odom.pose.pose.orientation.z = q[2]
            odom.pose.pose.orientation.w = q[3]
            odom.twist.twist.linear.x = data.get("v", 0.0)
            self.odom_pub.publish(odom)

            t0 = TransformStamped()
            t0.header.stamp = current_time
            t0.header.frame_id = "odom"
            t0.child_frame_id = self.robot_base_frame
            t0.transform.translation.x = data["ox"]
            t0.transform.translation.y = data["oy"]
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

        if "lidar" in data:
            stamp = data.get("lidar_stamp", 0)
            if stamp != self.last_lidar_stamp:
                self.last_lidar_stamp = stamp
                
                scan = LaserScan()
                scan.header.stamp = current_time
                scan.header.frame_id = "laser_frame"
                
                scan.angle_min = 0.0
                scan.angle_max = 2.0 * 3.1415926
                scan.angle_increment = (2.0 * 3.1415926) / len(data["lidar"])
                scan.range_min = 0.1
                # 🎯 扩容配合：动态读取 Web 引擎下发的 UI 最大雷达距离配置，告别硬编码！
                scan.range_max = float(data.get("range_max", 15.0))
                scan.ranges = [float(r) for r in data["lidar"]]
                
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
