# Known Technical Debt

Deliberate trade-offs accepted during refactoring, recorded so they are not
mistaken for oversights. Each entry names the phase that will address it.

---

## `_resolve_base_dir()` cwd fallback

**Where:** [`src/defect_risk_analyzer/config.py`](../src/defect_risk_analyzer/config.py)

`_resolve_base_dir()` cwd fallback'i, ileride pipx/wheel kurulumunda veri
dizinini çalışma dizinine bağlıyor. Kalıcı çözüm platformdirs ile kullanıcı
veri dizini. Faz 2'de ele alınacak.

**Detail:** resolution order is `DRA_BASE_DIR` → nearest ancestor containing
`pyproject.toml` → `Path.cwd()`. The first two are stable; the third is not.
In a source checkout, editable install, or the Docker image (`WORKDIR /app`,
`pyproject.toml` present) the second rule wins and the root is correct. Only a
wheel/pipx install with no project tree reaches the cwd fallback — there,
running `dra` from two different directories yields two different `data/`
directories, and neither is discoverable by the user.

**Workaround until then:** set `DRA_BASE_DIR` explicitly.

**Planned fix (Phase 2):** resolve the data directory via `platformdirs`
(`user_data_dir("defect-risk-analyzer")`) when no project root is found, and
migrate any existing `./data` contents on first run.

---

## `calculate_risk_score()`'s unused `module_name` parameter

**Where:** [`src/defect_risk_analyzer/core/scoring.py`](../src/defect_risk_analyzer/core/scoring.py)

`calculate_risk_score(module_name, module_stats)` imzasındaki `module_name`
gövdede hiç kullanılmıyor. Faz 2 Adım 1a bu fonksiyonu `risk_analyzer.py`'den
saf bir modüle taşırken imzayı bilerek korudu — parametreyi düşürmek, taşımanın
davranış-koruyan olduğunu kanıtlayan baseline diff'ine karışacak ayrı bir karar.

**Detail:** iki olasılık var ve hangisi olduğu koddan anlaşılmıyor. Ya parametre
baştan gereksizdi ve sadece çağrı yerlerinde taşınıyor, ya da formülde modüle
özgü bir ağırlık katsayısı düşünülmüş ama hiç uygulanmamış. İkincisi doğruysa
parametreyi silmek, tasarımın kaybolan tek izini de siler.

**Impact:** yok — davranışsal etkisi olmayan, yalnız kafa karıştıran bir imza.
`RiskAnalyzer.calculate_risk_score`'un 9 çağrı yeri parametreyi geçiyor, artı
sarmalayıcının `core.scoring`'e yaptığı delegasyon.

**Planned fix (Phase 4):** karar ver. Modül ağırlığı isteniyorsa formüle ekle,
istenmiyorsa parametreyi ve tüm çağrı yerlerini birlikte temizle.
