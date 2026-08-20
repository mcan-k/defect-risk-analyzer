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

**Faz 4(b) Bölüm B genişletmesi:** artık `data/` ve `.env` yalnız değil —
`module-map.json` da `BASE_DIR`'den çözülüyor (`config.MODULE_MAP_FILE`). Dosya
`src/` dışında, depo kökünde durduğu için wheel'e paket verisi olarak **girmiyor**;
bu kasıtlı, çünkü kullanıcı yapılandırması, paket varlığı değil. Sonuç: proje ağacı
olmayan bir `pip install .` kurulumunda harita bulunamaz ve `ci_analyzer` modül
çıkarımı yapmadan `NOT ASSESSED` raporlar. Sessiz değil — `ModuleMapMissing`
mesajı hem beklenen yolu hem `DRA_BASE_DIR`'i adlandırıyor. Kaynak checkout'ta,
editable kurulumda ve Docker imajında ikinci kural kazandığı için sorun görünmez;
`pr-risk-analysis.yml` de `actions/checkout` + `pip install -e .` kullandığı için
CI etkilenmiyor.

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

---

## Failed result writes are logged, not surfaced

**Where:** [`src/defect_risk_analyzer/adapters/results_repository.py`](../src/defect_risk_analyzer/adapters/results_repository.py)

`_write_json()` bir `OSError` yakaladığında hatayı logluyor ve `False` dönüyor.
`AnalysisService` bu dönüşü kontrol edip uyarı basıyor, ama **çağırana bir şey
söylemiyor**: analiz sonucu normal şekilde dönüyor, HTTP 200 çıkıyor, dashboard
sonucu gösteriyor. Disk doluysa ya da dosya sistemi salt-okunursa kullanıcı
LLM kotasını harcamış ama sonucu kaybetmiş olur ve bunu ancak sayfayı
yenilediğinde fark eder.

**Detail:** Faz 2 Adım 1b bu davranışı bilerek korudu. Fırlatmaya çevirmek
`/analyze` ve `/webhook/jira` uçlarının sözleşmesini değiştirirdi — bugün 200
dönen bir çağrı 500 dönmeye başlardı — ve bu değişikliği yakalayacak bir test
yok. Refactor'ün davranış-koruyan kalması önceliklendirildi.

**Impact:** sessiz veri kaybı, yalnız disk hatası durumunda. Log'da `ERROR`
kaydı kalıyor.

**Planned fix (Phase 3):** testler geldikten sonra sonuç sözlüğüne `persisted`
alanı ekle ya da yazma hatasını fırlat; UI kullanıcıya "sonuç kaydedilemedi"
uyarısı göstersin.

---

## Duplicate `API_KEY` lines in `.env`

**Where:** `.env` (kullanıcı dosyası) ve
[`src/defect_risk_analyzer/config.py`](../src/defect_risk_analyzer/config.py)

`.env` iki `API_KEY=` satırı içerebiliyor: biri `.env.example`'dan gelen boş
satır, diğeri eski otomatik üretimin dosya sonuna eklediği dolu satır. Bugün
doğru anahtar okunuyor çünkü `python-dotenv` aynı anahtarın **sonuncusunu**
kazandırıyor — yani davranış satır sırasına bağlı, tasarıma değil.

**Detail:** `config.set_env_value()` replace-or-append çalışıyor ve **ilk**
eşleşen satırı güncelliyor. Mükerrer satır varsa yeni değer boş olan üstteki
satıra yazılır, alttaki eski satır olduğu yerde kalır ve `reload()` sonrasında
yine o kazanır. Ayarlar sayfasındaki "API Key Yenile" butonu bu durumda
başarılı görünür (yeni key ekranda gösterilir, `os.environ` güncellenir) ama
bir sonraki `reload()`'da eski anahtara geri döner. Sessiz geri alma.

**Impact:** yalnız mükerrer satırı olan `.env` dosyalarında. Anahtar üretimi
artık örtük olmadığı için yeni kurulumlarda mükerrer satır oluşmuyor;
sorun mevcut dosyalardan miras.

**Workaround until then:** `.env` içindeki boş `API_KEY=` satırını elle silin.

**Planned fix (Phase 6):** kimlik bilgileri `keyring`'e taşınırken `API_KEY`
de `.env`'den çıkacak. O zamana kadar `set_env_value()` mükerrer satırları
tespit edip tekilleştirebilir.

---

## Sidebar connection indicators show presence, not validity

**Where:** [`src/defect_risk_analyzer/ui/shell.py`](../src/defect_risk_analyzer/ui/shell.py)

Sidebar'daki "✅ Jira: Bağlı" ve "✅ LLM: Groq" göstergeleri
`config.is_jira_configured()` / `config.is_llm_configured()` sonucunu
gösteriyor. Bu iki fonksiyon yalnızca **anahtarın dolu olup olmadığına**
bakıyor, geçerli olup olmadığına değil.

