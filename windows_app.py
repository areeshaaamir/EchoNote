import os
import re
import sys
import time
import uuid
import wave
import tempfile
import threading
import webbrowser
import winsound
from difflib import SequenceMatcher
import requests
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image
import customtkinter as ctk
import pyaudiowpatch as pyaudio
from groq import Groq


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# Load .env from both bundled resources and the executable's working directory
load_dotenv(resource_path(".env"))
load_dotenv()

API_BASE = os.getenv("ECHONOTE_API_BASE", "https://echonote-api.echonoteapp.workers.dev").strip().strip('"').rstrip("/")
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("green")


class EchoNoteDesktop(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EchoNote — Lecture Copilot")
        self.geometry("1200x760")
        self.minsize(1040, 680)

        try:
            ico_path = resource_path("app_logo.ico")
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
        except Exception:
            pass

        # Editorial Sage & Warm Alabaster Palette
        self.c_bg = ("#F6F4EF", "#111614")
        self.c_sidebar = ("#14211D", "#0D1512")
        self.c_card = ("#FFFFFF", "#19201D")
        self.c_subtle = ("#EDF2F0", "#222C28")
        self.c_border = ("#E5E2DC", "#2A3531")
        self.c_text = ("#18201D", "#F3F4F2")
        self.c_muted = ("#6E7774", "#8F9995")
        self.c_accent = ("#1D4E43", "#2E7D6B")
        self.c_accent_hover = ("#143830", "#236354")
        self.c_pill_bg = ("#E6F0EC", "#1D332D")
        self.c_pill_txt = ("#1D4E43", "#7CC4B2")
        self.c_amber_bg = ("#F7EEDB", "#3A2E1A")
        self.c_amber_txt = ("#9A6715", "#E5B567")

        # Typography
        self.f_serif_lg = ctk.CTkFont(family="Georgia", size=24, weight="bold")
        self.f_h1 = ctk.CTkFont(family="Segoe UI", size=20, weight="bold")
        self.f_h2 = ctk.CTkFont(family="Segoe UI", size=15, weight="bold")
        self.f_h3 = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        self.f_body = ctk.CTkFont(family="Segoe UI", size=13)
        self.f_small = ctk.CTkFont(family="Segoe UI", size=11)
        self.f_mono = ctk.CTkFont(family="Consolas", size=12)

        # App State
        self.user = None
        self.auth_mode = "login"
        self.is_listening = False
        self.active_triggers = []
        self.transcript_lines = []
        self.recent_buffer = []
        self.session_notes = []
        self.alert_history = []
        self.session_start = None
        self.generated_title = ""
        self.last_alert_cooldown = {}

        self.configure(fg_color=self.c_bg)
        self.logo_img = self._load_logo((30, 30))
        self.show_auth_screen()

    def _load_logo(self, size):
        try:
            path = resource_path("app_logo.jpg")
            if os.path.exists(path):
                img = Image.open(path)
                return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            pass
        return None

    def toggle_theme(self):
        current = ctk.get_appearance_mode()
        ctk.set_appearance_mode("Dark" if current == "Light" else "Light")

    # ==========================================================
    # SCREEN 1: AUTHENTICATION
    # ==========================================================
    def show_auth_screen(self):
        for w in self.winfo_children():
            w.destroy()

        outer = ctk.CTkFrame(self, fg_color=self.c_bg)
        outer.pack(fill="both", expand=True)

        card = ctk.CTkFrame(
            outer, width=420, corner_radius=18,
            fg_color=self.c_card, border_width=1, border_color=self.c_border
        )
        card.place(relx=0.5, rely=0.5, anchor="center")

        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.pack(fill="x", padx=32, pady=(28, 6))

        if self.logo_img:
            ctk.CTkLabel(header_row, image=self.logo_img, text="").pack(side="left", padx=(0, 10))
        ctk.CTkLabel(header_row, text="EchoNote", font=self.f_h1, text_color=self.c_text).pack(side="left")

        ctk.CTkButton(
            header_row, text="◐ Theme", width=76, height=28, corner_radius=8,
            fg_color=self.c_subtle, hover_color=self.c_border, text_color=self.c_text,
            font=self.f_small, command=self.toggle_theme
        ).pack(side="right")

        self.auth_sub = ctk.CTkLabel(
            card, text="Sign in to sync your lecture alerts & notes",
            font=self.f_body, text_color=self.c_muted
        )
        self.auth_sub.pack(anchor="w", padx=32, pady=(0, 18))

        self.name_entry = ctk.CTkEntry(
            card, placeholder_text="Full Name (e.g., Areesha Aamir)",
            width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text, font=self.f_body
        )

        self.email_entry = ctk.CTkEntry(
            card, placeholder_text="Email address",
            width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text, font=self.f_body
        )
        self.email_entry.pack(padx=32, pady=(0, 12))

        self.pass_entry = ctk.CTkEntry(
            card, placeholder_text="Password", show="•",
            width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text, font=self.f_body
        )
        self.pass_entry.pack(padx=32, pady=(0, 12))

        self.auth_err = ctk.CTkLabel(card, text="", font=self.f_small, text_color="#C2410C")
        self.auth_err.pack(padx=32, pady=(0, 8))

        self.auth_btn = ctk.CTkButton(
            card, text="Sign In", width=356, height=42, corner_radius=10,
            fg_color=self.c_accent, hover_color=self.c_accent_hover, font=self.f_h3,
            command=self._submit_auth
        )
        self.auth_btn.pack(padx=32, pady=(0, 10))

        ctk.CTkButton(
            card, text="G   Continue with Google", width=356, height=40, corner_radius=10,
            fg_color=self.c_bg, hover_color=self.c_subtle,
            border_width=1, border_color=self.c_border, text_color=self.c_text,
            font=self.f_h3, command=self._start_google_login
        ).pack(padx=32, pady=(0, 12))

        self.switch_btn = ctk.CTkButton(
            card, text="Don't have an account? Create one",
            fg_color="transparent", hover_color=self.c_subtle,
            text_color=self.c_muted, font=self.f_small,
            command=self._toggle_auth_mode
        )
        self.switch_btn.pack(padx=32, pady=(0, 24))

    def _toggle_auth_mode(self):
        self.auth_err.configure(text="")
        if self.auth_mode == "login":
            self.auth_mode = "signup"
            self.auth_sub.configure(text="Create an account to customize keywords & archive notes")
            self.name_entry.pack(before=self.email_entry, padx=32, pady=(0, 12))
            self.auth_btn.configure(text="Create Account")
            self.switch_btn.configure(text="Already have an account? Sign in")
        else:
            self.auth_mode = "login"
            self.auth_sub.configure(text="Sign in to sync your lecture alerts & notes")
            self.name_entry.pack_forget()
            self.auth_btn.configure(text="Sign In")
            self.switch_btn.configure(text="Don't have an account? Create one")

    def _submit_auth(self):
        email = self.email_entry.get().strip()
        password = self.pass_entry.get().strip()
        name = self.name_entry.get().strip()
        if not email or not password:
            self.auth_err.configure(text="Please enter both email and password.")
            return

        endpoint = "/api/signup" if self.auth_mode == "signup" else "/api/login"
        payload = {"name": name or "Student", "email": email, "password": password} if self.auth_mode == "signup" else {"email": email, "password": password}

        try:
            res = requests.post(f"{API_BASE}{endpoint}", json=payload, timeout=10)
            data = res.json()
            if res.status_code != 200:
                self.auth_err.configure(text=data.get("detail", "Authentication failed."))
                return
            self.user = data
            self.active_triggers = data.get("keywords", [])
            self.build_shell()
        except Exception as e:
            self.auth_err.configure(text=f"Connection error: {e}")

    def _start_google_login(self):
        state = str(uuid.uuid4())
        webbrowser.open(f"{API_BASE}/auth/google/login?state={state}")
        self.auth_err.configure(text="Complete sign-in in your browser...", text_color=self.c_muted)

        def poll():
            for _ in range(60):
                try:
                    res = requests.get(f"{API_BASE}/auth/google/poll/{state}", timeout=5).json()
                    if res.get("authenticated"):
                        self.user = res["user"]
                        self.active_triggers = self.user.get("keywords", [])
                        self.after(0, self.build_shell)
                        return
                except Exception:
                    pass
                time.sleep(2)

        threading.Thread(target=poll, daemon=True).start()

    # ==========================================================
    # SCREEN 2: MAIN SIDEBAR WORKSPACE SHELL
    # ==========================================================
    def build_shell(self):
        for w in self.winfo_children():
            w.destroy()

        # Left Dark Forest Sidebar
        sidebar = ctk.CTkFrame(self, width=224, corner_radius=0, fg_color=self.c_sidebar)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(24, 28))
        if self.logo_img:
            ctk.CTkLabel(brand, image=self.logo_img, text="").pack(side="left", padx=(0, 10))
        ctk.CTkLabel(brand, text="EchoNote", font=self.f_h1, text_color="#F8FAFC").pack(side="left")

        self.nav_buttons = {}
        nav_items = [
            ("dashboard", "◉   Dashboard"),
            ("keywords", "⚑   Trigger Keywords"),
            ("notes", "▤   Saved Notes"),
        ]
        for key, label in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=40, corner_radius=10,
                fg_color="transparent", hover_color="#1F302B",
                text_color="#D1DBD7", font=self.f_h3,
                command=lambda k=key: self.switch_page(k)
            )
            btn.pack(fill="x", padx=14, pady=3)
            self.nav_buttons[key] = btn

        # Bottom Profile & Theme Switcher
        bottom_box = ctk.CTkFrame(sidebar, fg_color="#1B2A25", corner_radius=12)
        bottom_box.pack(side="bottom", fill="x", padx=14, pady=18)

        first_name = self.user.get("name", "Student").split()[0]
        ctk.CTkLabel(bottom_box, text=self.user.get("name", "Student"), font=self.f_h3, text_color="#F8FAFC").pack(anchor="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(bottom_box, text=self.user.get("email", ""), font=self.f_small, text_color="#94A39E").pack(anchor="w", padx=12, pady=(0, 10))

        ctrl_row = ctk.CTkFrame(bottom_box, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(
            ctrl_row, text="◐ Theme", width=82, height=28, corner_radius=8,
            fg_color="#253832", hover_color="#2F463F", text_color="#E2E8F0", font=self.f_small,
            command=self.toggle_theme
        ).pack(side="left")
        ctk.CTkButton(
            ctrl_row, text="Sign Out", width=82, height=28, corner_radius=8,
            fg_color="transparent", hover_color="#3B2323", border_width=1, border_color="#364943",
            text_color="#CBD5E1", font=self.f_small,
            command=self._logout
        ).pack(side="right")

        # Main Content Canvas
        self.main_area = ctk.CTkFrame(self, fg_color=self.c_bg, corner_radius=0)
        self.main_area.pack(side="right", fill="both", expand=True)

        self.pages = {}
        self._build_dashboard_page(first_name)
        self._build_keywords_page()
        self._build_notes_page()

        self.switch_page("dashboard")
        self._refresh_triggers_from_server()
        self._update_timer()

    def _logout(self):
        self.is_listening = False
        self.user = None
        self.show_auth_screen()

    def switch_page(self, key: str):
        for k, frame in self.pages.items():
            frame.pack_forget()
            self.nav_buttons[k].configure(fg_color="transparent", text_color="#D1DBD7")

        self.pages[key].pack(fill="both", expand=True, padx=28, pady=24)
        self.nav_buttons[key].configure(fg_color="#233832", text_color="#FFFFFF")

        if key == "keywords":
            self._refresh_triggers_from_server()
        elif key == "notes":
            self._refresh_saved_notes()

    # ==========================================================
    # PAGE 1: DASHBOARD (LIVE LISTENER + ALERTS + FOCUS NOTES)
    # ==========================================================
    def _build_dashboard_page(self, first_name: str):
        page = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.pages["dashboard"] = page

        # Top Greeting Header
        top_bar = ctk.CTkFrame(page, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 18))

        greet_col = ctk.CTkFrame(top_bar, fg_color="transparent")
        greet_col.pack(side="left")
        ctk.CTkLabel(greet_col, text=datetime.now().strftime("%A, %d %B"), font=self.f_small, text_color=self.c_muted).pack(anchor="w")
        ctk.CTkLabel(greet_col, text=f"Good morning, {first_name}", font=self.f_serif_lg, text_color=self.c_text).pack(anchor="w")

        status_pill = ctk.CTkFrame(top_bar, fg_color=self.c_card, border_width=1, border_color=self.c_border, corner_radius=20)
        status_pill.pack(side="right", pady=6)
        self.cloud_lbl = ctk.CTkLabel(status_pill, text="● Cloud Connected", font=self.f_small, text_color=self.c_pill_txt)
        self.cloud_lbl.pack(padx=14, pady=6)

        # Asymmetric Two-Column Workspace
        cols = ctk.CTkFrame(page, fg_color="transparent")
        cols.pack(fill="both", expand=True)
        cols.grid_columnconfigure(0, weight=3)
        cols.grid_columnconfigure(1, weight=2)
        cols.grid_rowconfigure(0, weight=1)

        # LEFT CARD: Live Lecture Session
        left_card = ctk.CTkFrame(cols, fg_color=self.c_card, border_width=1, border_color=self.c_border, corner_radius=16)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        sess_head = ctk.CTkFrame(left_card, fg_color="transparent")
        sess_head.pack(fill="x", padx=20, pady=(18, 10))

        title_stack = ctk.CTkFrame(sess_head, fg_color="transparent")
        title_stack.pack(side="left")
        ctk.CTkLabel(title_stack, text="Live session", font=self.f_small, text_color=self.c_muted).pack(anchor="w")
        ctk.CTkLabel(title_stack, text="Current Lecture Session", font=self.f_h2, text_color=self.c_text).pack(anchor="w")

        ctrl_stack = ctk.CTkFrame(sess_head, fg_color="transparent")
        ctrl_stack.pack(side="right")
        self.timer_lbl = ctk.CTkLabel(ctrl_stack, text="00:00:00", font=self.f_mono, text_color=self.c_muted)
        self.timer_lbl.pack(side="left", padx=(0, 12))

        self.listen_btn = ctk.CTkButton(
            ctrl_stack, text="● Start Listening", width=148, height=34, corner_radius=17,
            fg_color=self.c_subtle, hover_color=self.c_border, text_color=self.c_text,
            font=self.f_h3, command=self.toggle_listening
        )
        self.listen_btn.pack(side="right")

        # Active Keywords Strip
        self.kw_strip = ctk.CTkFrame(left_card, fg_color="transparent")
        self.kw_strip.pack(fill="x", padx=20, pady=(0, 10))
        self._render_keyword_pills()

        # Live Transcript Stream
        self.transcript_scroll = ctk.CTkScrollableFrame(
            left_card, fg_color=self.c_bg, corner_radius=12, border_width=1, border_color=self.c_border
        )
        self.transcript_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        # Quick Test Bar
        test_bar = ctk.CTkFrame(left_card, fg_color="transparent")
        test_bar.pack(fill="x", padx=20, pady=(0, 12))
        self.sim_entry = ctk.CTkEntry(
            test_bar, placeholder_text="Simulate spoken sentence...",
            height=34, corner_radius=8, fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text, font=self.f_body
        )
        self.sim_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            test_bar, text="Test", width=64, height=34, corner_radius=8,
            fg_color=self.c_subtle, hover_color=self.c_border, text_color=self.c_text, font=self.f_h3,
            command=self._simulate_speech
        ).pack(side="right")

        # Bottom Auto-Notes Summary Footer
        note_footer = ctk.CTkFrame(left_card, fg_color="transparent")
        note_footer.pack(fill="x", padx=20, pady=(0, 16))

        nf_top = ctk.CTkFrame(note_footer, fg_color="transparent")
        nf_top.pack(fill="x")
        ctk.CTkLabel(nf_top, text="Auto notes", font=self.f_small, text_color=self.c_muted).pack(side="left")

        ctk.CTkButton(
            nf_top, text="Save Notes", width=92, height=26, corner_radius=7,
            fg_color=self.c_pill_bg, hover_color=self.c_border, text_color=self.c_pill_txt, font=self.f_small,
            command=self._save_session_to_archive
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            nf_top, text="Clear", width=64, height=26, corner_radius=7,
            fg_color="transparent", hover_color=self.c_subtle, border_width=1, border_color=self.c_border,
            text_color=self.c_muted, font=self.f_small,
            command=self._clear_session
        ).pack(side="right")

        self.auto_notes_lbl = ctk.CTkLabel(
            note_footer, text="Listening for lecture speech...",
            font=self.f_body, text_color=self.c_text, justify="left", wraplength=540
        )
        self.auto_notes_lbl.pack(anchor="w", pady=(6, 0))

        # RIGHT COLUMN: Alerts Card + Focus Notes Card
        right_col = ctk.CTkFrame(cols, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.grid_rowconfigure(0, weight=1)
        right_col.grid_rowconfigure(1, weight=1)
        right_col.grid_columnconfigure(0, weight=1)

        # Top Right Card: Alerts
        alerts_card = ctk.CTkFrame(right_col, fg_color=self.c_card, border_width=1, border_color=self.c_border, corner_radius=16)
        alerts_card.grid(row=0, column=0, sticky="nsew", pady=(0, 14))

        al_head = ctk.CTkFrame(alerts_card, fg_color="transparent")
        al_head.pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(al_head, text="Alerts", font=self.f_h2, text_color=self.c_text).pack(side="left")
        self.alert_count_pill = ctk.CTkLabel(
            al_head, text="0 new", fg_color=self.c_amber_bg, text_color=self.c_amber_txt,
            corner_radius=10, font=self.f_small, padx=10, pady=2
        )
        self.alert_count_pill.pack(side="right")

        self.alerts_scroll = ctk.CTkScrollableFrame(alerts_card, fg_color="transparent")
        self.alerts_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Bottom Right Card: Focus Notes
        focus_card = ctk.CTkFrame(right_col, fg_color=self.c_card, border_width=1, border_color=self.c_border, corner_radius=16)
        focus_card.grid(row=1, column=0, sticky="nsew")

        fc_head = ctk.CTkFrame(focus_card, fg_color="transparent")
        fc_head.pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(fc_head, text="Focus notes", font=self.f_h2, text_color=self.c_text).pack(side="left")
        ctk.CTkLabel(fc_head, text="Synced with mobile", font=self.f_small, text_color=self.c_muted).pack(side="right")

        self.session_title_entry = ctk.CTkEntry(
            focus_card, placeholder_text="Lecture title (auto-generated on save)...",
            height=32, corner_radius=8, fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text, font=self.f_small
        )
        self.session_title_entry.pack(fill="x", padx=18, pady=(0, 8))

        self.focus_box = ctk.CTkTextbox(
            focus_card, fg_color=self.c_bg, border_width=1, border_color=self.c_border,
            corner_radius=10, text_color=self.c_text, font=self.f_body, wrap="word"
        )
        self.focus_box.pack(fill="both", expand=True, padx=18, pady=(0, 16))

    def _render_keyword_pills(self):
        for w in self.kw_strip.winfo_children():
            w.destroy()
        for kw in self.active_triggers[:7]:
            pill = ctk.CTkLabel(
                self.kw_strip, text=kw, fg_color=self.c_pill_bg, text_color=self.c_pill_txt,
                corner_radius=12, font=self.f_small, padx=10, pady=3
            )
            pill.pack(side="left", padx=(0, 6))

    # ==========================================================
    # PAGE 2: TRIGGER KEYWORDS MANAGER
    # ==========================================================
    def _build_keywords_page(self):
        page = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.pages["keywords"] = page

        ctk.CTkLabel(page, text="Trigger Keywords", font=self.f_serif_lg, text_color=self.c_text).pack(anchor="w")
        ctk.CTkLabel(
            page, text="EchoNote monitors system audio for these words and pushes instant alerts to your mobile app.",
            font=self.f_body, text_color=self.c_muted
        ).pack(anchor="w", pady=(2, 18))

        card = ctk.CTkFrame(page, fg_color=self.c_card, border_width=1, border_color=self.c_border, corner_radius=16)
        card.pack(fill="both", expand=True)

        add_row = ctk.CTkFrame(card, fg_color="transparent")
        add_row.pack(fill="x", padx=22, pady=20)

        self.new_kw_entry = ctk.CTkEntry(
            add_row, placeholder_text="Add a keyword or phrase (e.g., surprise quiz, roll call, deadline)...",
            height=38, corner_radius=10, fg_color=self.c_bg, border_color=self.c_border, text_color=self.c_text, font=self.f_body
        )
        self.new_kw_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(
            add_row, text="+ Add Keyword", width=130, height=38, corner_radius=10,
            fg_color=self.c_accent, hover_color=self.c_accent_hover, font=self.f_h3,
            command=self._add_keyword
        ).pack(side="right")

        self.kw_list_scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self.kw_list_scroll.pack(fill="both", expand=True, padx=22, pady=(0, 20))

    def _refresh_triggers_from_server(self):
        if not self.user:
            return
        try:
            res = requests.get(f"{API_BASE}/api/triggers/{self.user['user_id']}", timeout=8).json()
            self.active_triggers = res.get("keywords", [])
            self._render_keyword_pills()
            self._render_keyword_manager_list()
        except Exception:
            pass

    def _render_keyword_manager_list(self):
        for w in self.kw_list_scroll.winfo_children():
            w.destroy()
        for kw in self.active_triggers:
            row = ctk.CTkFrame(self.kw_list_scroll, fg_color=self.c_bg, border_width=1, border_color=self.c_border, corner_radius=10)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=kw, font=self.f_h3, text_color=self.c_text).pack(side="left", padx=14, pady=10)
            ctk.CTkButton(
                row, text="Remove", width=74, height=28, corner_radius=8,
                fg_color="transparent", hover_color=self.c_subtle, text_color="#C2410C", font=self.f_small,
                command=lambda word=kw: self._delete_keyword(word)
            ).pack(side="right", padx=10)

    def _add_keyword(self):
        word = self.new_kw_entry.get().strip()
        if not word or not self.user:
            return
        updated = list(dict.fromkeys(self.active_triggers + [word]))
        try:
            res = requests.post(
                f"{API_BASE}/api/triggers/{self.user['user_id']}",
                json={"keywords": updated},
                timeout=8
            ).json()
            self.active_triggers = res.get("keywords", updated)
            self.new_kw_entry.delete(0, "end")
            self._render_keyword_pills()
            self._render_keyword_manager_list()
        except Exception:
            pass

    def _delete_keyword(self, word: str):
        if not self.user:
            return
        updated = [w for w in self.active_triggers if w != word]
        try:
            res = requests.post(
                f"{API_BASE}/api/triggers/{self.user['user_id']}",
                json={"keywords": updated},
                timeout=8
            ).json()
            self.active_triggers = res.get("keywords", updated)
            self._render_keyword_pills()
            self._render_keyword_manager_list()
        except Exception:
            pass

    # ==========================================================
    # PAGE 3: SAVED NOTES ARCHIVE
    # ==========================================================
    def _build_notes_page(self):
        page = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.pages["notes"] = page

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(head, text="Saved Lecture Notes", font=self.f_serif_lg, text_color=self.c_text).pack(side="left")
        ctk.CTkButton(
            head, text="↻ Refresh", width=90, height=32, corner_radius=8,
            fg_color=self.c_card, hover_color=self.c_subtle, border_width=1, border_color=self.c_border,
            text_color=self.c_text, font=self.f_small, command=self._refresh_saved_notes
        ).pack(side="right")

        self.notes_archive_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self.notes_archive_scroll.pack(fill="both", expand=True)

    def _refresh_saved_notes(self):
        if not self.user:
            return
        for w in self.notes_archive_scroll.winfo_children():
            w.destroy()
        try:
            res = requests.get(f"{API_BASE}/api/notes/{self.user['user_id']}", timeout=8).json()
            notes = res.get("notes", [])
            if not notes:
                ctk.CTkLabel(self.notes_archive_scroll, text="No saved lecture sessions yet.", font=self.f_body, text_color=self.c_muted).pack(pady=30)
                return
            for item in notes:
                card = ctk.CTkFrame(self.notes_archive_scroll, fg_color=self.c_card, border_width=1, border_color=self.c_border, corner_radius=14)
                card.pack(fill="x", pady=6)
                top = ctk.CTkFrame(card, fg_color="transparent")
                top.pack(fill="x", padx=18, pady=(14, 4))
                ctk.CTkLabel(top, text=item.get("title", "Lecture Note"), font=self.f_h2, text_color=self.c_text).pack(side="left")
                created_val = item.get("created_at", "")
                if isinstance(created_val, (int, float)):
                    created_val = datetime.fromtimestamp(created_val).strftime("%Y-%m-%d %H:%M")
                ctk.CTkLabel(top, text=str(created_val), font=self.f_small, text_color=self.c_muted).pack(side="right")
                body_txt = item.get("summary") or item.get("transcript", "")
                ctk.CTkLabel(card, text=body_txt, font=self.f_body, text_color=self.c_text, justify="left", wraplength=820).pack(anchor="w", padx=18, pady=(0, 14))
        except Exception:
            pass

    # ==========================================================
    # AUDIO CAPTURE, TRANSCRIPTION & TWO-STAGE AI SUMMARIZATION
    # ==========================================================
    def toggle_listening(self):
        if not self.is_listening:
            self.is_listening = True
            if not self.session_start:
                self.session_start = time.time()
            self.listen_btn.configure(text="■ Stop Listening", fg_color=self.c_accent, text_color="#FFFFFF")
            threading.Thread(target=self._capture_loopback_audio, daemon=True).start()
        else:
            self.is_listening = False
            self.listen_btn.configure(text="● Start Listening", fg_color=self.c_subtle, text_color=self.c_text)

    def _update_timer(self):
        if self.is_listening and self.session_start:
            elapsed = int(time.time() - self.session_start)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.timer_lbl.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.after(1000, self._update_timer)

    def _capture_loopback_audio(self):
        p = pyaudio.PyAudio()
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            if not default_speakers["isLoopbackDevice"]:
                for loopback in p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break

            rate = int(default_speakers["defaultSampleRate"])
            channels = default_speakers["maxInputChannels"]
            chunk = 1024
            stream = p.open(
                format=pyaudio.paInt16, channels=channels, rate=rate,
                input=True, input_device_index=default_speakers["index"],
                frames_per_buffer=chunk
            )

            frames = []
            record_seconds = 5
            chunks_needed = int(rate / chunk * record_seconds)

            while self.is_listening:
                data = stream.read(chunk, exception_on_overflow=False)
                frames.append(data)

                if len(frames) >= chunks_needed:
                    raw_bytes = b"".join(frames)
                    frames = []
                    audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
                    rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
                    if rms < 110:
                        continue
                    threading.Thread(
                        target=self._transcribe_wav_chunk,
                        args=(raw_bytes, channels, rate),
                        daemon=True
                    ).start()

            stream.stop_stream()
            stream.close()
        except Exception as exc:
            self.after(0, lambda: self.auto_notes_lbl.configure(text=f"Audio device error: {exc}"))
        finally:
            p.terminate()

    def _transcribe_wav_chunk(self, raw_bytes: bytes, channels: int, rate: int):
        if not groq_client:
            return
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(raw_bytes)

            # Guide Whisper's spelling with user's active keywords & English output
            vocab_hint = ", ".join(self.active_triggers) if self.active_triggers else "Areesha, attendance, quiz, assignment, exam, present"
            prompt_text = f"University lecture in English and Urdu/Hindi. Important names and terms: {vocab_hint}."

            with open(tmp_path, "rb") as audio_file:
                res = groq_client.audio.translations.create(
                    file=(os.path.basename(tmp_path), audio_file.read()),
                    model="whisper-large-v3",
                    prompt=prompt_text,
                    response_format="json",
                    temperature=0.0,
                )
            text = res.text.strip()
            hallucinations = {"thank you.", "thanks for watching.", "you", "bye."}
            if text and len(text) > 2 and text.lower() not in hallucinations:
                self.after(0, lambda t=text: self._handle_new_transcript(t))
        except Exception as exc:
            print(f"[Whisper Translation Error]: {exc}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _simulate_speech(self):
        txt = self.sim_entry.get().strip()
        if txt:
            self.sim_entry.delete(0, "end")
            self._handle_new_transcript(txt)

    def _match_trigger_keyword(self, text: str):
        lowered = text.lower()
        words = re.findall(r"[a-z0-9]+", lowered)
        for kw in self.active_triggers:
            kw_clean = kw.strip().lower()
            if not kw_clean:
                continue
            # 1. Exact word or phrase match
            if re.search(rf"\b{re.escape(kw_clean)}\b", lowered):
                return kw
            # 2. Phonetic/fuzzy single-word match (catches Adisha/Arisha for Areesha, etc.)
            if " " not in kw_clean and len(kw_clean) >= 4:
                for w in words:
                    if len(w) >= 4 and w[0] == kw_clean[0]:
                        if SequenceMatcher(None, kw_clean, w).ratio() >= 0.78:
                            return kw
        return None

    def _handle_new_transcript(self, text: str):
        stamp = datetime.now().strftime("%H:%M")
        self.transcript_lines.append((stamp, text))
        self.recent_buffer.append(text)

        matched_kw = self._match_trigger_keyword(text)

        row = ctk.CTkFrame(self.transcript_scroll, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text=stamp, font=self.f_small, text_color=self.c_muted, width=42).pack(side="left", anchor="n")
        lbl = ctk.CTkLabel(
            row, text=text, font=self.f_body,
            text_color=self.c_accent if matched_kw else self.c_text,
            justify="left", wraplength=520
        )
        lbl.pack(side="left", fill="x", expand=True)

        if matched_kw:
            now = time.time()
            if now - self.last_alert_cooldown.get(matched_kw.lower(), 0) > 15:
                self.last_alert_cooldown[matched_kw.lower()] = now
                self._trigger_keyword_alert(matched_kw, text, stamp)

        # Stage 1: Distill every 4 sentences with openai/gpt-oss-20b
        if len(self.recent_buffer) >= 4:
            batch = list(self.recent_buffer)
            self.recent_buffer.clear()
            threading.Thread(target=self._summarize_batch_with_groq, args=(batch,), daemon=True).start()

    def _trigger_keyword_alert(self, keyword: str, transcript: str, stamp: str):
        self.alert_history.insert(0, {"keyword": keyword, "transcript": transcript, "time": stamp})
        self.alert_count_pill.configure(text=f"{len(self.alert_history)} new")

        # Play distinct 3-tone ascending alarm chime on laptop speakers
        def play_laptop_alarm():
            try:
                for freq, dur in [(880, 180), (1175, 180), (1568, 320)]:
                    winsound.Beep(freq, dur)
                    time.sleep(0.06)
            except Exception:
                try:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    pass

        threading.Thread(target=play_laptop_alarm, daemon=True).start()

        for w in self.alerts_scroll.winfo_children():
            w.destroy()
        for item in self.alert_history[:12]:
            box = ctk.CTkFrame(self.alerts_scroll, fg_color="transparent")
            box.pack(fill="x", pady=6, padx=6)
            top = ctk.CTkFrame(box, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(top, text=f"Keyword: {item['keyword']}", font=self.f_h3, text_color=self.c_amber_txt).pack(side="left")
            ctk.CTkLabel(top, text=item["time"], font=self.f_small, text_color=self.c_muted).pack(side="right")
            ctk.CTkLabel(box, text=item["transcript"], font=self.f_small, text_color=self.c_muted, justify="left", wraplength=330).pack(anchor="w")

        def push():
            try:
                requests.post(
                    f"{API_BASE}/api/alerts",
                    json={
                        "user_id": self.user["user_id"],
                        "keyword": keyword,
                        "transcript": transcript,
                        "timestamp": time.time(),
                    },
                    timeout=8,
                )
            except Exception:
                pass

        threading.Thread(target=push, daemon=True).start()

    def _summarize_batch_with_groq(self, batch: list[str]):
        if not groq_client:
            self.after(0, lambda: self.auto_notes_lbl.configure(text="Auto-note error: GROQ_API_KEY missing."))
            return
        self.after(0, lambda: self.auto_notes_lbl.configure(text="Distilling recent lecture lines..."))
        try:
            res = groq_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {
                        "role": "system",
                        "content": "Translate any Urdu/mixed speech to clean English and extract 1-2 crisp factual bullet points from these 4 lecture lines. Output only the bullet points, no preamble.",
                    },
                    {"role": "user", "content": "\n".join(batch)},
                ],
                temperature=0.2,
                max_completion_tokens=600,
                reasoning_effort="low",
            )
            note_text = (res.choices[0].message.content or "").strip()
            if note_text:
                self.session_notes.append(note_text)
                combined = "\n".join(self.session_notes[-2:])
                self.after(0, lambda: self.auto_notes_lbl.configure(text=combined))
                self.after(0, lambda: self.focus_box.insert("end", f"\n[Auto Note]:\n{note_text}\n\n"))
            else:
                self.after(0, lambda: self.auto_notes_lbl.configure(text="Model returned empty summary—retrying on next batch."))
        except Exception as exc:
            err_msg = str(exc)
            print(f"[Groq Auto-Note Error]: {err_msg}")
            self.after(0, lambda: self.auto_notes_lbl.configure(text=f"Auto-note error: {err_msg[:80]}"))

    def _auto_generate_title(self, content: str):
        if not groq_client or not content:
            return
        try:
            res = groq_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "Generate a concise 3-5 word academic title for these lecture notes. No quotes."},
                    {"role": "user", "content": content},
                ],
                temperature=0.3,
                max_completion_tokens=200,
                reasoning_effort="low",
            )
            title = (res.choices[0].message.content or "").strip().strip('"')
            if title:
                self.generated_title = title
                self.after(0, lambda: self.session_title_entry.delete(0, "end"))
                self.after(0, lambda: self.session_title_entry.insert(0, self.generated_title))
        except Exception:
            pass

    def _save_session_to_archive(self):
        if not self.user:
            return

        # Prefer Stage-1 distilled notes from gpt-oss-20b; fall back to raw transcript if < 4 lines
        raw_transcript = "\n".join([f"[{t}] {line}" for t, line in self.transcript_lines]).strip()
        focus_manual = self.focus_box.get("1.0", "end").strip()
        content_to_summarize = (
            "\n".join(self.session_notes).strip()
            if self.session_notes
            else (raw_transcript or focus_manual)
        )

        if not content_to_summarize:
            return

        self.auto_notes_lbl.configure(text="Synthesizing final study guide with GPT-OSS 120B...")

        def worker():
            if not self.session_title_entry.get().strip():
                self._auto_generate_title(content_to_summarize)
            title = self.session_title_entry.get().strip() or self.generated_title or f"Lecture — {datetime.now().strftime('%b %d, %H:%M')}"
            try:
                res = requests.post(
                    f"{API_BASE}/api/notes",
                    json={
                        "user_id": self.user["user_id"],
                        "title": title,
                        "transcript": content_to_summarize,
                        "generate_summary": True,
                    },
                    timeout=25,
                )
                if res.status_code == 200:
                    data = res.json()
                    final_summary = data.get("summary") or content_to_summarize
                    self.after(0, lambda: self.auto_notes_lbl.configure(text="Saved & synthesized to cloud!"))
                    self.after(0, lambda: self.focus_box.delete("1.0", "end"))
                    self.after(0, lambda: self.focus_box.insert("1.0", final_summary))
            except Exception as exc:
                self.after(0, lambda: self.auto_notes_lbl.configure(text=f"Save error: {str(exc)[:70]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_session(self):
        self.transcript_lines.clear()
        self.recent_buffer.clear()
        self.session_notes.clear()
        self.session_start = None
        self.generated_title = ""
        self.timer_lbl.configure(text="00:00:00")
        self.session_title_entry.delete(0, "end")
        self.focus_box.delete("1.0", "end")
        self.auto_notes_lbl.configure(text="Listening for lecture speech...")
        for w in self.transcript_scroll.winfo_children():
            w.destroy()


if __name__ == "__main__":
    app = EchoNoteDesktop()
    app.mainloop()