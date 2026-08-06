"""Launch the real EEG pipeline with only the 14 Hz backward target."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    real_launch = os.path.join(
        get_package_share_directory("ssvep_simulation"),
        "launch",
        "turtlesim_real_eeg.launch.py",
    )
    return LaunchDescription(
        [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(real_launch),
                launch_arguments={
                    "visual_target_frequency": "14.0",
                    "visual_geometry": "760x760+20+100",
                    "visual_panel_gap": "100",
                    "data_file": "logs/eeg_accuracy_backward.txt",
                    "driver_log_file": (
                        "logs/runtime/linux_eeg_driver_accuracy_backward.log.txt"
                    ),
                    "pipeline_log_file": (
                        "logs/runtime/ssvep_accuracy_backward.log.txt"
                    ),
                }.items(),
            )
        ]
    )
