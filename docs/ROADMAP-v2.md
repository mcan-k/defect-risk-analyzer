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
      (Faz 5B notu: **ölçülmedi**, muhtemelen bayat — `README.md` dashboard'un
      servisi doğrudan çağırdığını söylüyor ve `api_request` kaynakta yok.
      Kapatmadan önce ayrı bir ölçüm gerekiyor.)
- [ ] `config.py`'ın import anındaki yan etkisini kaldır (testler `.env`'i bozmasın)
- [ ] LLM provider'ı `analysis_service` constructor'ından enjekte et
- [ ] `docker-compose.yml`'ı tek servise indir; `API_URL` / paylaşılan `API_KEY` sorunu ortadan kalkar

### Faz 3 — Testler (tamamlandı)
Kapsam bu bölümün ilk halinden dardı. Yapılanlar, yapılmayanlar ve nedenleri
aşağıda; ayrıntı `docs/KNOWN-DEBT.md`'de.

Yapıldı:
- [x] `pyproject.toml`'a pytest yapılandırması (`testpaths`, `pythonpath = ["src"]`)
- [x] `tests/test_scoring_regression.py` — silinmiş `risk_analyzer.py`'nin
      çıktısına karşı regresyon; snapshot'lar `tests/data/` altında commit'li
      (`aff55c6`, mode A). Faz 2'nin davranış-koruyan olduğunun tek kanıtı.
