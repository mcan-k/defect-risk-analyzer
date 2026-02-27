"""
FastAPI Backend - Akilli Hata Analizi ve Tahminleme
===================================================
Mevcut analiz motorunu REST API olarak disariya acar.
GitHub PR webhook, Jira Forge Addon ve diger entegrasyonlar
bu API uzerinden calisacak.

Calistirma:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    POST /analyze       - Tek bug/alan risk analizi
    POST /analyze/bulk  - Toplu risk analizi
    GET  /risks         - Mevcut risk skorlari ve defect density
    POST /refresh       - Jira'dan veri cek + ChromaDB senkronize et
    GET  /health        - Servis saglik kontrolu
"""

import os
import json
import time
import asyncio
import traceback
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# ===================== PROJE MODULLERI =====================
# Gercek fonksiyon imzalari:
#   jira_fetch.fetch_all_bugs(project_key="AP") -> list[dict]
#   jira_fetch.save_bugs(bugs, output_file="data/bugs.json")
#   risk_analyzer.setup_chromadb() -> collection
#   risk_analyzer.load_bugs_to_chromadb(collection, anonymizer) -> list[dict]
#   risk_analyzer.find_similar_bugs(collection, query, n_results=3) -> list[dict]
#   risk_analyzer.analyze_risk(query, similar_bugs, anonymizer) -> {"query", "analysis", "sources"}
#   anonymizer.DataAnonymizer() + .import_map() / .export_map()

from jira_fetch import fetch_all_bugs, save_bugs
from anonymizer import DataAnonymizer
from risk_analyzer import (
    setup_chromadb,
    load_bugs_to_chromadb,
    find_similar_bugs,
    analyze_risk,
)

from api_models import (
    AnalyzeSingleRequest, AnalyzeSingleResponse,
    AnalyzeBulkRequest, AnalyzeBulkResponse,
    RisksResponse, RiskSummary,
    RefreshResponse, HealthResponse,
    BugRiskResult, SimilarBugInfo, AnalysisStatus,
)
from api_auth import verify_api_key, get_or_create_api_key


# ===================== KONFIGURASYONLAR =====================

DATA_DIR = Path("data")
BUGS_FILE = DATA_DIR / "bugs.json"
TEST_HISTORY_FILE = DATA_DIR / "test_history.json"
DEFECT_DENSITY_FILE = DATA_DIR / "defect_density.json"
GROQ_SLEEP = float(os.getenv("GROQ_SLEEP", "2"))

# Groq rate limit icin semaphore - ayni anda max 1 LLM istegi
_groq_semaphore = asyncio.Semaphore(1)

# Uptime takibi
_start_time = time.time()

# Paylasilan kaynaklar (lifespan'de initialize edilir)
_anonymizer: DataAnonymizer = None
_collection = None


# ===================== LIFESPAN =====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama baslarken ChromaDB ve Anonymizer'i hazirlar."""
    global _anonymizer, _collection

    api_key = get_or_create_api_key()
    print("=" * 60)
    print("  Akilli Hata Analizi API baslatiliyor...")
    print(f"  API Key: {api_key[:16]}...")
    print(f"  Data dizini: {DATA_DIR.resolve()}")
    print("=" * 60)

    # Anonymizer baslat ve mevcut mapping'i yukle
    _anonymizer = DataAnonymizer()
    _anonymizer.import_map()
    print("[INIT] Anonymizer hazirlandi.")

    # ChromaDB baslat
    _collection = setup_chromadb()
    print(f"[INIT] ChromaDB hazirlandi. Kayit sayisi: {_collection.count()}")

    # Mevcut buglari ChromaDB'ye yukle (zaten varsa atlar)
    if BUGS_FILE.exists():
        load_bugs_to_chromadb(_collection, _anonymizer)
        _anonymizer.export_map()
        print(f"[INIT] ChromaDB senkronize edildi. Guncel kayit: {_collection.count()}")

    yield

    print("[API] Kapatiliyor...")


# ===================== APP TANIMI =====================

