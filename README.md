# SSVEP ROS2 Simulation

这是一个面向 Ubuntu 22.04 + ROS2 Humble 的 SSVEP 项目。它保留了可重复的模拟 EEG
流程，同时提供基于 Linux BlueZ 和 Python Bleak 的 VisionBCI 实机驱动。两种流程都只
控制 ROS2 turtlesim，不连接真实轮椅或真实电机。

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
仿真数据；实机流程使用独立的 `linux_eeg_driver`，模拟驱动仍然保留。

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

## Linux VisionBCI 实机驱动

实机链路如下：

```text
VisionBCI -- BLE/BlueZ --> linux_eeg_driver -- /eeg/raw --> ssvep_decoder
  --> /ssvep/command --> turtlesim_bridge --> /turtle1/cmd_vel --> turtlesim
```

驱动只使用 Linux BlueZ 和 Python Bleak，不使用 Windows DLL、EXE 或厂商 Windows
SDK。安装 Bleak 并构建工作区：

```bash
sudo systemctl enable --now bluetooth
python3 -m pip install --user "bleak>=0.20"
cd ~/3types_ROS2_Nodes/ros2_ws
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
cd ..
```

确认头环已开机且没有被手机或另一台电脑占用，然后启动：

```bash
ros2 launch ssvep_simulation turtlesim_real_eeg.launch.py
```

实机 launch 会同时打开一个四目标 SSVEP 视觉窗口和 turtlesim。视觉窗口默认暂停，
此时 decoder 发布无效的 `idle` 指令，turtle 保持停止。开始录像并佩戴好 EEG 后，
在视觉窗口按 `SPACE` 或点击 `START FLASHING`：

| 注视目标 | 解码指令 |
| --- | --- |
| `10 Hz / FORWARD` | forward |
| `14 Hz / BACKWARD` | backward |
| `18 Hz / LEFT` | left |
| `22 Hz / RIGHT` | right |

四个单目标准确率测试每次只显示一个闪烁目标，并为每个方向保存独立 EEG 和运行日志。
`8 Hz` 只是示例，不在当前 decoder 的候选频率中；准确率测试继续使用与 FBCCA 和控制映射
一致的 `10/14/18/22 Hz`。每次只运行下面一个 launch，结束后按 `Ctrl-C`，再启动下一个：

```bash
# 10 Hz -> forward
ros2 launch ssvep_simulation turtlesim_accuracy_forward.launch.py

# 14 Hz -> backward
ros2 launch ssvep_simulation turtlesim_accuracy_backward.launch.py

# 18 Hz -> left
ros2 launch ssvep_simulation turtlesim_accuracy_left.launch.py

# 22 Hz -> right
ros2 launch ssvep_simulation turtlesim_accuracy_right.launch.py
```

四个 launch 都接受与实机 launch 相同的 `device_name`、`device_address` 等参数。例如：

```bash
ros2 launch ssvep_simulation turtlesim_accuracy_forward.launch.py \
  device_name:=VIS_BCI_DFED857C
```

启动后按 `SPACE` 开始单目标闪烁，同时观察 `/ssvep/command`。decoder 仍然根据 EEG
计算四个候选频率的 FBCCA 分数，不会把屏幕已知频率直接当作识别结果。实机 launch 的
综合四目标窗口扩大为 `1080x820`，目标间保留 80 像素空白区，减少相邻目标的视觉干扰。
real-EEG launch 还会把 turtle 初始化在中心并朝上，因此 forward/backward 在屏幕上表现
为向上/向下运动。

按 `ESC` 或再次按 `SPACE` 会暂停闪烁并停止 turtle。快速闪光可能引起光敏反应；有
光敏性癫痫风险的人不要运行视觉刺激。软件目标频率由单调时钟生成，但正式实验仍应使用
光电二极管测量显示器实际刷新时序，不能把未测量的显示时序当作临床级校准结果。

默认扫描名称以 `VIS_BCI_` 开头的设备。也可以指定完整名称或 BlueZ 地址：

