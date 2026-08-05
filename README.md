# SSVEP ROS2 Simulation

这是一个面向 Ubuntu 22.04 + ROS2 Humble 的 SSVEP 全流程仿真项目。
项目暂时不连接真实 EEG 头环，也不控制真实轮椅；它通过程序生成带噪声的模拟 EEG，
再通过 FBCCA 风格的频率识别输出前后左右指令。

## 节点和话题

```text
ssvep_stimulus  ── /ssvep/stimulus ──┐
                                     ├──> ssvep_decoder
eeg_driver      ── /eeg/raw ─────────┘          ├── /ssvep/command
                                                └── /ssvep/quality
```

| 节点 | 作用 | 发布的话题 |
| --- | --- | --- |
| `eeg_driver` | 生成 8 通道、250 Hz 的模拟原始 EEG | `/eeg/raw` |
| `ssvep_stimulus` | 发布当前模拟刺激频率和模式 | `/ssvep/stimulus` |
| `ssvep_decoder` | 对 EEG 做频率识别并发布指令、置信度和质量 | `/ssvep/command`, `/ssvep/quality` |

仿真中 `eeg_driver` 会订阅刺激状态，用当前频率合成 EEG。这只是为了构造可重复的
仿真数据；接入真实 VisionBCI 头环时，`eeg_driver` 应替换为 BLE 驱动节点。

## Ubuntu 22.04 + ROS2 Humble 安装后运行

```bash
sudo apt update
sudo apt install python3-colcon-common-extensions python3-numpy
mkdir -p ~/ssvep_ros2_ws/src
cd ~/ssvep_ros2_ws/src
git clone https://github.com/Charlotte-Li-0606/3types_ROS2_Nodes.git
cd ..
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch ssvep_simulation simulation.launch.py
```

默认刺激频率会在 10、14、18、22 Hz 之间自动切换。日志会写入：

```text
logs/runtime/ssvep_simulation.log.txt
```

查看原始 EEG：

```bash
ros2 topic echo /eeg/raw
```

查看识别指令：

```bash
ros2 topic echo /ssvep/command
```

查看信号质量：

```bash
ros2 topic echo /ssvep/quality
```

## 脑控 turtlesim Demo

这个 Demo 用 ROS2 自带的二维小乌龟验证脑控链路。当前的 EEG_Driver 仍然生成
模拟 EEG，后面接入真实 VisionBCI 时，只需要替换 EEG_Driver，解码器和小乌龟桥接
接口可以继续使用。

```text
SSVEP_Decoder -- /ssvep/command --> turtlesim_bridge
                                      |
                                      +-- /turtle1/cmd_vel --> turtlesim
```

`turtlesim_bridge` 将识别结果转换为标准 `geometry_msgs/msg/Twist`：

| SSVEP 指令 | `Twist` 输出 |
| --- | --- |
| `forward` | `linear.x = +1.0` |
| `backward` | `linear.x = -1.0` |
| `left` | `angular.z = +1.2` |
| `right` | `angular.z = -1.2` |
| `idle`、无效或超时 | 速度全为 0 |

在 Ubuntu 22.04 + ROS2 Humble 中安装并运行：

```bash
sudo apt update
sudo apt install ros-humble-turtlesim
cd ~/3types_ROS2_Nodes/ros2_ws
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
cd ..
ros2 launch ssvep_simulation turtlesim_demo.launch.py
```

另开终端查看脑控指令和速度：

```bash
source /opt/ros/humble/setup.bash
source ~/3types_ROS2_Nodes/ros2_ws/install/setup.bash
ros2 topic echo /ssvep/command
ros2 topic echo /turtle1/cmd_vel
```

桥接节点以 10 Hz 发布速度，并在 1 秒内没有收到有效指令时自动停车。
这使得解码器约 2 Hz 的判断频率不会让小乌龟出现跳跃式移动。

手动切换刺激时，可以向 `/ssvep/stimulus/select` 发布一个 JSON 字符串，例如：

```bash
ros2 topic pub --once /ssvep/stimulus/select std_msgs/msg/String "{data: '{\"frequency\": 14, \"mode\": \"backward\"}'}"
```

## 话题消息

- `ssvep_interfaces/msg/EEGFrame`：时间戳、采样率、通道数、扁平化 EEG 样本。
- `ssvep_interfaces/msg/StimulusState`：当前刺激频率、模式和是否激活。
- `ssvep_interfaces/msg/SSVEPCommand`：方向、识别频率、置信度、是否有效。
- `ssvep_interfaces/msg/SignalQuality`：SNR、信号 RMS、噪声 RMS 和质量等级。

## 仿真边界

本项目输出的是轮椅控制程序可以订阅的高层方向指令，不直接连接轮椅电机。
后续可以增加一个 ROS2 bridge，将 `/ssvep/command` 转换为 `geometry_msgs/msg/Twist`
并发布到实际底盘使用的话题。
