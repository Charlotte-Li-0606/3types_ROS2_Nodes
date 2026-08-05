"""Four-target visual SSVEP stimulus for the real EEG turtlesim demo."""

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
    """Display four phase-driven flashing panels and publish their run state."""

    def __init__(self):
        super().__init__("ssvep_visual_stimulus")

        geometry = str(
            self.declare_parameter("geometry", "760x760+20+100").value
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
        self._root.title("SSVEP Visual Targets - VisionBCI Turtlesim")
        self._root.geometry(geometry)
        self._root.minsize(620, 620)
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

        target_grid = tk.Frame(self._root, background="#59616d", padx=3, pady=3)
        target_grid.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))
        for row in range(2):
            target_grid.grid_rowconfigure(row, weight=1, uniform="target")
        for column in range(2):
            target_grid.grid_columnconfigure(column, weight=1, uniform="target")

        self._panels = {}
        for index, (frequency, direction, location) in enumerate(TARGETS):
            row, column = divmod(index, 2)
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
                padx=3,
                pady=3,
            )
            label = tk.Label(
                panel,
                text=f"{direction}\n{frequency:.0f} Hz\n{location}",
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
                text="FLASHING ACTIVE", foreground="#79e08c"
            )
            self._toggle_button.configure(
                text="PAUSE", background="#f2b35f", activebackground="#ffc978"
            )
        else:
            self._status_label.configure(
                text="PAUSED — press SPACE when recording", foreground="#ffcc66"
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
        for frequency, _direction, _location in TARGETS:
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
        message.frequency = 0.0
        message.mode = "multi_target"
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