```bash
ros2 launch ssvep_simulation turtlesim_real_eeg.launch.py \
  device_name:=VIS_BCI_DFED857C

ros2 launch ssvep_simulation turtlesim_real_eeg.launch.py \
  device_address:=AA:BB:CC:DD:EE:FF
```

已确认的 BLE UUID 和数据格式：

- EEG service: `f0001680-0451-4000-b000-000000000000`
- Configuration characteristic: `f0001681-0451-4000-b000-000000000000`
- EEG notification characteristic: `f0001682-0451-4000-b000-000000000000`
- EEG payload 为 `data[2:122]`；每包 5 个 sample，每个 sample 8 通道；每个通道是
  signed 24-bit big-endian，随后乘以 `0.02235`

目前没有已确认的 configuration characteristic 写入内容，因此驱动默认只验证该
characteristic 存在，不会猜测或发送配置命令。如果厂商确认了配置字节，可以显式传入，
例如 `configuration_hex:="0102"`。不要使用未经确认的值。

每个 BLE notification 发布一个 `EEGFrame`，所以 `/eeg/raw` 的消息频率预期约为
50 Hz；每条消息包含 5 个 sample，消息中的 `sampling_rate` 是 250 Hz。驱动每 5 秒
根据实际通知间隔计算一次 sample rate，只有收到并成功解析真实 notification 后才会
记录“sampling verified”。

实机日志：

```text
logs/eeg_latest.txt                         # 每次运行覆盖，timestamp + EEG_1..EEG_8
logs/eeg_accuracy_forward.txt               # 10 Hz 单目标测试
logs/eeg_accuracy_backward.txt              # 14 Hz 单目标测试
logs/eeg_accuracy_left.txt                  # 18 Hz 单目标测试
logs/eeg_accuracy_right.txt                 # 22 Hz 单目标测试
logs/runtime/linux_eeg_driver.log.txt       # 发现、连接、notification、断开和采样率
logs/runtime/ssvep_real_eeg_pipeline.log.txt
```

检查话题：

```bash
ros2 topic list
ros2 topic echo /eeg/raw
ros2 topic hz /eeg/raw
ros2 topic echo /ssvep/command
ros2 topic echo /ssvep/quality
ros2 topic echo /turtle1/cmd_vel
```

### 在 ROS2 Humble Docker 中运行

容器必须复用主机 BlueZ 的 system D-Bus；否则 Bleak 无法看到主机蓝牙控制器。GUI
方式还要转发 X11：

```bash
docker run --rm -it --network host --security-opt apparmor=unconfined \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -e DISPLAY="$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -v "$PWD":/workspace -w /workspace \
  ros:humble-ros-base-jammy bash

apt update
apt install -y python3-colcon-common-extensions python3-rosdep python3-pip \
  ros-humble-turtlesim
python3 -m pip install "bleak>=0.20"
source /opt/ros/humble/setup.bash
cd ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
cd ..
ros2 launch ssvep_simulation turtlesim_real_eeg.launch.py
```

Docker 中的 Bluetooth service 仍由主机管理；不要在容器内启动第二个 BlueZ daemon。
Ubuntu 的 Docker AppArmor 默认策略会阻止容器向 system D-Bus 发送 BlueZ 请求，因此上面
只对这个临时容器禁用了 AppArmor confinement；这会降低容器隔离性，不要用于不受信任的
镜像或代码。
如果不能转发显示器，可以用模拟 launch 做无 GUI 的节点测试，但 turtlesim 窗口不会显示。

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

## SSVEP WHILL ROS2 bridge（仅抽象控制话题）

节点 `ssvep_whill_bridge` 将经过安全筛选的 SSVEP 方向转换为 JSON 字符串。它不连接
WHILL 硬件、电机控制器或其他物理执行器。

```text
/ssvep/command  (ssvep_interfaces/msg/SSVEPCommand) --+
                                                        +--> ssvep_whill_bridge
/ssvep/quality  (ssvep_interfaces/msg/SignalQuality) ---+          |
                                                                   v
                                             /whill/controller/bci_input
                                             (std_msgs/msg/String JSON)
```

输出 QoS 为 `RELIABLE`、`VOLATILE`、`KEEP_LAST`、depth `10`。方向 JSON 示例：

