import os
import re
import json
import hashlib
import sqlite3
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
NGROK_PUBLIC_URL = os.getenv("NGROK_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")

DB_PATH = "app.db"
DEFAULT_TRIGGERS = ["attendance", "quiz", "assignment", "deadline", "exam", "submit"]

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

app = FastAPI(title="EchoNote API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================
# DATABASE INITIALIZATION (SQLite: app.db)
# ==========================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            UNIQUE(user_id, word)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


# ==========================================================
# PYDANTIC SCHEMAS
# ==========================================================
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TriggerRequest(BaseModel):
    user_id: int
    word: str


class SaveNoteRequest(BaseModel):
    user_id: int
    title: Optional[str] = ""
    content: str


class GenerateTitleRequest(BaseModel):
    content: str


# ==========================================================
# AUTHENTICATION & GOOGLE OAUTH ROUTES
# ==========================================================
pending_oauth_sessions: dict[str, dict] = {}


@app.post("/api/signup")
def signup(req: SignupRequest):
    email = req.email.strip().lower()
    name = req.name.strip()
    if not name or not email or not req.password:
        raise HTTPException(status_code=400, detail="All fields are required.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, hash_password(req.password)),
        )
        uid = c.lastrowid
        first_name = name.split()[0].lower()
        for w in list(dict.fromkeys([first_name] + DEFAULT_TRIGGERS)):
            c.execute("INSERT OR IGNORE INTO triggers (user_id, word) VALUES (?, ?)", (uid, w))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Email is already registered.")
    conn.close()
    return {"user_id": uid, "name": name, "email": email}


@app.post("/api/login")
def login(req: LoginRequest):
    email = req.email.strip().lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, name, email FROM users WHERE email = ? AND password_hash = ?",
        (email, hash_password(req.password)),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {"user_id": row[0], "name": row[1], "email": row[2]}


@app.get("/auth/google/login")
def google_login(state: str, local: bool = False):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID is missing in .env")
    base = "http://127.0.0.1:8000" if local else NGROK_PUBLIC_URL
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{base}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": f"{'local' if local else 'ngrok'}:{state}",
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@app.get("/auth/google/callback")
async def google_callback(code: str, state: str):
    mode, clean_state = state.split(":", 1) if ":" in state else ("ngrok", state)
    base = "http://127.0.0.1:8000" if mode == "local" else NGROK_PUBLIC_URL

    token_data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{base}/auth/google/callback",
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        token_res = await client.post("https://oauth2.googleapis.com/token", data=token_data)
        access_token = token_res.json().get("access_token")
        if not access_token:
            return HTMLResponse(
                "<h3>Google sign-in failed. Check Authorized Redirect URIs in Google Cloud Console.</h3>",
                status_code=400,
            )

        profile_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile = profile_res.json()

    email = profile.get("email", "").lower()
    name = profile.get("name") or email.split("@")[0]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, email FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    if row:
        user_obj = {"user_id": row[0], "name": row[1], "email": row[2]}
    else:
        c.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, "GOOGLE_OAUTH_USER"),
        )
        uid = c.lastrowid
        first_name = name.split()[0].lower()
        for w in list(dict.fromkeys([first_name] + DEFAULT_TRIGGERS)):
            c.execute("INSERT OR IGNORE INTO triggers (user_id, word) VALUES (?, ?)", (uid, w))
        conn.commit()
        user_obj = {"user_id": uid, "name": name, "email": email}
    conn.close()

    pending_oauth_sessions[clean_state] = user_obj

    return HTMLResponse("""
    <html>
      <body style="font-family: 'Segoe UI', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #F6F4EF; color: #18201D; margin: 0;">
        <div style="background: #FFFFFF; padding: 36px; border-radius: 16px; border: 1px solid #E5E2DC; text-align: center; max-width: 380px;">
          <div style="width: 32px; height: 32px; border-radius: 8px; background: #79B8A8; margin: 0 auto 14px;"></div>
          <h2 style="margin: 0 0 8px;">Signed in to EchoNote</h2>
          <p style="color: #6E7774; font-size: 14px; margin: 0;">You can close this tab and return to the EchoNote app.</p>
        </div>
      </body>
    </html>
    """)


@app.get("/auth/google/poll/{state}")
def poll_google_login(state: str):
    user_obj = pending_oauth_sessions.pop(state, None)
    if user_obj:
        return {"authenticated": True, "user": user_obj}
    return {"authenticated": False}


# ==========================================================
# TRIGGER KEYWORDS API
# ==========================================================
def get_user_triggers(user_id: int) -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT word FROM triggers WHERE user_id = ? ORDER BY id ASC", (user_id,))
    words = [r[0] for r in c.fetchall()]
    conn.close()
    return words


@app.get("/api/triggers/{user_id}")
def list_triggers(user_id: int):
    return {"triggers": get_user_triggers(user_id)}


@app.post("/api/triggers")
def add_trigger(req: TriggerRequest):
    word = req.word.strip().lower()
    if not word:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO triggers (user_id, word) VALUES (?, ?)", (req.user_id, word))
    conn.commit()
    conn.close()
    return {"triggers": get_user_triggers(req.user_id)}