**Detail:** doğrulandı — ölü bir Jira token'ı ve ölü bir Groq anahtarıyla,
ikisi de 401 dönerken sidebar her ikisini de yeşil gösteriyordu. Kullanıcı
sistemi çalışır sanıp analiz başlatıyor ve hatayı ancak LLM çağrısı
başarısız olduğunda görüyor. Ayarlar sayfasındaki "Bağlantıyı Test Et"
butonları gerçek doğrulamayı yapıyor, ama sonucu hiçbir yerde saklamıyor.

**Impact:** yanlış güven. Fonksiyonel bir hata değil, ama arıza teşhisini
zorlaştırıyor.

**Planned fix (Phase 5):** UI bölünürken dört durum ayrılacak —
*yapılandırılmamış* / *kontrol edilmedi* / *geçersiz* / *doğrulanmış*. Ağ
doğrulaması `core/` katmanına giremez (bağımlılık kuralı), bu yüzden bir
adapter üzerinden ve her render'da değil; açık bir tetikleyiciyle ya da
önbelleğe alınmış sonuçla çalışmalı.

---

## The webhook extra is a declaration, not a physical separation

**Where:** [`requirements.txt`](../requirements.txt),
[`requirements-webhook.txt`](../requirements-webhook.txt)

Faz 2 Adım 4 `fastapi`, `uvicorn`, `pydantic` ve `httpx`'i `requirements.txt`
dışına, opsiyonel `webhook` ekstrasına taşıdı. Ama `chromadb` bu paketlerin
**dördünü de kendi bağımlılığı olarak** çekiyor, dolayısıyla ekstra
kurulmasa bile ortamda bulunuyorlar. Kurulum boyutu azalmadı.

**Detail:** `pip show chromadb` → `Requires: fastapi, httpx, pydantic,
uvicorn, opentelemetry-instrumentation-fastapi, ...`. Yalnız `requirements.txt`
ile kurulan temiz bir sanal ortamda dördü de mevcut.

**Impact:** ayrım gerçek ama **kod düzeyinde**, paket düzeyinde değil. Değeri
şurada: niyet açıkça yazılı, `pip install -e ".[webhook]"` çalışıyor, ve
çekirdek kod yolu bu modüllere hiç dokunmuyor —
`baseline/check_core_boundary.py` importları loader seviyesinde engelleyip
bunu doğruluyor. "Çekirdek ortamda fastapi yok" iddiası ise **yanlış olur**.

**Follow-up (Faz 2 kapanışı):** ilk halinde `requirements-webhook.txt` bu dört
paketi `==` ile sabitliyordu ve Docker build'i onları iki kez kuruyordu:
`chromadb` en güncelini çekiyor (fastapi 0.141.1, pydantic 2.13.4,
starlette 1.6.0, uvicorn 0.52.1), ardından ikinci `pip install` bunları
kaldırıp eski pinleri geri koyuyordu. Tesadüfen çalışıyordu çünkü
0.115.6 ≥ 0.95.2; `chromadb` tabanını yükseltseydi sessizce uyumsuz hale
gelirdi. Düzeltildi: pinler alt sınıra çevrildi ve iki dosya **tek bir pip
çağrısında** kuruluyor, böylece çözümleme bir kez yapılıyor ve gerçek bir
çakışma build'i sessizce geçmek yerine düşürüyor.

**Planned fix:** yok — `chromadb` bağımlılığı sürdükçe paket düzeyinde ayrım
çözülemez. Faz 4'te vektör katmanı ele alınırken daha hafif bir istemci
değerlendirilirse bu da kendiliğinden düzelir. Alt sınırlar sabitleme
sağlamadığı için, yeni bir fastapi sürümünün `api.py`'yi bozmasına karşı asıl
koruma Faz 3'teki testler olacak.

---

## Two processes share one ChromaDB directory

**Where:** [`docker-compose.yml`](../docker-compose.yml),
[`src/defect_risk_analyzer/adapters/vector_store.py`](../src/defect_risk_analyzer/adapters/vector_store.py)

`docker-compose --profile webhook up` çalıştırıldığında dashboard ve API
servisleri `app-data` volume'ünü paylaşıyor, yani ikisi de aynı
`data/chroma_db` dizinine bağlanıyor.

**Detail:** Faz 2 Adım 2 doğrulaması sırasında gerçek bir arıza olarak
görüldü: ikinci bir process veri yükleyince canlı dashboard'un Pattern
sayfası `Collection ... does not exist` verdi ve o oturum boyunca bozuk
kaldı. Sebebi, bir tam veri yüklemesinin (`load_bugs` → `VectorStore.reset()`)
koleksiyonu silip yeniden yaratması, o sırada yükleme yapmayan tarafın
elindeki tanıtıcıyı geçersiz bırakmasıydı. `VectorStore._run()` bu hatayı
tanıyıp istemciyi ve tanıtıcıyı düşürerek bir kez yeniden deniyor, dolayısıyla
kullanıcıya yansıyan kalıcı bozulma giderildi.

