import os
import json
import re
import sqlite3
import hashlib
import asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
from PIL import Image

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing from .env file!")

groq_client = Groq(api_key=GROQ_API_KEY)
DB_PATH = "app.db"

DEFAULT_TRIGGERS = [
    "areesha", "attendance", "hazri", "haazri", "quiz", "assignment",
    "test", "present", "roll number", "submit", "deadline", "paper",
    "tayari", "marks", "kaun kaun", "sun rahe ho"
]


def get_active_groq_model() -> str:
    try:
        available = [
            m.id for m in groq_client.models.list().data
            if "whisper" not in m.id.lower()
            and "guard" not in m.id.lower()
            and "tts" not in m.id.lower()
            and "orpheus" not in m.id.lower()
        ]
        preferred = [
            "llama-3.3-70b-versatile",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "gemma2-9b-it",
        ]
        for model in preferred:
            if model in available:
                print(f"[✓] Selected Groq Model: {model}")
                return model
        if available:
            return available[0]
    except Exception as e:
        print(f"[!] Could not list Groq models: {e}")
    return "llama-3.3-70b-versatile"


FAST_MODEL = get_active_groq_model()


# --- DATABASE SETUP (SQLite) ---
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
            UNIQUE(user_id, word),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS saved_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_user_triggers(user_id: int) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT word FROM triggers WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows if rows else DEFAULT_TRIGGERS


def build_keyword_regex(words: list[str]) -> re.Pattern:
    escaped = [re.escape(w.strip()) for w in words if w.strip()]
    if not escaped:
        return re.compile(r"(?!x)x")
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


# --- FASTAPI APP ---
app = FastAPI(title="EchoNote Backend Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthRequest(BaseModel):
    name: str = ""
    email: str
    password: str


class TriggerRequest(BaseModel):
    user_id: int
    word: str


class SaveNoteRequest(BaseModel):
    user_id: int
    title: str
    content: str


@app.post("/api/signup")
def signup(req: AuthRequest):
    if not req.name.strip() or not req.email.strip() or not req.password.strip():
        raise HTTPException(status_code=400, detail="All fields are required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (req.name.strip(), req.email.strip().lower(), hash_pw(req.password)),
        )
        user_id = c.lastrowid
        # Seed default trigger words + user's first name
        first_name = req.name.strip().split()[0].lower()
        seed_words = list(dict.fromkeys([first_name] + DEFAULT_TRIGGERS))
        for w in seed_words:
            c.execute("INSERT OR IGNORE INTO triggers (user_id, word) VALUES (?, ?)", (user_id, w))
        conn.commit()
        return {"user_id": user_id, "name": req.name.strip(), "email": req.email.strip().lower()}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    finally:
        conn.close()


@app.post("/api/login")
def login(req: AuthRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, name, email FROM users WHERE email = ? AND password_hash = ?",
        (req.email.strip().lower(), hash_pw(req.password)),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {"user_id": row[0], "name": row[1], "email": row[2]}


@app.get("/api/triggers/{user_id}")
def list_triggers(user_id: int):
    return {"triggers": get_user_triggers(user_id)}


@app.post("/api/triggers")
def add_trigger(req: TriggerRequest):
    word = req.word.strip().lower()
    if not word:
        raise HTTPException(status_code=400, detail="Trigger word cannot be empty.")
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
    c.execute("DELETE FROM triggers WHERE user_id = ? AND word = ?", (user_id, word.lower()))
    conn.commit()
    conn.close()
    return {"triggers": get_user_triggers(user_id)}


@app.get("/api/notes/{user_id}")
def get_saved_notes(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, title, content, created_at FROM saved_notes WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    )
    notes = [
        {"id": r[0], "title": r[1], "content": r[2], "created_at": r[3]}
        for r in c.fetchall()
    ]
    conn.close()
    return {"notes": notes}


@app.post("/api/notes/save")
def save_note_session(req: SaveNoteRequest):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Note content is empty.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.now().strftime("%b %d, %Y • %I:%M %p")
    title = req.title.strip() or f"Lecture Notes ({created_at})"
    c.execute(
        "INSERT INTO saved_notes (user_id, title, content, created_at) VALUES (?, ?, ?, ?)",
        (req.user_id, title, req.content.strip(), created_at),
    )
    conn.commit()
    conn.close()
    return {"status": "saved", "title": title, "created_at": created_at}

class TitleRequest(BaseModel):
    content: str


@app.post("/api/notes/generate-title")
def generate_note_title(req: TitleRequest):
    """Uses Groq to generate a concise 3-6 word academic title from the lecture notes."""
    if not req.content.strip():
        return {"title": f"Lecture Notes ({datetime.now().strftime('%b %d, %I:%M %p')})"}
    try:
        completion = groq_client.chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Generate a concise, clear 3 to 6 word title summarizing these lecture notes. Return ONLY the plain title text with no quotes or punctuation."
                },
                {"role": "user", "content": req.content[:1500]},
            ],
            temperature=0.3,
            max_tokens=30,
        )
        title = completion.choices[0].message.content.strip().strip('"').strip("'")
        return {"title": title or "Lecture Summary"}
    except Exception as e:
        print(f"[!] Title Generation Error: {e}")
        return {"title": f"Lecture Notes ({datetime.now().strftime('%b %d, %I:%M %p')})"}