@app.delete("/api/triggers/{user_id}/{word}")
def delete_trigger(user_id: int, word: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM triggers WHERE user_id = ? AND word = ?", (user_id, word.strip().lower()))
    conn.commit()
    conn.close()
    return {"triggers": get_user_triggers(user_id)}


# ==========================================================
# SAVED NOTES & AI TITLE GENERATION API
# ==========================================================
transcript_buffers: dict[int, List[str]] = {}


def generate_smart_title(content: str) -> str:
    if not groq_client or not content.strip():
        return f"Lecture Notes ({datetime.now().strftime('%d %b %H:%M')})"
    try:
        res = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate a concise, descriptive 3 to 6 word academic title for these lecture notes. "
                        "Return ONLY the plain title text without quotes, markdown, or prefixes."
                    ),
                },
                {"role": "user", "content": content[:2500]},
            ],
            temperature=0.2,
            max_tokens=24,
        )
        title = res.choices[0].message.content.strip().strip('"').strip("'")
        return title or f"Lecture Notes ({datetime.now().strftime('%d %b')})"
    except Exception:
        return f"Lecture Notes ({datetime.now().strftime('%d %b %H:%M')})"


@app.post("/api/notes/reset-buffer")
def reset_note_buffer(user_id: Optional[int] = None):
    if user_id is not None:
        transcript_buffers[user_id] = []
    else:
        transcript_buffers.clear()
    return {"status": "reset"}


@app.post("/api/notes/generate-title")
def api_generate_title(req: GenerateTitleRequest):
    return {"title": generate_smart_title(req.content)}


@app.post("/api/notes/save")
def save_note(req: SaveNoteRequest):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Cannot save empty notes.")
    final_title = req.title.strip() if req.title and req.title.strip() else generate_smart_title(req.content)
    created_at = datetime.now().strftime("%d %b %Y, %I:%M %p")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO notes (user_id, title, content, created_at) VALUES (?, ?, ?, ?)",
        (req.user_id, final_title, req.content.strip(), created_at),
    )
    conn.commit()
    conn.close()
    return {"status": "saved", "title": final_title, "created_at": created_at}


@app.get("/api/notes/{user_id}")
def get_notes(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, title, content, created_at FROM notes WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    )
    notes = [
        {"id": r[0], "title": r[1], "content": r[2], "created_at": r[3]}
        for r in c.fetchall()
    ]
    conn.close()
    return {"notes": notes}


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


# ==========================================================
# GROQ INTENT & BILINGUAL AUTO-NOTES HELPERS
# ==========================================================
def analyze_trigger_intent(text: str, triggers: List[str]) -> Optional[dict]:
    matched = [w for w in triggers if re.search(rf"\b{re.escape(w)}\b", text, re.I)]
    if not matched:
        return None

    matched_label = matched[0].upper()
    if not groq_client:
        return {
            "trigger_detected": True,
            "event_type": matched_label,
            "summary": f"Keyword '{matched[0]}' mentioned: {text}",
            "original_text": text,
        }

    try:
        res = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You monitor university lectures (in English, Urdu, or Roman Urdu). "
                        "A student's trigger keyword was detected. Summarize the actionable announcement in 1 crisp English sentence. "
                        'Respond ONLY as JSON: {"event_type": "SHORT_CATEGORY", "summary": "1-sentence English alert"}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"Matched keywords: {matched}. Spoken text: {text}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=90,
        )
        parsed = json.loads(res.choices[0].message.content)
        return {
            "trigger_detected": True,
            "event_type": parsed.get("event_type", matched_label),
            "summary": parsed.get("summary", text),
            "original_text": text,
        }
    except Exception:
        return {
            "trigger_detected": True,
            "event_type": matched_label,
            "summary": text,
            "original_text": text,
        }


def summarize_chunk_to_english_notes(lines: List[str]) -> List[str]:
    joined = " ".join(lines)
    if not groq_client:
        return [joined]
    try:
        res = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Convert these university lecture transcript lines (which may be in English, Urdu, or mixed Urdu-English) "
                        "into 1 to 2 concise, high-value English study bullet points. Ignore filler chatter. "
                        'Return ONLY JSON: {"notes": ["bullet 1", "bullet 2"]}'
                    ),
                },
                {"role": "user", "content": joined},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=160,
        )
        parsed = json.loads(res.choices[0].message.content)
        return [n.strip() for n in parsed.get("notes", []) if n.strip()]
    except Exception:
        return [joined]


# ==========================================================
# PER-USER WEBSOCKET STREAM (Desktop -> Backend -> Same User's Mobile)
# ==========================================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[tuple[int, WebSocket]] = []

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append((user_id, websocket))

    def disconnect(self, websocket: WebSocket):
        self.active_connections = [
            (uid, ws) for uid, ws in self.active_connections if ws != websocket
        ]

    async def send_to_user(self, user_id: int, message: dict):
        for uid, connection in list(self.active_connections):
            if uid == user_id:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass


manager = ConnectionManager()


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket, user_id: int = 1):
    await manager.connect(user_id, websocket)
    transcript_buffers.setdefault(user_id, [])

    try:
        while True:
            data = await websocket.receive_text()
            cleaned = data.strip()
            if not cleaned:
                continue

            print(f"[Transcript | User {user_id}]: {cleaned}")

            # 1. Echo live transcript only to this user's connected desktop & mobile devices
            await manager.send_to_user(user_id, {
                "type": "TRANSCRIPT",
                "text": cleaned,
                "timestamp": datetime.now().strftime("%H:%M"),
            })

            # 2. Check user's custom + default trigger keywords
            user_triggers = get_user_triggers(user_id)
            alert_payload = analyze_trigger_intent(cleaned, user_triggers)
            if alert_payload:
                await manager.send_to_user(user_id, alert_payload)

            # 3. Accumulate every 4 lines into bilingual -> English auto-notes
            buf = transcript_buffers.setdefault(user_id, [])
            buf.append(cleaned)
            if len(buf) >= 4:
                chunk = buf[:4]
                transcript_buffers[user_id] = buf[4:]
                notes = summarize_chunk_to_english_notes(chunk)
                if notes:
                    await manager.send_to_user(user_id, {
                        "type": "MEETING_NOTE",
                        "notes": notes,
                    })

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)