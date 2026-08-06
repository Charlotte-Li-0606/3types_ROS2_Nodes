"""Convert decoded SSVEP directions into turtlesim velocity commands.

This is the small integration layer between our brain-computer interface and
ROS2's standard turtlesim demo. The real wheelchair bridge can later reuse
the same idea with its own velocity topic.
"""

import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from turtlesim.srv import TeleportAbsolute

from ssvep_interfaces.msg import SSVEPCommand

from .logging_utils import create_file_logger


class TurtlesimBridge(Node):
    """Publish safe, continuously refreshed Twist commands for turtlesim."""

    def __init__(self):
        super().__init__("turtlesim_bridge")

        self._linear_speed = float(
            self.declare_parameter("linear_speed", 1.0).value
        )
        self._angular_speed = float(
            self.declare_parameter("angular_speed", 1.2).value
        )
        self._publish_rate = float(
            self.declare_parameter("publish_rate", 10.0).value
        )
        self._command_timeout = float(
            self.declare_parameter("command_timeout", 1.0).value
        )
        self._initialize_pose = bool(
            self.declare_parameter("initialize_pose", False).value
        )
        self._initial_x = float(
            self.declare_parameter("initial_x", 5.544445).value
        )
        self._initial_y = float(
            self.declare_parameter("initial_y", 5.544445).value
        )
        self._initial_theta = float(
            self.declare_parameter("initial_theta", 1.57079632679).value
        )
        log_file = self.declare_parameter(
            "log_file", "logs/runtime/ssvep_simulation.log.txt"
        ).value
        self._file_logger, self._log_path = create_file_logger(
            "turtlesim_bridge", log_file
        )

        self._latest_direction = "stop"
        self._latest_confidence = 0.0
        self._last_command_time = 0.0
        self._last_published_direction = None
        self._initial_pose_future = None

        self._publisher = self.create_publisher(
            Twist, "/turtle1/cmd_vel", 10
        )
        self.create_subscription(
            SSVEPCommand,
            "/ssvep/command",
            self._command_callback,
            10,
        )
        self._timer = self.create_timer(
            1.0 / max(self._publish_rate, 1.0),
            self._publish_velocity,
        )
        self._initial_pose_timer = None
        if self._initialize_pose:
            self._teleport_client = self.create_client(
                TeleportAbsolute, "/turtle1/teleport_absolute"
            )
            self._initial_pose_timer = self.create_timer(
                0.25, self._request_initial_pose
            )

        message = (
            f"started; publishing /turtle1/cmd_vel at "
            f"{self._publish_rate:.1f} Hz; timeout={self._command_timeout:.1f}s; "
            f"log={self._log_path}"
        )
        self.get_logger().info(message)
        self._file_logger.info(message)

    def _request_initial_pose(self):
        if self._initial_pose_future is not None:
            return
        if not self._teleport_client.service_is_ready():
            return

        request = TeleportAbsolute.Request()
        request.x = self._initial_x
        request.y = self._initial_y
        request.theta = self._initial_theta
        self._initial_pose_future = self._teleport_client.call_async(request)
        self._initial_pose_future.add_done_callback(self._initial_pose_response)

    def _initial_pose_response(self, future):
        try:
            future.result()
        except Exception as exc:
            self._initial_pose_future = None
            self.get_logger().warning(
                f"initial turtle pose request failed; retrying: {exc}"
            )
            return

        if self._initial_pose_timer is not None:
            self._initial_pose_timer.cancel()
        message = (
            "initialized turtle pose: "
            f"x={self._initial_x:.3f}, y={self._initial_y:.3f}, "
            f"theta={self._initial_theta:.3f} rad"
        )
        self.get_logger().info(message)
        self._file_logger.info(message)

    def _command_callback(self, msg: SSVEPCommand):
        direction = str(msg.direction).lower()
        confidence = float(msg.confidence)
        if not msg.valid or direction not in {
            "forward",
            "backward",
            "left",
            "right",
        }:
            direction = "stop"

        self._latest_direction = direction
        self._latest_confidence = confidence
        self._last_command_time = time.monotonic()

    def _publish_velocity(self):
        command_age = time.monotonic() - self._last_command_time
        direction = self._latest_direction
        if self._last_command_time == 0.0 or command_age > self._command_timeout:
            direction = "stop"

        twist = Twist()
        if direction == "forward":
            twist.linear.x = self._linear_speed
        elif direction == "backward":
            twist.linear.x = -self._linear_speed
        elif direction == "left":
            twist.angular.z = self._angular_speed
        elif direction == "right":
            twist.angular.z = -self._angular_speed

        self._publisher.publish(twist)
        if direction != self._last_published_direction:
            message = (
                f"direction={direction}; linear_x={twist.linear.x:.2f}; "
                f"angular_z={twist.angular.z:.2f}; "
                f"confidence={self._latest_confidence:.2f}"
            )
            self.get_logger().info(message)
            self._file_logger.info(message)
            self._last_published_direction = direction


def main(args=None):
    rclpy.init(args=args)
    node = TurtlesimBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
