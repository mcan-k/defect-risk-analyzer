"""
Pydantic Models - Akilli Hata Analizi API
Tum request/response semalari burada tanimlanir.
Ayni semalar ileride Forge Addon icin de kullanilacak.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ===================== ENUMS =====================

class AnalysisStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


# ===================== REQUEST MODELS =====================

class AnalyzeSingleRequest(BaseModel):
    """
    Tek analiz istegi.
    - bug_key verilirse: bugs.json'dan summary+description query olarak kullanilir
    - query verilirse: dogrudan ChromaDB similarity + LLM analizi yapilir
    - ikisi birden verilebilir (query oncelikli)
    """
    bug_key: Optional[str] = Field(
        None,
        description="Jira bug key, ornegin AP-12",
        pattern=r"^[A-Z]+-\d+$"
    )
    query: Optional[str] = Field(
        None,
        description="Analiz edilecek alan veya degisiklik aciklamasi"
    )
    n_results: int = Field(
        3,
        ge=1,
        le=10,
        description="Benzer bug sayisi (ChromaDB'den cekilecek)"
    )

    def model_post_init(self, __context):
        if not self.bug_key and not self.query:
            raise ValueError("bug_key veya query'den en az biri verilmeli")


class AnalyzeBulkRequest(BaseModel):
    """Toplu analiz icin request body"""
    bug_keys: Optional[list[str]] = Field(
        None,
        description="Jira bug key listesi"
    )
    all_bugs: bool = Field(
        False,
        description="True ise mevcut tum buglar analiz edilir"
    )

    def model_post_init(self, __context):
        if not self.bug_keys and not self.all_bugs:
            raise ValueError("bug_keys listesi veya all_bugs=true olmali")


# ===================== RESPONSE MODELS =====================

class SimilarBugInfo(BaseModel):
    """Benzer bug bilgisi"""
    bug_key: str
    priority: str
    status: str
    similarity_pct: float = Field(..., description="Benzerlik yuzdesi 0-100")
    snippet: str


class BugRiskResult(BaseModel):
    """Tek bir analiz sonucu"""
    bug_key: Optional[str] = None
    query: str
    risk_score: int = Field(..., ge=0, le=100)
    risk_level: str
    reason: str
    test_scenarios: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    similar_bugs: list[SimilarBugInfo] = Field(default_factory=list)
    source_bug_keys: list[str] = Field(default_factory=list)
    raw_analysis: str = Field("", description="LLM ciktisinin tamami")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class AnalyzeSingleResponse(BaseModel):
    status: AnalysisStatus
    result: Optional[BugRiskResult] = None
    error: Optional[str] = None
    duration_ms: float


class AnalyzeBulkResponse(BaseModel):
    status: AnalysisStatus
    total: int
    successful: int
    failed: int
    results: list[BugRiskResult] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    duration_ms: float


class RiskSummary(BaseModel):
    total_bugs: int
    risk_distribution: dict[str, int]
    area_risks: dict
    last_updated: Optional[datetime] = None


class RisksResponse(BaseModel):
    status: AnalysisStatus
    summary: RiskSummary
    bugs: list[dict] = Field(default_factory=list)


class RefreshResponse(BaseModel):
    status: AnalysisStatus
    previous_count: int
    new_count: int
    new_bugs_added_to_db: int
    new_bug_keys: list[str] = Field(default_factory=list)
    duration_ms: float
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    components: dict[str, bool]
    bug_count: int
    chromadb_count: int
    uptime_seconds: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
