# Defect Risk Analyzer — v2 yol haritası

**Hedef:** GitHub'dan indirilip 5 dakikada çalışan, bakımlı, güvenilir bir QA aracı.
**Dağıtım:** `pipx install` + `dra` komutu (ana) · Docker (ikincil) · Streamlit Cloud mock demo (vitrin)
**Marketplace hedefi yok.**

---

## Mimari kurallar

Bu üç kural v2 boyunca ihlal edilmez:

1. **Bağımlılık tek yöne akar.** `ui/`, `server/`, `ci/` → `services/` → `core/` + `adapters/`.
   `core/` içindeki hiçbir dosya streamlit, fastapi, chromadb veya requests import etmez.
2. **Risk skoru Python'da hesaplanır, LLM yorumlar.** Bu projenin özü; değişmez.
3. **Kullanıcıya görünen metin sadece `ui/` katmanında üretilir.** İş mantığı yapısal veri döner:
   `{"code": "stale_module", "params": {"module": "Payment", "days": 21}}`

### Hedef dizin yapısı

```
src/defect_risk_analyzer/
├── __init__.py          # tek __version__ kaynağı
├── cli.py               # dra komutu
├── config.py            # Settings sınıfı, import yan etkisi yok
├── core/                # saf: dict al, dict ver — I/O yok
│   ├── scoring.py
│   ├── anonymizer.py
│   ├── component_classifier.py
│   ├── blind_spot_detector.py
│   └── pattern_detector.py
├── adapters/            # ağ, disk, veritabanı
│   ├── jira_client.py
│   ├── llm_provider.py
│   ├── vector_store.py
│   ├── results_repository.py
│   └── secrets.py       # keyring sarmalayıcı
├── services/
│   └── analysis_service.py
├── ui/
│   ├── app.py
│   ├── pages/           # 4 sayfa
│   └── locales/{tr,en}.json
├── server/              # opsiyonel FastAPI: webhook + dış entegrasyon
└── ci/
tests/
pyproject.toml
```

---

## Fazlar

### Faz 0 — Dürüstlük yaması (1 saat)
Repo şu an public ve yanlış bilgi veriyor. Kod taşımadan:

- [ ] `ci_analyzer.py`'daki `Kartall01` GitHub linkini `mcan-k` ile değiştir
- [ ] README'deki `scripts/*.bat` referanslarını `BASLAT.bat` / `DURDUR.bat` ile hizala
- [ ] README: 5 sayfa → 7, 9 endpoint → 13, risk formülüne `volume_factor` ekle
- [ ] README proje yapısına eksik 3 modülü ekle, tamamlanmış roadmap maddelerini işaretle
- [ ] `api.py`'daki `except (LLMError, Exception)` ifadesini düzelt

### Faz 1 — Paket iskeleti (yarım gün)
Import satırları burada bir kez değişsin, sonraki fazlarda tekrar dokunulmasın.

- [ ] Tüm modülleri `src/defect_risk_analyzer/` altına taşı, `__init__.py` ekle
- [ ] Tek `__version__` kaynağı; `api.py` ve CLI oradan okusun
- [ ] `pyproject.toml` (PEP 621): `requires-python = ">=3.11"`, bağımlılıklar requirements.txt'ten
- [ ] `[project.scripts]` ile `dra` konsol giriş noktası
- [ ] `requirements-dev.txt`: pytest, pytest-cov, ruff, pip-audit
- [ ] `BASLAT.bat` ve Dockerfile'ın hâlâ çalıştığını doğrula

### Faz 2 — Servis katmanı (1-2 gün)
Projenin en kritik adımı. `ui/` ile `server/` arasındaki HTTP bağımlılığı burada ölür.

