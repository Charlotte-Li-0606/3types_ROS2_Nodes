"""Launch turtlesim with the Linux VisionBCI EEG pipeline."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    device_name = LaunchConfiguration("device_name")
    device_name_prefix = LaunchConfiguration("device_name_prefix")
    device_address = LaunchConfiguration("device_address")
    configuration_hex = LaunchConfiguration("configuration_hex")
    data_file = LaunchConfiguration("data_file")
    driver_log_file = LaunchConfiguration("driver_log_file")
    pipeline_log_file = LaunchConfiguration("pipeline_log_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "device_name",
                default_value="",
                description="Exact VisionBCI BLE name; empty uses the name prefix",
            ),
            DeclareLaunchArgument(
                "device_name_prefix",
                default_value="VIS_BCI_",
                description="VisionBCI BLE name prefix",
            ),
            DeclareLaunchArgument(
                "device_address",
                default_value="",
                description="Exact BLE address; takes precedence when non-empty",
            ),
            DeclareLaunchArgument(
                "configuration_hex",
                default_value="",
                description=(
                    "Confirmed vendor configuration bytes as hex; empty performs "
                    "no configuration write"
                ),
            ),
            DeclareLaunchArgument(
                "data_file",
                default_value="logs/eeg_latest.txt",
                description="Latest tab-separated EEG samples (overwritten per run)",
            ),
            DeclareLaunchArgument(
                "driver_log_file",
                default_value="logs/runtime/linux_eeg_driver.log.txt",
                description="Linux EEG driver runtime log",
            ),
            DeclareLaunchArgument(
                "pipeline_log_file",
                default_value="logs/runtime/ssvep_real_eeg_pipeline.log.txt",
                description="Decoder and turtlesim bridge runtime log",
            ),
            Node(
                package="turtlesim",
                executable="turtlesim_node",
                name="turtlesim",
                output="screen",
            ),
            Node(
                package="ssvep_simulation",
                executable="linux_eeg_driver",
                name="linux_eeg_driver",
                output="screen",
                parameters=[
                    {
                        "device_name": device_name,
                        "device_name_prefix": device_name_prefix,
                        "device_address": device_address,
                        "configuration_hex": configuration_hex,
                        "scan_timeout": 10.0,
                        "connect_timeout": 15.0,
                        "reconnect_delay": 3.0,
                        "notification_timeout": 3.0,
                        "data_file": data_file,
                        "log_file": driver_log_file,
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
                        "log_file": pipeline_log_file,
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
                        "log_file": pipeline_log_file,
                    }
                ],
            ),
        ]
    )