@app.delete("/api/notes/{note_id}")
def delete_saved_note(note_id: int):
    """Deletes a specific saved note session from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM saved_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "note_id": note_id}


@app.post("/api/notes/reset-buffer")
def reset_transcript_buffer():
    """Clears any leftover sentences in the rolling buffer before a new capture starts."""
    global transcript_buffer
    transcript_buffer.clear()
    return {"status": "cleared"}


# --- GROQ & WEBSOCKET ENGINE ---
ALERT_SYSTEM_PROMPT = """
You are a real-time meeting alert classifier for a university student.
Input is live speech in English, Urdu, or mixed Roman Urdu.
Determine if an urgent alert is needed (attendance call, quiz, assignment, direct question, or trigger word match).
Ignore negations (e.g., "no quiz today", "not taking attendance yet").

Respond ONLY in valid JSON:
{
  "trigger_detected": true or false,
  "event_type": "ATTENDANCE" | "ASSIGNMENT" | "QUIZ" | "DIRECT_QUESTION" | "NONE",
  "urgency": "HIGH" | "MEDIUM" | "NONE",
  "original_text": "raw transcript",
  "summary": "1-sentence English summary of what was said"
}
"""

NOTES_SYSTEM_PROMPT = """
You are an academic meeting note-taker. Convert the following raw lecture transcript (which may mix Urdu and English) into concise, clean English study notes.
Extract key concepts, announcements, or action items into 1-3 short bullet points.

Respond ONLY in valid JSON:
{
  "type": "MEETING_NOTE",
  "notes": ["bullet 1", "bullet 2"]
}
"""


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()
transcript_buffer: list[str] = []
BUFFER_FLUSH_THRESHOLD = 4


def classify_intent_groq(transcript: str, trigger_words: list[str]) -> dict:
    try:
        prompt = f"Active Trigger Words: {', '.join(trigger_words)}\nTranscript: \"{transcript}\""
        completion = groq_client.chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {"role": "system", "content": ALERT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=600,
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"[!] Groq Alert Error: {e}")
        return {"trigger_detected": False}


def generate_notes_groq(chunk_text: str) -> dict:
    try:
        completion = groq_client.chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {"role": "system", "content": NOTES_SYSTEM_PROMPT},
                {"role": "user", "content": f"Lecture Segment:\n{chunk_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=600,
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"[!] Groq Notes Error: {e}")
        return {"type": "MEETING_NOTE", "notes": []}


@app.get("/")
def read_root():
    return {"status": "EchoNote Backend Live", "active_model": FAST_MODEL}


@app.websocket("/ws/stream")
async def websocket_stream_endpoint(websocket: WebSocket, user_id: int = 1):
    global transcript_buffer
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[Transcript | User {user_id}]: {data}")
            
            await manager.broadcast({
                "type": "TRANSCRIPT",
                "text": data,
                "timestamp": datetime.now().strftime("%H:%M"),
            })

            # Load latest trigger words dynamically from SQLite
            active_triggers = get_user_triggers(user_id)
            pattern = build_keyword_regex(active_triggers)

            if pattern.search(data):
                await manager.broadcast({
                    "type": "ALERT",
                    "trigger_detected": True,
                    "event_type": "KEYWORD_DETECTED",
                    "urgency": "HIGH",
                    "original_text": data,
                    "summary": "Trigger keyword matched. Verifying context...",
                })

                alert_payload = await asyncio.to_thread(classify_intent_groq, data, active_triggers)
                if alert_payload.get("trigger_detected"):
                    alert_payload["type"] = "ALERT"
                    alert_payload["original_text"] = data
                    await manager.broadcast(alert_payload)

            transcript_buffer.append(data)
            if len(transcript_buffer) >= BUFFER_FLUSH_THRESHOLD:
                combined_text = "\n".join(transcript_buffer)
                transcript_buffer.clear()

                notes_payload = await asyncio.to_thread(generate_notes_groq, combined_text)
                if notes_payload.get("notes"):
                    await manager.broadcast(notes_payload)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[!] WebSocket Error: {e}")
        manager.disconnect(websocket)