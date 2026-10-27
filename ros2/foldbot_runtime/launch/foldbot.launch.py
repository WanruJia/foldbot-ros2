"""Launch the ROS runtime without starting a garment cycle."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("model_path"),
        DeclareLaunchArgument("px_per_m"),
        DeclareLaunchArgument("image_topic", default_value="/camera/image_raw"),
        DeclareLaunchArgument("board_frame", default_value="board"),
        Node(
            package="foldbot_runtime", executable="foldbot_node", output="screen",
            namespace="foldbot", name="runtime",
            parameters=[{
                "model_path": LaunchConfiguration("model_path"),
                "px_per_m": ParameterValue(LaunchConfiguration("px_per_m"), value_type=float),
                "image_topic": LaunchConfiguration("image_topic"),
                "board_frame": LaunchConfiguration("board_frame"),
            }],
        ),
    ])