"""Launch the SSVEP-to-WHILL JSON bridge without any hardware connection."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    min_confidence = LaunchConfiguration("min_confidence")
    required_results = LaunchConfiguration("required_consecutive_results")
    timeout_sec = LaunchConfiguration("command_timeout_sec")
    log_file = LaunchConfiguration("log_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "min_confidence",
                default_value="0.75",
                description="Minimum confidence accepted for WHILL direction",
            ),
            DeclareLaunchArgument(
                "required_consecutive_results",
                default_value="2",
                description="Matching results required before direction change",
            ),
            DeclareLaunchArgument(
                "command_timeout_sec",
                default_value="1.0",
                description="Safety timeout for valid direction refresh",
            ),
            DeclareLaunchArgument(
                "log_file",
                default_value="logs/runtime/ssvep_whill_bridge.log.txt",
                description="Standalone WHILL bridge runtime log",
            ),
            Node(
                package="ssvep_simulation",
                executable="ssvep_whill_bridge",
                name="ssvep_whill_bridge",
                output="screen",
                parameters=[
                    {
                        "min_confidence": ParameterValue(
                            min_confidence, value_type=float
                        ),
                        "required_consecutive_results": ParameterValue(
                            required_results, value_type=int
                        ),
                        "command_timeout_sec": ParameterValue(
                            timeout_sec, value_type=float
                        ),
                        "allowed_quality": ["fair", "good"],
                        "log_file": log_file,
                    }
                ],
            ),
        ]
    )
