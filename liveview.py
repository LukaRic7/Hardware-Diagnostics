import csv
import os
import time
from collections import defaultdict
from datetime import datetime
from tkinter import Tk, StringVar, Listbox, MULTIPLE, END, filedialog, messagebox
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

POLL_MS = 1000


def parse_timestamp(text):
    return datetime.fromisoformat(text.strip())


class CsvLiveViewer:
    def __init__(self, root):
        self.root = root
        root.title("Hardware Metrics Live Viewer")
        root.geometry("1200x800")
        root.minsize(850, 550)

        self.path = None
        self.file = None
        self.file_pos = 0
        self.header = []
        self.sensor_columns = []
        # Keep the full history in memory so All time can plot every loaded sample.
        self.data = defaultdict(list)
        self.window_seconds = 60
        self.dirty = True
        self.last_redraw = 0

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        self.path_var = StringVar(value="No CSV selected")
        ttk.Label(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Open CSV…", command=self.open_csv).pack(side="left", padx=5)
        ttk.Label(top, text="Time window:").pack(side="left", padx=(12, 4))

        self.window_var = StringVar(value="1 minute")
        self.window_box = ttk.Combobox(
            top, textvariable=self.window_var, state="readonly", width=10,
            values=("1 minute", "5 minutes", "10 minutes", "All time")
        )
        self.window_box.pack(side="left")
        self.window_box.bind("<<ComboboxSelected>>", self.change_window)

        main = ttk.PanedWindow(root, orient="horizontal")
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main, padding=(8, 8))
        main.add(left, weight=0)
        ttk.Label(left, text="Sensors (Ctrl/Shift-select multiple)").pack(anchor="w")
        self.sensor_list = Listbox(left, selectmode=MULTIPLE, exportselection=False, width=70)
        self.sensor_list.pack(fill="both", expand=True, pady=(5, 5))
        self.sensor_list.bind("<<ListboxSelect>>", self.selection_changed)
        buttons = ttk.Frame(left)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Select all", command=self.select_all).pack(side="left")
        ttk.Button(buttons, text="Clear", command=self.clear_selection).pack(side="left", padx=4)

        right = ttk.Frame(main, padding=(5, 5))
        main.add(right, weight=1)
        self.figure = plt.Figure(figsize=(9, 6), dpi=100, constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, right, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(fill="x")

        self.status_var = StringVar(value="Open a metrics.csv file to begin.")
        ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(250, self.poll)

    def open_csv(self):
        chosen = filedialog.askopenfilename(
            title="Select hardware metrics CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if chosen:
            self.load_file(chosen)

    def load_file(self, path):
        self.close_file()
        self.path = path
        self.path_var.set(path)
        self.header = []
        self.sensor_columns = []
        self.data.clear()
        self.sensor_list.delete(0, END)
        self.dirty = True

        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                self.header = next(reader, [])
                if not self.header or self.header[0].strip().lower() != "timestamp":
                    raise ValueError("CSV must have Timestamp as its first column.")
                self.sensor_columns = self.header[1:]
                for name in self.sensor_columns:
                    self.sensor_list.insert(END, name)
                for row in reader:
                    self.add_row(row)

            # Reopen and seek to EOF. New rows are streamed from here onward.
            self.file = open(path, "r", encoding="utf-8-sig", newline="")
            self.file.seek(0, os.SEEK_END)
            self.file_pos = self.file.tell()
            self.status_var.set(f"Loaded {self.sample_count} samples. Watching for new rows…")
            self.redraw()
        except Exception as exc:
            self.close_file()
            messagebox.showerror("CSV error", str(exc))
            self.status_var.set("Failed to load CSV.")

    @property
    def sample_count(self):
        if not self.sensor_columns:
            return 0
        return len(self.data[self.sensor_columns[0]])

    def add_row(self, row):
        if not row or len(row) < len(self.header):
            return
        try:
            ts = parse_timestamp(row[0])
        except Exception:
            return
        for i, name in enumerate(self.sensor_columns, start=1):
            try:
                value = float(row[i]) if i < len(row) and row[i].strip() else None
            except (ValueError, TypeError):
                value = None
            self.data[name].append((ts, value))
        self.dirty = True

    def poll_file(self):
        if not self.path or not self.file:
            return
        try:
            size = os.path.getsize(self.path)
            if size < self.file_pos:
                # Logger truncated/replaced the file; load it again.
                self.load_file(self.path)
                return

            self.file.seek(self.file_pos)
            while True:
                start = self.file.tell()
                line = self.file.readline()
                if not line:
                    break
                if not line.endswith("\n"):
                    self.file.seek(start)  # leave partial write for next poll
                    break
                self.file_pos = self.file.tell()
                row = next(csv.reader([line]), [])
                self.add_row(row)

            if self.dirty:
                self.status_var.set(
                    f"Live • {self.sample_count} samples • Updated {datetime.now().strftime('%H:%M:%S')}"
                )
        except (OSError, ValueError):
            pass

    def change_window(self, _event=None):
        choice = self.window_var.get()
        self.window_seconds = None if choice == "All time" else {
            "1 minute": 60, "5 minutes": 300, "10 minutes": 600
        }[choice]
        self.dirty = True
        self.redraw()

    def selected_sensors(self):
        return [self.sensor_list.get(i) for i in self.sensor_list.curselection()]

    def selection_changed(self, _event=None):
        self.dirty = True
        self.redraw()

    def select_all(self):
        self.sensor_list.select_set(0, END)
        self.dirty = True
        self.redraw()

    def clear_selection(self):
        self.sensor_list.selection_clear(0, END)
        self.dirty = True
        self.redraw()

    def redraw(self):
        selected = self.selected_sensors()
        self.figure.clear()
        if not selected:
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, "Select one or more sensors from the list",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            self.canvas.draw_idle()
            self.dirty = False
            return

        axes = self.figure.subplots(len(selected), 1, sharex=True, squeeze=False).flatten()
        now = datetime.now().astimezone()
        all_time = self.window_seconds is None

        for ax, sensor in zip(axes, selected):
            samples = self.data.get(sensor, [])
            points = []
            for ts, value in samples:
                if value is None:
                    continue
                age = (now - ts.astimezone()).total_seconds()
                if age >= -2 and (all_time or age <= self.window_seconds):
                    points.append((-age, value))

            if points:
                x = [p[0] for p in points]
                y = [p[1] for p in points]
                ax.plot(x, y, linewidth=1.2)
                ax.set_xlim(min(x), 0) if all_time else ax.set_xlim(-self.window_seconds, 0)
            elif not all_time:
                ax.set_xlim(-self.window_seconds, 0)

            ax.set_ylabel(sensor, fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.tick_params(axis="both", labelsize=8)

        axes[-1].set_xlabel("Seconds relative to now (0 = now)")
        title = "All time" if all_time else f"Last {self.window_seconds // 60} minute(s)"
        self.figure.suptitle(f"{title} • Live", fontsize=11)
        self.canvas.draw_idle()
        self.dirty = False

    def poll(self):
        self.poll_file()
        now = time.monotonic()
        if self.dirty or now - self.last_redraw >= 1:
            self.redraw()
            self.last_redraw = now
        self.root.after(POLL_MS, self.poll)

    def close_file(self):
        if self.file:
            self.file.close()
            self.file = None

    def close(self):
        self.close_file()
        self.root.destroy()


def main():
    root = Tk()
    CsvLiveViewer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
