"""Single- or four-target visual SSVEP stimulus for turtlesim demos."""

import signal
import time
import tkinter as tk

import rclpy
from rclpy.node import Node

from ssvep_interfaces.msg import StimulusState


TARGETS = (
    (10.0, "FORWARD", "Top left"),
    (14.0, "BACKWARD", "Top right"),
    (18.0, "LEFT", "Bottom left"),
    (22.0, "RIGHT", "Bottom right"),
)


class SSVEPVisualStimulus(Node):
    """Display phase-driven flashing panels and publish their run state."""

    def __init__(self):
        super().__init__("ssvep_visual_stimulus")

        geometry = str(
            self.declare_parameter("geometry", "1080x820+20+100").value
        )
        requested_frequency = float(
            self.declare_parameter("target_frequency", 0.0).value
        )
        self._panel_gap = max(
            0, int(self.declare_parameter("panel_gap", 80).value)
        )
        self._targets = self._select_targets(requested_frequency)
        self._single_target = len(self._targets) == 1
        self._target_frequency = (
            self._targets[0][0] if self._single_target else 0.0
        )
        self._active = bool(
            self.declare_parameter("start_active", False).value
        )
        self._render_interval_ms = max(
            1, int(self.declare_parameter("render_interval_ms", 4).value)
        )
        self._publisher = self.create_publisher(
            StimulusState, "/ssvep/stimulus", 10
        )
        self._phase_start = time.perf_counter()
        self._last_state_publish = 0.0
        self._closed = False

        self._root = tk.Tk()
        if self._single_target:
            frequency, direction, _location = self._targets[0]
            title = f"SSVEP Accuracy Test - {direction} - {frequency:.0f} Hz"
            self._mode_description = f"TEST: {direction} / {frequency:.0f} Hz"
        else:
            title = "SSVEP Visual Targets - VisionBCI Turtlesim"
            self._mode_description = "4-TARGET CONTROL"
        self._root.title(title)
        self._root.geometry(geometry)
        self._root.minsize(700, 620)
        self._root.configure(background="#20242b")
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._root.bind("<space>", self._toggle)
        self._root.bind("<Return>", self._toggle)
        self._root.bind("<Escape>", self._pause)

        self._root.grid_columnconfigure(0, weight=1)
        self._root.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self._root, background="#20242b", padx=12, pady=8)
        header.grid(row=0, column=0, sticky="nsew")
        header.grid_columnconfigure(0, weight=1)

        self._status_label = tk.Label(
            header,
            text="",
            font=("DejaVu Sans", 18, "bold"),
            background="#20242b",
            foreground="#ffcc66",
        )
        self._status_label.grid(row=0, column=0, sticky="w")
        self._toggle_button = tk.Button(
            header,
            command=self._toggle,
            font=("DejaVu Sans", 13, "bold"),
            padx=16,
            pady=5,
        )
        self._toggle_button.grid(row=0, column=1, sticky="e")

        target_grid = tk.Frame(self._root, background="#20242b", padx=3, pady=3)
        target_grid.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        if self._single_target:
            target_grid.grid_rowconfigure(0, weight=1)
            target_grid.grid_columnconfigure(0, weight=1)
            grid_positions = ((0, 0),)
        else:
            target_grid.grid_rowconfigure(0, weight=1, uniform="target")
            target_grid.grid_rowconfigure(1, minsize=self._panel_gap)
            target_grid.grid_rowconfigure(2, weight=1, uniform="target")
            target_grid.grid_columnconfigure(0, weight=1, uniform="target")
            target_grid.grid_columnconfigure(1, minsize=self._panel_gap)
            target_grid.grid_columnconfigure(2, weight=1, uniform="target")
            grid_positions = ((0, 0), (0, 2), (2, 0), (2, 2))

        self._panels = {}
        for target, (row, column) in zip(self._targets, grid_positions):
            frequency, direction, location = target
            panel = tk.Frame(
                target_grid,
                background="#080808",
                highlightbackground="#87909d",
                highlightthickness=3,
            )
            panel.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=self._panel_gap if self._single_target else 3,
                pady=max(30, self._panel_gap // 2) if self._single_target else 3,
            )
            target_note = (
                "Single visible target" if self._single_target else location
            )
            label = tk.Label(
                panel,
                text=f"{direction}\n{frequency:.0f} Hz\n{target_note}",
                font=("DejaVu Sans", 22, "bold"),
                justify="center",
                background="#080808",
                foreground="#e8edf2",
            )
            label.place(relx=0.5, rely=0.5, anchor="center")
            self._panels[frequency] = (panel, label)

        footer = tk.Label(
            self._root,
            text=(
                "SPACE/ENTER: start or pause   ESC: pause\n"
                "Warning: rapidly flashing light can trigger photosensitive reactions."
            ),
            font=("DejaVu Sans", 11),
            background="#20242b",
            foreground="#d8dde5",
            pady=6,
        )
        footer.grid(row=2, column=0, sticky="ew")

        self._update_controls()
        self._root.after(0, self._render)

    @staticmethod
    def _select_targets(requested_frequency):
        if requested_frequency <= 0.0:
            return TARGETS
        for target in TARGETS:
            if abs(target[0] - requested_frequency) < 0.01:
                return (target,)
        allowed = ", ".join(f"{target[0]:.0f}" for target in TARGETS)
        raise ValueError(
            f"target_frequency must be 0 (all targets) or one of: {allowed} Hz"
        )

    def _toggle(self, _event=None):
        self._active = not self._active
        self._phase_start = time.perf_counter()
        self._update_controls()
        self._publish_state()

    def _pause(self, _event=None):
        if self._active:
            self._active = False
            self._update_controls()
            self._publish_state()

    def _update_controls(self):
        if self._active:
            self._status_label.configure(
                text=f"{self._mode_description} — FLASHING ACTIVE",
                foreground="#79e08c",
            )
            self._toggle_button.configure(
                text="PAUSE", background="#f2b35f", activebackground="#ffc978"
            )
        else:
            self._status_label.configure(
                text=(
                    f"{self._mode_description} — PAUSED\n"
                    "Press SPACE when recording"
                ),
                foreground="#ffcc66",
            )
            self._toggle_button.configure(
                text="START FLASHING",
                background="#79e08c",
                activebackground="#9cf0ab",
            )

    def _render(self):
        if self._closed:
            return

        now = time.perf_counter()
        elapsed = now - self._phase_start
        for frequency, _direction, _location in self._targets:
            is_bright = self._active and (
                int(elapsed * frequency * 2.0) % 2 == 0
            )
            background = "#f4f7fa" if is_bright else "#080808"
            foreground = "#101216" if is_bright else "#e8edf2"
            panel, label = self._panels[frequency]
            panel.configure(background=background)
            label.configure(background=background, foreground=foreground)

        if now - self._last_state_publish >= 0.1:
            self._publish_state()
            self._last_state_publish = now
        self._root.after(self._render_interval_ms, self._render)

    def _publish_state(self):
        if not rclpy.ok():
            return
        message = StimulusState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "visual_ssvep_targets"
        message.frequency = self._target_frequency
        message.mode = "single_target" if self._single_target else "multi_target"
        message.active = self._active
        self._publisher.publish(message)

    def _close(self):
        if self._closed:
            return
        self._active = False
        self._publish_state()
        self._closed = True
        self._root.destroy()

    def run(self):
        self._root.mainloop()


def main(args=None):
    rclpy.init(args=args)
    node = SSVEPVisualStimulus()
    signal.signal(signal.SIGINT, lambda _signum, _frame: node._close())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: node._close())
    try:
        node.run()
    except KeyboardInterrupt:
        node._close()
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