```json
{"sequence":1,"stamp_ns":1786000000000000000,"command":"direction","direction":"forward","confidence":0.91,"valid":true,"quality":"good"}
```

停车 JSON 示例：

```json
{"sequence":2,"stamp_ns":1786000000500000000,"command":"stop","reason":"low_confidence"}
```

默认安全参数：

- `min_confidence: 0.75`
- `required_consecutive_results: 2`
- `command_timeout_sec: 1.0`
- `allowed_quality: [fair, good]`

只有 `valid=true`、置信度不低于阈值、质量为 `fair/good` 且方向为
`forward/backward/left/right` 时才可接受方向。首次方向和方向切换都需要两个连续一致
结果；已接受的相同方向会随每条有效输入重复发布，用作连续状态刷新，不会转换为固定距离
移动。`idle`、显式 `stop`、无效方向、低置信度、`poor/unknown` 质量和 1 秒超时都会输出
停车。节点以停车状态启动，并在正常退出时尽可能再发布一次 `bridge_shutdown` 停车消息。
所有输入触发消息都使用 `SSVEPCommand.header.stamp`；超时和其他桥接安全事件使用 ROS
clock，序号从 1 开始并对每条输出严格加 1。

构建并启动：

```bash
cd ~/3types_ROS2_Nodes/ros2_ws
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
cd ..
ros2 launch ssvep_simulation whill_bridge.launch.py
```

也可以直接运行，并在另一终端查看 JSON：

```bash
ros2 run ssvep_simulation ssvep_whill_bridge
ros2 topic echo /whill/controller/bci_input
```

先发布质量，再发布两次相同方向（首次方向需要两个连续结果）：

```bash
ros2 topic pub --once /ssvep/quality \
  ssvep_interfaces/msg/SignalQuality \
  "{snr_db: 8.0, signal_rms: 1.0, noise_rms: 0.3, quality: good}"

ros2 topic pub --rate 2 --times 2 /ssvep/command \
  ssvep_interfaces/msg/SSVEPCommand \
  "{header: {stamp: {sec: 1786000000, nanosec: 123}}, direction: forward, detected_frequency: 10.0, confidence: 0.91, valid: true}"
```

预期第二条结果后出现 `command="direction"`、`direction="forward"`。以下命令分别验证
低置信度、差质量、无效结果和 idle 停车；每条命令应在输出 JSON 中产生对应 `reason`：

```bash
# low_confidence
ros2 topic pub --once /ssvep/command ssvep_interfaces/msg/SSVEPCommand \
  "{direction: forward, confidence: 0.50, valid: true}"

# poor_signal_quality（先更新质量，再发送高置信度方向）
ros2 topic pub --once /ssvep/quality ssvep_interfaces/msg/SignalQuality \
  "{snr_db: -5.0, signal_rms: 0.2, noise_rms: 1.0, quality: poor}"
ros2 topic pub --once /ssvep/command ssvep_interfaces/msg/SSVEPCommand \
  "{direction: forward, confidence: 0.91, valid: true}"

# ssvep_invalid
ros2 topic pub --once /ssvep/command ssvep_interfaces/msg/SSVEPCommand \
  "{direction: forward, confidence: 0.91, valid: false}"

# ssvep_idle（idle 优先于 valid 字段）
ros2 topic pub --once /ssvep/command ssvep_interfaces/msg/SSVEPCommand \
  "{direction: idle, confidence: 0.0, valid: false}"
```

恢复 `good` 质量并接受一个方向后停止发布 `/ssvep/command`，等待超过 1 秒，应出现
`reason="command_timeout"`。独立运行日志写入：

```text
logs/runtime/ssvep_whill_bridge.log.txt
```

## 安全边界

本项目的 `turtlesim_bridge` 只发布到 `/turtle1/cmd_vel`。它不会连接真实轮椅、真实
底盘或真实电机；无效指令和超过 1 秒未更新的指令都会发布零速度。
`ssvep_whill_bridge` 同样只发布抽象 JSON 字符串，不包含 WHILL SDK、串口、CAN、蓝牙
轮椅连接或固定距离移动命令。
