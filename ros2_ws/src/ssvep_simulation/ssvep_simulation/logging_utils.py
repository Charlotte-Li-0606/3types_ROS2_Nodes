"""Small file-logging helper shared by the three ROS2 nodes."""

from pathlib import Path
import logging


def create_file_logger(node_name: str, configured_path: str):
    """Create a logger and return ``(logger, absolute_path)``.

    ROS2 already prints to the terminal. This second logger provides the
    requested standalone text log for a complete simulation run.
    """
    path = Path(str(configured_path)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"ssvep_simulation.{node_name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(path, mode="a", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        logger.addHandler(handler)

    return logger, path
