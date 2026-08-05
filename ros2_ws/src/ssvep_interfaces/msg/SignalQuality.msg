std_msgs/Header header

# Approximate signal-to-noise ratio of the selected component in dB.
float32 snr_db

# RMS of the band-limited signal.
float32 signal_rms

# RMS of the residual/noise estimate.
float32 noise_rms

# One of unknown, poor, fair, or good.
string quality
