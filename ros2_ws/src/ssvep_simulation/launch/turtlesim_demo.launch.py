"""Launch the SSVEP simulation and the ROS2 turtlesim window."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    log_file = LaunchConfiguration("log_file")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "log_file",
                default_value="logs/runtime/ssvep_simulation.log.txt",
                description="Standalone text log path",
            ),
            Node(
                package="turtlesim",
                executable="turtlesim_node",
                name="turtlesim",
                output="screen",
            ),
            Node(
                package="ssvep_simulation",
                executable="ssvep_stimulus",
                name="ssvep_stimulus",
                output="screen",
                parameters=[
                    {
                        "auto_cycle": True,
                        "cycle_seconds": 6.0,
                        "frequency": 10.0,
                        "mode": "forward",
                        "log_file": log_file,
                    }
                ],
            ),
            Node(
                package="ssvep_simulation",
                executable="eeg_driver",
                name="eeg_driver",
                output="screen",
                parameters=[
                    {
                        "sampling_rate": 250.0,
                        "channel_count": 8,
                        "frame_samples": 10,
                        "signal_amplitude": 1.0,
                        "noise_std": 0.35,
                        "log_file": log_file,
                    }
                ],
            ),
            Node(
                package="ssvep_simulation",
                executable="ssvep_decoder",
                name="ssvep_decoder",
                output="screen",
                parameters=[
                    {
                        "window_seconds": 3.0,
                        "analysis_period": 0.5,
                        "min_confidence": 0.40,
                        "log_file": log_file,
                    }
                ],
            ),
            Node(
                package="ssvep_simulation",
                executable="turtlesim_bridge",
                name="turtlesim_bridge",
                output="screen",
                parameters=[
                    {
                        "linear_speed": 1.0,
                        "angular_speed": 1.2,
                        "publish_rate": 10.0,
                        "command_timeout": 1.0,
                        "log_file": log_file,
                    }
                ],
            ),
        ]
    )
