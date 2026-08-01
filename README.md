# AI Innovation Mentor

A Flask application that pairs users with an AI mentor — **Aria** — to guide them through every stage of building an AI-powered product.

## Features
| Feature | Details |
|---|---|
| User auth | Register / login / logout via Flask-Login |
| Sessions | Create named innovation sessions, delete them from the dashboard |
| Stage-aware AI | Aria adapts her advice across **Ideation → Prototype → Scale** |
| Chat history | All messages persisted in SQLite (switchable to Postgres) |
| REST endpoints | JSON API for sending messages & switching stages |

---

## Quick Start

```bash
# 1. Create & activate a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env       # Windows
# cp .env.example .env       # macOS / Linux
# → edit .env and add your OPENAI_API_KEY

# 4. Initialise the database
flask --app app db init
flask --app app db migrate -m "initial"
flask --app app db upgrade

# 5. Run
flask --app app run --debug
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## Project Structure

```
ai_mentor/
├── app.py                  # Application factory
├── config.py               # Config classes (dev / prod / test)
├── extensions.py           # SQLAlchemy, Login, Migrate instances
├── models.py               # User, MentorSession, Message
├── user_loader.py          # Flask-Login user loader
├── requirements.txt
├── .env.example
│
├── routes/
│   ├── auth.py             # /auth  — register, login, logout
│   ├── dashboard.py        # /dashboard — session list & CRUD
│   └── mentor.py           # /mentor — chat + JSON API
│
├── services/
│   └── ai_service.py       # OpenAI wrapper with stage-aware prompts
│
├── templates/
│   ├── base.html           # Shared layout
│   ├── auth/
│   │   ├── login.html
│   │   └── register.html
│   ├── dashboard/
│   │   └── index.html
│   └── mentor/
│       └── chat.html
│
└── static/
    ├── css/main.css
    └── js/
        ├── main.js         # Shared utilities
        └── chat.js         # Chat UI & stage switcher
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/mentor/chat/<id>/send` | Send a message; returns `{user_message, assistant_message}` |
| `POST` | `/mentor/chat/<id>/stage` | Change the stage; body: `{"stage": "ideation"}` |

---

## Extending

- **Swap the LLM** — update `AIService.get_response()` in [`services/ai_service.py`](services/ai_service.py) to point at any OpenAI-compatible endpoint.
- **Add a new stage** — add to `STAGE_HINTS` in `ai_service.py` and the `<select>` in [`templates/dashboard/index.html`](templates/dashboard/index.html).
- **Switch to Postgres** — set `DATABASE_URL=postgresql://...` in `.env`.