- [ ] `risk_analyzer.py`'ı böl: `vector_store` / `scoring` / `results_repository` / `analysis_service`
- [ ] `dashboard.py`'daki `api_request()` çağrılarını doğrudan servis çağrısına çevir
- [ ] `config.py`'ın import anındaki yan etkisini kaldır (testler `.env`'i bozmasın)
- [ ] LLM provider'ı `analysis_service` constructor'ından enjekte et
- [ ] `docker-compose.yml`'ı tek servise indir; `API_URL` / paylaşılan `API_KEY` sorunu ortadan kalkar

### Faz 3 — Testler (yarım gün)
- [ ] `tests/test_adf_parser.py` — saf fonksiyon, en yüksek getiri
- [ ] `tests/test_scoring.py` — `calculate_risk_score`, `calculate_module_stats`
- [ ] `tests/test_anonymizer.py` — round-trip + **telefon regex'i düzeltmesi**
      (sürüm numarası, sipariş kodu, tarih maskelenmemeli)
- [ ] CI'a `pytest` + `ruff` + `pip-audit` adımları
- [ ] Kapsam rozeti — gerçek olsun, sahte rozet koyma

### Faz 4 — Veri katmanı (yarım gün)
- [ ] ChromaDB toptan silme yerine diff-sync (`collection.get` → karşılaştır → `delete` + `upsert`)
- [ ] `defect_history_mock` / `defect_history_live` ayrı koleksiyonlar
- [ ] `data/chroma_db` içindeki 9 yetim HNSW segment klasörünü temizle
- [ ] `ci_analyzer` modül isimlerini `component_classifier` ile hizala
      (`API`/`Backend API`, `General`/`Genel` uyuşmazlığı — CI çıktısı şu an boş)

### Faz 5 — UI + i18n (2 gün)
- [ ] `blind_spot_detector` yapısal veri dönsün (API kontratını kıran adım, önce yapılmalı)
- [ ] 7 sayfa → 4: Genel bakış · Buglar · Analiz · Ayarlar
- [ ] Streamlit native `pages/` yapısı; string eşlemeli router'ı sil
- [ ] 110 satırlık gömülü CSS → `.streamlit/config.toml` teması
- [ ] `locales/tr.json` + `locales/en.json`, sidebar'da dil seçici
- [ ] Renk sadece risk seviyesini kodlasın
- [ ] `data/sample_bugs_en.json` (İngilizce demo için)
- [ ] N+1 API çağrısı ve her render'daki `config.reload()` düzeltmesi

### Faz 6 — Güven katmanı (yarım gün)
- [ ] **Jira token'ı `keyring`'e taşı** — düz metin `.env`'de kimlik bilgisi kalmasın
      (`.env` sadece dil, port, mock modu gibi hassas olmayan ayarları tutar)
- [ ] `SECURITY.md`: veri akışı (ne maskeleniyor, hangi API'ye ne gidiyor, ne saklanıyor),
      açıklama kanalı, yanıt süresi taahhüdü
- [ ] Dependabot etkinleştir
- [ ] `CONTRIBUTING.md`, issue şablonları

### Faz 7 — Vitrin (yarım gün)
- [ ] README sıfırdan: tek cümlelik tanım, GIF/ekran görüntüsü, tek satır kurulum, gerçek rozetler
- [ ] `README.tr.md`
- [ ] `CHANGELOG.md` + `v1.0.0` git tag + GitHub Release
- [ ] Streamlit Cloud demo — sadece mock data, kimlik bilgisi girişi kapalı

---

## Kalite kontrol listesi (bitişte)

- [ ] Temiz bir makinede `pipx install` → `dra` → 5 dakikada çalışan dashboard
- [ ] Windows, macOS, Linux üçünde de çalışıyor
- [ ] Hiçbir `.bat` dosyasına bağımlılık yok
- [ ] README'deki her komut gerçekten çalışıyor
- [ ] Her rozetin arkasında gerçek bir CI çalışması var
- [ ] Kimlik bilgisi hiçbir yerde düz metin diskte durmuyor
- [ ] `core/` içindeki hiçbir dosya dış dünyayı import etmiyor
