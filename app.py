"""
Plex Playlist Builder — macOS window app
Scans a Plex library and auto-creates playlists from folder structure
and technical metadata (duration, resolution).
"""

import json
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from collections import defaultdict
from pathlib import Path

from plexapi.server import PlexServer

from config import PLEX_URL, PLEX_TOKEN

# ---------------------------------------------------------------------------
# Settings (mirrors build_playlists.py)
# ---------------------------------------------------------------------------
PORN_ROOT = "/other/Porn"
CATEGORIES_FOLDER = "CATEGORIES"
PLAYLIST_PREFIX = "Auto: "
MIN_ITEMS = 2

DURATION_BUCKETS = {
    "Duration: Short (under 20 min)": (0,       20 * 60),
    "Duration: Medium (20–60 min)":   (20 * 60, 60 * 60),
    "Duration: Long (over 60 min)":   (60 * 60, float("inf")),
}
RESOLUTION_BUCKETS = {
    "Quality: SD (under 720p)":  (0,    720),
    "Quality: HD (720p–1079p)":  (720,  1080),
    "Quality: Full HD (1080p+)": (1080, 2160),
    "Quality: 4K (2160p+)":      (2160, float("inf")),
}

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def get_ffprobe_technical(file_path: str) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", file_path],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        info = {}
        try:
            info["duration"] = float(data["format"].get("duration", 0))
        except (KeyError, ValueError):
            info["duration"] = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["height"] = stream.get("height", 0)
                break
        return info
    except Exception:
        return {}


def parse_path_groups(file_path: str) -> dict:
    groups = {}
    try:
        rel = Path(file_path).relative_to(PORN_ROOT)
        parts = rel.parts
        if not parts:
            return groups
        if parts[0].upper() == CATEGORIES_FOLDER.upper():
            if len(parts) >= 2:
                groups["category"] = parts[1].title()
        else:
            groups["studio"] = parts[0]
    except ValueError:
        pass
    return groups


