# 🔍 Defect Risk Analyzer

**AI-powered Jira defect risk prediction using RAG and ISTQB principles.**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.41-red.svg)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Defect Risk Analyzer connects to your Jira instance, analyzes historical bug data using **Retrieval-Augmented Generation (RAG)**, and predicts which modules are most likely to produce defects. It gives QA teams actionable recommendations like _"focus your testing on Authentication — it has 6 open bugs with increasing trend."_

Built on **ISTQB testing principles**: Defect Clustering (Pareto), Risk-Based Testing, and Pesticide Paradox.

---

## ✨ Key Features

- **Deterministic Risk Scoring** — Risk scores are calculated in Python using priority weights, bug density, open ratios, and trend analysis. The LLM interprets, not calculates.
- **RAG Pipeline** — ChromaDB vector database stores historical bugs. Similar defects are retrieved for context-aware analysis. Loads are incremental: only bugs whose text or metadata changed are re-embedded, and bugs that left the source are removed.
- **BYOK (Bring Your Own Key)** — Works with Groq (LLaMA 3.3 70b) or OpenAI (GPT-4o-mini). You provide your own API key.
- **4-Page Dashboard** — Genel Bakış (risk heatmap, trend charts, blind spots), Buglar (browser and pattern detection), Analiz (single, bulk and webhook analysis), Ayarlar (self-service settings).
- **Pattern Detection** — Clusters similar bugs via vector similarity and extracts common root causes and duplicate candidates — no LLM call required.
- **Blind Spot Detection** — Surfaces risky modules that were never analyzed, neglected critical bugs, and stale or rising-unattended areas.
- **Circuit Breaker** — Bulk analysis stops on rate limit errors, protecting your API budget.
- **CI/CD Integration** — GitHub Actions workflow posts risk reports on every PR.
- **Data Privacy** — PII is anonymized before any LLM call. No personal data leaves your environment.
- **Mock Data Mode** — Try the full tool without Jira credentials using realistic sample data.

---

## 🏗️ Architecture

```
Jira API → jira_client.py → bugs.json → anonymizer → ChromaDB (vectors)
                                                          ↓
User query → find_similar_bugs() → similar bugs from history
                                       ↓
calculate_module_stats() → statistics → LLM prompt → Groq/OpenAI → JSON response
                                                                       ↓
                              analysis_results.json + defect_density.json → Dashboard
```

**Key architectural rule:** The risk score is calculated deterministically in Python, NOT by the LLM. The LLM's job is to interpret the pre-calculated statistics and generate reasoning, test scenarios, and action recommendations.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Frontend | Streamlit |
| Vector DB | ChromaDB (local, cosine similarity, separate mock/live collections) |
| LLM | Groq (LLaMA 3.3 70b) or OpenAI (GPT-4o-mini) |
| CI/CD | GitHub Actions |
| Security | DataAnonymizer (PII masking) |
| Container | Docker & Docker Compose |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- A Groq or OpenAI API key (free tier works)
- (Optional) Jira Cloud or Server instance

### Option A: Windows (Recommended)

```powershell
# 1. Clone the repository
git clone https://github.com/mcan-k/defect-risk-analyzer.git
cd defect-risk-analyzer

# 2. Start the application
BASLAT.bat
```

`BASLAT.bat` does everything in one step: on first run it creates the virtual environment, installs dependencies, and prepares the `.env` file; on every run it starts both the API and the Dashboard, then opens your browser.

To stop all services, run `DURDUR.bat`.

### Option B: Manual Setup

```bash
# 1. Clone and enter directory
git clone https://github.com/mcan-k/defect-risk-analyzer.git
cd defect-risk-analyzer

# 2. Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 3. Install dependencies and the package itself
pip install -r requirements.txt
pip install -e .

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials (or set USE_MOCK_DATA=True for demo)

# 5. Start the dashboard — that is the whole application
dra
# ...or equivalently:
streamlit run src/defect_risk_analyzer/ui/app.py --server.port 8501
```

`pip install -e .` is required — the modules live in `src/defect_risk_analyzer/` and import each other by package name.

The `dra` console command launches the dashboard on the port set by `STREAMLIT_PORT`.

**No server needed.** The analysis engine runs inside the dashboard process. The
FastAPI service is optional and only used for the Jira webhook and external REST
integrations:

```bash
pip install -e ".[webhook]"
uvicorn defect_risk_analyzer.api:app --host 0.0.0.0 --port 8000
```

### Option C: Docker

```bash
# 1. Clone and configure
git clone https://github.com/mcan-k/defect-risk-analyzer.git
cd defect-risk-analyzer
cp .env.example .env
# Edit .env with your credentials

# 2. Build and run — dashboard only
docker-compose up --build

# Dashboard: http://localhost:8501
```

