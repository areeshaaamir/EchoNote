import os
import io
import re
import uuid
import wave
import math
import json
import time
import struct
import threading
import webbrowser
import winsound
from datetime import datetime
import requests
import customtkinter as ctk
import websocket
import pyaudiowpatch as pyaudio
from PIL import Image
from groq import Groq
from dotenv import load_dotenv
import sys

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
API_BASE = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000/ws/stream"

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
ctk.set_appearance_mode("light")

def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


class EchoNoteDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EchoNote — AFK Study Copilot")
        self.geometry("1160x740")
        self.minsize(1020, 660)

        # App State
        self.user = None
        self.theme_mode = "light"
        self.is_listening = False
        self.away_mode = ctk.BooleanVar(value=True)
        self.topmost_var = ctk.BooleanVar(value=False)

        self.session_seconds = 0
        self.active_triggers: list[str] = []
        self.transcript_entries: list[tuple[str, str]] = []
        self.session_notes: list[str] = []
        self.generated_title: str = ""
        self.alerts_history: list[dict] = []

        self.backend_ws = None
        self.ws_connected = False

        # Editorial Palette: (Light Mode, Dark Mode)
        self.c_sidebar = ("#14211D", "#0D1512")
        self.c_sidebar_active = ("#253530", "#1E2D28")
        self.c_sidebar_text = ("#A3B1AC", "#94A39E")
        self.c_bg = ("#F6F4EF", "#111614")
        self.c_card = ("#FFFFFF", "#19201D")
        self.c_subtle = ("#EDF2F0", "#222C28")
        self.c_border = ("#E5E2DC", "#2A3531")
        self.c_text = ("#18201D", "#F3F4F2")
        self.c_muted = ("#6E7774", "#8F9995")
        self.c_accent = ("#1D4E43", "#2E7D6B")
        self.c_accent_hover = ("#153B32", "#236354")
        self.c_pill_bg = ("#E6F0EC", "#1D332D")
        self.c_pill_text = ("#1D4E43", "#7CC4B2")
        self.c_amber_bg = ("#F7EEDB", "#3A2E1A")
        self.c_amber_text = ("#9A6715", "#E5B567")

        # Fonts
        self.f_serif_lg = ctk.CTkFont(family="Georgia", size=28, weight="bold")
        self.f_brand = ctk.CTkFont(family="Bahnschrift", size=21, weight="bold")
        self.f_h2 = ctk.CTkFont(family="Segoe UI", size=17, weight="bold")
        self.f_h3 = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
        self.f_body = ctk.CTkFont(family="Segoe UI", size=13)
        self.f_small = ctk.CTkFont(family="Segoe UI", size=12)
        self.f_tiny = ctk.CTkFont(family="Segoe UI", size=11, weight="bold")

        self.configure(fg_color=self.c_bg)

        # Load app_logo.jpg from project root
        self.logo_img = None
        for fname in ("app_logo.jpg", "logo.png", "logo.jpg"):
            full_path = resource_path(fname)
            if os.path.exists(fname):
                self.logo_img = ctk.CTkImage(
                    light_image=Image.open(fname),
                    dark_image=Image.open(fname),
                    size=(28, 28),
                )
                break

        self.show_auth_screen()

    def clear_window(self):
        for w in self.winfo_children():
            w.destroy()

    def toggle_theme(self):
        self.theme_mode = "dark" if self.theme_mode == "light" else "light"
        ctk.set_appearance_mode(self.theme_mode)

    def _greeting_text(self) -> str:
        hour = datetime.now().hour
        part = "morning" if hour < 12 else ("afternoon" if hour < 17 else "evening")
        first = self.user["name"].split()[0] if self.user else "Student"
        return f"Good {part}, {first}"

    # ==========================================================
    # 1. AUTHENTICATION SCREEN
    # ==========================================================
    def show_auth_screen(self):
        self.clear_window()
        self.auth_mode = "login"

        wrapper = ctk.CTkFrame(self, fg_color=self.c_bg)
        wrapper.pack(fill="both", expand=True)

        card = ctk.CTkFrame(
            wrapper, width=420, corner_radius=16,
            fg_color=self.c_card, border_width=1, border_color=self.c_border
        )
        card.place(relx=0.5, rely=0.5, anchor="center")

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=32, pady=(28, 6))

        if self.logo_img:
            ctk.CTkLabel(top, text="", image=self.logo_img).pack(side="left", padx=(0, 10))
        else:
            logo_box = ctk.CTkFrame(top, width=26, height=26, corner_radius=6, fg_color="#79B8A8")
            logo_box.pack(side="left", padx=(0, 10))
            logo_box.pack_propagate(False)

        ctk.CTkLabel(
            top, text="EchoNote", font=self.f_brand, text_color=self.c_text
        ).pack(side="left")

        ctk.CTkButton(
            top, text="◐ Theme", width=74, height=28, corner_radius=8,
            fg_color=self.c_subtle, hover_color=self.c_border,
            text_color=self.c_text, font=self.f_small, command=self.toggle_theme
        ).pack(side="right")

        self.auth_sub = ctk.CTkLabel(
            card, text="Sign in to your study workspace and saved notes",
            font=self.f_small, text_color=self.c_muted
        )
        self.auth_sub.pack(anchor="w", padx=32, pady=(0, 20))

        self.name_entry = ctk.CTkEntry(
            card, placeholder_text="Full Name (e.g., Areesha Aamir)",
            width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text
        )

        self.email_entry = ctk.CTkEntry(
            card, placeholder_text="University Email",
            width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text
        )
        self.email_entry.pack(padx=32, pady=(0, 12))

        self.pass_entry = ctk.CTkEntry(
            card, placeholder_text="Password", show="•",
            width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text
        )
        self.pass_entry.pack(padx=32, pady=(0, 10))

        self.auth_err = ctk.CTkLabel(card, text="", font=self.f_small, text_color="#C2410C")
        self.auth_err.pack(padx=32, pady=(0, 8))

        self.auth_btn = ctk.CTkButton(
            card, text="Sign In", width=356, height=42, corner_radius=10,
            fg_color=self.c_accent, hover_color=self.c_accent_hover,
            font=self.f_h3, text_color="#FFFFFF", command=self._submit_auth
        )
        self.auth_btn.pack(padx=32, pady=(0, 10))

        ctk.CTkButton(
            card, text="G   Continue with Google", width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, hover_color=self.c_subtle,
            border_width=1, border_color=self.c_border, text_color=self.c_text,
            font=self.f_h3, command=self._start_google_login
        ).pack(padx=32, pady=(0, 12))

        self.auth_toggle_btn = ctk.CTkButton(
            card, text="Don't have an account? Create one",
            fg_color="transparent", hover_color=self.c_subtle,
            text_color=self.c_muted, font=self.f_small, command=self._toggle_auth_mode
        )
        self.auth_toggle_btn.pack(padx=32, pady=(0, 26))

    def _toggle_auth_mode(self):
        if self.auth_mode == "login":
            self.auth_mode = "signup"
            self.auth_sub.configure(text="Create an account to customize keywords & archive notes")
            self.name_entry.pack(before=self.email_entry, padx=32, pady=(0, 12))
            self.auth_btn.configure(text="Create Account")
            self.auth_toggle_btn.configure(text="Already have an account? Sign in")
        else:
            self.auth_mode = "login"
            self.auth_sub.configure(text="Sign in to your study workspace and saved notes")
            self.name_entry.pack_forget()
            self.auth_btn.configure(text="Sign In")
            self.auth_toggle_btn.configure(text="Don't have an account? Create one")
        self.auth_err.configure(text="")

    def _submit_auth(self):
        email = self.email_entry.get().strip()
        password = self.pass_entry.get().strip()
        name = self.name_entry.get().strip()
        try:
            url = f"{API_BASE}/api/signup" if self.auth_mode == "signup" else f"{API_BASE}/api/login"
            payload = {"name": name, "email": email, "password": password} if self.auth_mode == "signup" else {"email": email, "password": password}
            res = requests.post(url, json=payload, timeout=5)
            if res.status_code == 200:
                self.user = res.json()
                self.build_shell()
            else:
                self.auth_err.configure(text=res.json().get("detail", "Authentication failed."))
        except Exception:
            self.auth_err.configure(text="Backend offline. Start uvicorn on port 8000.")

    def _start_google_login(self):
        state = str(uuid.uuid4())
        webbrowser.open(f"{API_BASE}/auth/google/login?state={state}&local=true")
        self.auth_err.configure(text="Complete sign-in in your browser...", text_color=self.c_muted)

        def poll():
            for _ in range(60):
                try:
                    res = requests.get(f"{API_BASE}/auth/google/poll/{state}", timeout=4).json()
                    if res.get("authenticated"):
                        self.user = res["user"]
                        self.after(0, self.build_shell)
                        return
                except Exception:
                    pass
                time.sleep(2)

        threading.Thread(target=poll, daemon=True).start()

    # ==========================================================
    # 2. MAIN EDITORIAL SHELL
    # ==========================================================
    def build_shell(self):
        self.clear_window()
        self.transcript_entries.clear()
        self.session_notes.clear()
        self.generated_title = ""

        root = ctk.CTkFrame(self, fg_color=self.c_bg, corner_radius=0)
        root.pack(fill="both", expand=True)

        # --- LEFT SIDEBAR ---
        sidebar = ctk.CTkFrame(root, width=220, corner_radius=0, fg_color=self.c_sidebar)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand_row = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand_row.pack(fill="x", padx=22, pady=(26, 28))

        if self.logo_img:
            ctk.CTkLabel(brand_row, text="", image=self.logo_img).pack(side="left", padx=(0, 10))
        else:
            badge = ctk.CTkFrame(brand_row, width=24, height=24, corner_radius=6, fg_color="#79B8A8")
            badge.pack(side="left", padx=(0, 10))
            badge.pack_propagate(False)

        ctk.CTkLabel(
            brand_row, text="EchoNote", font=self.f_brand, text_color="#F8FAFC"
        ).pack(side="left")

        self.nav_buttons = {}
        nav_items = [
            ("dashboard", "Dashboard"),
            ("live", "Live session"),
            ("notes", "Notes"),
            ("alerts", "Alerts"),
            ("keywords", "Keywords"),
        ]
        for key, label in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=f"  {label}", anchor="w", height=40, corner_radius=8,
                fg_color="transparent", hover_color=self.c_sidebar_active,
                text_color=self.c_sidebar_text, font=self.f_body,
                command=lambda k=key: self.select_page(k)
            )
            btn.pack(fill="x", padx=14, pady=2)
            self.nav_buttons[key] = btn

        # Bottom Sidebar Controls
        bottom_nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom_nav.pack(side="bottom", fill="x", padx=14, pady=20)

        settings_btn = ctk.CTkButton(
            bottom_nav, text="  Settings", anchor="w", height=38, corner_radius=8,
            fg_color="transparent", hover_color=self.c_sidebar_active,
            text_color=self.c_sidebar_text, font=self.f_body,
            command=lambda: self.select_page("settings")
        )
        settings_btn.pack(fill="x", pady=2)
        self.nav_buttons["settings"] = settings_btn

        ctk.CTkButton(
            bottom_nav, text="  Sign out", anchor="w", height=36, corner_radius=8,
            fg_color="transparent", hover_color=self.c_sidebar_active,
            text_color="#8A9994", font=self.f_small, command=self._sign_out
        ).pack(fill="x", pady=(2, 0))

        # --- MAIN RIGHT AREA ---
        main_area = ctk.CTkFrame(root, fg_color=self.c_bg, corner_radius=0)
        main_area.pack(side="right", fill="both", expand=True)

        header = ctk.CTkFrame(main_area, fg_color="transparent")
        header.pack(fill="x", padx=32, pady=(26, 18))

        left_head = ctk.CTkFrame(header, fg_color="transparent")
        left_head.pack(side="left")

        date_str = datetime.now().strftime("%A, %d %B")
        ctk.CTkLabel(
            left_head, text=date_str, font=self.f_small, text_color=self.c_muted
        ).pack(anchor="w")

        ctk.CTkLabel(
            left_head, text=self._greeting_text(), font=self.f_serif_lg, text_color=self.c_text
        ).pack(anchor="w", pady=(2, 0))

        away_pill = ctk.CTkFrame(
            header, corner_radius=20, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        away_pill.pack(side="right", pady=8)

        ctk.CTkLabel(
            away_pill, text="Away mode", font=self.f_small, text_color=self.c_text
        ).pack(side="left", padx=(16, 10), pady=8)

        ctk.CTkSwitch(
            away_pill, text="", width=44, variable=self.away_mode,
            progress_color=self.c_accent, button_color="#FFFFFF", button_hover_color="#F1F5F9"
        ).pack(side="right", padx=(0, 12), pady=8)

        self.page_host = ctk.CTkFrame(main_area, fg_color="transparent")
        self.page_host.pack(fill="both", expand=True, padx=32, pady=(0, 28))

        self.pages = {
            "dashboard": ctk.CTkFrame(self.page_host, fg_color="transparent"),
            "live": ctk.CTkFrame(self.page_host, fg_color="transparent"),
            "notes": ctk.CTkFrame(self.page_host, fg_color="transparent"),
            "alerts": ctk.CTkFrame(self.page_host, fg_color="transparent"),
            "keywords": ctk.CTkFrame(self.page_host, fg_color="transparent"),
            "settings": ctk.CTkFrame(self.page_host, fg_color="transparent"),
        }

        self._build_dashboard_page(self.pages["dashboard"])
        self._build_live_focus_page(self.pages["live"])
        self._build_notes_page(self.pages["notes"])
        self._build_alerts_page(self.pages["alerts"])
        self._build_keywords_page(self.pages["keywords"])
        self._build_settings_page(self.pages["settings"])

        self._fetch_triggers_sync()
        self.select_page("dashboard")
        self._connect_ws()
        self._tick_timer()

    def select_page(self, key: str):
        for k, frame in self.pages.items():
            frame.pack_forget()
        for k, btn in self.nav_buttons.items():
            if k == key:
                btn.configure(fg_color=self.c_sidebar_active, text_color="#FFFFFF", font=self.f_h3)
            else:
                btn.configure(fg_color="transparent", text_color=self.c_sidebar_text, font=self.f_body)

        self.pages[key].pack(fill="both", expand=True)

        if key == "keywords":
            self._render_keywords_manager()
        elif key == "notes":
            self._refresh_saved_notes()
        elif key == "alerts":
            self._render_full_alerts()

    # ==========================================================
    # PAGE 1: DASHBOARD
    # ==========================================================
    def _build_dashboard_page(self, parent):
        parent.grid_columnconfigure(0, weight=13)
        parent.grid_columnconfigure(1, weight=7)
        parent.grid_rowconfigure(0, weight=1)

        left_card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        s_top = ctk.CTkFrame(left_card, fg_color="transparent")
        s_top.pack(fill="x", padx=24, pady=(20, 10))

        title_col = ctk.CTkFrame(s_top, fg_color="transparent")
        title_col.pack(side="left")

        ctk.CTkLabel(
            title_col, text="Live session", font=self.f_small, text_color=self.c_muted
        ).pack(anchor="w")

        self.session_title_entry = ctk.CTkEntry(
            title_col, width=280, height=32, border_width=0,
            fg_color="transparent", text_color=self.c_text, font=self.f_h2
        )
        self.session_title_entry.insert(0, "Current Lecture Session")
        self.session_title_entry.pack(anchor="w", pady=(2, 0))

        ctrl_col = ctk.CTkFrame(s_top, fg_color="transparent")
        ctrl_col.pack(side="right")

        self.listen_pill_btn = ctk.CTkButton(
            ctrl_col, text="● Start Listening", height=32, corner_radius=16,
            fg_color=self.c_pill_bg, hover_color=self.c_border,
            text_color=self.c_pill_text, font=self.f_small,
            command=self.toggle_audio_capture
        )
        self.listen_pill_btn.pack(side="right")

        self.timer_lbl = ctk.CTkLabel(
            ctrl_col, text="00:00:00", font=self.f_small, text_color=self.c_muted
        )
        self.timer_lbl.pack(side="right", padx=(0, 12))

        self.dash_chips_frame = ctk.CTkFrame(left_card, fg_color="transparent")
        self.dash_chips_frame.pack(fill="x", padx=24, pady=(2, 12))

        self.transcript_scroll = ctk.CTkScrollableFrame(
            left_card, fg_color="transparent"
        )
        self.transcript_scroll.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        self.transcript_empty_lbl = ctk.CTkLabel(
            self.transcript_scroll,
            text="Click 'Start Listening' to capture system lecture audio, or simulate a phrase below.",
            font=self.f_small, text_color=self.c_muted
        )
        self.transcript_empty_lbl.pack(anchor="w", padx=6, pady=12)

        sim_row = ctk.CTkFrame(left_card, fg_color="transparent")
        sim_row.pack(fill="x", padx=24, pady=(0, 10))

        self.sim_entry = ctk.CTkEntry(
            sim_row, placeholder_text="Simulate spoken sentence...", height=32, corner_radius=8,
            fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text, font=self.f_small
        )
        self.sim_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            sim_row, text="Test", width=64, height=32, corner_radius=8,
            fg_color=self.c_subtle, hover_color=self.c_border,
            text_color=self.c_text, font=self.f_small, command=self._send_sim_phrase
        ).pack(side="right")

        div = ctk.CTkFrame(left_card, height=1, fg_color=self.c_border)
        div.pack(fill="x", padx=24)

        notes_footer = ctk.CTkFrame(left_card, fg_color="transparent")
        notes_footer.pack(fill="x", padx=24, pady=(12, 18))

        nf_head = ctk.CTkFrame(notes_footer, fg_color="transparent")
        nf_head.pack(fill="x")

        ctk.CTkLabel(
            nf_head, text="Auto notes", font=self.f_small, text_color=self.c_muted
        ).pack(side="left")

        ctk.CTkButton(
            nf_head, text="Save Notes", width=86, height=26, corner_radius=8,
            fg_color=self.c_pill_bg, hover_color=self.c_border,
            text_color=self.c_pill_text, font=self.f_tiny, command=self.save_notes_to_db
        ).pack(side="right")

        ctk.CTkButton(
            nf_head, text="Clear", width=64, height=26, corner_radius=8,
            fg_color="transparent", hover_color=self.c_subtle,
            border_width=1, border_color=self.c_border,
            text_color=self.c_muted, font=self.f_tiny, command=self.clear_session_notes
        ).pack(side="right", padx=(0, 8))

        self.auto_notes_lbl = ctk.CTkLabel(
            notes_footer,
            text="English study notes appear here automatically every 4 sentences.",
            font=self.f_body, text_color=self.c_text, justify="left", wraplength=540
        )
        self.auto_notes_lbl.pack(anchor="w", pady=(6, 0))

        # --- RIGHT CARD: ALERTS ---
        right_card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        right_card.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        a_head = ctk.CTkFrame(right_card, fg_color="transparent")
        a_head.pack(fill="x", padx=22, pady=(20, 12))

        ctk.CTkLabel(
            a_head, text="Alerts", font=self.f_h2, text_color=self.c_text
        ).pack(side="left")

        self.alert_count_pill = ctk.CTkLabel(
            a_head, text=" 0 new ", corner_radius=12,
            fg_color=self.c_amber_bg, text_color=self.c_amber_text, font=self.f_tiny
        )
        self.alert_count_pill.pack(side="right")

        self.dash_alerts_scroll = ctk.CTkScrollableFrame(right_card, fg_color="transparent")
        self.dash_alerts_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.dash_alerts_empty = ctk.CTkLabel(
            self.dash_alerts_scroll, text="No alerts triggered yet.",
            font=self.f_small, text_color=self.c_muted
        )
        self.dash_alerts_empty.pack(anchor="w", padx=6, pady=8)

        ctk.CTkButton(
            right_card, text="View all alerts", height=40, corner_radius=10,
            fg_color="transparent", hover_color=self.c_subtle,
            border_width=1, border_color=self.c_border,
            text_color=self.c_pill_text, font=self.f_h3,
            command=lambda: self.select_page("alerts")
        ).pack(fill="x", padx=22, pady=(4, 20))

    def _render_dashboard_chips(self):
        for w in self.dash_chips_frame.winfo_children():
            w.destroy()
        for word in self.active_triggers[:7]:
            chip = ctk.CTkLabel(
                self.dash_chips_frame, text=f"  {word}  ", height=26, corner_radius=13,
                fg_color=self.c_pill_bg, text_color=self.c_pill_text, font=self.f_small
            )
            chip.pack(side="left", padx=(0, 6))

    def _append_transcript_row(self, ts: str, text: str):
        if self.transcript_empty_lbl.winfo_exists():
            self.transcript_empty_lbl.destroy()

        row = ctk.CTkFrame(self.transcript_scroll, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=6)

        ctk.CTkLabel(
            row, text=ts, width=46, anchor="nw", font=self.f_small, text_color=self.c_muted
        ).pack(side="left", anchor="n")

        matched = [w for w in self.active_triggers if re.search(rf"\b{re.escape(w)}\b", text, re.I)]
        txt_frame = ctk.CTkFrame(row, fg_color="transparent")
        txt_frame.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            txt_frame, text=text, font=self.f_body, text_color=self.c_text,
            justify="left", wraplength=460, anchor="w"
        ).pack(anchor="w")

        if matched:
            tag_row = ctk.CTkFrame(txt_frame, fg_color="transparent")
            tag_row.pack(anchor="w", pady=(3, 0))
            for m in matched[:3]:
                ctk.CTkLabel(
                    tag_row, text=f" {m} ", corner_radius=6,
                    fg_color=self.c_amber_bg, text_color=self.c_amber_text, font=self.f_tiny
                ).pack(side="left", padx=(0, 4))

    def _add_dashboard_alert_card(self, alert: dict):
        if self.dash_alerts_empty.winfo_exists():
            self.dash_alerts_empty.destroy()

        card = ctk.CTkFrame(self.dash_alerts_scroll, fg_color="transparent")
        card.pack(fill="x", padx=6, pady=6)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x")

        tag_label = alert.get("event_type", "alert").lower().replace("_", " ")
        ctk.CTkLabel(
            top, text=tag_label, font=self.f_h3, text_color=self.c_amber_text
        ).pack(side="left")

        ctk.CTkLabel(
            top, text=alert.get("time", ""), font=self.f_small, text_color=self.c_muted
        ).pack(side="right")

        ctk.CTkLabel(
            card, text=alert.get("summary", alert.get("original_text", "")),
            font=self.f_body, text_color=self.c_text, justify="left", wraplength=260, anchor="w"
        ).pack(anchor="w", pady=(2, 8))

        sep = ctk.CTkFrame(card, height=1, fg_color=self.c_border)
        sep.pack(fill="x")

        self.alert_count_pill.configure(text=f" {len(self.alerts_history)} new ")

    # ==========================================================
    # PAGE 2: LIVE SESSION FOCUS VIEW
    # ==========================================================
    def _build_live_focus_page(self, parent):
        card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            card, text="Full Session Transcript & Live Notes",
            font=self.f_h2, text_color=self.c_text
        ).pack(anchor="w", padx=24, pady=(20, 6))

        ctk.CTkLabel(
            card, text="Everything captured during your active lecture session appears below.",
            font=self.f_small, text_color=self.c_muted
        ).pack(anchor="w", padx=24, pady=(0, 14))

        self.focus_box = ctk.CTkTextbox(
            card, wrap="word", fg_color=self.c_bg, text_color=self.c_text,
            border_width=1, border_color=self.c_border, font=self.f_body
        )
        self.focus_box.pack(fill="both", expand=True, padx=24, pady=(0, 20))

    # ==========================================================
    # PAGE 3: NOTES ARCHIVE
    # ==========================================================
    def _build_notes_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=2)
        parent.grid_rowconfigure(0, weight=1)

        list_card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        ctk.CTkLabel(
            list_card, text="Saved Notes", font=self.f_h2, text_color=self.c_text
        ).pack(anchor="w", padx=20, pady=(20, 10))

        self.notes_list_scroll = ctk.CTkScrollableFrame(list_card, fg_color="transparent")
        self.notes_list_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 16))

        reader_card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        reader_card.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        self.reader_title_lbl = ctk.CTkLabel(
            reader_card, text="Select a saved note session", font=self.f_h2, text_color=self.c_text
        )
        self.reader_title_lbl.pack(anchor="w", padx=24, pady=(20, 10))

        self.reader_textbox = ctk.CTkTextbox(
            reader_card, wrap="word", fg_color=self.c_bg, text_color=self.c_text,
            border_width=1, border_color=self.c_border, font=self.f_body
        )
        self.reader_textbox.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.reader_textbox.configure(state="disabled")

    def _refresh_saved_notes(self):
        for w in self.notes_list_scroll.winfo_children():
            w.destroy()
        try:
            res = requests.get(f"{API_BASE}/api/notes/{self.user['user_id']}", timeout=5)
            notes = res.json().get("notes", [])
            if not notes:
                ctk.CTkLabel(
                    self.notes_list_scroll, text="No saved notes yet.",
                    font=self.f_small, text_color=self.c_muted
                ).pack(pady=16)
                return

            for item in notes:
                row = ctk.CTkFrame(
                    self.notes_list_scroll, fg_color=self.c_bg, corner_radius=10,
                    border_width=1, border_color=self.c_border
                )
                row.pack(fill="x", padx=4, pady=4)

                ctk.CTkButton(
                    row, text=f"{item['title']}\n{item['created_at']}",
                    anchor="w", height=50, fg_color="transparent", hover_color=self.c_subtle,
                    text_color=self.c_text, font=self.f_small,
                    command=lambda n=item: self._open_saved_note(n)
                ).pack(side="left", fill="x", expand=True, padx=(6, 2), pady=2)

                ctk.CTkButton(
                    row, text="Delete", width=56, height=28, corner_radius=6,
                    fg_color="transparent", hover_color=self.c_subtle,
                    text_color="#C2410C", font=self.f_tiny,
                    command=lambda nid=item["id"]: self._delete_saved_note(nid)
                ).pack(side="right", padx=(2, 8))
        except Exception:
            pass

    def _open_saved_note(self, note: dict):
        self.reader_title_lbl.configure(text=f"{note['title']}  •  {note['created_at']}")
        self.reader_textbox.configure(state="normal")
        self.reader_textbox.delete("1.0", "end")
        self.reader_textbox.insert("end", note["content"])
        self.reader_textbox.configure(state="disabled")

    def _delete_saved_note(self, note_id: int):
        try:
            requests.delete(f"{API_BASE}/api/notes/{note_id}", timeout=5)
            self.reader_title_lbl.configure(text="Select a saved note session")
            self.reader_textbox.configure(state="normal")
            self.reader_textbox.delete("1.0", "end")
            self.reader_textbox.configure(state="disabled")
            self._refresh_saved_notes()
        except Exception:
            pass

    # ==========================================================
    # PAGE 4: ALERTS HISTORY
    # ==========================================================
    def _build_alerts_page(self, parent):
        card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            card, text="All Session Alerts", font=self.f_h2, text_color=self.c_text
        ).pack(anchor="w", padx=24, pady=(20, 12))

        self.full_alerts_scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self.full_alerts_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    def _render_full_alerts(self):
        for w in self.full_alerts_scroll.winfo_children():
            w.destroy()
        if not self.alerts_history:
            ctk.CTkLabel(
                self.full_alerts_scroll, text="No alerts recorded in this session.",
                font=self.f_small, text_color=self.c_muted
            ).pack(anchor="w", padx=6, pady=8)
            return

        for a in self.alerts_history:
            box = ctk.CTkFrame(
                self.full_alerts_scroll, fg_color=self.c_bg, corner_radius=10,
                border_width=1, border_color=self.c_border
            )
            box.pack(fill="x", padx=4, pady=6)

            ctk.CTkLabel(
                box, text=f"{a.get('event_type')}  •  {a.get('time')}",
                font=self.f_h3, text_color=self.c_amber_text
            ).pack(anchor="w", padx=16, pady=(12, 2))

            ctk.CTkLabel(
                box, text=a.get("summary", ""), font=self.f_body, text_color=self.c_text
            ).pack(anchor="w", padx=16)

            ctk.CTkLabel(
                box, text=f"\"{a.get('original_text', '')}\"",
                font=self.f_small, text_color=self.c_muted
            ).pack(anchor="w", padx=16, pady=(2, 12))

    # ==========================================================
    # PAGE 5: KEYWORDS MANAGER
    # ==========================================================
    def _build_keywords_page(self, parent):
        card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            card, text="Trigger Keywords", font=self.f_h2, text_color=self.c_text
        ).pack(anchor="w", padx=24, pady=(20, 4))

        ctk.CTkLabel(
            card, text="Customize the default and personal keywords that trigger instant alerts.",
            font=self.f_small, text_color=self.c_muted
        ).pack(anchor="w", padx=24, pady=(0, 14))

        add_bar = ctk.CTkFrame(card, fg_color="transparent")
        add_bar.pack(fill="x", padx=24, pady=(0, 16))

        self.kw_entry = ctk.CTkEntry(
            add_bar, placeholder_text="Add a new keyword (e.g., roll 219, viva, submission)...",
            height=38, corner_radius=10, fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text
        )
        self.kw_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            add_bar, text="Add Keyword", width=120, height=38, corner_radius=10,
            fg_color=self.c_accent, hover_color=self.c_accent_hover,
            text_color="#FFFFFF", font=self.f_h3, command=self._add_keyword
        ).pack(side="right")

        self.kw_scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self.kw_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    def _fetch_triggers_sync(self):
        try:
            res = requests.get(f"{API_BASE}/api/triggers/{self.user['user_id']}", timeout=5)
            self.active_triggers = res.json().get("triggers", [])
            self._render_dashboard_chips()
        except Exception:
            pass

    def _render_keywords_manager(self):
        self._fetch_triggers_sync()
        for w in self.kw_scroll.winfo_children():
            w.destroy()
        for word in self.active_triggers:
            row = ctk.CTkFrame(
                self.kw_scroll, fg_color=self.c_bg, corner_radius=10,
                border_width=1, border_color=self.c_border
            )
            row.pack(fill="x", padx=4, pady=4)

            ctk.CTkLabel(
                row, text=word, font=self.f_h3, text_color=self.c_text
            ).pack(side="left", padx=16, pady=10)

            ctk.CTkButton(
                row, text="Remove", width=70, height=28, corner_radius=6,
                fg_color="transparent", hover_color=self.c_subtle,
                text_color="#C2410C", font=self.f_small,
                command=lambda w=word: self._remove_keyword(w)
            ).pack(side="right", padx=12, pady=8)

    def _add_keyword(self):
        word = self.kw_entry.get().strip()
        if not word:
            return
        try:
            requests.post(
                f"{API_BASE}/api/triggers",
                json={"user_id": self.user["user_id"], "word": word},
                timeout=5
            )
            self.kw_entry.delete(0, "end")
            self._render_keywords_manager()
        except Exception:
            pass

    def _remove_keyword(self, word: str):
        try:
            requests.delete(f"{API_BASE}/api/triggers/{self.user['user_id']}/{word}", timeout=5)
            self._render_keywords_manager()
        except Exception:
            pass

    # ==========================================================
    # PAGE 6: SETTINGS
    # ==========================================================
    def _build_settings_page(self, parent):
        card = ctk.CTkFrame(
            parent, corner_radius=16, fg_color=self.c_card,
            border_width=1, border_color=self.c_border
        )
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            card, text="Workspace Settings", font=self.f_h2, text_color=self.c_text
        ).pack(anchor="w", padx=24, pady=(20, 16))

        ctk.CTkButton(
            card, text="Switch Light / Dark Appearance", width=220, height=38, corner_radius=10,
            fg_color=self.c_subtle, hover_color=self.c_border,
            text_color=self.c_text, font=self.f_body, command=self.toggle_theme
        ).pack(anchor="w", padx=24, pady=(0, 14))

        ctk.CTkCheckBox(
            card, text="Keep EchoNote window pinned above other apps",
            variable=self.topmost_var, text_color=self.c_text, font=self.f_body,
            fg_color=self.c_accent,
            command=lambda: self.attributes("-topmost", self.topmost_var.get())
        ).pack(anchor="w", padx=24, pady=6)

    # ==========================================================
    # BACKEND WEBSOCKET, TIMER & GROQ WHISPER AUDIO STREAM
    # ==========================================================
    def _tick_timer(self):
        if self.user and hasattr(self, "timer_lbl") and self.timer_lbl.winfo_exists():
            if self.is_listening:
                self.session_seconds += 1
                hrs = self.session_seconds // 3600
                mins = (self.session_seconds % 3600) // 60
                secs = self.session_seconds % 60
                self.timer_lbl.configure(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")
            self.after(1000, self._tick_timer)

    def _connect_ws(self):
        def run():
            while self.user:
                try:
                    ws = websocket.WebSocketApp(
                        f"{WS_BASE}?user_id={self.user['user_id']}",
                        on_open=lambda ws: self.after(0, lambda: setattr(self, "ws_connected", True)),
                        on_message=lambda ws, msg: self.after(0, self._on_ws_message, msg),
                        on_close=lambda ws, *a: self.after(0, lambda: setattr(self, "ws_connected", False)),
                    )
                    self.backend_ws = ws
                    ws.run_forever()
                except Exception:
                    pass
                time.sleep(2)

        threading.Thread(target=run, daemon=True).start()

    def _on_ws_message(self, raw: str):
        data = json.loads(raw)
        msg_type = data.get("type")

        if msg_type == "TRANSCRIPT":
            ts = data.get("timestamp", datetime.now().strftime("%H:%M"))
            txt = data.get("text", "")
            self.transcript_entries.append((ts, txt))
            self._append_transcript_row(ts, txt)
            self.focus_box.insert("end", f"[{ts}] {txt}\n")

        elif msg_type == "MEETING_NOTE" and data.get("notes"):
            for n in data["notes"]:
                self.session_notes.append(n)
            combined = " ".join(self.session_notes[-3:])
            self.auto_notes_lbl.configure(text=combined)
            self.focus_box.insert("end", f"\n[Auto Note]: {combined}\n\n")

        elif data.get("trigger_detected"):
            if self.away_mode.get():
                threading.Thread(target=lambda: winsound.Beep(920, 320), daemon=True).start()
            alert_obj = {
                "time": datetime.now().strftime("%H:%M"),
                "event_type": data.get("event_type", "ALERT"),
                "summary": data.get("summary", ""),
                "original_text": data.get("original_text", ""),
            }
            self.alerts_history.insert(0, alert_obj)
            self._add_dashboard_alert_card(alert_obj)

    def _send_sim_phrase(self):
        txt = self.sim_entry.get().strip()
        if txt and self.backend_ws:
            self.backend_ws.send(txt)
            self.sim_entry.delete(0, "end")
            
    def clear_session_notes(self):
        self.session_notes.clear()
        self.transcript_entries.clear()
        self.generated_title = ""

        # Reset session title & timer if not actively recording
        self.session_title_entry.delete(0, "end")
        self.session_title_entry.insert(0, "Current Lecture Session")
        if not self.is_listening:
            self.session_seconds = 0
            self.timer_lbl.configure(text="00:00:00")

        # Reset Auto Notes footer text
        self.auto_notes_lbl.configure(
            text="English study notes appear here automatically every 4 sentences."
        )

        # Clear Dashboard transcript stream & restore empty prompt
        for w in self.transcript_scroll.winfo_children():
            w.destroy()
        self.transcript_empty_lbl = ctk.CTkLabel(
            self.transcript_scroll,
            text="Click 'Start Listening' to capture system lecture audio, or simulate a phrase below.",
            font=self.f_small, text_color=self.c_muted
        )
        self.transcript_empty_lbl.pack(anchor="w", padx=6, pady=12)

        # Clear Live Session focus box
        if hasattr(self, "focus_box") and self.focus_box.winfo_exists():
            self.focus_box.delete("1.0", "end")

        # Reset backend rolling buffer so old sentences don't bleed into new notes
        threading.Thread(
            target=lambda: requests.post(f"{API_BASE}/api/notes/reset-buffer", timeout=2),
            daemon=True
        ).start()

    def save_notes_to_db(self):
        if not self.session_notes:
            return
        content = "\n".join(f"• {n}" for n in self.session_notes)
        title_to_use = self.generated_title or self.session_title_entry.get().strip()
        try:
            res = requests.post(
                f"{API_BASE}/api/notes/save",
                json={"user_id": self.user["user_id"], "title": title_to_use, "content": content},
                timeout=5
            )
            if res.status_code == 200:
                self.auto_notes_lbl.configure(text=f"✓ Saved to Notes: {res.json().get('title', '')}")
        except Exception:
            pass

    def toggle_audio_capture(self):
        if not self.is_listening:
            if not groq_client:
                return
            self.session_notes.clear()
            self.generated_title = ""
            self.session_seconds = 0
            self.timer_lbl.configure(text="00:00:00")
            self.auto_notes_lbl.configure(text="Listening for lecture speech...")
            threading.Thread(
                target=lambda: requests.post(f"{API_BASE}/api/notes/reset-buffer", timeout=2),
                daemon=True
            ).start()

            self.is_listening = True
            self.listen_pill_btn.configure(
                text="● Listening", fg_color=self.c_pill_bg, text_color=self.c_pill_text
            )
            threading.Thread(target=self._stream_wasapi_to_groq, daemon=True).start()
        else:
            self.is_listening = False
            self.listen_pill_btn.configure(
                text="● Start Listening", fg_color=self.c_subtle, text_color=self.c_text
            )
            if self.session_notes:
                threading.Thread(target=self._auto_generate_title, daemon=True).start()

    def _auto_generate_title(self):
        content = "\n".join(f"• {n}" for n in self.session_notes)
        try:
            res = requests.post(
                f"{API_BASE}/api/notes/generate-title",
                json={"content": content},
                timeout=8
            )
            if res.status_code == 200:
                self.generated_title = res.json().get("title", "Lecture Summary")
                self.after(0, lambda: self.session_title_entry.delete(0, "end"))
                self.after(0, lambda: self.session_title_entry.insert(0, self.generated_title))
        except Exception:
            pass

    def _stream_wasapi_to_groq(self):
        p = pyaudio.PyAudio()
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            if not default_speakers["isLoopbackDevice"]:
                for loopback in p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break

            sample_rate = int(default_speakers["defaultSampleRate"])
            channels = default_speakers["maxInputChannels"]

            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=sample_rate,
                frames_per_buffer=1024,
                input=True,
                input_device_index=default_speakers["index"],
            )

            frames_per_chunk = int((sample_rate / 1024) * 4)

            while self.is_listening:
                frames = []
                for _ in range(frames_per_chunk):
                    if not self.is_listening:
                        break
                    frames.append(stream.read(1024, exception_on_overflow=False))
                if not frames:
                    break

                raw_pcm = b"".join(frames)
                samples = struct.unpack(f"<{len(raw_pcm)//2}h", raw_pcm)
                rms = math.sqrt(sum(s * s for s in samples) / max(len(samples), 1))
                if rms < 80:
                    continue

                wav_buf = io.BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(raw_pcm)
                wav_buf.seek(0)

                def send_chunk(buf):
                    try:
                        res = groq_client.audio.transcriptions.create(
                            file=("chunk.wav", buf.read()),
                            model="whisper-large-v3-turbo",
                            prompt="Transcribe mixed Urdu and English university lecture speech accurately.",
                            response_format="json",
                            temperature=0.0,
                        )
                        text = res.text.strip()
                        if text and self.backend_ws:
                            self.backend_ws.send(text)
                    except Exception as err:
                        print(f"[Groq Whisper Error]: {err}")

                threading.Thread(target=send_chunk, args=(wav_buf,), daemon=True).start()

            stream.stop_stream()
            stream.close()
        except Exception as e:
            print(f"[WASAPI Loopback Error]: {e}")
        finally:
            p.terminate()

    def _sign_out(self):
        self.user = None
        self.is_listening = False
        if self.backend_ws:
            self.backend_ws.close()
        self.show_auth_screen()


if __name__ == "__main__":
    app = EchoNoteDesktopApp()
    app.mainloop()