- [x] `tests/test_scoring_units.py` — `calculate_risk_score` /
      `calculate_module_stats` (ROADMAP'teki `test_scoring.py` bu ikiye bölündü:
      biri snapshot'a, diğeri elle türetilmiş değerlere dayanıyor)
- [x] `tests/test_llm_provider.py` — 429 → `RateLimitError`, diğer hatalar →
      `LLMError`; iki tipin birbirinin alt sınıfı **olmadığı** da sabitlendi
- [x] `tests/test_analysis_service_breaker.py` — `analyze_bulk` devre kesicisi.
      Asıl sıralama tehlikesi `llm_provider.py`'de değil burada:
      `except RateLimitError` sondaki `except Exception`'ın altına taşınırsa
      kesici sessizce hiç tetiklenmez.
- [x] `tests/test_config_init.py` — `init()` çağrılmadığında sessizce
      default'lara düşen davranışı **belgeliyor** (düzeltme Faz 6)
- [x] `tests/test_core_boundary.py` — `baseline/check_core_boundary.py` buraya
      taşındı; **alt süreçte** koşuyor (aynı süreçte `sys.modules` önbelleği
      yüzünden boşuna geçerdi) ve CI'da koşuyor
- [x] `tests/test_dashboard_pages.py` — `baseline/walk_pages.py` portu, 7 sayfa
      `streamlit.testing.v1.AppTest` ile headless; üretilen geçici `.env` ve
      stub vector store sayesinde ChromaDB/Jira/ağ gerektirmiyor
      (Faz 5B'de dört sayfaya göre yeniden yazıldı ve içerik doğrulaması eklendi)
- [x] CI'a `pytest` + `ruff` adımları (`.github/workflows/tests.yml`)

Yapılmadı — ~~Faz 5'e taşındı~~ **Faz 5 kapandı; bu maddeler Faz 6A'da yeniden
sahiplendirildi** (gerekçeleri `KNOWN-DEBT.md`'de):
- [ ] `tests/test_adf_parser.py` — saf fonksiyon, en yüksek getiri → **Faz 6E**
- [x] `tests/test_anonymizer.py` — **Faz 6B'de yazıldı**, 21 test; sekizi
      yazıldığı gün kırmızıydı. Telefon regex'i düzeltildi, ama bu maddenin
      parantezi YANLIŞTI ve ölçüm onu yalanladı: sürüm numarası, sipariş kodu
      ve tarih zaten maskelenmiyordu. Gerçek kusur üç sınıftı — yedi ve üzeri
      basamaklı kesintisiz rakam dizileri (build no, trace id), üçlü sayı
      grupları (ölçüm, boyut, adet), ve on altı basamaklı bir dizide son dört
      hanenin token'ın yanında kalması. Düzeltme ölçülen davranışa göre
      yazıldı. Ayrıca `deanonymize_text`'in bir oturumun değerini başka bir
      oturumun çıktısına koyduğu sızıntı kapatıldı (`anon_map.json` ile aynı
      çalışma).
- [ ] `pattern_detector` / `component_classifier` testleri
      (`blind_spot_detector` Faz 5A'da karşılandı) → **Faz 6E**
- [x] `compare_service.py` emekliye ayrılırken düşen üç **karşılaştırma
      bölümü**: `risk_for_query`, `defect_density`, `blind_spots` — karşılıkları
      **Faz 5A**'da sıfırdan yazıldı. İki ayrı özne, çelişki değil: düşen şey
      izlenmeyen scratch script'in bölümleriydi (Faz 3'te, Faz 2'de değil); bu
      üçünü sınayan bir **test** ise git geçmişinde hiç var olmadı. Ölçüldü:
      `git log --all --diff-filter=D -- 'tests/*'` boş (hiçbir test dosyası
      silinmemiş), üç terim de `tests/` altına ekleme commit'leriyle girmiş ve
      `baseline/` hiç commit'lenmemiş. Ayrıntı: `KNOWN-DEBT.md`.
- [ ] CI'a `pip-audit` adımı → **Faz 6D** (Dependabot ile aynı çalışma)

Reddedildi (ertelenmedi):
- ~~Kapsam rozeti~~ — yüzde hedefi, kapsamı yükseltmek için zayıf test yazma
  baskısı yaratır. Ölçüt testin gerçekten bir şeyi kontrol etmesi.
  `pytest-cov` kurulu, isteyen elle çalıştırır. Bkz. `KNOWN-DEBT.md`.

### Faz 4 — Veri katmanı (yarım gün)
- [x] **Faz 4(a) PR-1** — ChromaDB toptan silme yerine diff-sync
      (`collection.get` → karşılaştır → `delete` + `upsert`),
      `defect_history_mock` / `defect_history_live` ayrı koleksiyonlar,
      boş-liste koruması ve `ci_analyzer`'ın indekslemeyi atlaması.

      `upsert_bugs()` her çağrıda `reset()` ile başlıyordu ve boş-liste
      kontrolü ondan sonra geliyordu. `refresh_data()` eksik `bugs.json`,
      okunamayan dosya ve yapılandırılmamış Jira için aynı `[]`'i döndürdüğü
      için, bozuk kurulumda `POST /refresh` ve dashboard sync butonu indeksi
      siliyordu. `analysis_service.refresh()` `api.py:99` ile
      `ui/service.py`'deki `get_service()`'in guard'ından yoksundu; artık var ve
      hangi okumayı
      seçtiğini `reindexed` ile bildiriyor. Katman "fetch başarısız" ile
      "gerçekten hiç bug yok"u ayırt **edemediği** için her zaman muhafazakâr
      okumayı seçiyor; indeksi kasten boşaltmak açık bir `reset()` işi.

      Diff karşılaştırması doküman metni **ve** metadata üzerinden yapılıyor.
      `updated` alanı yetmezdi: `classify_bugs()` upsert'ten önce `component`'i
      yerinde değiştirdiği için `COMPONENT_KEYWORDS` değişimi `updated`'ı
      kıpırdatmadan embedding'i bayatlatıyor. `created` ise metadata'da var,
      doküman metninde yok.

      `ci_analyzer` yalnız `calculate_module_stats` ve `calculate_risk_score`
      çağırıyor, benzerlik aramasını hiç kullanmıyor; artık
      `load_bugs(..., index=False)` ile yüklüyor. Temiz CI makinesinde her koşu
      "ilk koşu" olduğu için diff-sync orada zaten kazanç sağlamıyordu, ve
      `:720`'de try/except olmadığından ChromaDB init'i patladığında rapor hiç
      üretilmiyordu — artık patlayacak çağrı yok.

      chromadb 0.5.23'ün dayanılan dört sözleşmesi kaynak okunarak doğrulandı
      ve `vector_store.py` başına `file:line` atıflarıyla yazıldı; sürüm
      yükseldiğinde kontrol noktası olacak. Beşincisi (olmayan bir id'yi
      silmek no-op mu) kaynaktan çözülemedi, tasarımla erişilemez kılındı:
      silinecek id'ler her zaman az önce yapılan `get()`'ten gelir ve bu
      değişmez testle sabit.
- [x] **Faz 4(a) PR-2** — `data/chroma_db` disk ve SQLite temizliği:
      `tests/tools/chroma_cleanup.py`. Rapor modu (varsayılan) ölçer ve hiçbir
      şey yazmaz; `--apply` yazılı onayla siler. Otomatik değil, kasıtlı olarak:
      açılışta sessizce silen bir mekanizma, silme mantığı yanlışsa canlı veriyi
      kimse görmeden götürür.

      Bu satır önceden "9 yetim klasör" diyordu. 2026-08-15'te salt okunur
      ölçüldü (`mode=ro&immutable=1`): 47 klasör / 78.964.700 bayt,
      `chroma.sqlite3` 3.158.016 bayt, 46 klasör hiçbir `segments` satırında
      geçmiyor, 956 yetim `embeddings` ve 6.692 yetim `embedding_metadata`
      satırı, ayrıca `segment_metadata` / `collection_metadata` / `max_seq_id`
      tablolarının her birinde 46 yetim satır — bu üçü keşifte hiç sayılmamıştı.
      Keşfin "6.832 yetim `embedding_metadata`" rakamı tablonun tamamıydı,
      yetim olan 6.692.

      Sıralama kasıtlıydı: temizlik diff-sync'ten önce yapılsaydı kova ilk
      yüklemede yeniden dolardı.

      Silme chromadb'nin API'siyle **yapılmıyor**, olamazdı da. Yetim satırlar
      hiçbir koleksiyona ait olmadığı için `list_collections` onları hiç görmez;
      üstelik `delete_collection` yüklenmemiş bir segmenti diskte bırakarak bu
      yetimleri üreten mekanizmanın ta kendisi (`KNOWN-DEBT.md`). Araç SQLite ve
      dosya sistemine doğrudan yazıyor, chroma'nın kendi silme sırasını
      izleyerek (önce FTS, sonra `embedding_metadata`, sonra `embeddings` —
      `segment/impl/metadata/sqlite.py:595-648`) ve `chromadb`'yi hiç import
      etmeden. `chroma utils vacuum` CLI'si kullanılmadı: `automatically_purge`
      ayarını kalıcı olarak değiştiriyor (`cli/cli.py:168`) ve bir temizlik
      aracı kullanıcının yapılandırmasını değiştirmemeli.

      Silme kararı `plan_sync` kalıbında saf bir fonksiyon (`plan_cleanup`):
      envanter girer, silinecekler listesi çıkar, hiçbir şeye dokunmaz. Karar
      her zaman *korunacaklar* kümesinden türetiliyor, bu yüzden şema büyürse
      araç fazla değil az siler.

      Tanınan koleksiyon yoksa `--apply` reddediyor. "Araç bozuk" (adlar
      değişmiş, şema değişmiş) ile "kullanıcı henüz senkronize etmemiş" aynı
      envanteri üretiyor ve biri her şeyi silmeyi meşrulaştırıyor;
      `upsert_bugs()`'ın boş-liste kararının aynısı. Geliştirici makinesinde
      bugün tam olarak bu durum var — `defect_history_mock` ve
      `defect_history_live` PR-1'den beri hiç `refresh` çalışmadığı için diskte
      oluşmamış — dolayısıyla araç kendi deposuna karşı henüz uygulanmadı.
      PR-2 sonrası ölçümler bir `refresh`'ten sonra alınacak ve
      `KNOWN-DEBT.md`'deki boşluğa girecek.
- [x] **Faz 4(b) Bölüm A** — `ci_analyzer` yanlış pozitif modül eşleşmesi.
      `infer_modules_from_files` yol içinde çıplak alt dizgi arıyordu, bu yüzden
      değişmemiş bir modül hakkında geçmiş bug verisinden risk uyduruyordu:
      `auth` ∈ `docs/probe/auth-probe.md` → Authentication `79/100 HIGH RISK`,
      `ui` ∈ `req**ui**rements.txt` → Frontend. Aynı içerikli ikinci probe
      (`docs/probe/notes.md`) `General` + `No Data` + `LOW RISK` veriyordu, yani
      verdict dosya adına bağlıydı. Düzeltme iki katmanlı: kapsam filtresi
      (`docs/`, `.github/`, `*.md`, `*.txt`, `*.toml`, `*.cfg`, asset uzantıları
      modül çıkarımına hiç girmiyor) ve token sınırı eşleşmesi (anahtar bir yol
      token'ına ya da düzenli çoğuluna eşit olmalı). Eşleşme yoksa rapor artık
      `NOT ASSESSED` yazıyor, `LOW RISK` değil; eşleşen her modülün yanında onu
      üreten dosya ve token gösteriliyor. PR #3'te iki probe ile ölçüldü.
- [x] **Faz 4(b) Bölüm B** — eşleme tahminden yapılandırmaya taşındı.
      Ölçüm: takip edilen 34 `.py` dosyasının 8'i modül üretiyordu ve **1'i
      doğruydu** (`api.py` → API). En pahalısı `api_auth.py`: tek satırlık bir
      değişiklik `auth` token'ı üzerinden Authentication'ı ateşleyip
      `79/100 HIGH RISK` veriyordu — bu dosya aracın kendi `X-API-Key` başlığını
      doğruluyor, bug verisindeki Authentication modülüyle ilgisi yok. `api.py`
      ile `api_auth.py`'yi hiçbir token ayarı ayıramaz; fark dosya adında değil,
      dosyanın ne yaptığında. Dolayısıyla bu, token yaklaşımının tamir edilebilir
      bir hatası değil, sınırıydı.

      `MODULE_KEYWORDS`, `_path_tokens`, `_matched_token`, `EXCLUDED_DIRS` ve
      `EXCLUDED_SUFFIXES` silindi. Yerlerine depo kökünde `module-map.json`:
      `modules` (yol deseni → modül adı) ve `exclude` (kapsam dışı desenler).
      Kapsam da dosyaya taşındı çünkü yanlış pozitiflerin tamamı kapsam
      tarafındaydı; haritayı taşıyıp filtreleri kodda bırakmak kullanıcıya asıl
      kolu vermezdi. Gömülü varsayılan yok — görünmeyen bir kural düzeltilemeyen
      bir kuraldır. `tests/` varsayılan olarak kapsam dışı (ölçümde doğru pozitif
      kaybı sıfır: 2/2 tesadüfi). Çoklu eşleşmede hepsi raporlanır. Eşleşme
      kanıtı artık token yerine deseni gösteriyor:
      `Authentication ← pattern src/auth/** matched src/auth/login.py`.

      Harita yoksa, bozuksa ya da `modules` boşsa modül çıkarımı hiç çalışmıyor;
      rapor üç durumu üç ayrı mesajla söylüyor ve `NOT ASSESSED` veriyor. Çıkış
      kodu 0 kalıyor — aksi halde iş adımı düşer ve açıklamayı taşıyan yorum da
      hiç gönderilmez.

      Gönderilen `module-map.json` bu deponun **kendi** bileşenlerini adlandırıyor
      (`CI Analyzer`, `Dashboard UI`, `API Server`, …), ürün modüllerini değil.
      Sonucu bilinçli: bu deponun PR'ları `Matched, no historical data` +
      `NOT ASSESSED` veriyor. `dashboard.py`'yi `Frontend`'e bağlamak risk
      tablosunu doldururdu, ama oradaki `Frontend` kurgusal bir e-ticaret
      ürününün arayüzü — bu, PR #3 hatasının beyan edilmiş, dolayısıyla görünür
      ama yine de yanlış bir kopyası olurdu. Skorlu yolun kanıtı
      `test_ci_analyzer_report.py::test_scored_report_end_to_end_from_a_map_on_disk`
      testinde, snapshot'tan türetilen `79/HIGH` değeriyle.

      B sonrası ölçüm (`tests/tools/module_map_report.py`): 20 dosya eşleşiyor,
      10 modül, hepsi savunulabilir. `docs/**`, `tests/**` ve `.github/**`
      desenleri bugün hiçbir eşleşmeyi engellemiyor çünkü modül desenlerinin
      tamamı `src/defect_risk_analyzer/` altında — savunma derinliği olarak
      duruyorlar ve bu, paragraf değil test olarak kayıtlı
      (`test_shipped_directory_excludes_are_defence_in_depth`).

  > Eski madde ("`ci_analyzer` modül isimlerini `component_classifier` ile
  > hizala — `API`/`Backend API`, `General`/`Genel` uyuşmazlığı, CI çıktısı şu an
  > boş") yanlış teşhisti ve gözleme dayanmıyordu. CI çıktısı boş değildi,
  > uydurmaydı. Hizalama da yapılmadı: `component_classifier.classify_bugs`
  > yalnızca `component` alanı boş ya da `Unknown` olan bug'a yazıyor,
  > `data/sample_bugs.json`'da 20/20 bug'ın component'i dolu — yani
  > `component_classifier` bu kod yolunda hiç çalışmıyor ve isimlerini hizalamak
  > CI raporunu değiştirmezdi.

### Faz 5 — UI + i18n (2 gün)

Faz 5 üçe bölündü ve üçü de kapandı. **5A** sözleşme, **5B** sayfa birleştirme
ve dosya taşıma, **5C** i18n. Sıra zorunluydu: 5B sayfaları taşıdı ve testsiz
bir davranışı taşımak sessiz kayıp demektir; 5C de taşınmış sayfalar üzerinde
çalıştı.

- [x] **Faz 5A** — `blind_spot_detector` yapısal veri dönüyor: her bulgu
      `recommendation` cümlesi yerine `code` + `params` taşıyor, cümleler
      `ui/messages.py`'ye taşındı. Mimari kural 3 artık bu yolda geçerli.

      Kırılma öngörüldüğü gibi `GET /blind-spots`'a ulaştı. Endpoint dict'i ham
      döndürüyordu — `response_model` yok, model yok — yani sözleşme literal
      dict'in kendisiydi. `BlindSpotReport` kırılmanın olduğu commit'te eklendi
      ve alan kaybı olmadığı round-trip testiyle kanıtlandı.

      Sıra tutuldu: üç regresyon testi yeniden yazımdan **önce** yazıldı, ve
      commit'lerin diff'i cümlelerin yalnız yer değiştirdiğini gösteriyor.
      `ui/` paketi şimdiden açıldı, böylece 5B bu dosyayı taşımak yerine
      yanına ekleyecek. `dashboard.py`'ye dokunuş üç render satırı + bir import.

      Karar: `page_setup_wizard` ayrı kalıyor, Ayarlar'a katlanmıyor. Wizard bir
      sayfa değil bir akış — sidebar'dan seçilmiyor, `is_first_run()` ile
      koşullu çalışıyor, işi bitince görünmüyor. "7→4 sayfa" hedefiyle aynı
      kategoride değil. 5B'nin kapsamı için kayda geçti.
- [x] **Faz 5B** — sayfa birleştirme, native `pages/`, dosya taşıma, lint temizliği
- [x] 7 sayfa → 4: Genel Bakış · Buglar · Analiz · Ayarlar

      Gruplama verinin kaynağına göre: Genel Bakış ve Kör Nokta mevcut veriyi
      okuyup raporluyor, LLM çağırmıyor; Canlı Analiz ve Webhook aynı
      `display_analysis_result`'ı paylaşıyor. Her eski sayfa başlığı bir sekme
      etiketi olarak yaşıyor. `page_setup_wizard` 5A kararı gereği ayrı akış
      olarak kaldı ve hedef sayıya dahil değil.

      İki bilinçli davranış değişikliği: Canlı Analiz'in iç sekmeleri üst düzeye
      çıktı (bir tık azaldı, "Canlı Analiz" adı arayüzden kalktı), ve LLM guard'ı
      artık sayfayı değil yalnız iki analiz sekmesini kesiyor — eski hâli merge
      sonrası webhook geçmişini de gizlerdi, oysa o LLM'siz okunabilir.
- [x] Streamlit native `pages/` yapısı; string eşlemeli router'ı sil

      `st.navigation` **değil** `pages/` dizini seçildi. Streamlit 1.41.1'in
      `AppTest`'i `st.navigation`/`st.Page` ile uyumsuz olduğunu kendi
      docstring'inde söylüyor (`testing/v1/app_test.py:129`) ve sebebi yapısal:
      `st.Page` URL yolunu hash'liyor, `AppTest.switch_page` mutlak dosya yolunu.
      `st.navigation` ile dört sayfanın üçü test edilemez olurdu.

      Yerleşik `pages/` navigasyonu kapalı, `shell.render_nav()` dört
      `st.page_link` çiziyor. MPA-v1 giriş dosyasını her zaman listenin başına
      koyduğu için aksi hâlde sidebar'da "app" yazan beşinci bir madde çıkardı;
      ayrıca bu sayede `bootstrap()` wizard yolunda `st.stop()`'u nav'dan önce
      çağırabiliyor ve sidebar eskisi gibi bomboş kalıyor. Bedeli
      `KNOWN-DEBT.md`'de kayıtlı: `st.page_link`'i yalnız kaynak okuyan bir test
      koruyor.
- [~] 110 satırlık gömülü CSS → `.streamlit/config.toml` teması

      **Bu madde yazıldığı gibi tutulamadı; kabul edilmiş sapma.** Streamlit
      1.41.1'de `[theme]` bölümü tam **altı** seçenek sunuyor (`base`,
      `primaryColor`, `backgroundColor`, `secondaryBackgroundColor`, `textColor`,
      `font` — `config.py:958`). Gömülü bloğun **21 kuralının 0'ı** bunlarla
      ifade edilebiliyor: beşi eleman gizliyor, on üçü geometri/tipografi ölçeği,
      üçü element-başına alfa metin rengi ve `textColor` global. `borderColor`,
      `baseRadius`, `headingFont` gibi seçenekler bu sürümde **yok**.

      Yapılan: CSS `ui/theme.py::inject_css()`'e taşındı — import anındaki yan
      etki açık bir çağrıya döndü, ki `st.set_page_config`'in ilk çağrı olma
      zorunluluğu bunu gerektiriyordu. `config.toml`'a giren tek tema ayarı
      `base = "dark"`: blok baştan sona `rgba(255,255,255,a)` bindirmesi, yani
      koyu bir zemin varsayıyordu ama bunu hiçbir yerde sabitlememişti — teması
      açık çözülen kullanıcı beyaz üstüne beyaz görüyordu.

      Kalan iş: kuralların gerçekten temaya çevrilmesi bir tasarım işi, sürüm
      yükseltmesi de gerektirebilir. Sahipli bir faza bağlanmadı.
- [x] **Faz 5C** — `locales/{tr,en}.json`, `t()`, sidebar'da dil seçici

      Ölçüm 5B öncesine aitti ve yenilendi: `ui/` altındaki sekiz dosyada
      **227 çağrı yeri / 207 farklı dize** (288 rakamı `dashboard.py`
      dönemindendi). 251 anahtar, iki locale'de de aynı küme.

      `ui/i18n.py` streamlit import etmiyor: aktif dil bir modül global'i,
      `bootstrap()` her koşuda `session_state`'ten set ediyor. Bedeli budur ki
      locale sözleşmesinin 40+ testi `AppTest` maliyeti olmadan koşuyor;
      çok oturumlu yarış `KNOWN-DEBT.md`'de.

      5A'nın açık bıraktığı fallback sorusu kapandı: bir locale'de eksik
      anahtar kaynak dile düşüyor + uyarı, her ikisinde de eksik anahtar
      `UnknownMessageKey` fırlatıyor. Birinci yol sevk edilen üründe
      erişilemez, çünkü `test_locale_key_sets_match` iki dosyanın anlaşmasını
      zorunlu kılıyor — yani fallback bir mazeret değil güvenlik ağı.

      **Katman 2 çözüldü:** DataFrame kolonları artık İngilizce ve sabit;
      etiket `column_config` ve `labels=` ile render anında veriliyor. Önceden
      kolon adı etiketin kendisiydi (`px.bar(x="Risk Skoru")`), yani dil
      değiştirmek veri çerçevesini değiştirmek demekti. Ölçüm: streamlit
      1.41.1 `column_config`'i DataFrame'e karşı **hiç doğrulamıyor**, yanlış
      anahtar sessizce ham kolon adını başlık bırakıyor — bu yüzden her
      sayfadaki her tablo için anahtarların gerçek kolon olduğunu doğrulayan
      bir test var.

      **Beyan edilmiş metin değişikliği:** risk seviyeleri Türkçe arayüzde
      artık KRİTİK / YÜKSEK / ORTA / DÜŞÜK. Aynı ekranda pattern önemleri
      zaten öyleydi. Değer katmanı (`core/scoring.py`, `BlindSpotReport`,
      API yanıtları, `tests/data/`, `RISK_COLORS` anahtarları) İngilizce
      kaldı; çeviri yalnız render anında. Renk haritası İngilizce
      anahtarlardan **türetiliyor**, tersi değil.

      **İkinci beyan edilmiş değişiklik:** kör nokta cümlesi ve Önerilen
      Aksiyonlar satırı "Canlı Analiz sayfasından" diyordu — 5B o sayfa adını
      kaldırmıştı, yani cümle var olmayan bir sayfaya yönlendiriyordu.
      "Analiz sayfasından" oldu, kendi commit'inde.

      Taşıma üç kusur ortaya çıkardı, ikisi i18n olmadan görünmezdi:
      `"Demo" in mode`, `analysis_type == "Bug Key ile"` (İngilizce arayüzde
      tekli analizi sessizce bozardı) ve ölü `col.rank` anahtarı. Kalıp hatası
      `KNOWN-DEBT.md`'de kayıtlı — bu depoda üçüncü kez.

      `pattern_detector` de 5A muamelesi gördü (`code` + `params`,
      `PatternResponse` + `response_model=`). `component_classifier`
      **bilinçli olarak** görmedi: anahtarları Jira bileşen adlarıyla eşleşmek
      zorunda, listelerdeki Türkçe bug metnine karşı arama anahtarı, ve tek
      çıktısı `"Genel"` bir modül **adı** — cümle değil. Gerekçe commit
      mesajında ve `KNOWN-DEBT.md`'de.

      363 → 440 test.
- [ ] Renk sadece risk seviyesini kodlasın → 5B kapsamına alınmadı
- [x] `data/sample_bugs_en.json` (İngilizce demo için)

      Brifing "demo veri tamamen İngilizce" diyordu; ölçüm tersini gösterdi —
      20 bug'ın 20'sinin `summary`/`description`'ı **Türkçe**, İngilizce olan
      yalnız `component`/`priority`/`status` enum'ları. Yani bu bir çeviri
      işiydi, kopya değil.

      Sadece prose çevrildi (`summary`, `description`, `assignee`, `reporter`);
      `key`, `created`, `updated`, `priority`, `status`, `component`,
      `resolution`, `labels` kaynak dict'ten kopyalandı. Denklik testi bunu
      türeterek doğruluyor: yedi skorlama alanı bug bug eşit, dört prose alanı
      gerçekten değişmiş, `calculate_module_stats` + `calculate_risk_score`
      bit bit aynı, **ve** ikisi de `tests/data/scores-aff55c6-now2026-04-01.json`
      ile hâlâ uyuşuyor. Snapshot yalnız okunuyor.

      Hangi dosyanın yükleneceği `config.LANGUAGE`'ten, canlı oturum dilinden
      değil: canlı dile bağlamak her geçişte servis cache'ini temizlemek, yani
      ChromaDB'ye yeniden indekslemek demekti — Faz 4(a)'nın kaldırdığı sessiz
      yan etkinin yeni tetikleyicisi. Demo veri bir sonraki açık
      senkronizasyonda ya da açılışta değişiyor.

      **Düzeltme (5C sonrası):** bu vaadin senkronizasyon yarısı kapanışta
      **çalışmıyordu**. Seçici `.env`'e `config.set_env_value` ile yazıyordu; o
      çağrı dosyayı ve `os.environ`'ı güncelliyor ama `config.LANGUAGE` modül
      global'ini bırakıyor. `LANGUAGE`'ı yazan tek yer `reload()`, seçici onun
      yolunda değil, `init()` de `_initialized` bayrağıyla korunduğu için asla
      yetişmiyor. Sonuç: `LANGUAGE` sürecin açıldığı değerde donuyor ve
      `sample_bugs_file()` o donmuş değeri okuyor.

      Bu bir EN→TR hatası değildi. Ölçüm iki yönde de aynı sonucu verdi:
      **seçicinin veri seçimine katkısı sıfırdı.** Sürecin açıldığı dile geçmek
      çalışıyormuş gibi görünüyor (`LANGUAGE` zaten o değerde), o dilden çıkmak
      hiçbir zaman çalışmıyor. "Çalışan" durum tesadüftü. Kaza onarım yolu da
      vardı: Ayarlar'da herhangi bir kayıt `save_multiple_env` → `reload()`
      üzerinden global'i sessizce düzeltiyor, bu da hatayı "bazen oluyor" gibi
      gösteriyordu.

      `config.persist_language()` eklendi — `ensure_api_key()` ile aynı şekil:
      dosyayı yaz, sahibi olduğun tek global'i güncelle. `reload()` değil; o on
      yedi ayarı diskten yeniden okur ve bir sunum kontrolünün Jira kimlik
      bilgilerini yeniden okumakta işi yok. LLM sağlayıcısı düşmüyor: `_llm`'i
      düşüren tek şey `reset_llm()` ve bu yolda değil. Faz 4(a) kararı da
      korunuyor — seçici hâlâ hiçbir şey indekslemiyor, servis cache'ini hâlâ
      temizlemiyor; yeniden indeksleme yalnız kullanıcının açık senkronizasyon
      tıklamasında oluyor.

      Ölçüldü: düzeltmeden sonra **senkronizasyon tek başına yetiyor**, yeniden
      açılış gerekmiyor. Seçiciye ayrıca yönlendirici bir `help` metni eklendi
      (moda göre iki cümle); daha önce hiç yoktu, yani vaat hiçbir kullanıcı
      yüzeyinde yazılı değildi. 440 → 445 test.
- [ ] N+1 API çağrısı ve her render'daki `config.reload()` düzeltmesi

      Faz 5B notu: **ölçülmedi**, muhtemelen bayat. `config.init()`
      `_initialized` bayrağıyla korunuyor (`config.py:295-319`) ve `reload()`
      yalnız `save_multiple_env` içinde çağrılıyor. Kapatmadan önce ayrı bir
      ölçüm gerekiyor.

### Faz 6 — Güven katmanı (yarım gün)
- [x] **Faz 6A — `.env` tekilleştirme ve yapılandırma bütünlüğü.**
      `set_env_value()` artık dotenv'in okuduğu **son** satırı yazıyor; önceki
      mükerrerleri silmiyor, işaretleyip yorumluyor. Yazma atomik (`.env.tmp` +
      `os.replace`), kodlama iki tarafta da açıkça UTF-8, satır sonu ve POSIX
      izin bitleri korunuyor. `BASLAT.bat`'ın her taze kurulumda mükerrer
      `USE_MOCK_DATA` üreten append bloğu kaldırıldı — o satır `is_first_run()`
      üzerinden ilk kurulum sihirbazını da atlatıyordu. Bir AST bekçisi sekiz
      giriş noktasının `config.init()`'e ulaştığını CI'da doğruluyor.
      445 → **473 toplanan test** (biri Windows'ta atlanıyor: POSIX izin testi,
      CI'da koştuğu henüz doğrulanmadı). Kalan borçlar: `KNOWN-DEBT.md`.
- [x] **Kimlik bilgilerini `keyring`'e taşı** — Faz 6B. İki katmanlı: keyring
      varsa ve backend çözülüyorsa orada, aksi hâlde `.env`, ve Ayarlar hangi
      katmanın kullanıldığını yazıyor. `keyring` ayrı bir extra (`desktop`);
      `requirements.txt`'e girmiyor çünkü Linux'ta çalışamayacağı yerlere
      `SecretStorage` + `jeepney` getiriyor.
- [x] `SECURITY.md` — Faz 6B'de ölçümlerden türetildi, önce yazılıp sonra
      doğrulanmadı. Desteklenemeyen on bir iddia kasten dışarıda bırakıldı;
      hangilerinin neden yazılmadığı keşif kaydında duruyor.
- [ ] Dependabot etkinleştir
- [ ] `CONTRIBUTING.md`, issue şablonları

### Faz 7 — Vitrin (yarım gün)
- [ ] README sıfırdan: tek cümlelik tanım, GIF/ekran görüntüsü, tek satır kurulum, gerçek rozetler
- [ ] `README.tr.md`
- [ ] `CHANGELOG.md` + `v1.0.0` git tag + GitHub Release
- [ ] Streamlit Cloud demo — sadece mock data, kimlik bilgisi girişi kapalı
- [ ] **`desktop` extra'sını bu makineye kur ve 6B'nin taşımasını canlıda
      doğrula.** PR #17 extra'nın beyan edildiğini ve geçici bir venv'de
      kurulduğunu kanıtladı — `keyring` geliyor, backend çözülüyor. Taşımanın
      kendisi bugüne kadar hiç koşmadı: `keyring` kurulamadığı sürece
      `resolve_store()` her zaman `no_keyring` döndü ve `bootstrap()` taşımayı
      hiç denemedi. Ayrı bir iş değil — aşağıdaki kalite kontrol listesinin
      "temiz makinede `pipx install` → `dra` → 5 dakikada çalışan dashboard"
      denemesinin içinde yapılır, ve aynı listenin kimlik bilgileri maddesinin
      prosedürüdür; o maddeyi tekrarlamaz.

      `pip install -e ".[desktop]"` → dashboard → sırayla:

      1. Üç sır kimlik deposuna taşınıyor mu — `JIRA_API_TOKEN`,
         `GROQ_API_KEY`, `API_KEY`.
      2. `.env`'de o üç satırın değeri boşalıyor mu, anahtar kalıyor mu.
      3. Marker taşıyan yorumlanmış `API_KEY` satırının değeri boşalıyor mu —
         satır kalır, değer gitmelidir.
      4. Ayarlar `store_active` katmanını ve çözülen backend adını gösteriyor
         mu.

      **Kurulum yolu Faz 7'de kararlaştırılacak.** Yukarıdaki komut geliştirici
      kurulumu (`pip install -e`); kalite kontrol listesi ise `pipx install` →
      `dra` yolunu tarif ediyor. İkisi farklı kurulum yolları, ve `pipx`
      üzerinden bir extra'nın nasıl kurulacağı bugün ölçülmedi. Hangisinin —
      ya da ikisinin de — deneneceği o zaman kararlaşır; aşağıdaki taşıma
      gözlemleri seçilen yola bağlı değil.

      **Sıra sözleşmedir**: store'a yaz → geri oku ve doğrula → `.env`'i
      boşalt. Bu yüzden ikinci gözlem birincisi olmadan hiçbir şey söylemez —
      boşalmış bir `.env` satırı, değerin başka bir yerde tutulduğunun kanıtı
      değildir; yalnız burada olmadığının kanıtıdır.

      Üçüncü gözlemin beklentisi tahmin değil, koddan okundu:
      `set_env_value`'nun boşaltma dalı (`config.py:353-357`) daha önce
      yorumlanmış satırları da boşaltıyor, ve oradaki yorum bu dalın tam
      olarak keyring taşıması için yazıldığını söylüyor.

      Başlangıç durumu (bu makinenin `.env`'i, gitignore'da): üç anahtarın
      üçü de dolu, `OPENAI_API_KEY` boş olduğu için kapsam dışı, ve marker
      taşıyan yorumlanmış bir `API_KEY` satırı değerini hâlâ tutuyor.
      Ertelemenin ikinci gerekçesi de bu: bu makinenin `.env` katmanında
      kalması 6D-3'ün bağımlılık pinleme ölçümlerine zemin sağlıyor.

---

## Kalite kontrol listesi (bitişte)

- [ ] Temiz bir makinede `pipx install` → `dra` → 5 dakikada çalışan dashboard
- [ ] Windows, macOS, Linux üçünde de çalışıyor
- [ ] Hiçbir `.bat` dosyasına bağımlılık yok
- [ ] README'deki her komut gerçekten çalışıyor
- [ ] Her rozetin arkasında gerçek bir CI çalışması var
- [ ] Yapılandırılmış kimlik bilgileri masaüstü kurulumunda keyring'de; keyring
      backend'i çözülemediğinde `.env`'e düşülüyor ve kullanıcıya hangisinin
      kullanıldığı söyleniyor. Docker ve CI `env_file`/ortam değişkeni yolunu
      kullanır — bu yollarda taahhüt geçerli değil.
- [ ] Çalışma zamanı artıklarında sır tutulmuyor: `anon_map.json` yazılmıyor,
      loglar ve `analysis_results.json` ham kullanıcı metni saklamıyor.
- [ ] `core/` içindeki hiçbir dosya dış dünyayı import etmiyor
