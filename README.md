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
- **RAG Pipeline** — ChromaDB vector database stores historical bugs. Similar defects are retrieved for context-aware analysis.
- **BYOK (Bring Your Own Key)** — Works with Groq (LLaMA 3.3 70b) or OpenAI (GPT-4o-mini). You provide your own API key.
- **5-Page Dashboard** — Risk heatmap, bug browser, live analysis, webhook history, and self-service settings.
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
| Vector DB | ChromaDB (local, cosine similarity) |
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
git clone https://github.com/Kartall01/defect-risk-analyzer.git
cd defect-risk-analyzer

# 2. Run the setup script
scripts\setup.bat

# 3. Start the application
scripts\start.bat
```

The setup script creates a virtual environment, installs dependencies, and prepares the `.env` file.
The start script launches both the API and Dashboard, then opens your browser.

### Option B: Manual Setup

```bash
# 1. Clone and enter directory
git clone https://github.com/Kartall01/defect-risk-analyzer.git
cd defect-risk-analyzer

# 2. Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials (or set USE_MOCK_DATA=True for demo)

# 5. Start the API backend
uvicorn api:app --host 0.0.0.0 --port 8000

# 6. In a new terminal, start the dashboard
streamlit run dashboard.py --server.port 8501
```

### Option C: Docker

```bash
# 1. Clone and configure
git clone https://github.com/Kartall01/defect-risk-analyzer.git
cd defect-risk-analyzer
cp .env.example .env
# Edit .env with your credentials

# 2. Build and run
docker-compose up --build

# API: http://localhost:8000
# Dashboard: http://localhost:8501
```

### Try Without Jira (Mock Mode)

Set `USE_MOCK_DATA=True` in your `.env` file. The app will load 20 realistic sample bugs and work without any Jira credentials. Perfect for evaluation.

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

## 🔌 API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/health` | ❌ | Service health check |
| `POST` | `/analyze` | ✅ | Single bug/area risk analysis |
| `POST` | `/analyze/bulk` | ✅ | Bulk analysis with circuit breaker |
| `GET` | `/risks` | ✅ | Current risk overview (no new analysis) |
| `POST` | `/refresh` | ✅ | Sync data from Jira |
| `POST` | `/webhook/jira` | ✅ | Auto-analyze on Jira events |
| `GET` | `/bugs` | ✅ | List loaded bugs |
| `GET` | `/results` | ✅ | All analysis results |
| `GET` | `/rate-limit` | ✅ | Rate limit status |

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
adjusted   = base_score × open_ratio_factor × trend_multiplier
risk_score = clamp(adjusted, 0, 100)
```

**Components:**
- **Priority factor** (0-1): Weighted score from bug priorities (Highest=5, High=4, Medium=3, Low=2, Lowest=1)
- **Bug density** (0-1): Module's share of total bugs (Defect Clustering / Pareto Principle)
- **Open ratio factor** (1.0-1.5): More open bugs = higher risk
- **Trend multiplier**: Increasing=1.3×, Stable=1.0×, Decreasing=0.8×

**Risk Levels:**
| Score | Level |
|-------|-------|
| ≥ 80 | 🔴 CRITICAL |
| ≥ 60 | 🟠 HIGH |
| ≥ 35 | 🟡 MEDIUM |
| < 35 | 🟢 LOW |

---

## 🔒 Security

- **Zero PII to LLM**: All personal data (names, emails, IPs, URLs, phone numbers) is anonymized before any external API call
- **API Key Auth**: All endpoints require `X-API-Key` header
- **No Hardcoded Secrets**: Everything via `.env` (gitignored)
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

---

## 📁 Project Structure

```
defect-risk-analyzer/
├── api.py                  # FastAPI backend — all REST endpoints
├── api_models.py           # Pydantic request/response models
├── api_auth.py             # X-API-Key authentication
├── llm_provider.py         # BYOK — Strategy Pattern (Groq / OpenAI)
├── risk_analyzer.py        # RAG engine — ChromaDB + risk scoring + LLM
├── prompt_templates.py     # System & User prompts (ISTQB-standard)
├── anonymizer.py           # PII masking — reversible tokenization
├── jira_client.py          # Jira REST API v3 + ADF parser
├── ci_analyzer.py          # Headless CLI for GitHub Actions
├── dashboard.py            # Streamlit UI (5 pages, Turkish)
├── config.py               # Centralized .env configuration
├── scripts/
│   ├── start.bat           # Windows: launch everything
│   ├── stop.bat            # Windows: stop all services
│   └── setup.bat           # Windows: first-time setup
├── data/
│   └── sample_bugs.json    # Mock data for demo mode
├── .github/workflows/
│   └── pr-risk-analysis.yml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── LICENSE
```

---

## 🗺️ Roadmap

- [ ] PDF risk report export
- [ ] Trend charts (module risk over time)
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

**Mustafa Can** — QA Engineer

- GitHub: [@Kartall01](https://github.com/Kartall01)

---

_Built with ISTQB principles: Defect Clustering, Risk-Based Testing, and Pesticide Paradox._
