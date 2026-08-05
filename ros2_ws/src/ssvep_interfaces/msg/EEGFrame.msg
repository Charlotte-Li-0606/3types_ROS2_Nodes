# First sample timestamp for this frame.
std_msgs/Header header

# Samples per second for each channel.
float32 sampling_rate

# Number of EEG channels.
uint16 channel_count

# Number of samples stored for each channel in this frame.
uint16 samples_per_channel

# Row-major values: sample_0_ch_0 ... sample_0_ch_N, sample_1_ch_0 ...
float32[] values