**Faz 4(a) PR-1 sonrası:** olağan bir yükleme artık hiçbir şeyi toptan
silmiyor. Diff-sync yalnız değişen id'leri `upsert`, gelen listede olmayanları
`delete` ediyor; mock ve canlı veri de ayrı koleksiyonlarda. Tanıtıcıyı
geçersiz kılan silme-yeniden-yaratma yalnız açık bir `reset()` çağrısında
kaldı ve `reset()`'in `src/` içinde çağıranı yok. Yani yukarıdaki arızayı
üretmek için birinin `reset()`'i kasten çağırması gerekiyor.

**Impact:** yarış daraldı, bitmedi. İki process aynı anda senkronize ederse
`get()` ile `upsert`/`delete` arasına girmek hâlâ mümkün: A tarafı mevcut
durumu okur, B tarafı yazar, A eskimiş bir plana göre siler. Kaybedilen kayıt
bir sonraki senkronizasyonda geri gelir — eskisi gibi oturum boyu süren
bozulma değil, tek turluk bayatlama. SQLite kilit çakışması da teorik olarak
mümkün. Varsayılan `docker-compose up` tek servis çalıştırdığı için normal
kullanımda görülmez; yalnız `webhook` profili açıkken geçerli.

`_run()`'ın stale-handle kurtarma dalı bu yüzden korunuyor: tam olarak
`reset()` yaşadığı sürece yük taşıyor. `reset()` bir gün silinirse kurtarma
dalı aynı commit'te silinmeli — not `_run()`'ın docstring'inde duruyor.

**Workaround until then:** iki profil birlikte çalışıyorken veri
senkronizasyonunu tek taraftan yapın.

**Planned fix:** kalan yarış için tek yazar kilidi ya da tek yönlü
senkronizasyon gerekir. Varsayılan kurulum tek servis çalıştırdığı ve kalan
etki tek turluk bayatlamaya indiği için önceliklendirilmedi; bir faza
bağlanmadı.

---

## `delete_collection` yüklenmemiş segmenti diskte bırakıyor

