# Codebase Research Agent

An AI-powered **codebase research API** built with Django. Submit a Git repository URL and a natural-language question; the service clones the repo, runs a **Gemini** tool-calling agent over the local tree, and returns a structured answer with an auditable trail of tool calls and findings—persisted in **PostgreSQL** (Supabase-compatible).

---

## At a glance

| Layer | Technology |
|--------|------------|
| API & orchestration | Django 6, Django REST Framework |
| Database | PostgreSQL via `DATABASE_URL` (e.g. [Supabase](https://supabase.com)) |
| LLM | Google Gemini (`google-generativeai`) with function calling |
| Repo access | GitPython (shallow clone + pull into `repos/`) |
| Config | `python-dotenv`, `dj-database-url` |

```mermaid
flowchart LR
    Client["HTTP Client"] --> API["Django REST API"]
    API --> DB[(PostgreSQL / Supabase)]
    API --> Git["Git clone / pull"]
    API --> Agent["agent_runner.py"]
    Agent --> Gemini["Gemini API"]
    Agent --> Tools["code_tools + db_tools"]
    Tools --> Disk["Local repo checkout"]
    Agent --> DB
```

---

## How it works (end-to-end)

```mermaid
sequenceDiagram
    participant C as Client
    participant V as POST /api/sessions/
    participant R as repo_utils
    participant A as agent_runner
    participant G as Gemini
    participant T as Tools
    participant D as Database

    C->>V: repo_url + question
    V->>D: Create Repository + ResearchSession (pending)
    V->>R: ensure_local_copy()
    R-->>V: local_path under repos/
    V->>A: run_research_session(id)
    A->>D: status = running
    loop Up to N iterations / 10 tool calls
        A->>G: generate_content + tools
        G-->>A: function_calls or final text
        A->>T: list_files / search_code / read_file / ...
        T-->>A: JSON results (truncated)
        A->>D: ToolCall rows
    end
    A->>D: final_answer, tokens, completed
    V-->>C: 201 + full session JSON
```

**Agent tools (8):**

| Tool | Purpose |
|------|---------|
| `list_files` | Directory listing (capped) |
| `search_code` | Substring / glob search (skips `docs/`, vendor dirs) |
| `read_file` | Numbered snippet (line-capped) |
| `get_file_summary` | Size + head preview |
| `save_finding` | Persist insight for this session |
| `get_previous_findings` | Reuse notes from past runs on same repo |
| `list_past_sessions` | History for the repository |

---

## Project layout

```
codebase-research-agent/
├── agent/
│   ├── agent_runner.py      # Gemini loop, retries, tool cap
│   ├── views.py               # REST endpoints
│   ├── models.py              # Repository, ResearchSession, ToolCall, Finding
│   ├── serializers.py
│   ├── repo_utils.py          # Clone / resolve local path
│   └── tools/
│       ├── code_tools.py      # Read-only repo exploration
│       └── db_tools.py        # Session memory
├── config/                    # Django settings & URLs
├── repos/                     # Cloned repositories (gitignored in prod)
├── manage.py
├── requirements.txt
├── README.md
└── DECISIONS.md
```

---

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Git** on your PATH (for cloning remote repositories)
- **PostgreSQL** connection string **or** SQLite for local-only dev (omit `DATABASE_URL`)
- **Google AI Studio API key** — [Get a Gemini API key](https://aistudio.google.com/apikey)
- Optional: **Supabase** project for hosted Postgres (`DATABASE_URL` from Project Settings → Database)

---

## Setup (step by step)

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url> codebase-research-agent
cd codebase-research-agent
python -m venv venv
```

**Windows (PowerShell):**

```powershell
.\venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file in the project root (never commit secrets):

```env
SECRET_KEY=change-me-to-a-long-random-string
DEBUG=True
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres
GEMINI_API_KEY=your_google_ai_studio_key
REPOS_DIR=repos

# Recommended for free tier / demos
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_MAX_AGENT_ITERATIONS=20
GEMINI_MAX_TOOL_CALLS=10
GEMINI_MAX_TOOL_RESULT_CHARS=8000
GEMINI_MAX_OUTPUT_TOKENS=6144

# Offline demo (no Gemini calls) — set true if quota is exhausted
GEMINI_DEMO_MODE=false
```

For **local SQLite** only, leave `DATABASE_URL` unset; Django falls back to `db.sqlite3`.

### 4. Apply database migrations

```bash
python manage.py migrate
```

### 5. (Optional) Seed sample data

```bash
python manage.py seed_sample_data
```

---

## Run the server

```bash
python manage.py runserver
```

API base URL: **http://127.0.0.1:8000/api/**

Django admin: **http://127.0.0.1:8000/admin/** (create a superuser with `python manage.py createsuperuser` if needed).

> **Note:** `POST /api/sessions/` is **synchronous**—the HTTP request blocks until the agent finishes or fails. Large repos and long questions can take several minutes.

---

## API reference (3 endpoints)

### 1. Start research — `POST /api/sessions/`

Creates a session, clones/updates the repo, runs the agent, returns the completed (or failed) session.

**Body (JSON):**

```json
{
  "repo_url": "https://github.com/tiangolo/fastapi",
  "question": "How does FastAPI handle dependency injection internally?"
}
```

**curl:**

```bash
curl -X POST http://127.0.0.1:8000/api/sessions/ \
  -H "Content-Type: application/json" \
  -d "{\"repo_url\":\"https://github.com/tiangolo/fastapi\",\"question\":\"How does FastAPI handle dependency injection internally?\"}"
```

**PowerShell:**

```powershell
$body = '{"repo_url":"https://github.com/tiangolo/fastapi","question":"How does FastAPI handle dependency injection internally?"}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/sessions/" -Method Post -Body $body -ContentType "application/json"
```

**Response fields (high level):** `id`, `status`, `final_answer`, `error_message`, `input_tokens`, `output_tokens`, `findings[]`, `tool_calls[]`.

```mermaid
stateDiagram-v2
    [*] --> pending: POST /api/sessions/
    pending --> running: agent starts
    running --> completed: final text answer
    running --> failed: error / clone failure
    completed --> [*]
    failed --> [*]
```

---

### 2. Get session — `GET /api/sessions/<id>/`

Fetch a single session with findings and tool call log (useful after a long run or for polling if you later add async jobs).

**curl:**

```bash
curl http://127.0.0.1:8000/api/sessions/1/
```

**PowerShell:**

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/sessions/1/" -Method Get
```

---

### 3. List sessions for a repo — `GET /api/repos/sessions/?repo_url=...`

Returns prior sessions for the same `repo_url` (question, status, answer preview).

**curl:**

```bash
curl "http://127.0.0.1:8000/api/repos/sessions/?repo_url=https://github.com/tiangolo/fastapi"
```

**PowerShell:**

```powershell
$repo = [uri]::EscapeDataString("https://github.com/tiangolo/fastapi")
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/repos/sessions/?repo_url=$repo" -Method Get
```

---

## Agent loop (conceptual)

```mermaid
flowchart TD
    Start([run_research_session]) --> Demo{GEMINI_DEMO_MODE?}
    Demo -->|yes| Offline[grep-based demo answer]
    Demo -->|no| Loop[Iteration ≤ MAX_AGENT_ITERATIONS]
    Loop --> Gemini[Gemini generate_content]
    Gemini --> FC{Tool calls?}
    FC -->|yes| Cap{tool_calls < 10?}
    Cap -->|no| Force[Disable tools + nudge final answer]
    Cap -->|yes| Exec[Execute tools → append to context]
    Exec --> Loop
    FC -->|no| Text{Plain text answer?}
    Text -->|yes| Done([Save completed])
    Text -->|no| Nudge[Prompt model again]
    Nudge --> Loop
    Loop -->|max iterations| Last[One no-tools summary attempt]
    Force --> Loop
    Offline --> Done
    Last --> Done
```

---

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Model id for `generateContent` |
| `GEMINI_DEMO_MODE` | `false` | Skip API; return offline search summary |
| `GEMINI_MAX_AGENT_ITERATIONS` | `20` | Max model turns per session |
| `GEMINI_MAX_TOOL_CALLS` | `10` | Hard cap on tool executions |
| `GEMINI_MAX_TOOL_RESULT_CHARS` | `12000` | Truncate tool JSON sent back to the model |
| `GEMINI_MAX_OUTPUT_TOKENS` | `8192` | Cap completion size per turn |
| `REPOS_DIR` | `repos` | Clone destination |

---

## Run tests

```bash
python manage.py test agent
```

Verbose output:

```bash
python manage.py test agent -v 2
```

Current tests cover **code_tools** (line numbering, path traversal protection). Extend with API/integration tests as needed.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|----------------|------------|
| `404 models/gemini-...` | Invalid or retired model id | Set `GEMINI_MODEL` to a current id from [AI Studio](https://aistudio.google.com/) |
| `429 quota exceeded` | Free tier limits | Wait for reset, switch model, enable billing, or `GEMINI_DEMO_MODE=true` |
| `Stopped after maximum iterations...` | Model kept calling tools | Lower searches; ensure server restarted after config changes |
| Huge `input_tokens` | Noisy `search_code` results | Already mitigated: `docs/` skipped, results truncated |

---

## Further reading

- **[DECISIONS.md](./DECISIONS.md)** — Architecture rationale, trade-offs, and known limitations.

---

## License

Add your license here (e.g. MIT).