def bucket_label(value: float, buckets: dict):
    for label, (lo, hi) in buckets.items():
        if lo <= value < hi:
            return label
    return None


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Plex Playlist Builder — v1 (old desktop)")
        self.resizable(False, False)
        self.configure(bg="#1e1e2e")
        self._build_ui()
        # Version watermark so the builds can't be mistaken for each other.
        tk.Label(self, text="v1 · OLD DESKTOP", bg="#6B7280", fg="white",
                 font=("Helvetica", 12, "bold"), padx=10, pady=3).place(relx=1.0, rely=1.0, anchor="se")
        self.plex = None
        self._running = False
        self.after(100, self._connect_plex)

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        PAD = 16
        BG = "#1e1e2e"
        CARD = "#2a2a3e"
        ACC = "#bd93f9"
        FG = "#f8f8f2"
        MUTED = "#6272a4"
        FONT = ("SF Pro Display", 13)
        FONT_SM = ("SF Pro Display", 11)
        FONT_MONO = ("SF Mono", 11)

        self.configure(bg=BG)
        style = ttk.Style(self)
        style.theme_use("clam")

        # Header
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=PAD, pady=(PAD, 0))
        tk.Label(hdr, text="Plex Playlist Builder", font=("SF Pro Display", 18, "bold"),
                 bg=BG, fg=FG).pack(side="left")
        self.status_dot = tk.Label(hdr, text="●", font=("SF Pro Display", 14),
                                   bg=BG, fg="#ff5555")
        self.status_dot.pack(side="right", padx=(0, 4))
        self.status_label = tk.Label(hdr, text="Connecting…", font=FONT_SM,
                                     bg=BG, fg=MUTED)
        self.status_label.pack(side="right")

        # Library row
        lib_row = tk.Frame(self, bg=BG)
        lib_row.pack(fill="x", padx=PAD, pady=(PAD, 0))
        tk.Label(lib_row, text="Library", font=FONT, bg=BG, fg=FG,
                 width=8, anchor="w").pack(side="left")
        self.lib_var = tk.StringVar()
        self.lib_combo = ttk.Combobox(lib_row, textvariable=self.lib_var,
                                      state="disabled", font=FONT, width=30)
        style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                         foreground=FG, selectbackground=ACC)
        self.lib_combo.pack(side="left", padx=(8, 0))

        # Run button
        self.run_btn = tk.Button(
            self, text="Build Playlists", font=("SF Pro Display", 13, "bold"),
            bg=ACC, fg="#1e1e2e", activebackground="#caa9fa",
            relief="flat", cursor="hand2", padx=16, pady=8,
            state="disabled", command=self._start_run,
        )
        self.run_btn.pack(pady=(PAD, 0))

        # Progress bar
        style.configure("Accent.Horizontal.TProgressbar",
                         troughcolor=CARD, background=ACC, thickness=6)
        self.progress = ttk.Progressbar(self, style="Accent.Horizontal.TProgressbar",
                                         length=500, mode="determinate")
        self.progress.pack(padx=PAD, pady=(PAD, 0))

        self.progress_label = tk.Label(self, text="", font=FONT_SM, bg=BG, fg=MUTED)
        self.progress_label.pack()

        # Log area
        log_frame = tk.Frame(self, bg=CARD, bd=0)
        log_frame.pack(padx=PAD, pady=(8, PAD), fill="both", expand=True)
        self.log = tk.Text(log_frame, font=FONT_MONO, bg=CARD, fg=FG,
                           insertbackground=FG, relief="flat", wrap="word",
                           width=70, height=20, padx=8, pady=8,
                           state="disabled")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        # Tag colors
        self.log.tag_config("info",    foreground=FG)
        self.log.tag_config("success", foreground="#50fa7b")
        self.log.tag_config("muted",   foreground=MUTED)
        self.log.tag_config("error",   foreground="#ff5555")
        self.log.tag_config("accent",  foreground=ACC)

        self.geometry("560x560")

    # ── Logging ──────────────────────────────────────────────────────────

    def _log(self, msg: str, tag: str = "info"):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ── Plex connection ──────────────────────────────────────────────────

    def _connect_plex(self):
        def connect():
            try:
                plex = PlexServer(PLEX_URL, PLEX_TOKEN)
                self.plex = plex
                sections = [s.title for s in plex.library.sections()
                            if s.type in ("movie", "show")]
                self.after(0, self._on_connected, plex.friendlyName, sections)
            except Exception as e:
                self.after(0, self._on_connect_failed, str(e))
        threading.Thread(target=connect, daemon=True).start()

    def _on_connected(self, server_name: str, sections: list):
        self.status_dot.configure(fg="#50fa7b")
        self.status_label.configure(text=f"Connected · {server_name}")
        self.lib_combo.configure(values=sections, state="readonly")
        if sections:
            self.lib_var.set(sections[0])
        self.run_btn.configure(state="normal")
        self._log(f"Connected to {server_name}", "success")
        self._log(f"Libraries: {', '.join(sections)}", "muted")

    def _on_connect_failed(self, err: str):
        self.status_label.configure(text="Connection failed")
        self._log(f"Could not connect: {err}", "error")

    # ── Run ──────────────────────────────────────────────────────────────

    def _start_run(self):
        library = self.lib_var.get()
        if not library or not self.plex:
            return
        self._running = True
        self.run_btn.configure(state="disabled", text="Running…")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress["value"] = 0
        threading.Thread(target=self._run_worker, args=(library,), daemon=True).start()

    def _run_worker(self, library_name: str):
        try:
            section = self.plex.library.section(library_name)
            all_items = section.all()
            total = len(all_items)

            self.after(0, self._log, f"Scanning {total} items in '{library_name}' …", "accent")
            self.after(0, lambda: self.progress.configure(maximum=total))

            groups: dict[str, list] = defaultdict(list)

            for i, item in enumerate(all_items, 1):
                try:
                    file_path = item.media[0].parts[0].file
                except (IndexError, AttributeError):
                    continue

                path_groups = parse_path_groups(file_path)
                if "studio" in path_groups:
                    groups[f"Studio: {path_groups['studio']}"].append(item)
                if "category" in path_groups:
                    groups[f"Category: {path_groups['category']}"].append(item)

                tech = get_ffprobe_technical(file_path)
                if tech.get("duration"):
                    label = bucket_label(tech["duration"], DURATION_BUCKETS)
                    if label:
                        groups[label].append(item)
                if tech.get("height"):
                    label = bucket_label(tech["height"], RESOLUTION_BUCKETS)
                    if label:
                        groups[label].append(item)

                # Update progress every 10 items
                if i % 10 == 0 or i == total:
                    pct = int(i / total * 100)
                    self.after(0, self._set_progress, i, f"Scanning {i}/{total} ({pct}%)")

            self.after(0, self._log, f"\nBuilding playlists …", "accent")

            created = skipped = 0
            for name, items in sorted(groups.items()):
                if len(items) >= MIN_ITEMS:
                    self._upsert_playlist(name, items, library_name)
                    created += 1
                    self.after(0, self._log,
                               f"  ✓  Auto: {name}  ({len(items)} items)", "success")
                else:
                    skipped += 1

            self.after(0, self._on_done, created, skipped)

        except Exception as e:
            self.after(0, self._log, f"Error: {e}", "error")
            self.after(0, self._reset_btn)

    def _set_progress(self, value: int, label: str):
        self.progress["value"] = value
        self.progress_label.configure(text=label)

    def _upsert_playlist(self, name: str, items: list, library_name: str):
        full_name = f"{PLAYLIST_PREFIX}{name}"
        for pl in self.plex.playlists():
            if pl.title == full_name:
                pl.delete()
                break
        self.plex.createPlaylist(full_name,
                                 section=self.plex.library.section(library_name),
                                 items=items)

    def _on_done(self, created: int, skipped: int):
        self._log(
            f"\nDone — {created} playlists created/updated, "
            f"{skipped} groups skipped (< {MIN_ITEMS} items).",
            "accent",
        )
        self.progress_label.configure(text="Complete")
        self._reset_btn()

    def _reset_btn(self):
        self.run_btn.configure(state="normal", text="Build Playlists")
        self._running = False


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
