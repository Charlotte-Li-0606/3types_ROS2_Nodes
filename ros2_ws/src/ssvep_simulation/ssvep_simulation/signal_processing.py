"""NumPy-only signal helpers used by the SSVEP decoder.

The implementation follows the FBCCA idea: several frequency bands are
scored with CCA against sine/cosine reference signals and then combined.
It intentionally avoids SciPy so the ROS2 package stays easy to install.
"""

import numpy as np


def reference_signals(frequency: float, sampling_rate: float, samples: int,
                      harmonics: int = 3) -> np.ndarray:
    """Return sine/cosine reference columns for one candidate frequency."""
    time_axis = np.arange(samples, dtype=float) / sampling_rate
    columns = []
    for harmonic in range(1, harmonics + 1):
        phase = 2.0 * np.pi * frequency * harmonic * time_axis
        columns.extend((np.sin(phase), np.cos(phase)))
    return np.column_stack(columns)


def _center(matrix: np.ndarray) -> np.ndarray:
    return matrix - np.mean(matrix, axis=0, keepdims=True)


def cca_score(eeg: np.ndarray, refs: np.ndarray) -> float:
    """Compute the largest squared canonical correlation using NumPy."""
    x = _center(np.asarray(eeg, dtype=float))
    y = _center(np.asarray(refs, dtype=float))
    if x.shape[0] < 4 or y.shape[0] != x.shape[0]:
        return 0.0

    scale = max(1, x.shape[0] - 1)
    cxx = (x.T @ x) / scale
    cyy = (y.T @ y) / scale
    cxy = (x.T @ y) / scale
    regularization_x = max(float(np.trace(cxx)), 1.0) * 1e-7
    regularization_y = max(float(np.trace(cyy)), 1.0) * 1e-7
    cxx += regularization_x * np.eye(cxx.shape[0])
    cyy += regularization_y * np.eye(cyy.shape[0])

    def inverse_square_root(covariance):
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        eigenvalues = np.maximum(eigenvalues, 1e-10)
        return eigenvectors @ np.diag(1.0 / np.sqrt(eigenvalues)) @ eigenvectors.T

    whitened = (
        inverse_square_root(cxx) @ cxy @ inverse_square_root(cyy)
    )
    singular_values = np.linalg.svd(whitened, compute_uv=False)
    return float(np.clip(singular_values[0] ** 2, 0.0, 1.0))


def _fft_bandpass(eeg: np.ndarray, sampling_rate: float,
                  low_hz: float, high_hz: float) -> np.ndarray:
    """Simple zero-phase FFT band-pass used for the simulation."""
    samples = eeg.shape[0]
    frequencies = np.fft.rfftfreq(samples, d=1.0 / sampling_rate)
    spectrum = np.fft.rfft(eeg, axis=0)
    mask = (frequencies >= low_hz) & (frequencies <= high_hz)
    spectrum[~mask, :] = 0.0
    return np.fft.irfft(spectrum, n=samples, axis=0)


def fbcca_scores(eeg: np.ndarray, sampling_rate: float,
                 targets, harmonics: int = 3) -> np.ndarray:
    """Return one combined FBCCA-style score for each target frequency."""
    eeg = np.asarray(eeg, dtype=float)
    targets = [float(target) for target in targets]
    # The first wide band preserves the complete SSVEP component. The other
    # bands give higher weight to lower, middle, and upper harmonics.
    bands = ((6.0, 45.0), (8.0, 15.0), (14.0, 23.0), (20.0, 32.0))
    weights = (1.0, 0.8, 0.6, 0.4)
    total_weight = sum(weights)
    scores = np.zeros(len(targets), dtype=float)

    for band, weight in zip(bands, weights):
        if band[0] >= sampling_rate / 2.0:
            continue
        filtered = _fft_bandpass(eeg, sampling_rate, band[0], band[1])
        for index, target in enumerate(targets):
            refs = reference_signals(target, sampling_rate, eeg.shape[0], harmonics)
            scores[index] += weight * cca_score(filtered, refs)

    if total_weight:
        scores /= total_weight
    return scores


def estimate_quality(eeg: np.ndarray, sampling_rate: float,
                     frequency: float, harmonics: int = 2):
    """Estimate SNR from a sinusoidal projection for the best channel."""
    eeg = np.asarray(eeg, dtype=float)
    refs = reference_signals(frequency, sampling_rate, eeg.shape[0], harmonics)
    best_signal_rms = 0.0
    best_noise_rms = 0.0
    best_snr = -60.0

    for channel in range(eeg.shape[1]):
        channel_data = _center(eeg[:, channel:channel + 1])[:, 0]
        coefficients, _, _, _ = np.linalg.lstsq(refs, channel_data, rcond=None)
        reconstructed = refs @ coefficients
        residual = channel_data - reconstructed
        signal_rms = float(np.sqrt(np.mean(reconstructed ** 2)))
        noise_rms = float(np.sqrt(np.mean(residual ** 2)))
        snr = 20.0 * np.log10((signal_rms + 1e-9) / (noise_rms + 1e-9))
        if snr > best_snr:
            best_snr = snr
            best_signal_rms = signal_rms
            best_noise_rms = noise_rms

    if best_snr >= 6.0:
        quality = "good"
    elif best_snr >= 2.0:
        quality = "fair"
    else:
        quality = "poor"
    return best_snr, best_signal_rms, best_noise_rms, quality
