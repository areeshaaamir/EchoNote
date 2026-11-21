import hashlib
import json
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlparse
from workers import Response, WorkerEntrypoint, fetch

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _json_response(data, status=200):
    return Response(
        json.dumps(data),
        status=status,
        headers={**CORS_HEADERS, "Content-Type": "application/json"},
    )


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _user_key(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()


async def _fb_request(env, path: str, method: str = "GET", payload=None):
    # Strip accidental quotes or whitespace from secret
    base = str(env.FIREBASE_DB_URL).strip().strip('"').strip("'").rstrip("/")
    secret = str(getattr(env, "FIREBASE_DB_SECRET", "")).strip().strip('"').strip("'")
    auth_q = f"?auth={secret}" if secret else ""
    url = f"{base}/{path.lstrip('/')}.json{auth_q}"

    opts = {
        "method": method,
        "headers": {"Content-Type": "application/json"},
    }
    if payload is not None:
        opts["body"] = json.dumps(payload)

    resp = await fetch(url, **opts)
    raw = await resp.text()
    return json.loads(raw) if raw else None


async def _summarize_with_groq(env, transcript: str) -> str:
    groq_key = str(getattr(env, "GROQ_API_KEY", "")).strip().strip('"').strip("'")
    if not groq_key or not transcript.strip():
        return ""
    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an academic study assistant. Take these raw running lecture notes, "
                    "remove duplicates, and organize them into a clean, structured summary with "
                    "Key Concepts, Deadlines/Action Items, and Likely Exam Questions."
                ),
            },
            {"role": "user", "content": transcript},
        ],
        "temperature": 0.2,
        "max_tokens": 1000,
        "reasoning_effort": "low",
    }
    try:
        resp = await fetch(
            "https://api.groq.com/openai/v1/chat/completions",
            method="POST",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            },
            body=json.dumps(payload),
        )
        if resp.status == 200:
            data = json.loads(await resp.text())
            return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        pass
    return ""

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if request.method == "OPTIONS":
            return Response("", status=204, headers=CORS_HEADERS)

        parsed = urlparse(request.url)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        method = request.method.upper()
        origin = f"{parsed.scheme}://{parsed.netloc}"

        try:
            # GET / or /docs
            if method == "GET" and path in ("/", "/docs"):
                html = """
                <!DOCTYPE html>
                <html lang="en">
                <head>
                  <meta charset="UTF-8" />
                  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                  <title>EchoNote — Live Cloud Backend</title>
                  <style>
                    body { font-family: system-ui, sans-serif; background: #F6F4EF; color: #14211D; margin: 0; padding: 40px 20px; }
                    .card { max-width: 680px; margin: auto; background: #FFF; border: 1px solid #E5E2DC; border-radius: 16px; padding: 32px; }
                    .badge { display: inline-block; background: #1D4E43; color: #FFF; padding: 6px 12px; border-radius: 20px; font-size: 12px; }
                    code { background: #F1EFEA; padding: 2px 6px; border-radius: 4px; }
                  </style>
                </head>
                <body>
                  <div class="card">
                    <span class="badge">Cloudflare Workers + Firebase Realtime Sync Active</span>
                    <h1>EchoNote Lecture Copilot API</h1>
                    <p>Status: <strong>Online</strong>. Active endpoints:</p>
                    <ul>
                      <li><code>POST /api/signup</code> & <code>POST /api/login</code></li>
                      <li><code>GET /auth/google/login</code> (Google OAuth)</li>
                      <li><code>GET / POST /api/triggers/{user_id}</code></li>
                      <li><code>POST /api/alerts</code> (Instant Firebase push to Android)</li>
                      <li><code>GET / POST /api/notes/{user_id}</code> (Groq AI summaries)</li>
                    </ul>
                  </div>
                </body>
                </html>
                """
                return Response(html, headers={**CORS_HEADERS, "Content-Type": "text/html; charset=utf-8"})

            # --- GOOGLE OAUTH FLOW ---
            if method == "GET" and path == "/auth/google/login":
                state = qs.get("state", [str(uuid.uuid4())])[0]
                client_id = str(getattr(self.env, "GOOGLE_CLIENT_ID", "")).strip().strip('"')
                if not client_id:
                    return Response("GOOGLE_CLIENT_ID is not configured on Cloudflare.", status=500)
                redirect_uri = f"{origin}/auth/google/callback"
                params = urlencode({
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": state,
                    "prompt": "select_account",
                })
                return Response("", status=302, headers={"Location": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"})

            if method == "GET" and path == "/auth/google/callback":
                code = qs.get("code", [""])[0]
                state = qs.get("state", [""])[0]
                client_id = str(getattr(self.env, "GOOGLE_CLIENT_ID", "")).strip().strip('"')
                client_secret = str(getattr(self.env, "GOOGLE_CLIENT_SECRET", "")).strip().strip('"')
                redirect_uri = f"{origin}/auth/google/callback"

                token_resp = await fetch(
                    "https://oauth2.googleapis.com/token",
                    method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    body=urlencode({
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    }),
                )
                token_data = json.loads(await token_resp.text())
                access_token = token_data.get("access_token")
                if not access_token:
                    return Response(f"Google OAuth failed: {token_data}", status=400)

                profile_resp = await fetch(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                profile = json.loads(await profile_resp.text())
                email = profile.get("email", "").strip().lower()
                name = profile.get("name") or email.split("@")[0]
                uid = _user_key(email)

                user_doc = await _fb_request(self.env, f"users/{uid}", "GET")
                if not user_doc:
                    user_doc = {
                        "user_id": uid,
                        "email": email,
                        "name": name,
                        "keywords": [name.split()[0], "attendance", "quiz", "assignment", "exam"],
                    }
                    await _fb_request(self.env, f"users/{uid}", "PUT", user_doc)

                await _fb_request(self.env, f"oauth_states/{state}", "PUT", {
                    "authenticated": True,
                    "user": {
                        "user_id": uid,
                        "email": user_doc["email"],
                        "name": user_doc.get("name", name),
                        "keywords": user_doc.get("keywords", []),
                    },
                })

                return Response(
                    "<html><body style='font-family:sans-serif;text-align:center;padding:50px;'><h2>Signed in to EchoNote!</h2><p>You can close this browser tab and return to the app.</p></body></html>",
                    headers={"Content-Type": "text/html"},
                )

            if method == "GET" and path.startswith("/auth/google/poll/"):
                state = path.split("/auth/google/poll/", 1)[1]
                record = await _fb_request(self.env, f"oauth_states/{state}", "GET")
                if record and record.get("authenticated"):
                    return _json_response(record)
                return _json_response({"authenticated": False})

            # Parse JSON body for POST routes
            body = {}
            if method == "POST":
                raw_body = await request.text()
                body = json.loads(raw_body) if raw_body else {}

            # POST /api/signup
            if method == "POST" and path == "/api/signup":
                email = body.get("email", "").strip().lower()
                password = body.get("password", "")
                name = body.get("name") or "Student"
                if not email or not password:
                    return _json_response({"detail": "Email and password required"}, 400)

                uid = _user_key(email)
                existing = await _fb_request(self.env, f"users/{uid}", "GET")
                if existing is not None:
                    return _json_response({"detail": "Account already exists"}, 400)

                user_doc = {
                    "user_id": uid,
                    "email": email,
                    "name": name,
                    "password_hash": _hash_pw(password),
                    "keywords": [name.split()[0], "attendance", "quiz", "assignment", "exam"],
                }
                await _fb_request(self.env, f"users/{uid}", "PUT", user_doc)
                return _json_response({
                    "user_id": uid,
                    "email": email,
                    "name": name,
                    "keywords": user_doc["keywords"],
                })

            # POST /api/login
            if method == "POST" and path == "/api/login":
                email = body.get("email", "").strip().lower()
                password = body.get("password", "")
                uid = _user_key(email)
                user_doc = await _fb_request(self.env, f"users/{uid}", "GET")
                if not user_doc or user_doc.get("password_hash") != _hash_pw(password):
                    return _json_response({"detail": "Invalid email or password"}, 401)
                return _json_response({
                    "user_id": uid,
                    "email": user_doc["email"],
                    "name": user_doc.get("name", "Student"),
                    "keywords": user_doc.get("keywords", []),
                })

            # GET or POST /api/triggers/{user_id}
            if path.startswith("/api/triggers/"):
                user_id = path.split("/api/triggers/", 1)[1]
                if method == "GET":
                    kws = await _fb_request(self.env, f"users/{user_id}/keywords", "GET") or []
                    return _json_response({"keywords": kws})
                if method == "POST":
                    cleaned = [k.strip() for k in body.get("keywords", []) if k.strip()]
                    await _fb_request(self.env, f"users/{user_id}/keywords", "PUT", cleaned)
                    return _json_response({"keywords": cleaned})

            # POST /api/alerts
            if method == "POST" and path == "/api/alerts":
                user_id = body.get("user_id", "")
                alert_data = {
                    "id": str(uuid.uuid4()),
                    "keyword": body.get("keyword", ""),
                    "transcript": body.get("transcript", ""),
                    "timestamp": body.get("timestamp") or time.time(),
                }
                await _fb_request(self.env, f"live_alerts/{user_id}", "PUT", alert_data)
                await _fb_request(self.env, f"alert_history/{user_id}", "POST", alert_data)
                return _json_response({"status": "broadcasted", "alert": alert_data})

            # POST /api/notes
            if method == "POST" and path == "/api/notes":
                user_id = body.get("user_id", "")
                transcript = body.get("transcript", "")
                summary = await _summarize_with_groq(self.env, transcript) if body.get("generate_summary", True) else ""
                note_id = str(uuid.uuid4())
                note_doc = {
                    "id": note_id,
                    "title": body.get("title", "Lecture Note"),
                    "transcript": transcript,
                    "summary": summary,
                    "created_at": time.time(),
                }
                await _fb_request(self.env, f"notes/{user_id}/{note_id}", "PUT", note_doc)
                return _json_response(note_doc)

            # GET /api/notes/{user_id}
            if method == "GET" and path.startswith("/api/notes/"):
                user_id = path.split("/api/notes/", 1)[1]
                raw = await _fb_request(self.env, f"notes/{user_id}", "GET") or {}
                notes = sorted(raw.values(), key=lambda x: x.get("created_at", 0), reverse=True)
                return _json_response({"notes": notes})

            return _json_response({"detail": "Not Found"}, 404)

        except Exception as exc:
            return _json_response({"detail": str(exc)}, 500)