`docker-compose up` starts a single service and **does not open port 8000**. If
you need the Jira webhook receiver, bring it up with its profile:

```bash
docker-compose --profile webhook up --build

# Dashboard: http://localhost:8501
# Webhook API: http://localhost:8000
```

Both services share the same `app-data` volume, so they read the same ChromaDB
directory — see [`docs/KNOWN-DEBT.md`](docs/KNOWN-DEBT.md) for the caveat.

### Try Without Jira (Mock Mode)

Set `USE_MOCK_DATA=True` in your `.env` file. The app will load 20 realistic sample bugs and work without any Jira credentials. Perfect for evaluation.

Mock and live bugs are indexed into separate ChromaDB collections
(`defect_history_mock` and `defect_history_live`), so switching modes never
mixes sample keys into a real index — and switching back does not cost you the
other one.

---

## 📖 Configuration

All configuration is done via the `.env` file or the Settings page in the dashboard.

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_URL` | For live mode | Your Jira instance URL |
| `JIRA_EMAIL` | For live mode | Jira account email |
| `JIRA_API_TOKEN` | For live mode | Jira API token |
| `JIRA_PROJECT_KEY` | For live mode | Project key (e.g., "AP") |
| `LLM_PROVIDER` | Yes | `groq` or `openai` |
| `GROQ_API_KEY` | If using Groq | Your Groq API key |
| `OPENAI_API_KEY` | If using OpenAI | Your OpenAI API key |
| `USE_MOCK_DATA` | No | `True` for demo mode (default: `False`) |
| `MAX_DAILY_REQUESTS` | No | Daily LLM call limit (default: `50`) |
| `GROQ_SLEEP` | No | Seconds between LLM calls (default: `2`) |
| `API_KEY` | No | Auto-generated on first run |

See [`.env.example`](.env.example) for the complete list.

---

## 🔌 API Endpoints (optional webhook service)

These belong to the optional FastAPI service (`pip install -e ".[webhook]"`).
**The dashboard does not use them** — it calls the analysis service directly, in
its own process. They exist for the Jira webhook and external integrations.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/health` | ❌ | Service health check |
| `POST` | `/reload-config` | ✅ | Re-read `.env` and apply settings without a restart |
| `GET` | `/rate-limit` | ✅ | Rate limit status |
| `POST` | `/analyze` | ✅ | Single bug/area risk analysis |
| `POST` | `/analyze/bulk` | ✅ | Bulk analysis with circuit breaker |
| `GET` | `/patterns` | ✅ | Bug clusters and common root causes |
| `GET` | `/patterns/{bug_key}/duplicates` | ✅ | Similar/duplicate bugs for one bug |
| `GET` | `/risks` | ✅ | Current risk overview (no new analysis) |
| `POST` | `/refresh` | ✅ | Sync data from Jira |
| `GET` | `/bugs` | ✅ | List loaded bugs |
| `GET` | `/results` | ✅ | All analysis results |
| `GET` | `/results/webhook` | ✅ | Webhook-triggered analysis results |
| `GET` | `/blind-spots` | ✅ | Risky areas not analyzed yet |
| `POST` | `/webhook/jira` | ✅ | Auto-analyze on Jira events |

**Authentication:** All endpoints (except `/health`) require `X-API-Key` header.

```bash
curl -X POST http://localhost:8000/analyze \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"bug_key": "AP-101"}'
```

---

## 🧮 Risk Scoring Formula

Risk scores are **deterministic** — calculated in Python, not by the LLM.

```
base_score = (priority_factor × 60) + (bug_density × 40)
adjusted   = base_score × open_ratio_factor × trend_multiplier × volume_factor
risk_score = clamp(adjusted, 0, 100)
```

**Components:**
- **Priority factor** (0-1): Weighted score from bug priorities (Highest=5, High=4, Medium=3, Low=2, Lowest=1)
- **Bug density** (0-1): Module's share of total bugs (Defect Clustering / Pareto Principle)
- **Open ratio factor** (1.0-1.5): More open bugs = higher risk
- **Trend multiplier**: Increasing=1.3×, Stable=1.0×, Decreasing=0.8×
- **Volume factor** (0.55-1.0): Statistical confidence damper — `0.4 + (min(total_bugs / 4, 1.0) × 0.6)`. Prevents modules with only one or two bugs from reaching CRITICAL; a high-confidence score needs 3+ bugs.

| Bugs in module | Volume factor |
|----------------|---------------|
| 1 | 0.55 |
| 2 | 0.70 |
| 3 | 0.85 |
| 4+ | 1.00 |