**Where:** `data/chroma_db` (izlenmiyor, `.gitignore`'da), chromadb 0.5.23

Bir koleksiyon silindiğinde HNSW segment klasörü ve `embeddings` satırları
diskte kalabiliyor. `SegmentAPI.delete_collection` (`api/segment.py:376-390`)
önce `sysdb.delete_collection` ile defter kaydını siliyor, sonra
`manager.delete_segments` çağırıyor; ama `LocalSegmentManager.delete_segments`
asıl silmeyi `if segment["id"] in self._instances` koşulunun içinde yapıyor —
yani segment o süreçte daha önce **yüklendiyse**. Koleksiyonu hiç okumamış taze
bir istemci sildiğinde `_instances` boştur: `collections` ve `segments` satırları
gider, klasör ve `embeddings` satırları yetim kalır.

Faz 4(a) PR-1 öncesi her yükleme koleksiyonu silip yeniden yarattığı için bu
mekanizma yükleme başına bir klasör biriktirdi.

**Detail:** 2026-08-15'te geliştirici makinesinde (PR-2 öncesi) ölçüldü:
47 segment klasörü / 78.964.700 bayt, `chroma.sqlite3` 3.158.016 bayt
(771 sayfa, `auto_vacuum` 0, `freelist_count` 0). 46 klasör hiçbir `segments`
satırında geçmiyordu; 976 `embeddings` satırının 956'sı, 6.832
`embedding_metadata` satırının 6.692'si yetimdi; `segment_metadata`,
`collection_metadata` ve `max_seq_id` tablolarının her birinde 46 yetim satır
vardı. ROADMAP bu klasör sayısını önce 9 olarak kaydetmişti; arada büyümüş.
Sayılar geliştirici makinesine özgüdür — dizin izlenmiyor.

Cascade'e güvenilemiyor: `collection_metadata.collection_id` DDL'de
`ON DELETE CASCADE` taşıdığı ve chroma `PRAGMA foreign_keys = ON` yaptığı
(`db/impl/sqlite.py:102`) hâlde 46 yetim satır ölçüldü. Nedeni araştırılmadı —
`segments.collection` var olmayan bir tabloya işaret ediyor
(`REFERENCES collection(id)`, tablo adı `collections`), pragma bağlantı başına
ve satırlar pragma'sız bir bağlantıdan silinmiş olabilir. Araç bu yüzden hiçbir
cascade'e güvenmiyor, her yan tabloyu açıkça siliyor ve sonrasında doğruluyor.

**Impact:** yalnız disk; okunan hiçbir şey etkilenmiyor. Artık araçla
temizlenebiliyor ama **tekrar birikiyor**: `reset()` ya da elle bir
`delete_collection` her çağrıldığında aynı mekanizma bir klasör daha bırakır.
Faz 4(a) PR-1 sonrası olağan yüklemeler diff-sync yaptığı için birikme hızı
yükleme başına birden sıfıra indi, ama sıfırlanmadı.

**Workaround:** [`tests/tools/chroma_cleanup.py`](../tests/tools/chroma_cleanup.py).
Varsayılan mod ölçer ve yazmaz; `--apply` açık onayla siler. Tanınan koleksiyon
bulunmazsa uygulamayı reddeder — "araç bozuk" ile "kullanıcı henüz senkronize
etmemiş" aynı envanteri ürettiği için. Dizin `.gitignore`'lu ve tek bir
`refresh` ile yeniden üretilebilir, geri dönüş güvencesi budur.

**Kapandı (Faz 4(a) PR-2):** terk edilmiş `defect_history` koleksiyonunun
kendisi. Araç onu siliyor; ayrı bir borç olarak izlenmesi gerekmiyor.

**PR-2 sonrası ölçüm (2026-08-15, geliştirici makinesi):** araç bir `refresh`
sonrası gerçek dizine karşı uygulandı. `refresh` `defect_history_mock`
koleksiyonunu oluşturdu, böylece araç artık tanıdığı bir koleksiyon buldu ve
reddetmeyi bıraktı.

| | Temizlik öncesi | Sonrası |
|---|---|---|
| Segment klasörü | 48 (47 yetim + 1 canlı) | 1 (`defect_history_mock`) |
| `chroma.sqlite3` | 3.321.856 bayt / 811 sayfa | 1.241.088 bayt / 303 sayfa |

Silinen: 47 klasör / 78.964.700 bayt. Satırlar — `embedding_fulltext_search`
976, `embedding_metadata` 6.832, `embeddings` 976, `embeddings_queue` 20,
`max_seq_id` 47, `segment_metadata` 47, `segments` 2, `collection_metadata` 47,
`collections` 1.

`chroma.sqlite3` VACUUM ile 2.080.768 bayt (508 sayfa) küçüldü; klasörlerle
birlikte toplam 81.045.468 bayt geri alındı. Yeniden koşturulan rapor modu
`DROP 0` diyor ve tüm satır sayaçları sıfır.

Silme doğrulandı: dashboard 20 bug gösteriyor, örüntü tespiti çalışıyor,
AP-104 için benzerlik araması %75-78 skorlarla 5 sonuç döndürüyor — yani VACUUM
sonrası HNSW indeksi sağlam ve canlı koleksiyon zarar görmemiş.

Ayrıca canlıda doğrulandı: **kova artık dolmuyor.** İki ardışık yükleme arasında
klasör sayısı 1'de kaldı. Faz 4(a) PR-1'in diff-sync iddiası ölçümle tutuyor —
yukarıdaki "tekrar birikiyor" uyarısı olağan yüklemeler için değil, yalnız
`reset()` ya da elle bir `delete_collection` çağrıldığı durumlar için geçerli.

**Küçük çıktı tutarsızlığı:** temizlik sonrası raporda `embeddings_queue` ve
`collections` satırları hiç listelenmiyor, önceki raporda vardı. Sebebi
`deletion_statements`: bu iki yüklem yalnız düşecek koleksiyon varken listeye
ekleniyor, düşecek koleksiyon kalmayınca satırları da kayboluyor. İşlevsel bir
sorun değil — her iki durumda da silinecek satır sıfır — ama tablonun şekli
koşudan koşuya değişiyor.

---

## ~~Retiring `compare_service.py` drops three regression checks~~ — Faz 5A'da kapatıldı

**Where:** [`tests/test_blind_spots.py`](../tests/test_blind_spots.py),
[`tests/test_analysis_service_query.py`](../tests/test_analysis_service_query.py),
[`tests/test_risk_summary_contract.py`](../tests/test_risk_summary_contract.py)

Faz 3, `baseline/compare_service.py`'yi emekli etti. O script beş bölümü
refactor öncesi `RiskAnalyzer` ile karşılaştırıyordu; yeni test paketi bunların
ikisini devraldı, biri kısmen karşılandı, **üçü karşılıksız kaldı**:
`risk_for_query`, `defect_density`, `blind_spots`.

Emekli etmek yine de doğruydu: script eski `RiskAnalyzer`'ı
`git show <ref>:...` ile git geçmişinden yüklüyordu, yani geçmiş yaşlandıkça
çürüyor ve CI'da hiç koşamıyordu.

**Faz 5A kapanışı.** Üçü de karşılandı, `blind_spot_detector` yeniden
yazımından **önce** — sıra tutuldu. Kapanırken iki şey düzeltildi:

- **Bu testler "geri getirilmedi", sıfırdan yazıldı.** Bu kayıt "geri getir"
  diyordu ve bu yanıltıcıydı: `baseline/` dizini hiçbir commit'te, hiçbir
  branch'te, hiçbir dangling object'te yok (`git log --diff-filter=D -- "tests/*"`
  boş; deponun tamamındaki tek dosya silmesi `risk_analyzer.py` ve üç `scripts/*.bat`).
  `compare_service.py` versiyon kontrolü dışında yaşayan bir scratch script'ti.
  Kurtarılacak bir referans yoktu.
- **Kayıp Faz 3'te oldu, Faz 2'de değil.** Faz 2 (`2a52585`) `risk_analyzer.py`'yi
  sildi; üç kontrolü düşüren, `compare_service.py`'yi emekliye ayıran Faz 3.

**Beklenen değerler nereden geldi:** `blind_spots` testi `module_stats` ve
`risk_scores` girdilerini `tests/data/scores-aff55c6-now2026-04-01.json`'dan
okuyor — dosya `trend`, `total_bugs`, `open_bugs`, `recent_bug_count`,
`risk_score` ve `risk_level`'ı zaten taşıyor. Beklenen `risk_level` dizgileri de
oradan okunuyor, yazılmıyor; böylece `_score_to_level`'in özel 80/60/35 kopyası
commit edilmiş kanıta karşı denetleniyor. `days_open` değerleri sabit saate karşı
tarih çıkarması, türetmesi assert'in üstünde yazılı. `tests/data/` altına yeni
dosya eklenmedi.

Not: `rising_unattended` örnek veriyle **hiç** üretilemiyor — `increasing`
trendli tek iki modül (Authentication, Payment) örnekteki tek iki
"üzerinde çalışılan" bug'ı taşıyan modüller. Boş sonuç gerekçesiyle pinlendi,
dolu hâli sentetik girdiyle.

---

## `GET /blind-spots` sözleşmesi Faz 5A'da kırıldı

**Where:** [`src/defect_risk_analyzer/api.py`](../src/defect_risk_analyzer/api.py),
[`src/defect_risk_analyzer/api_models.py`](../src/defect_risk_analyzer/api_models.py)

Her bulgu artık hazır cümle taşıyan `recommendation` alanı yerine `code` ve
`params` döndürüyor. Bu **kırıcı** bir değişiklik ve ROADMAP:268 onu
"API kontratını kıran adım" olarak zaten öngörmüştü.

**Detail:** endpoint dict'i ham döndürüyordu — `response_model` yok,
`api_models.py`'de model yok. Yani sözleşme yalnızca fonksiyonun literal
dict'iydi, ve kırılmanın tek bir test tarafından bile fark edilmemesinin sebebi
buydu. Faz 5A kırılmanın olduğu commit'te `BlindSpotReport`'u ekledi ve
`response_model=` bağladı.

`response_model` ters riski getiriyor: model payload ile uyuşmazsa FastAPI
alanları sessizce düşürür ve gürültülü bir kırılma sessizleşir. Bu yüzden model
alan alan assert edilmiyor, gerçek bir detector çıktısına karşı round-trip
ediliyor (`BlindSpotReport(**payload).model_dump() == payload`); Pydantic
bilinmeyen anahtarları attığı için modelin unuttuğu her alan karşılaştırmayı
düşürür.

**Kalan borç:** `params` `dict[str, Any]`, `code` başına ayrımlı birlik değil.
Daha kesin olurdu ama 5C'nin genişleteceği dört şekli çivilerdi. Ayrıca bu
endpoint'in HTTP davranışı hâlâ test edilmiyor — pakette API test altyapısı yok
(`TestClient` yok, `api.py` modül seviyesinde `analyzer` singleton'ı kuruyor,
route API anahtarı bağımlılığı taşıyor). Sözleşme servis seviyesinde pinlendi.

---

## `calculate_risk_for_query`'nin sıfır-skor guard'ı — latent, canlı değil

**Where:** [`src/defect_risk_analyzer/services/analysis_service.py:226-232`](../src/defect_risk_analyzer/services/analysis_service.py)

Anahtar eşleme döngüsü `best_score = 0`'dan başlayıp `score > best_score` ile
koruyor. Yani adı sorguda geçen ama skoru 0 olan bir modül `best_module`'ü hiç
atamıyor; sorgu, modül hiç adlandırılmamış gibi vektör yoluna düşüyor ve bambaşka
bir modüle atfedilerek dönebiliyor.

**Bu kusur bugün tetiklenemiyor, ve bunu ölçmek önemliydi.** Faz 5A planı bunu
"canlı hata" diye kaydediyordu; test yazılınca kırmızı verdi ve varsayım yanlış
çıktı. `module_stats`'tan gelen hiçbir modül 0 alamıyor:
tanınmayan öncelik bile `DEFAULT_PRIORITY_WEIGHT` 2.5 ağırlığında, en düşük
gerçek ağırlık Low 2.0, yani `priority_factor` tabanı 0.4. Mümkün olan en sessiz
modül — tek kapalı Low bug, azalan trend, ihmal edilebilir yoğunluk — yine de
**11** alıyor:

    (0.4 × 60 + 0.0 × 40) × 1.0 × 0.8 × 0.55 = 10.56 -> 11

Hiç bug'ı olmayan bir modül 0 alırdı ama `module_stats` bug'ları gruplayarak
kurulduğu için oraya giremez.

**Impact:** bugün yok. Yarın olabilir — bir öncelik ağırlığı eklemek, hacim
çarpanını değiştirmek ya da `bug_density`'yi yeniden tanımlamak gerçek bir
modülü 0'a indirdiği anda kusur sessizce canlanır.

**Neden burada:** hem tabanı (gerçek bug'lardan üretilen hiçbir modül 0 almaz)
hem guard'ın kendisini (enjekte edilmiş 0 atılır) `test_analysis_service_query.py`
pinliyor. İkinci test bugün varsayımsal; skorlama değişirse kimse fark etmeden
varsayımsal olmaktan çıkar.

**Planned fix:** guard `score > best_score` yerine "modül adlandırıldı mı"
sorusunu ayrı tutmalı — `best_module is None or score > best_score`. Faz 6.

---

## `_days_since` naive bir referans saatini sessizce 0'a çeviriyor

**Where:** [`src/defect_risk_analyzer/blind_spot_detector.py`](../src/defect_risk_analyzer/blind_spot_detector.py)

`detect_blind_spots` Faz 5A'da keyword-only `now` parametresi aldı. Naive bir
`now` geçilirse ve bug'lar aware ise (gerçek Jira verisinin tamamı `+0300`
taşıyor), çıkarma `TypeError` fırlatıyor — ve `_days_since`'in
`except (ValueError, TypeError): return 0` bloğu bunu yutuyor.

**Impact:** her `days_open` sıfır olur. `stale_bugs` tamamen boşalır,
`neglected_critical_bugs` her bug'ı "bugün açılmış" gösterir. Hata **yeşil
tarafta** başarısız oluyor: hiçbir şey fırlatmıyor, hiçbir şey loglamıyor, rapor
yalnızca sessizce boşalıyor.

Bu teorik değil: `tests/data/` snapshot'larının `_baseline_now` alanı naive
(`"2026-04-01T12:00:00"`), yani pinleme testinin doğal olarak yapacağı ilk şey
tam olarak bu hataydı. Test aware bir saat kuruyor ve tuzağı ayrıca pinliyor
(`test_a_naive_now_is_swallowed_into_zero_days`).

**Planned fix:** `_days_since`'in `except` bloğu ayrıştırma hatasıyla
karşılaştırma hatasını ayırmalı; ikincisi yutulmamalı. Faz 5A davranış
değiştirmediği için yalnızca görünür kılındı. Faz 6.

---

## Kör nokta analizi "analiz edilmiş" sayarken tarihe bakmıyor

**Where:** [`src/defect_risk_analyzer/blind_spot_detector.py`](../src/defect_risk_analyzer/blind_spot_detector.py)
(`_find_unanalyzed_risky_modules`)

Fonksiyon kendisine verilen her `analysis_results` kaydının `affected_modules`
listesini birleştiriyor — **hiçbir zaman penceresi yok**. Tek bir analiz, kaç
yıl önce yapılmış olursa olsun, o modülü rapordan kalıcı olarak siliyor.
Eşleşme ayrıca tam ve büyük/küçük harfe duyarlı bir dizgi karşılaştırması, ve
`affected_modules` ham LLM çıktısından geliyor.

**Impact:** bugün geliştirici makinesinde tam olarak bu durum var.
`data/analysis_results.json` 16 kayıt taşıyor, hepsi `2026-03-23` tarihli, ve bu
kayıtlar bugünün riskli modüllerini "analiz edilmiş" sayarak listeden eliyor.
Sayfa daha temiz görünüyor çünkü veri bayat, çünkü kapsam iyi değil.

**Neden 5A'da düzeltilmedi:** üç sebep. (1) Bir recency penceresi eklemek
pencere uzunluğuna dair bir tasarım kararı ve 5A'nın davranış-koruyucu iddiasını
kirletirdi. (2) İlgili veri dosyaları `.gitignore`'da ve takip edilmiyor
(`git ls-files data/` yalnız `.gitkeep` ve `sample_bugs.json` döndürüyor), yani
bir PR'ın düzeltebileceği bir depo içeriği yok. (3) Kusur artık
`test_an_ancient_analysis_still_counts_a_module_as_analyzed` ile pinli, yani
değiştirildiğinde görünür bir diff üretecek.

**Planned fix:** `analyzed_at` üzerinden bir tazelik penceresi; ayrıca modül adı
eşleşmesi normalize edilmeli. Faz 6.

---

## `classify_bugs` diske hiç yazmıyor

**Where:** [`src/defect_risk_analyzer/component_classifier.py`](../src/defect_risk_analyzer/component_classifier.py),
[`src/defect_risk_analyzer/jira_client.py`](../src/defect_risk_analyzer/jira_client.py)

`classify_bugs` yalnızca bellekteki dict'leri yerinde değiştiriyor
(`bug["component"] = new_component`) ve aynı listeyi döndürüyor. Modülde hiçbir
kalıcılık yok — ne `open`, ne `json`, ne `config` importu.

**Detail:** `jira_client.fetch_and_save()` `bugs.json`'u `_normalize_issue()`
çıktısından doğrudan yazıyor ve eksik component'leri `"Unknown"` yapıyor. Bu
yazma, `AnalysisService.load_bugs()` veriyi görmeden **önce** oluyor. Sınıflandırma
sonrasında hiçbir şey sonucu geri yazmıyor.

**Sonuç:** `data/bugs.json` diskte kalıcı olarak 24/24 `"Unknown"`, buna karşın
her süreç açılışında 24'ü de bellekte yeniden sınıflandırılıyor. Sınıflandırıcı
bozuk değil; kalıcılık hiç bağlanmamış. `data/defect_density.json`'daki tek
`"Unknown"` modülü de bunun fosili — sınıflandırma `load_bugs`'a bağlanmadan
önceki bir kod yolundan kalma, `risk_score: 100 / CRITICAL` ile.

Mock ile canlı arasındaki fark girdide, kodda değil: `classify_bugs` her iki
modda da koşuyor (`analysis_service.py:98-108`, mock/live ayrımının üstünde),
ama `sample_bugs.json`'da 20/20 component dolu olduğu için orada no-op.

**Test durumu:** `component_classifier`'ın anahtar mantığının hâlâ testi yok.
`test_analysis_service_indexing.py:189-213` yalnızca çağrı noktasını pinliyor
(boş component'li bir bug `Authentication`'a düşüyor). Faz 5A'ya alınmadı:
asıl bulgu bir test boşluğu değil, bir veri katmanı kararı, ve ROADMAP:115
`pattern_detector` / `component_classifier` testlerini zaten tek kalem olarak
listeliyor.

**Planned fix:** kalıcılık kararı (sınıflandırılmış component'ler `bugs.json`'a
geri yazılsın mı, yoksa türetilmiş veri olarak mı kalsın) Faz 6; anahtar mantığı
testleri `pattern_detector` ile birlikte.

---

## Sidebar navigasyonunu yalnız kaynak okuyan bir test koruyor

**Where:** [`src/defect_risk_analyzer/ui/shell.py`](../src/defect_risk_analyzer/ui/shell.py),
[`tests/test_dashboard_pages.py`](../tests/test_dashboard_pages.py)

Faz 5B navigasyonu `st.page_link` ile çiziyor. Streamlit 1.41.1'in `AppTest`'i bu
elemanı tanımıyor: `testing/v1/element_tree.py`'de karşılığı yok, `UnknownElement`
olarak düşüyor. Yani render edilmiş sayfaya bakan hiçbir iddia sidebar'da dört
bağlantı mı, üç mü, hiç mi olduğunu söyleyemez. Biri yanlışlıkla silinirse o sayfa
erişilemez hâle gelir ve süit yeşil kalır.

`test_nav_declares_all_four_pages` bu boşluğu kaynağı `ast` ile okuyarak kapatıyor:
`page_link` çağrılarını topluyor, tam dördü olduğunu, hedeflerin sırasıyla
`app.py`, `pages/buglar.py`, `pages/analiz.py`, `pages/ayarlar.py` olduğunu ve her
birinin diskte var olduğunu doğruluyor. Mutasyonla sınandı: bir `page_link`
silinince kırmızıya dönüyor.

**Impact:** test çağrının **varlığını** görüyor, **çalıştığını** değil. Bir
`page_link` koşullu bir dalın içine taşınırsa — `if config.is_llm_configured():`
gibi — AST hâlâ dört çağrı sayar ve test yeşil kalır, ama kullanıcı üç bağlantı
görür. Aynı şekilde `render_nav()` hiç çağrılmaz olursa da fark etmez; onu tutan
tek şey `bootstrap()`'ın kendisi.

**Planned fix:** yok, ve bilinçli. Doğru çözüm yukarı akışta — `AppTest`'in
`page_link` için bir erişimci kazanması. Streamlit sürümü yükseltildiğinde
`element_tree.py`'de `page_link` var mı diye bakılsın; varsa bu test render
edilmiş ağaca karşı yeniden yazılabilir ve AST sürümü silinir.

---

## ROADMAP Faz 3'te olup Faz 3'e alınmayanlar

**Where:** [`docs/ROADMAP-v2.md`](ROADMAP-v2.md), [`tests/`](../tests/)

Faz 3'ün kapsamı, ROADMAP-v2'nin "Faz 3 — Testler" başlığından dardı. Aşağıdakiler
teknik bir engelden değil, faz kapsamında olmadıkları için yapılmadı. Belge ile
gerçeğin sessizce ayrışmaması için buraya yazıldı.

**Detail:**

- **`tests/test_adf_parser.py`** — `parse_adf_to_text`
  ([`jira_client.py:25`](../src/defect_risk_analyzer/jira_client.py)) saf ve
  özyinelemeli; ROADMAP'in kendi deyimiyle "en yüksek getiri". Buradaki en ucuz
  gerçek boşluk.
- **`tests/test_anonymizer.py`** — round-trip **ve telefon regex'i düzeltmesi**
  (sürüm numarası, sipariş kodu ve tarih maskelenmemeli). Dikkat: bu eksik bir
  test değil, **yaşayan bir hata**; test yazmak tek başına yetmez.
- **`pattern_detector.py`, `component_classifier.py`** — hiç testleri yok.
  `blind_spot_detector.py` Faz 5A'da karşılandı (`tests/test_blind_spots.py`);
  `component_classifier` için ayrıca yukarıdaki "`classify_bugs` diske hiç
  yazmıyor" kaydına bakın.
- **`pip-audit`** — ROADMAP hem `requirements-dev.txt` hem CI için istiyor;
  ikisinde de yok. Faz 3 CI'a `pytest` + `ruff` ekledi, bunu eklemedi.
- **Kapsam rozeti / `pytest-cov` eşiği** — **bilerek reddedildi**, ertelenmedi.
  Yüzde hedefi, kapsamı yükseltmek için zayıf test yazma baskısı yaratır; ölçüt
  testin gerçekten bir şeyi kontrol etmesidir. `pytest-cov` kurulu kalıyor,
  isteyen elle çalıştırabilir. Sonradan gözden kaçmış bir eksik sanılmasın diye
  buraya yazıldı.

**Planned fix (Phase 5):** `test_adf_parser.py` ve `test_anonymizer.py`
(regex düzeltmesiyle birlikte) önce; detektör testleri `blind_spot_detector`
yeniden yazımıyla aynı fazda.

---

## `ruff check .` 70 hatayla düşüyordu; per-file-ignores ile karantinada

**Where:** [`pyproject.toml`](../pyproject.toml)

Faz 3 CI'a `ruff check .` eklerken, deponun bu komutu **hiç geçmediği** ortaya
çıktı: 70 ihlal. README (`### Development`) komutu geçiyormuş gibi belgeliyordu.

**Detail:** dağılım — 54 `E501` (uzun satır), 15 `B904`
(`raise ... from` yok), 1 `F841` (kullanılmayan yerel):

| dosya | kural | adet |
|---|---|---|
| `dashboard.py` — Faz 5B'de temizlendi | E501 / F841 | 37 / 1 |
| `api.py` | B904 | 9 |
| `llm_provider.py` | B904 | 6 |
| `ci_analyzer.py` — Faz 4(b)'de temizlendi | E501 | 5 |
| `api_models.py` | E501 | 4 |
| `prompt_templates.py` | E501 | 3 |
| `blind_spot_detector.py`, `pattern_detector.py` | E501 | 2 + 2 |
| `anonymizer.py` | E501 | 1 |

Genel bir `ignore` listesi yerine `[tool.ruff.lint.per-file-ignores]` kullanıldı:
kurallar depo genelinde açık kalıyor, yani `src/` altına eklenen **yeni** kod —
aynı paketteki diğer dosyalar dahil — hâlâ denetleniyor. Doğrulandı: karantinada
olmayan bir dosyaya eklenen E501 ve yalnız E501 için karantinaya alınmış bir
dosyaya eklenen B904 hâlâ yakalanıyor.

**Impact:** ödünleşim gerçek — karantinaya alınmış bir dosyada, karantinaya
alınmış kuralın **yeni** bir ihlali de gözden kaçar. Girdiler bunu sınırlamak
için olabildiğince dar tutuldu.

**Planned fix:** girdiler dosya bazında ve fazı yazılı olarak konuldu;
`pyproject.toml`'daki her satırın üstünde hangi fazda kalkacağı yazıyor
(api.py → Faz 6, llm_provider.py → Faz 6, kalanlar sahipsiz). Silinmek için
konuldular, büyütülmek için değil.

**Kapanan:** `dashboard.py` → Faz 5B'de temizlendi (37 E501 + 1 F841).
Taşımadan **önce** yapıldı: 37 uzun satırın yalnız biri yeniden yazımla ölüyordu
(sidebar radio'sunun yedi etiketlik satır içi listesi), kalan 36'sı olduğu gibi
`ui/` altına taşınacaktı ve orada hiçbir karantina yok — yani taşıma commit'i
CI'da kırmızı olurdu. Sarmaların çoğu örtük dize birleştirmesi, yani yanlış
konan bir boşluk kullanıcının okuduğu metni sessizce değiştirir; bir önceki
commit'in içerik testleri değişmeden yeşil kaldığı için bu iddia denetlenebilir.
F841 gerçek bir ölü atamaydı: `page_webhook_results` hiç kullanmadığı bir renk
hesaplıyordu, `display_analysis_result` zaten kendi rengini üretiyor.
`api.py`'nin `B904` girdisi Faz 5'i işaret ediyordu; beklediği sözleşme
yeniden yazımı 5A'da chaining'e dokunulmadan yapıldı, girdi Faz 6'ya taşındı.

**Kapanan:** `ci_analyzer.py` → Faz 4(b) Bölüm A'da temizlendi (5 E501). Satır
sarma gerekmedi: rapor gövdesi yanlış pozitif düzeltmesi sırasında yeniden
yazıldığı için uzun satırlar zaten kalmamıştı, `pyproject.toml` girdisi silindi.
Girdinin üstündeki yorum da yanlış teşhisi tekrar ediyordu ("Faz 4 aligns this
module's component names with component_classifier"); bkz. `ROADMAP-v2.md` Faz 4.

Yukarıdaki 70 / 54 / 5 sayıları Faz 3 anındaki ölçümdür ve geriye dönük
düzeltilmiyor — tarihsel kayıt. Bugünkü bakiye ayrı bir sayıdır: **25 açık**
(10 E501 + 15 B904). Faz 5B ölçümü: `ruff check --isolated --line-length 100
--select E501,F841 src` → `api_models.py` 4, `prompt_templates.py` 3,
`pattern_detector.py` 2, `anonymizer.py` 1. Hiçbiri sahipli bir faza bağlı
değil.
