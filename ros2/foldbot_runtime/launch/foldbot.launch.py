"""Launch the ROS runtime without starting a garment cycle."""
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _runtime_node(context):
    overrides = {}
    for name in ("model_path", "px_per_m", "image_topic", "board_frame"):
        value = LaunchConfiguration(name).perform(context)
        if value:
            overrides[name] = float(value) if name == "px_per_m" else value
    return [Node(
        package="foldbot_runtime", executable="foldbot_node", output="screen",
        namespace="foldbot", name="runtime",
        parameters=[LaunchConfiguration("params_file").perform(context), overrides],
    )]


def generate_launch_description():
    config = Path(get_package_share_directory("foldbot_runtime")) / "config" / "mini_pc.yaml"
    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=str(config)),
        DeclareLaunchArgument("model_path", default_value=""),
        DeclareLaunchArgument("px_per_m", default_value=""),
        DeclareLaunchArgument("image_topic", default_value=""),
        DeclareLaunchArgument("board_frame", default_value=""),
        OpaqueFunction(function=_runtime_node),
    ])