**Risk Levels:**
| Score | Level |
|-------|-------|
| ≥ 80 | 🔴 CRITICAL |
| ≥ 60 | 🟠 HIGH |
| ≥ 35 | 🟡 MEDIUM |
| < 35 | 🟢 LOW |

---

## 🔒 Security

- **PII masking before the LLM**: e-mail, IP, URL, phone, Bearer tokens and
  known API-key prefixes are replaced with reversible tokens before any
  external call. Person names are **not** masked — no name recogniser ships
  today, and the Settings page says so. See [SECURITY.md](SECURITY.md).
- **Credentials in the OS keyring**: on a desktop install with the `desktop`
  extra; `.env` otherwise, and the Settings page states which. Docker and CI
  always use environment variables.
- **API Key Auth**: 13 of 14 endpoints require `X-API-Key`; the comparison is
  constant-time. `GET /health` is the only open endpoint.
- **No Hardcoded Secrets**: nothing in the source; `.env` is gitignored
- **Rate Limiting**: Daily cap + per-request throttle
- **Circuit Breaker**: Bulk operations stop on rate limit errors
- **Cost Control**: `MAX_DAILY_REQUESTS` prevents runaway API charges

---

## 🔄 CI/CD Integration

The included GitHub Actions workflow automatically analyzes PRs for risk:

1. Developer opens a PR
2. Workflow runs `ci_analyzer.py` with the PR diff
3. Risk report is posted as a PR comment
4. Reviewers see which modules are affected and their risk levels

The workflow uses mock data mode, so it works without Jira credentials in CI.

### Module map (`module-map.json`)

Step 2 needs to know which of your directories belong to which module. It does
not guess. `module-map.json` at the repository root maps path patterns to
module names, and also defines what is out of scope:

```json
{
  "_comment": "Free text. Ignored by the tool.",
  "modules": {
    "src/auth/**": "Authentication",
    "src/payments/**": "Payment",
    "web/**/*_view.tsx": "Frontend"
  },
  "exclude": ["docs/**", "tests/**", "**/*.md"]
}
```

`exclude` is applied first and its result is final: those files never reach
inference at all. Everything else is matched against `modules`, and **every**
matching pattern is reported — a file that two patterns claim affects both
modules. To drop a match you do not want, remove the pattern or exclude the
path.

**Module names must match the `component` field in your bug data** (for Jira,
the component name). A name your bug history has never seen is reported as
`Matched, no historical data` — never as low risk. Leaving files unmapped is
fine; the report says `NOT ASSESSED` rather than inventing a module.

Pattern syntax:

| | |
|---|---|
| `*` | any characters **within one path segment** — `src/*.py` does not match `src/a/b.py` |
| `?` | exactly one character, not `/` |
| `**` | any number of segments, including none — `**/*.md` matches `README.md` |

Patterns are anchored at the repository root (`auth/**` does not match
`src/auth/login.py`), always use `/` regardless of platform, and are case
sensitive everywhere. Character classes (`[abc]`), braces (`{a,b}`) and
negation (`!`) are not supported and are rejected when the file is loaded.

The committed `module-map.json` describes *this* repository. It is a working
example, not a default that fits your project — replace it.

If the file is missing, unreadable or empty, the analyzer reports that and
scores nothing rather than guessing. The file is found relative to the project
root; if you installed the package with `pip install .` outside a source
checkout, set `DRA_BASE_DIR` to the project root (see
[`docs/KNOWN-DEBT.md`](docs/KNOWN-DEBT.md)).

To see what your map covers before opening a PR:

```bash
python tests/tools/module_map_report.py
```

---

## 📁 Project Structure

