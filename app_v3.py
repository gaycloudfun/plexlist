"""
Structly — Plex Playlist Builder
"""

import os
import sys
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import filedialog, messagebox

if getattr(sys, "frozen", False):
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import json
import threading
import customtkinter as ctk
from collections import defaultdict
from pathlib import Path
from PIL import Image

from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from config import PLEX_TOKEN

# ── Settings persistence ──────────────────────────────────────────────────────
SETTINGS_PATH = Path.home() / ".structly_settings.json"

def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text())
            return {"token": data.get("token", PLEX_TOKEN)}
        except Exception:
            pass
    return {"token": PLEX_TOKEN}

def save_settings(token: str):
    SETTINGS_PATH.write_text(json.dumps({"token": token}, indent=2))

# ── Theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ORANGE     = "#F06428"
ORANGE_HOV = "#FF7A3D"
BG         = "#141414"
CARD       = "#1E1E1E"
CARD2      = "#252525"
FG         = "#F8F8F2"
MUTED      = "#A0A0B0"
GREEN      = "#4CAF50"
RED        = "#EF5350"

MIN_ITEMS         = 2
RECENT_DAYS       = 30
PORN_ROOT         = "/other/Porn"
CATEGORIES_FOLDER = "CATEGORIES"

RESOLUTION_MAP = {
    "4k": "4K", "2160": "4K",
    "1080": "1080p",
    "720": "720p",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_path_groups(file_path: str) -> dict:
    groups = {}
    try:
        rel   = Path(file_path).relative_to(PORN_ROOT)
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


def resolution_label(item) -> str | None:
    try:
        res = str(item.media[0].videoResolution).lower()
        return RESOLUTION_MAP.get(res, "SD")
    except (IndexError, AttributeError):
        return None


def load_logo(height: int = 45) -> ctk.CTkImage | None:
    logo_path = Path(__file__).parent / "structly_logo.png"
    if not logo_path.exists():
        return None
    img = Image.open(logo_path).convert("RGBA")
    new_data = []
    for r, g, b, a in img.getdata():
        if a < 50:
            new_data.append((0, 0, 0, 0))
        elif (0.299 * r + 0.587 * g + 0.114 * b) > 200:
            new_data.append((0, 0, 0, 0))
        elif r > 150 and g < 120:
            new_data.append((r, g, b, a))
        else:
            new_data.append((248, 248, 242, a))
    img.putdata(new_data)
    aspect = img.width / img.height
    new_w = int(height * aspect)
    img = img.resize((new_w, height), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(new_w, height))


def load_prefix_image(path: str, size: int = 28) -> ctk.CTkImage | None:
    try:
        img = Image.open(path).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:
        return None


# ── App ───────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Structly v3 (old desktop) — Playlist Builder")
        self.update_idletasks()
        win_h = min(980, self.winfo_screenheight() - 80)
        self.geometry(f"620x{win_h}")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.plex              = None
        self._running          = False
        self._rules            = []
        self._rule_seq         = 0
        self._prefix_img_path  = None
        self._prefix_ctk_img   = None
        self._build_ui()
        # Version watermark so the builds can't be mistaken for each other.
        tk.Label(self, text="v3 · OLD DESKTOP", bg="#2563EB", fg="white",
                 font=("Helvetica", 12, "bold"), padx=10, pady=3).place(relx=1.0, rely=1.0, anchor="se")
        self.after(200, self._connect_plex)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):

        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(28, 0))

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left")
        logo_img = load_logo(height=45)
        if logo_img:
            ctk.CTkLabel(title_col, image=logo_img, text="").pack(anchor="w")
        else:
            ctk.CTkLabel(title_col, text="structly",
                         font=ctk.CTkFont("Inter", 26, "bold"),
                         text_color=FG).pack(anchor="w")
        ctk.CTkLabel(title_col, text="Playlist Builder for Plex",
                     font=ctk.CTkFont("Inter", 13), text_color=MUTED).pack(anchor="w")

        ctk.CTkButton(
            header, text="⚙", width=36, height=36,
            font=ctk.CTkFont(size=18),
            fg_color="transparent", hover_color=CARD2, text_color=MUTED,
            corner_radius=8, command=self._open_settings,
        ).pack(side="right", padx=(0, 8), pady=4)

        self.badge = ctk.CTkFrame(header, fg_color=CARD2, corner_radius=20)
        self.badge.pack(side="right", pady=4)
        self.badge_dot = ctk.CTkLabel(self.badge, text="●",
                                       font=ctk.CTkFont(size=10),
                                       text_color=MUTED, width=14)
        self.badge_dot.pack(side="left", padx=(10, 0), pady=6)
        self.badge_text = ctk.CTkLabel(self.badge, text="Connecting…",
                                        font=ctk.CTkFont("Inter", 12),
                                        text_color=MUTED)
        self.badge_text.pack(side="left", padx=(4, 12), pady=6)

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=CARD2).pack(
            fill="x", padx=28, pady=(20, 0))

        # ── Library ───────────────────────────────────────────────────────────
        lib_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        lib_card.pack(fill="x", padx=28, pady=(18, 0))
        ctk.CTkLabel(lib_card, text="LIBRARY",
                     font=ctk.CTkFont("Inter", 22, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=18, pady=(14, 4))
        self.lib_var = ctk.StringVar()
        self.lib_combo = ctk.CTkOptionMenu(
            lib_card, variable=self.lib_var, values=["Connecting…"],
            fg_color=CARD2, button_color=CARD2, button_hover_color="#333333",
            text_color=FG, dropdown_fg_color=CARD2,
            dropdown_hover_color="#333333", dropdown_text_color=FG,
            font=ctk.CTkFont("Inter", 18), corner_radius=10,
            state="disabled", width=564, height=40,
        )
        self.lib_combo.pack(padx=18, pady=(0, 14))

        # ── Prefix card ───────────────────────────────────────────────────────
        prefix_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        prefix_card.pack(fill="x", padx=28, pady=(14, 0))

        prefix_row = ctk.CTkFrame(prefix_card, fg_color="transparent")
        prefix_row.pack(fill="x", padx=18, pady=14)

        ctk.CTkLabel(prefix_row, text="PREFIX",
                     font=ctk.CTkFont("Inter", 22, "bold"),
                     text_color=MUTED).pack(side="left")

        self.prefix_var = ctk.StringVar(value="t ")
        self.prefix_var.trace_add("write", self._clamp_prefix)
        prefix_entry = ctk.CTkEntry(
            prefix_row, textvariable=self.prefix_var,
            font=ctk.CTkFont("Inter", 18, "bold"),
            fg_color=CARD2, border_color=CARD2,
            text_color=ORANGE, justify="center",
            width=72, height=36, corner_radius=8,
        )
        prefix_entry.pack(side="left", padx=(14, 0))

        ctk.CTkLabel(prefix_row, text="max 3 chars",
                     font=ctk.CTkFont("Inter", 12),
                     text_color=MUTED).pack(side="left", padx=(8, 0))

        self.prefix_img_preview = ctk.CTkLabel(prefix_row, text="", width=0)
        self.prefix_img_preview.pack(side="left", padx=(14, 0))

        ctk.CTkButton(
            prefix_row, text="Use Image",
            font=ctk.CTkFont("Inter", 13),
            fg_color=CARD2, hover_color="#333333", text_color=MUTED,
            corner_radius=8, height=36, width=100,
            command=self._pick_prefix_image,
        ).pack(side="right")

        ctk.CTkLabel(
            prefix_card,
            text="Image is cosmetic (app only, not stored in Plex).  "
                 "Square PNG with transparent background recommended.  "
                 "Max useful size: 256×256px — DPI does not matter for screen display, only pixel dimensions count.",
            font=ctk.CTkFont("Inter", 11),
            text_color=MUTED,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 12))

        # ── Mode switcher ─────────────────────────────────────────────────────
        self.mode_var = ctk.StringVar(value="Quick")
        ctk.CTkSegmentedButton(
            self, values=["Quick", "Custom"],
            variable=self.mode_var, command=self._on_mode_change,
            font=ctk.CTkFont("Inter", 15, "bold"),
            selected_color=ORANGE, selected_hover_color=ORANGE_HOV,
            unselected_color=CARD2, unselected_hover_color="#333333",
            text_color_disabled=MUTED, fg_color=CARD2,
        ).pack(fill="x", padx=28, pady=(14, 0))

        # ── Mode panel container ──────────────────────────────────────────────
        self._mode_container = ctk.CTkFrame(self, fg_color="transparent")
        self._mode_container.pack(fill="x")
        self._build_quick_panel()
        self._build_custom_panel()
        self.quick_frame.pack(fill="x", padx=28, pady=(14, 0))

        # ── Stats ─────────────────────────────────────────────────────────────
        stats_row = ctk.CTkFrame(self, fg_color="transparent")
        stats_row.pack(fill="x", padx=28, pady=(14, 0))
        self.stat_scanned   = self._stat_tile(stats_row, "Scanned", "—")
        self.stat_playlists = self._stat_tile(stats_row, "Playlists", "—")
        self.stat_skipped   = self._stat_tile(stats_row, "Skipped", "—")

        # ── Progress ──────────────────────────────────────────────────────────
        prog_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        prog_card.pack(fill="x", padx=28, pady=(14, 0))
        inner = ctk.CTkFrame(prog_card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)
        self.progress_label = ctk.CTkLabel(inner, text="Ready",
                                            font=ctk.CTkFont("Inter", 18),
                                            text_color=MUTED, anchor="w")
        self.progress_label.pack(fill="x")
        self.progress = ctk.CTkProgressBar(inner, height=6, corner_radius=3,
                                            fg_color=CARD2, progress_color=ORANGE)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(8, 0))

        # ── Buttons (packed bottom-up) ────────────────────────────────────────
        self.destroy_btn = ctk.CTkButton(
            self, text="Destroy All Matching Playlists",
            font=ctk.CTkFont("Inter", 13),
            fg_color="transparent", hover_color="#3A1010",
            text_color=RED, border_color="#5A2020", border_width=1,
            corner_radius=14, height=40, state="disabled",
            command=self._confirm_destroy,
        )
        self.destroy_btn.pack(fill="x", padx=28, pady=(0, 8), side="bottom")

        self.run_btn = ctk.CTkButton(
            self, text="Build Playlists",
            font=ctk.CTkFont("Inter", 15, "bold"),
            fg_color=ORANGE, hover_color=ORANGE_HOV, text_color="#000000",
            corner_radius=14, height=52, state="disabled",
            command=self._start_run,
        )
        self.run_btn.pack(fill="x", padx=28, pady=(14, 8), side="bottom")

        # ── Log ───────────────────────────────────────────────────────────────
        log_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        log_card.pack(fill="both", expand=True, padx=28, pady=(14, 0))
        ctk.CTkLabel(log_card, text="LOG",
                     font=ctk.CTkFont("Inter", 22, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=18, pady=(14, 0))
        self.log = ctk.CTkTextbox(
            log_card, font=ctk.CTkFont("Courier New", 11),
            fg_color="transparent", text_color=FG, wrap="word", state="disabled",
        )
        self.log.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.log._textbox.tag_configure("orange", foreground=ORANGE)
        self.log._textbox.tag_configure("red", foreground=RED)

    def _build_quick_panel(self):
        self.quick_frame = ctk.CTkFrame(self._mode_container,
                                         fg_color=CARD, corner_radius=14)
        ctk.CTkLabel(self.quick_frame, text="PLAYLIST TYPES",
                     font=ctk.CTkFont("Inter", 22, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=18, pady=(14, 8))

        toggle_grid = ctk.CTkFrame(self.quick_frame, fg_color="transparent")
        toggle_grid.pack(fill="x", padx=18, pady=(0, 4))

        row1 = ctk.CTkFrame(toggle_grid, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 6))
        row2 = ctk.CTkFrame(toggle_grid, fg_color="transparent")
        row2.pack(fill="x")

        row3 = ctk.CTkFrame(toggle_grid, fg_color="transparent")
        row3.pack(fill="x", pady=(6, 0))

        TYPES = [
            ("studio",     "Studio",        row1),
            ("genre",      "Genre",          row1),
            ("director",   "Director",       row1),
            ("actor",      "Actor",          row2),
            ("resolution", "Resolution",     row2),
            ("recent",     "Recently Added", row2),
            ("duration",   "Duration",       row3),
            ("folder",     "Folder",         row3),
        ]

        self.type_switches = {}
        for key, label, row in TYPES:
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.pack(side="left", expand=True, fill="x")
            sw = ctk.CTkSwitch(
                cell, text=label,
                font=ctk.CTkFont("Inter", 15), text_color=FG,
                progress_color=ORANGE, button_color=FG, button_hover_color=MUTED,
                command=self._on_actor_toggle if key == "actor" else None,
            )
            sw.select()  # default on
            sw.pack(anchor="w", padx=8)
            self.type_switches[key] = sw

        self.actor_entry_frame = ctk.CTkFrame(self.quick_frame, fg_color="transparent")
        self.actor_entry_frame.pack(fill="x", padx=18, pady=(8, 14))
        ctk.CTkLabel(self.actor_entry_frame, text="Actor name",
                     font=ctk.CTkFont("Inter", 14), text_color=MUTED).pack(anchor="w")
        self.actor_entry = ctk.CTkEntry(
            self.actor_entry_frame,
            placeholder_text="e.g. Tom Hardy  (leave blank for all)",
            font=ctk.CTkFont("Inter", 15), fg_color=CARD2, border_color=CARD2,
            text_color=FG, placeholder_text_color=MUTED, height=38, corner_radius=10,
        )
        self.actor_entry.pack(fill="x", pady=(4, 0))

    def _build_custom_panel(self):
        self.custom_frame = ctk.CTkFrame(self._mode_container,
                                          fg_color=CARD, corner_radius=14)
        ctk.CTkLabel(self.custom_frame, text="CUSTOM RULES",
                     font=ctk.CTkFont("Inter", 22, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=18, pady=(14, 8))

        self.rules_scroll = ctk.CTkScrollableFrame(
            self.custom_frame, fg_color="transparent", height=230,
        )
        self.rules_scroll.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkButton(
            self.custom_frame, text="+ Add Rule",
            font=ctk.CTkFont("Inter", 14, "bold"),
            fg_color=CARD2, hover_color="#333333", text_color=ORANGE,
            corner_radius=10, height=36, command=self._add_rule,
        ).pack(fill="x", padx=18, pady=(0, 14))

    def _stat_tile(self, parent, label: str, value: str):
        tile = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        tile.pack(side="left", expand=True, fill="x", padx=(0, 8))
        val_lbl = ctk.CTkLabel(tile, text=value,
                                font=ctk.CTkFont("Inter", 22, "bold"),
                                text_color=FG)
        val_lbl.pack(pady=(12, 2))
        ctk.CTkLabel(tile, text=label,
                     font=ctk.CTkFont("Inter", 18), text_color=MUTED).pack(pady=(0, 12))
        return val_lbl

    # ── Prefix config ─────────────────────────────────────────────────────────

    def _clamp_prefix(self, *_):
        v = self.prefix_var.get()
        if len(v) > 3:
            self.prefix_var.set(v[:3])

    def _pick_prefix_image(self):
        path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.ico")],
            title="Choose prefix image",
        )
        if not path:
            return
        img = load_prefix_image(path, size=28)
        if img:
            self._prefix_img_path = path
            self._prefix_ctk_img  = img
            self.prefix_img_preview.configure(image=img, text="", width=28)

    # ── Mode switching ────────────────────────────────────────────────────────

    def _on_mode_change(self, mode: str):
        if mode == "Quick":
            self.custom_frame.pack_forget()
            self.quick_frame.pack(fill="x", padx=28, pady=(14, 0))
        else:
            self.quick_frame.pack_forget()
            self.custom_frame.pack(fill="x", padx=28, pady=(14, 0))

    def _on_actor_toggle(self):
        if self.type_switches["actor"].get():
            self.actor_entry_frame.pack(fill="x", padx=18, pady=(8, 14))
        else:
            self.actor_entry_frame.pack_forget()

    # ── Custom rules ──────────────────────────────────────────────────────────

    def _add_rule(self):
        rule_id = self._rule_seq
        self._rule_seq += 1

        card = ctk.CTkFrame(self.rules_scroll, fg_color=CARD2, corner_radius=10)
        card.pack(fill="x", pady=(0, 8), padx=2)

        # Row 1: name + remove
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))
        name_entry = ctk.CTkEntry(
            top, placeholder_text="Playlist name  (auto-generated if blank)",
            font=ctk.CTkFont("Inter", 14), fg_color=CARD, border_color=CARD,
            text_color=FG, placeholder_text_color=MUTED, height=32, corner_radius=8,
        )
        name_entry.pack(side="left", fill="x", expand=True)
        remove_btn = ctk.CTkButton(
            top, text="×", width=32, height=32,
            font=ctk.CTkFont("Inter", 18, "bold"),
            fg_color="transparent", hover_color=RED,
            text_color=MUTED, corner_radius=8,
        )
        remove_btn.pack(side="right", padx=(8, 0))

        # Row 2: filter fields
        filters = ctk.CTkFrame(card, fg_color="transparent")
        filters.pack(fill="x", padx=10, pady=(0, 6))
        field_entries = {}
        for placeholder in ("Studio", "Genre", "Director", "Actor"):
            e = ctk.CTkEntry(
                filters, placeholder_text=placeholder,
                font=ctk.CTkFont("Inter", 13), fg_color=CARD, border_color=CARD,
                text_color=FG, placeholder_text_color=MUTED,
                height=30, corner_radius=8,
            )
            e.pack(side="left", fill="x", expand=True, padx=(0, 6))
            field_entries[placeholder.lower()] = e

        # Return on Actor field adds a new rule
        field_entries["actor"].bind("<Return>", lambda e: self._add_rule())

        # Row 3: duration
        dur_row = ctk.CTkFrame(card, fg_color="transparent")
        dur_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(dur_row, text="Duration",
                     font=ctk.CTkFont("Inter", 13), text_color=MUTED).pack(side="left")
        dur_var = ctk.StringVar(value="Any")
        ctk.CTkOptionMenu(
            dur_row, variable=dur_var,
            values=["Any", "< 2 min", "2–5 min", "5–10 min", "> 1 hour"],
            font=ctk.CTkFont("Inter", 13),
            fg_color=CARD, button_color=CARD, button_hover_color="#333333",
            text_color=FG, dropdown_fg_color=CARD2,
            dropdown_hover_color="#333333", dropdown_text_color=FG,
            corner_radius=8, height=28, width=140,
        ).pack(side="left", padx=(10, 0))
        field_entries["duration"] = dur_var

        rule = {"id": rule_id, "frame": card, "name": name_entry, **field_entries}
        self._rules.append(rule)
        remove_btn.configure(command=lambda r=rule: self._remove_rule(r))

        # Focus the name field of the new rule
        name_entry.focus()

    def _remove_rule(self, rule: dict):
        rule["frame"].destroy()
        self._rules = [r for r in self._rules if r["id"] != rule["id"]]

    def _get_rules_data(self) -> list:
        result = []
        for rule in self._rules:
            dur = rule["duration"].get() if isinstance(rule["duration"], ctk.StringVar) else "Any"
            data = {
                "id":          rule["id"],
                "custom_name": rule["name"].get().strip(),
                "studio":      rule["studio"].get().strip(),
                "genre":       rule["genre"].get().strip(),
                "director":    rule["director"].get().strip(),
                "actor":       rule["actor"].get().strip(),
                "duration":    dur,
            }
            if any(v for k, v in data.items() if k not in ("id", "custom_name", "duration"))  \
                    or data["duration"] != "Any":
                result.append(data)
        return result

    # ── Playlist destroyer ────────────────────────────────────────────────────

    def _confirm_destroy(self):
        prefix = self.prefix_var.get()
        confirmed = messagebox.askyesno(
            "Destroy Playlists",
            f"This will permanently delete ALL Plex playlists that start with '{prefix}'.\n\n"
            f"⚠️  If you're changing your prefix, destroy FIRST — then update the prefix and rebuild. "
            f"Destroying after a prefix change won't find the old playlists.\n\n"
            f"This cannot be undone. Continue?",
        )
        if confirmed:
            self.destroy_btn.configure(state="disabled")
            threading.Thread(target=self._destroy_playlists, daemon=True).start()

    def _destroy_playlists(self):
        prefix = self.prefix_var.get()
        try:
            targets = [pl for pl in self.plex.playlists()
                       if pl.title.startswith(prefix)]
            count = len(targets)
            self.after(0, self._log,
                       f"Destroying {count} playlist(s) with prefix '{prefix}' …")
            for pl in targets:
                title = pl.title
                pl.delete()
                self.after(0, self._log_deleted, title)
            self.after(0, self._log, f"\nDone — {count} playlist(s) destroyed.")
        except Exception as e:
            self.after(0, self._log, f"Error: {e}")
        finally:
            self.after(0, self.destroy_btn.configure, {"state": "normal"})

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_playlist(self, name: str, count: int):
        prefix = self.prefix_var.get().strip()
        self.log.configure(state="normal")
        self.log._textbox.insert("end", "  ✓  ")
        self.log._textbox.insert("end", prefix, "orange")
        self.log._textbox.insert("end", f" {name}  ({count} items)\n")
        self.log._textbox.see("end")
        self.log.configure(state="disabled")

    def _log_deleted(self, title: str):
        self.log.configure(state="normal")
        self.log._textbox.insert("end", "  ✗  ")
        self.log._textbox.insert("end", title + "\n", "red")
        self.log._textbox.see("end")
        self.log.configure(state="disabled")

    # ── Settings dialog ───────────────────────────────────────────────────────

    def _open_settings(self):
        cfg = load_settings()

        dlg = ctk.CTkToplevel(self)
        dlg.title("Plex Settings")
        dlg.geometry("440x200")
        dlg.resizable(False, False)
        dlg.configure(fg_color=BG)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Plex Token",
                     font=ctk.CTkFont("Inter", 13), text_color=MUTED).pack(
            anchor="w", padx=24, pady=(24, 4))
        ctk.CTkLabel(dlg,
                     text="Connects to your server via Plex cloud — works from anywhere.",
                     font=ctk.CTkFont("Inter", 11), text_color=MUTED).pack(
            anchor="w", padx=24, pady=(0, 6))
        token_entry = ctk.CTkEntry(
            dlg, font=ctk.CTkFont("Inter", 14),
            fg_color=CARD2, border_color=CARD2, text_color=FG,
            height=38, corner_radius=10, show="•",
        )
        token_entry.insert(0, cfg["token"])
        token_entry.pack(fill="x", padx=24)

        def _save():
            token = token_entry.get().strip()
            if not token:
                return
            save_settings(token)
            dlg.destroy()
            self.badge_dot.configure(text_color=MUTED)
            self.badge_text.configure(text="Connecting…", text_color=MUTED)
            self.run_btn.configure(state="disabled")
            self.destroy_btn.configure(state="disabled")
            self.lib_combo.configure(values=["Connecting…"], state="disabled")
            self.lib_var.set("Connecting…")
            self.after(100, self._connect_plex)

        ctk.CTkButton(
            dlg, text="Save & Reconnect",
            font=ctk.CTkFont("Inter", 14, "bold"),
            fg_color=ORANGE, hover_color=ORANGE_HOV, text_color="#000000",
            corner_radius=10, height=42, command=_save,
        ).pack(fill="x", padx=24, pady=(16, 0))

    # ── Plex connection ───────────────────────────────────────────────────────

    def _connect_plex(self):
        def connect():
            try:
                cfg     = load_settings()
                account = MyPlexAccount(token=cfg["token"])
                servers = [r for r in account.resources()
                           if r.product == "Plex Media Server"]
                if not servers:
                    raise Exception("No Plex Media Server found on this account.")
                plex = servers[0].connect()
                self.plex = plex
                sections = [s.title for s in plex.library.sections()
                            if s.type in ("movie", "show")]
                self.after(0, self._on_connected, plex.friendlyName, sections)
            except Exception as e:
                self.after(0, self._on_connect_failed, str(e))
        threading.Thread(target=connect, daemon=True).start()

    def _on_connected(self, server_name: str, sections: list):
        self.badge_dot.configure(text_color=GREEN)
        self.badge_text.configure(text=f"Connected · {server_name}", text_color=FG)
        self.lib_combo.configure(values=sections, state="normal")
        if sections:
            self.lib_var.set(sections[0])
        self.run_btn.configure(state="normal")
        self.destroy_btn.configure(state="normal")
        self._log(f"Connected to {server_name}")
        self._log(f"Libraries available: {', '.join(sections)}")

    def _on_connect_failed(self, err: str):
        self.badge_dot.configure(text_color=RED)
        self.badge_text.configure(text="Connection failed", text_color=RED)
        self._log(f"Error: {err}")

    # ── Run ───────────────────────────────────────────────────────────────────

    def _start_run(self):
        library = self.lib_var.get()
        if not library or not self.plex:
            return

        mode = self.mode_var.get()

        if mode == "Quick":
            selected = {k for k, sw in self.type_switches.items() if sw.get()}
            if not selected:
                self._log("No playlist types selected — toggle at least one on.")
                return
            actor_filter = self.actor_entry.get().strip().lower()
        else:
            rules = self._get_rules_data()
            if not rules:
                self._log("No rules defined — add at least one rule before building.")
                return

        self._running = True
        self.run_btn.configure(state="disabled", text="Building…")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.set(0)
        self.stat_scanned.configure(text="—")
        self.stat_playlists.configure(text="—")
        self.stat_skipped.configure(text="—")

        if mode == "Quick":
            threading.Thread(
                target=self._run_worker_quick,
                args=(library, selected, actor_filter),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._run_worker_custom,
                args=(library, rules),
                daemon=True,
            ).start()

    def _run_worker_quick(self, library_name: str, selected: set, actor_filter: str):
        try:
            section   = self.plex.library.section(library_name)
            all_items = section.all()
            total     = len(all_items)
            cutoff    = datetime.now() - timedelta(days=RECENT_DAYS)

            self.after(0, self._log, f"Scanning {total} items in '{library_name}' …")
            self.after(0, self.progress_label.configure,
                       {"text": f"Scanning 0 of {total}"})

            groups: dict[str, list] = defaultdict(list)

            for i, item in enumerate(all_items, 1):
                if "studio" in selected:
                    studio = getattr(item, "studio", None)
                    if studio:
                        groups[f"Studio: {studio}"].append(item)

                if "genre" in selected:
                    for g in getattr(item, "genres", []):
                        groups[f"Genre: {g.tag}"].append(item)

                if "director" in selected:
                    for d in getattr(item, "directors", []):
                        groups[f"Director: {d.tag}"].append(item)

                if "actor" in selected:
                    for role in getattr(item, "roles", []):
                        if not actor_filter or actor_filter in role.tag.lower():
                            groups[f"Actor: {role.tag}"].append(item)

                if "resolution" in selected:
                    label = resolution_label(item)
                    if label:
                        groups[f"Resolution: {label}"].append(item)

                if "recent" in selected:
                    added = getattr(item, "addedAt", None)
                    if added and added >= cutoff:
                        groups[f"Recently Added (Last {RECENT_DAYS} Days)"].append(item)

                if "folder" in selected:
                    try:
                        file_path   = item.media[0].parts[0].file
                        path_groups = parse_path_groups(file_path)
                        if "studio" in path_groups:
                            groups[f"FLDR STU: {path_groups['studio']}"].append(item)
                        if "category" in path_groups:
                            groups[f"FLDR Cat: {path_groups['category']}"].append(item)
                    except (IndexError, AttributeError):
                        pass

                if "duration" in selected:
                    ms = getattr(item, "duration", None)
                    if ms:
                        if ms < 2 * 60 * 1000:
                            groups["Duration: Under 2 Min"].append(item)
                        elif ms < 5 * 60 * 1000:
                            groups["Duration: 2–5 Min"].append(item)
                        elif ms < 10 * 60 * 1000:
                            groups["Duration: 5–10 Min"].append(item)
                        elif ms > 60 * 60 * 1000:
                            groups["Duration: Over 1 Hour"].append(item)

                if i % 10 == 0 or i == total:
                    pct = i / total
                    self.after(0, self.progress.set, pct)
                    self.after(0, self.progress_label.configure,
                               {"text": f"Scanning {i} of {total}"})
                    self.after(0, self.stat_scanned.configure, {"text": str(i)})

            self._finish_groups(groups, library_name, total)

        except Exception as e:
            self.after(0, self._log, f"Error: {e}")
            self.after(0, self._reset_btn)

    def _run_worker_custom(self, library_name: str, rules: list):
        try:
            section   = self.plex.library.section(library_name)
            all_items = section.all()
            total     = len(all_items)

            self.after(0, self._log,
                       f"Scanning {total} items against {len(rules)} rule(s) …")
            self.after(0, self.progress_label.configure,
                       {"text": f"Scanning 0 of {total}"})

            buckets: dict[int, list] = defaultdict(list)

            for i, item in enumerate(all_items, 1):
                for rule in rules:
                    if self._item_matches_rule(item, rule):
                        buckets[rule["id"]].append(item)

                if i % 10 == 0 or i == total:
                    pct = i / total
                    self.after(0, self.progress.set, pct)
                    self.after(0, self.progress_label.configure,
                               {"text": f"Scanning {i} of {total}"})
                    self.after(0, self.stat_scanned.configure, {"text": str(i)})

            self.after(0, self._log, "Building playlists …")
            created  = 0
            misc     = []
            seen_ids = set()

            for rule in rules:
                items = buckets[rule["id"]]
                name  = rule["custom_name"] or self._auto_name(rule)
                if len(items) >= MIN_ITEMS:
                    self._upsert_playlist(name, items, library_name)
                    created += 1
                    self.after(0, self._log_playlist, name, len(items))
                    self.after(0, self.stat_playlists.configure, {"text": str(created)})
                else:
                    for item in items:
                        if item.ratingKey not in seen_ids:
                            misc.append(item)
                            seen_ids.add(item.ratingKey)

            if misc:
                self._upsert_playlist("Misc", misc, library_name)
                created += 1
                self.after(0, self._log_playlist, "Misc", len(misc))
                self.after(0, self.stat_playlists.configure, {"text": str(created)})

            self.after(0, self.stat_skipped.configure, {"text": "0"})
            self.after(0, self._on_done, created, 0, total)

        except Exception as e:
            self.after(0, self._log, f"Error: {e}")
            self.after(0, self._reset_btn)

    def _item_matches_rule(self, item, rule: dict) -> bool:
        if rule.get("studio"):
            studio = (getattr(item, "studio", "") or "").lower()
            if rule["studio"].lower() not in studio:
                return False
        if rule.get("genre"):
            genres = [g.tag.lower() for g in getattr(item, "genres", [])]
            if not any(rule["genre"].lower() in g for g in genres):
                return False
        if rule.get("director"):
            dirs = [d.tag.lower() for d in getattr(item, "directors", [])]
            if not any(rule["director"].lower() in d for d in dirs):
                return False
        if rule.get("actor"):
            actors = [r.tag.lower() for r in getattr(item, "roles", [])]
            if not any(rule["actor"].lower() in a for a in actors):
                return False
        dur_filter = rule.get("duration", "Any")
        if dur_filter != "Any":
            ms = getattr(item, "duration", None) or 0
            if dur_filter == "< 2 min"  and not (ms < 2 * 60 * 1000):
                return False
            if dur_filter == "2–5 min"  and not (2 * 60 * 1000 <= ms < 5 * 60 * 1000):
                return False
            if dur_filter == "5–10 min" and not (5 * 60 * 1000 <= ms < 10 * 60 * 1000):
                return False
            if dur_filter == "> 1 hour"  and not (ms > 60 * 60 * 1000):
                return False
        return True

    def _auto_name(self, rule: dict) -> str:
        parts = [rule[k].title() for k in ("studio", "genre", "director", "actor")
                 if rule.get(k)]
        return " · ".join(parts) or "Custom"

    def _finish_groups(self, groups: dict, library_name: str, total: int):
        self.after(0, self._log,
                   f"Building playlists from {len(groups)} groups …")
        created  = 0
        misc     = []
        seen_ids = set()

        for name, items in sorted(groups.items()):
            if len(items) >= MIN_ITEMS:
                self._upsert_playlist(name, items, library_name)
                created += 1
                self.after(0, self._log_playlist, name, len(items))
                self.after(0, self.stat_playlists.configure, {"text": str(created)})
            else:
                for item in items:
                    if item.ratingKey not in seen_ids:
                        misc.append(item)
                        seen_ids.add(item.ratingKey)

        if misc:
            self._upsert_playlist("Misc", misc, library_name)
            created += 1
            self.after(0, self._log_playlist, "Misc", len(misc))
            self.after(0, self.stat_playlists.configure, {"text": str(created)})

        self.after(0, self.stat_skipped.configure, {"text": "0"})
        self.after(0, self._on_done, created, 0, total)

    def _upsert_playlist(self, name: str, items: list, library_name: str):
        full_name = f"{self.prefix_var.get()}{name}"
        for pl in self.plex.playlists():
            if pl.title == full_name:
                pl.delete()
                break
        self.plex.createPlaylist(
            full_name,
            section=self.plex.library.section(library_name),
            items=items,
        )

    def _on_done(self, created: int, skipped: int, total: int):
        self.progress.set(1)
        self.progress_label.configure(text="Complete")
        self.stat_scanned.configure(text=str(total))
        self.stat_playlists.configure(text=str(created))
        self.stat_skipped.configure(text=str(skipped))
        self._log(f"\nDone — {created} playlists created, {skipped} groups skipped.")
        self._reset_btn()

    def _reset_btn(self):
        self.run_btn.configure(state="normal", text="Build Playlists")
        self._running = False


if __name__ == "__main__":
    app = App()
    app.mainloop()
