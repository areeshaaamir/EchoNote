# EchoNote — Real-Time Bilingual Lecture Copilot

**EchoNote** is a cross-platform AI lecture copilot built for students attending live online or recorded classes. It captures system audio directly from Windows, translates mixed **Urdu/Hindi and English** speech into live English transcripts, triggers instant multi-device alerts when high-stakes keywords (like your name, *attendance*, *quiz*, or *deadline*) are spoken, and distills lectures into structured study guides via a two-stage LLM pipeline.

---

## Live Cloud Infrastructure & Quick Downloads

* **Live Serverless Backend (Cloudflare Workers):** `https://echonote-api.echonoteapp.workers.dev`
* **Prebuilt Releases (Windows `.exe` & Android `.apk`):** Download the latest ready-to-run builds from the [**GitHub Releases**](../../releases) tab, no local Python or Node.js setup required.

---

## Key Features

* **Zero-Config System Audio Capture (WASAPI Loopback):** Records lecture audio directly from Windows output devices (`PyAudioWPatch`) without needing virtual audio cables or microphone routing.
* **Bilingual Speech-to-English Translation:** Uses Groq's `whisper-large-v3` audio translation endpoint with custom vocabulary prompting so Urdu, Hindi, and code-switched English lectures transcribe cleanly in English.
* **Phonetic & Exact Keyword Detection:** Matches user-defined trigger keywords in real time using both regex word-boundary checks and `difflib.SequenceMatcher` phonetic similarity (catching transcription variants of South Asian names like *Areesha* / *Arisha* / *Adisha*).
* **Cross-Device Instant Alarms:**
  * **Windows Desktop:** Plays a 3-tone ascending alert chime (`winsound`) and logs the timestamped snippet.
  * **Android Companion App:** Syncs live via Firebase Realtime Database and fires high-priority heads-up notifications with vibration patterns even when the app is in the background.
* **Two-Stage AI Summarization Pipeline:**
  1. **Stage 1 — Real-Time Distillation (`openai/gpt-oss-20b`):** Processes every 4 spoken sentences into crisp English bullet points in the live **Auto notes** feed.
  2. **Stage 2 — Final Study Synthesis (`openai/gpt-oss-120b`):** On session save, deduplicates and structures the running notes into **Key Concepts**, **Deadlines/Action Items**, and **Likely Exam Questions**.
* **Cloud Sync & Authentication:** Supports Email/Password accounts and **Continue with Google (OAuth 2.0)**, keeping trigger keywords and saved study guides synced between Windows and Android.

---

## System Architecture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                        Windows Desktop Copilot                          │
│  WASAPI Loopback Audio ─► Groq Whisper-Large-V3 (English Translation)   │
│         │                                                               │
│         ├──► Keyword & Phonetic Matcher ──► Laptop Chime (winsound)     │
│         │                               └──► POST /api/alerts           │
│         └──► Stage-1 Live Notes (gpt-oss-20b every 4 sentences)         │
│                                         └──► POST /api/notes            │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        │ HTTPS / JSON
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                 Cloudflare Workers API (src/worker.py)                  │
│  • Google OAuth 2.0 & Email/Password Auth                               │
│  • Trigger Keyword & Alert Broadcasting                                 │
│  • Stage-2 Study Guide Synthesis (openai/gpt-oss-120b)                  │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        │ REST / Realtime Sync
                                        ▼
┌───────────────────────────────────────┴─────────────────────────────────┐
│                       Firebase Realtime Database                        │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        │ Live Polling / Sync
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Android Companion App (Expo / RN)                    │
│  • Away Mode Toggle & High-Priority Notification Channel                │
│  • Live Keyword Alert Feed & Synced Study Guide Archive                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Desktop Client | Python 3.12, CustomTkinter, PyAudioWPatch, NumPy, Pillow, PyInstaller |
| Mobile Client | React Native, Expo (`expo-notifications`), AsyncStorage |
| Serverless Backend | Cloudflare Workers (Python Workers Runtime), Wrangler CLI |
| Database & Sync | Firebase Realtime Database |
| AI & Speech Models | Groq API (`whisper-large-v3`, `openai/gpt-oss-20b`, `openai/gpt-oss-120b`) |

---

## Project Structure

```text
EchoNote/
├── src/
│   └── worker.py           # Cloudflare Workers serverless API & Google OAuth handler
├── mobile-app/             # Expo / React Native Android companion app
├── windows_app.py          # Windows desktop application (UI, audio capture, Stage-1 AI)
├── app_logo.ico            # Windows executable icon
├── app_logo.jpg            # Application branding asset
├── wrangler.toml           # Cloudflare Workers deployment configuration
├── pyproject.toml          # Python Worker dependencies
├── requirements.txt        # Desktop Python dependencies
└── README.md               # Project documentation
```

---

## Local Setup & Development

### 1. Prerequisites

* Windows 10/11 (for WASAPI system audio loopback capture)
* Python 3.11 or 3.12
* A free [Groq API Key](https://console.groq.com/keys)

### 2. Run the Windows Desktop App from Source

```powershell
# Clone the repository
git clone https://github.com/areeshaaamir/EchoNote
cd EchoNote

# Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

Create a `.env` file in the root directory:

```env
GROQ_API_KEY=gsk_your_groq_api_key_here
ECHONOTE_API_BASE=https://echonote-api.echonoteapp.workers.dev
```

Launch the desktop app:

```powershell
python windows_app.py
```

### 3. Build Standalone Windows Executable (`EchoNote.exe`)

```powershell
.\venv\Scripts\pyinstaller.exe --noconsole --onefile --name "EchoNote" --icon "app_logo.ico" --add-data "app_logo.jpg;." --add-data ".env;." --collect-all customtkinter windows_app.py
```

The compiled executable will be generated at `dist/EchoNote.exe`.

### 4. Deploy Cloudflare Workers Backend (Optional — Already Hosted)

If deploying your own backend instance, configure your secrets in Cloudflare and deploy via Wrangler:

```powershell
npx wrangler secret put GROQ_API_KEY
npx wrangler secret put FIREBASE_DB_URL
npx wrangler secret put FIREBASE_DB_SECRET
npx wrangler secret put GOOGLE_CLIENT_ID
npx wrangler secret put GOOGLE_CLIENT_SECRET
npx wrangler deploy
```

---

## API Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/signup` | Register a new user with default academic trigger keywords |
| `POST` | `/api/login` | Authenticate user via email and SHA-256 hashed password |
| `GET` | `/auth/google/login` | Initiate Google OAuth 2.0 browser sign-in flow |
| `GET` | `/auth/google/poll/{state}` | Poll OAuth completion state for desktop/mobile clients |
| `GET` / `POST` | `/api/triggers/{user_id}` | Fetch or update synced trigger keywords |
| `POST` | `/api/alerts` | Broadcast a detected keyword alert to Firebase for mobile push |
| `GET` / `POST` | `/api/notes/{user_id}` | Synthesize notes via `gpt-oss-120b` and sync saved lecture archives |