```
defect-risk-analyzer/
├── src/defect_risk_analyzer/
│   ├── __init__.py             # Single source of __version__
│   ├── cli.py                  # "dra" console entry point
│   ├── config.py               # Centralized .env configuration (no import side effects)
│   ├── core/                   # Pure logic — dict in, dict out, no I/O
│   │   └── scoring.py          # Risk score, module stats, risk thresholds
│   ├── adapters/               # Network, disk, vector database
│   │   ├── vector_store.py     # ChromaDB wrapper
│   │   └── results_repository.py  # JSON persistence for results + density
│   ├── services/
│   │   └── analysis_service.py # Orchestration + LLM lock — the single entry point
│   ├── ui/                     # Everything the user reads (Turkish)
│   │   ├── app.py             # Entry script AND the Genel Bakış page
│   │   ├── pages/             # Buglar · Analiz · Ayarlar (Streamlit MPA-v1)
│   │   ├── shell.py           # bootstrap(): page config, CSS, first-run gate, nav
│   │   ├── service.py         # Shared AnalysisService handle + error boundary
│   │   ├── theme.py           # Colors, chart styling, the stylesheet
│   │   ├── results.py         # One analysis result, rendered
│   │   ├── setup_wizard.py    # First-run flow — a flow, not a page
│   │   └── messages.py        # Finding sentences (locales/ in Phase 5C)
│   ├── ci_analyzer.py          # Headless CLI for GitHub Actions
│   ├── api.py                  # Optional FastAPI service — webhook + REST
│   ├── api_models.py           # Pydantic request/response models
│   ├── api_auth.py             # X-API-Key authentication
│   ├── llm_provider.py         # BYOK — Strategy Pattern (Groq / OpenAI)
│   ├── prompt_templates.py     # System & User prompts (ISTQB-standard)
│   ├── anonymizer.py           # PII masking — reversible tokenization
│   ├── pattern_detector.py     # Bug clustering + common root cause extraction
│   ├── blind_spot_detector.py  # Unanalyzed risky areas (no LLM)
│   ├── component_classifier.py # Keyword-based component inference for empty Jira fields
│   └── jira_client.py          # Jira REST API v3 + ADF parser
├── docs/
│   ├── ROADMAP-v2.md           # Phased plan for v2
│   └── KNOWN-DEBT.md           # Accepted trade-offs, with planned fixes
├── data/
│   └── sample_bugs.json        # Mock data for demo mode
├── .github/workflows/
│   └── pr-risk-analysis.yml
├── BASLAT.bat                  # Windows: setup + launch the dashboard
├── DURDUR.bat                  # Windows: stop running services
├── module-map.json             # Path pattern -> module name, plus the analysis scope
├── pyproject.toml              # Packaging (PEP 621) + ruff config
├── requirements.txt            # Core deps (also read by pyproject.toml)
├── requirements-webhook.txt    # Optional FastAPI service deps — ".[webhook]"
├── requirements-dev.txt        # pytest, pytest-cov, ruff
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── LICENSE
```

Dependencies flow one way: `dashboard` / `api` / `ci_analyzer` → `services/` →
`core/` + `adapters/`. Nothing under `core/` imports streamlit, fastapi,
chromadb or requests.

`data/` and `.env` stay at the project root. `config.py` locates the root via
`DRA_BASE_DIR` → the nearest ancestor holding `pyproject.toml` → the current
working directory; see [`docs/KNOWN-DEBT.md`](docs/KNOWN-DEBT.md) for the
limits of that last fallback.

### Development

```bash
pip install -r requirements-dev.txt
pip install -e .
ruff check .
pytest
```

The test suite needs no network, ChromaDB, Jira or LLM credentials, and never
writes into the working tree — `tests/conftest.py` redirects every data path to
a temporary directory and fails the run if that redirection does not take
effect. The `pip install -e .` above is optional for the tests alone:
`pythonpath = ["src"]` makes them run from a bare checkout.

The streamlit page walk is the slow part; skip it with `pytest -m "not slow"`.

#### Cleaning up `data/chroma_db`

Deleting a collection can leave its HNSW segment directory and its rows behind
(see [`docs/KNOWN-DEBT.md`](docs/KNOWN-DEBT.md)), so the store accumulates
directories that nothing reads. To see what is in there:

```bash
python tests/tools/chroma_cleanup.py
```

That measures and prints; it writes nothing. Adding `--apply` deletes what it
listed, after asking you to type the number of directories back. It refuses to
apply when it finds no collection it recognises — that looks identical whether
the tool is wrong or you simply have not synced yet, so it stops instead of
guessing. The directory is gitignored and one refresh rebuilds it.

Both commands run in CI on every push and pull request
([`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

---

## 🗺️ Roadmap

- [x] Trend charts (bug volume over time)
- [x] Pattern detection (bug clustering + duplicate finder)
- [x] Blind spot detection (unanalyzed risky areas)
- [ ] PDF risk report export
- [ ] Sprint-based risk summaries
- [ ] Bug prediction model
- [ ] Additional LLM providers (Anthropic, Ollama, Azure OpenAI)
- [ ] Streamlit Cloud deployment

---

## 🇹🇷 Türkçe Kullanım Notu

Dashboard arayüzü Türkçe'dir. Mock data modundaki örnek buglar da Türkçe yazılmıştır. LLM, bug verisi hangi dildeyse o dilde analiz sonucu üretir.

Hızlı başlangıç için `.env` dosyasında `USE_MOCK_DATA=True` yapın ve Jira bilgisi girmeden uygulamayı deneyin.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**M. Can** —

- GitHub: [@mcan-k](https://github.com/mcan-k)

---

_Built with ISTQB principles: Defect Clustering, Risk-Based Testing, and Pesticide Paradox._