app = FastAPI(
    title="Akilli Hata Analizi API",
    description="Defect Prediction & Clustering - RAG tabanli risk analiz motoru",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",   # Streamlit
        "http://localhost:3000",   # Gelecek React frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== YARDIMCI FONKSIYONLAR =====================

def _load_bugs() -> list[dict]:
    """bugs.json'dan mevcut buglari yukler."""
    if not BUGS_FILE.exists():
        return []
    with open(BUGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_bug_by_key(bug_key: str) -> dict | None:
    """bugs.json'dan tek bir bug bulur."""
    for bug in _load_bugs():
        if bug.get("key") == bug_key:
            return bug
    return None


def _load_defect_density() -> dict:
    """defect_density.json yukler."""
    if not DEFECT_DENSITY_FILE.exists():
        return {}
    with open(DEFECT_DENSITY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_analysis(text: str) -> dict:
    """
    LLM ciktisini parse eder.
    dashboard.py'deki parse_analysis() ile ayni mantik.
    Turkce karakterleri de destekler (RİSK_SKORU, MODÜLLER vb.)
    """
    result = {
        "risk_score": 0,
        "risk_level": "Bilinmiyor",
        "reason": "",
        "test_scenarios": [],
        "modules": []
    }

    lines = text.strip().split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        line_upper = line.upper().replace("\u0130", "I").replace("\u00dc", "U").replace("\u00d6", "O")

        if line_upper.startswith("RISK_SKORU:"):
            try:
                score_str = line.split(":", 1)[1].strip()
                result["risk_score"] = int(score_str)
            except (ValueError, IndexError):
                result["risk_score"] = 0
        elif line_upper.startswith("RISK_SEVIYESI:"):
            result["risk_level"] = line.split(":", 1)[1].strip()
        elif line_upper.startswith("NEDEN:"):
            result["reason"] = line.split(":", 1)[1].strip()
            current_section = "reason"
        elif line_upper.startswith("TEST_SENARYOLARI:"):
            current_section = "test"
        elif line_upper.startswith("MODULLER:"):
            current_section = "modules"
        elif line.startswith("- ") and current_section == "test":
            result["test_scenarios"].append(line[2:])
        elif line.startswith("- ") and current_section == "modules":
            result["modules"].append(line[2:])
        elif current_section == "reason" and line and not line_upper.startswith("TEST"):
            result["reason"] += " " + line

    return result


def _build_similar_bug_infos(similar_bugs: list) -> list[SimilarBugInfo]:
    """find_similar_bugs() ciktisini API response modeline donusturur."""
    infos = []
    for b in similar_bugs:
        meta = b["metadata"]
        similarity_pct = round((1 - b["distance"]) * 100, 1)
        infos.append(SimilarBugInfo(
            bug_key=meta["key"],
            priority=meta["priority"],
            status=meta["status"],
            similarity_pct=similarity_pct,
            snippet=b["document"][:300],
        ))
    return infos


async def _run_single_analysis(query: str, n_results: int, bug_key: str = None) -> BugRiskResult:
    """
    Tek bir analiz calistirir.
    Gercek akis: find_similar_bugs -> analyze_risk -> parse
    Groq rate limit icin semaphore ile korunur.
    """
    async with _groq_semaphore:
        loop = asyncio.get_event_loop()

        # 1. Benzer buglari bul (ChromaDB - sync)
        similar_bugs = await loop.run_in_executor(
            None,
            find_similar_bugs,
            _collection, query, n_results
        )

        # 2. LLM analizi (Groq - sync)
        # analyze_risk(query, similar_bugs, anonymizer) -> {"query", "analysis", "sources"}
        raw_result = await loop.run_in_executor(
            None,
            analyze_risk,
            query, similar_bugs, _anonymizer
        )

        # 3. Rate limit bekleme
        await asyncio.sleep(GROQ_SLEEP)

    # 4. LLM ciktisini parse et
    analysis_text = raw_result["analysis"]
    parsed = _parse_analysis(analysis_text)

    return BugRiskResult(
        bug_key=bug_key,
        query=query,
        risk_score=parsed["risk_score"],
        risk_level=parsed["risk_level"],
        reason=parsed["reason"],
        test_scenarios=parsed["test_scenarios"],
        modules=parsed["modules"],
        similar_bugs=_build_similar_bug_infos(similar_bugs),
        source_bug_keys=raw_result["sources"],
        raw_analysis=analysis_text,
        analyzed_at=datetime.utcnow(),
    )


# ===================== ENDPOINTS =====================

# ---------- 1. POST /analyze ----------

@app.post(
    "/analyze",
    response_model=AnalyzeSingleResponse,
    summary="Tek bug/alan risk analizi",
    dependencies=[Depends(verify_api_key)],
)
async def analyze_single(request: AnalyzeSingleRequest):
    """
    Tek bir alan veya bug icin RAG tabanli risk analizi.
    
    Kullanim:
    - {"query": "Karakter hareket sistemi degisti"} -> dogrudan analiz
    - {"bug_key": "AP-5"} -> bug'in summary+description'i query olarak kullanilir
    - {"bug_key": "AP-5", "query": "ozel soru"} -> query oncelikli
    """
    start = time.time()

    try:
        # Query belirle
        query = request.query
        bug_key = request.bug_key

        if not query and bug_key:
            bug = _find_bug_by_key(bug_key)
            if not bug:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Bug bulunamadi: {bug_key}. Once POST /refresh ile veriyi guncelleyin."
                )
            # Bug'in summary + description'ini query olarak kullan
            query = f"{bug['summary']}. {bug.get('description', '')}"

        result = await _run_single_analysis(query, request.n_results, bug_key)
        duration = (time.time() - start) * 1000

        return AnalyzeSingleResponse(
            status=AnalysisStatus.SUCCESS,
            result=result,
            duration_ms=round(duration, 2),
        )

    except HTTPException:
        raise
    except Exception as e:
        duration = (time.time() - start) * 1000
        print(f"[HATA] /analyze basarisiz: {e}")
        traceback.print_exc()
        return AnalyzeSingleResponse(
            status=AnalysisStatus.FAILED,
            error=str(e),
            duration_ms=round(duration, 2),
        )


# ---------- 2. POST /analyze/bulk ----------

@app.post(
    "/analyze/bulk",
    response_model=AnalyzeBulkResponse,
    summary="Toplu risk analizi",
    dependencies=[Depends(verify_api_key)],
)
async def analyze_bulk(request: AnalyzeBulkRequest):
    """
    Birden fazla bug icin risk analizi.
    Her bug'in summary+description'i query olarak kullanilir.
    Groq rate limit nedeniyle sirayla calistirilir.
    """
    start = time.time()
    results: list[BugRiskResult] = []
    errors: list[dict] = []

    all_bugs = _load_bugs()

    if request.all_bugs:
        target_bugs = all_bugs
    else:
        target_bugs = []
        for key in request.bug_keys:
            bug = _find_bug_by_key(key)
            if bug:
                target_bugs.append(bug)
            else:
                errors.append({"bug_key": key, "error": "Bug bulunamadi"})

    for bug in target_bugs:
        try:
            query = f"{bug['summary']}. {bug.get('description', '')}"
            result = await _run_single_analysis(query, 3, bug["key"])
            results.append(result)
        except Exception as e:
            errors.append({"bug_key": bug.get("key", "?"), "error": str(e)})
            print(f"[HATA] Bulk - {bug.get('key')}: {e}")

    duration = (time.time() - start) * 1000
    total = len(target_bugs) + len([e for e in errors if e.get("bug_key") not in [b.bug_key for b in results]])
    successful = len(results)
    failed = len(errors)

    if failed == 0:
        s = AnalysisStatus.SUCCESS
    elif successful == 0:
        s = AnalysisStatus.FAILED
    else:
        s = AnalysisStatus.PARTIAL

    return AnalyzeBulkResponse(
        status=s,
        total=total,
        successful=successful,
        failed=failed,
        results=results,
        errors=errors,
        duration_ms=round(duration, 2),
    )


# ---------- 3. GET /risks ----------

@app.get(
    "/risks",
    response_model=RisksResponse,
    summary="Mevcut risk skorlari ve defect density",
    dependencies=[Depends(verify_api_key)],
)
async def get_risks():
    """
    Mevcut bugs.json ve defect_density.json verilerini doner.
    Yeni analiz calistirmaz, sadece son durumu gosterir.
    Detayli analiz icin POST /analyze kullanin.
    """
    bugs = _load_bugs()
    density = _load_defect_density()

    # Oncelik dagilimi
    risk_distribution = {}
    for bug in bugs:
        p = bug.get("priority", "Medium")
        risk_distribution[p] = risk_distribution.get(p, 0) + 1

    summary = RiskSummary(
        total_bugs=len(bugs),
        risk_distribution=risk_distribution,
        area_risks=density,
        last_updated=datetime.utcnow(),
    )

    return RisksResponse(
        status=AnalysisStatus.SUCCESS,
        summary=summary,
        bugs=bugs,
    )


# ---------- 4. POST /refresh ----------

@app.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Jira'dan veri cek ve ChromaDB'yi senkronize et",
    dependencies=[Depends(verify_api_key)],
)
async def refresh_data():
    """
    1. Jira'dan guncel buglari ceker (fetch_all_bugs)
    2. bugs.json'a kaydeder (save_bugs)
    3. Yeni buglari ChromaDB'ye yukler (load_bugs_to_chromadb)
    4. Anonymizer mapping'i gunceller
    """
    start = time.time()

    try:
        # Mevcut durumu kaydet
        old_bugs = _load_bugs()
        old_keys = {b.get("key") for b in old_bugs}
        old_chromadb_count = _collection.count()

        # 1. Jira'dan cek (sync)
        loop = asyncio.get_event_loop()
        new_bugs = await loop.run_in_executor(None, fetch_all_bugs, "AP")

        # 2. Kaydet
        await loop.run_in_executor(None, save_bugs, new_bugs)

        # 3. ChromaDB senkronize et
        await loop.run_in_executor(
            None, load_bugs_to_chromadb, _collection, _anonymizer
        )
        _anonymizer.export_map()

        # Sonuclari hesapla
        new_keys = {b.get("key") for b in new_bugs}
        added_keys = sorted(new_keys - old_keys)
        new_chromadb_count = _collection.count()
        added_to_db = new_chromadb_count - old_chromadb_count

        duration = (time.time() - start) * 1000

        return RefreshResponse(
            status=AnalysisStatus.SUCCESS,
            previous_count=len(old_bugs),
            new_count=len(new_bugs),
            new_bugs_added_to_db=added_to_db,
            new_bug_keys=added_keys,
            duration_ms=round(duration, 2),
            message=f"{len(added_keys)} yeni bug eklendi, {added_to_db} kayit ChromaDB'ye yuklendi."
            if added_keys
            else "Yeni bug yok, veriler guncel.",
        )

    except Exception as e:
        duration = (time.time() - start) * 1000
        print(f"[HATA] /refresh basarisiz: {e}")
        traceback.print_exc()
        return RefreshResponse(
            status=AnalysisStatus.FAILED,
            previous_count=len(old_bugs) if "old_bugs" in locals() else 0,
            new_count=0,
            new_bugs_added_to_db=0,
            duration_ms=round(duration, 2),
            message=f"Jira veri cekme hatasi: {str(e)}",
        )


# ---------- 5. GET /health ----------

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Servis saglik kontrolu",
    # Auth yok - monitoring sistemleri icin acik
)
async def health_check():
    """
    API, Jira, ChromaDB ve Groq baglantilarini kontrol eder.
    Auth gerektirmez.
    """
    components = {}

    # Jira config
    components["jira"] = bool(os.getenv("JIRA_BASE_URL") and os.getenv("JIRA_API_TOKEN"))

    # ChromaDB
    components["chromadb"] = _collection is not None
    chromadb_count = _collection.count() if _collection else 0

    # Groq API key
    components["groq"] = bool(os.getenv("GROQ_API_KEY"))

    # Data dosyalari
    components["bugs_json"] = BUGS_FILE.exists()
    components["defect_density"] = DEFECT_DENSITY_FILE.exists()

    # Anonymizer
    components["anonymizer"] = _anonymizer is not None

    # Bug sayisi
    bug_count = len(_load_bugs()) if BUGS_FILE.exists() else 0

    # Genel durum
    critical_ok = components["groq"] and components["chromadb"] and components["anonymizer"]
    all_ok = all(components.values())

    if all_ok:
        status_str = "healthy"
    elif critical_ok:
        status_str = "degraded"
    else:
        status_str = "unhealthy"

    return HealthResponse(
        status=status_str,
        version="1.0.0",
        components=components,
        bug_count=bug_count,
        chromadb_count=chromadb_count,
        uptime_seconds=round(time.time() - _start_time, 2),
        timestamp=datetime.utcnow(),
    )


# ===================== MAIN =====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
