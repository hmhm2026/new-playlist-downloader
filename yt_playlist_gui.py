"""
YouTube Playlist Downloader (desktop GUI)

- Paste a playlist URL
- Pick quality: Best available / 4K / 1080p / 720p / 480p / 360p
- Choose where to save (Browse button)
- Creates a folder named after the playlist, and numbers files 001, 002, 003...

Requirements:
    pip install -U yt-dlp
    ffmpeg must be installed and available in PATH (needed to merge video + audio)
"""

import os
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yt_dlp
from yt_dlp.utils import sanitize_filename

# label shown in the dropdown -> max height (None = no limit)
QUALITIES = {
    "Best available": None,
    "4K (2160p)": 2160,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}


class StopDownload(Exception):
    pass


class QuietLogger:
    """Sends yt-dlp messages to the GUI log."""

    def __init__(self, q):
        self.q = q

    def debug(self, msg):
        if msg.startswith("[download] Destination") or msg.startswith("[Merger]"):
            self.q.put(("log", msg))

    def info(self, msg):
        pass

    def warning(self, msg):
        self.q.put(("log", "Warning: " + msg))

    def error(self, msg):
        self.q.put(("log", "Error: " + msg))


def build_format(max_height):
    """Pick the best video+audio up to max_height; if a video has less, take what it has."""
    if max_height is None:
        return "bv*+ba/b"
    return f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Playlist Downloader")
        self.geometry("720x520")
        self.minsize(640, 460)

        self.q = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker = None

        self.url_var = tk.StringVar()
        self.quality_var = tk.StringVar(value="Best available")
        self.folder_var = tk.StringVar()

        self._build_ui()
        self.after(100, self._poll_queue)

        if not shutil.which("ffmpeg"):
            self._log("WARNING: ffmpeg was not found in PATH. Merging video+audio will fail.")

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=8, pady=8)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Playlist URL:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.url_var).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frm, text="Quality:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(
            frm, textvariable=self.quality_var, values=list(QUALITIES.keys()), state="readonly", width=20
        ).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Save to:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.folder_var).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse...", command=self._browse).grid(row=2, column=2, **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=3, pady=8)
        self.start_btn = ttk.Button(btns, text="Download", command=self._start)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(btns, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frm, textvariable=self.status_var).grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        self.bar = ttk.Progressbar(frm, maximum=100)
        self.bar.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)

        self.log = tk.Text(frm, height=12, state="disabled", wrap="word")
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(6, weight=1)

    def _browse(self):
        folder = filedialog.askdirectory(title="Choose where to save the videos")
        if folder:
            self.folder_var.set(folder)

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- actions ----------
    def _start(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a playlist URL first.")
            return
        if not self.folder_var.get().strip():
            self._browse()
            if not self.folder_var.get().strip():
                return
        base = self.folder_var.get().strip()
        max_height = QUALITIES[self.quality_var.get()]

        self.stop_flag.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.bar["value"] = 0
        self._log(f"Starting... quality: {self.quality_var.get()}")

        self.worker = threading.Thread(target=self._run, args=(url, base, max_height), daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_flag.set()
        self.status_var.set("Stopping...")

    # ---------- worker thread ----------
    def _run(self, url, base, max_height):
        try:
            self.q.put(("status", "Reading playlist info..."))
            with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True, "skip_download": True}) as y:
                info = y.extract_info(url, download=False)

            title = sanitize_filename(info.get("title") or "Playlist")
            entries = info.get("entries")
            count = len(list(entries)) if entries is not None else 1
            width = max(3, len(str(count)))

            folder = os.path.join(base, title)
            os.makedirs(folder, exist_ok=True)
            self.q.put(("log", f"Playlist: {title}  ({count} videos)"))
            self.q.put(("log", f"Folder: {folder}"))

            def hook(d):
                if self.stop_flag.is_set():
                    raise StopDownload()
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    frac = (d.get("downloaded_bytes") or 0) / total if total else 0
                    idx = d["info_dict"].get("playlist_index") or 1
                    self.q.put(("progress", ((idx - 1) + frac) / count * 100))
                    self.q.put(("status", f"Video {idx}/{count} - {frac * 100:.0f}%  {d.get('_speed_str', '').strip()}"))
                elif d["status"] == "finished":
                    idx = d["info_dict"].get("playlist_index") or 1
                    self.q.put(("progress", idx / count * 100))

            opts = {
                "format": build_format(max_height),
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(folder, f"%(playlist_index)0{width}d - %(title)s.%(ext)s"),
                "ignoreerrors": True,
                "retries": 10,
                "concurrent_fragment_downloads": 4,
                "noplaylist": False,
                "restrictfilenames": False,
                "windowsfilenames": True,
                "progress_hooks": [hook],
                "logger": QuietLogger(self.q),
            }
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([url])

            self.q.put(("done", "Finished!"))
        except StopDownload:
            self.q.put(("done", "Stopped."))
        except yt_dlp.utils.DownloadError as e:
            if self.stop_flag.is_set():
                self.q.put(("done", "Stopped."))
            else:
                self.q.put(("done", f"Error: {e}"))
        except Exception as e:  # noqa: BLE001
            self.q.put(("done", f"Error: {e}"))

    # ---------- queue -> UI ----------
    def _poll_queue(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self._log(val)
                elif kind == "status":
                    self.status_var.set(val)
                elif kind == "progress":
                    self.bar["value"] = val
                elif kind == "done":
                    self.status_var.set(val)
                    self._log(val)
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


if __name__ == "__main__":
    App().mainloop()
