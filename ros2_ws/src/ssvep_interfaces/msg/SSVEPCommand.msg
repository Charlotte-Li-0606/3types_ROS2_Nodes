std_msgs/Header header

# One of idle, forward, backward, left, right, or stop.
string direction

# Frequency selected by the decoder.
float32 detected_frequency

# Decoder confidence in the range [0, 1].
float32 confidence

# False means that the decoder did not meet its confidence threshold.
bool valid
