# Known Technical Debt

Deliberate trade-offs accepted during refactoring, recorded so they are not
mistaken for oversights. Each entry names the phase that will address it.

---

## De-anonimleştirme yalnız `reasoning` alanına uygulanıyor

**Where:** [`services/analysis_service.py`](../src/defect_risk_analyzer/services/analysis_service.py) (`:388`, `:445`)

`affected_modules`, `test_scenarios` ve `recommended_actions` LLM'den anonim
token'larla gelip öyle saklanıyor ve öyle gösteriliyor; yalnız `reasoning` geri
çevriliyor. 6B'nin çağrı-başına eşleme kararı bunu kalıcı hâle getiriyor —
çağrı bittikten sonra geri çevirmek artık mümkün değil. Bugün de mümkün değildi
(eşleme diskteydi ama hiçbir kod okumuyordu), yani regresyon değil.

| Borç | İşaret |
|---|---|
| Üç alanda ham `[EMAIL_001]` biçimli token'lar kullanıcıya görünebiliyor | Tetikleyici: **bu üç alandan biri kullanıcı metni taşımaya başladığında**; aksi hâlde **v1.1** |

---

## Sır yüzeyinin 6B sonrası bıraktıkları

**Where:** [`config.py`](../src/defect_risk_analyzer/config.py)
(`_get_secret`, `migrate_secrets_to_store`, `save_secret`),
[`ui/shell.py`](../src/defect_risk_analyzer/ui/shell.py) (`bootstrap`),
[`anonymizer.py`](../src/defect_risk_analyzer/anonymizer.py),
[`tests/tools/make_baseline.py`](../tests/tools/make_baseline.py)

Hiçbiri bugün bir kullanıcıyı vurmuyor; hepsi 6B'nin kapsamı dışında bırakılmış
bilinçli sınırlar.

| Borç | İşaret |
|---|---|
| **`.env` gölgelemesi.** `_get_secret` dolu bir `.env` değerini kazandırıyor, yani kullanıcı elle eski bir anahtar yazarsa keyring'deki yenisi sessizce gölgelenir. Sıra kasıtlı (yarıda kalmış bir taşıma çalışmaya devam etsin, elle yapıştırılan anahtar etkili olsun) ve Ayarlar hangi katmanın kullanıldığını yazıyor — ama hangi *değerin* kazandığını yazmıyor | Tetikleyici: **bir kullanıcı "anahtarı değiştirdim ama eskisi kullanılıyor" diye bildirdiğinde**; aksi hâlde **v1.1** |
| **Geri dönüş yolu yok.** Keyring'e taşınan bir kimlik bilgisini `.env`'e geri almanın yolu yok. Kullanıcı `.env`'e elle yazarak fiilen geri dönebilir (yukarıdaki gölgeleme sayesinde), ama bu belgelenmiş bir yol değil ve store'daki kopya kalır | Tetikleyici: **kullanıcı keyring'den çıkmak istediğini bildirdiğinde**; aksi hâlde **v1.1** |
| **Fallback yolunda kalan ölü sır.** Keyring kullanılamadığında taşıma hiç çalışmıyor (doğru karar), ama o kullanıcıda 6A'nın markerıyla yorumlanmış ölü bir sır satırı kalabiliyor. Etkin satırın gerekçesi var — uygulama onu okuyor; ölü satırın hiçbir işlevi yok. 6B'de düzeltilmedi çünkü o yolda `.env` zaten düz metin sır tutuyor ve kazanç marjinal. **Aşağıdaki satırdan farklı: bu, taşınan anahtarın fallback'te kalan ölü kopyası** | Tetikleyici: **keyring fallback yolu bir daha ele alındığında**; aksi hâlde **v1.1** |
| **Marker taşıyan ama taşınmayan anahtarlar.** `set_env_value`'nun boşaltma dalı yalnız boşaltılan anahtarın yorumlanmış satırlarını temizliyor. Başka bir anahtara ait marker'lı bir satır — kullanıcı elle yazmış olabilir — dokunulmadan kalıyor. Kapsam kasten dar tutuldu: patlama yarıçapı işlemin amacına eşit | Tetikleyici: **`.env`'e sır tutan yeni bir anahtar eklendiğinde**; aksi hâlde **v1.1** |
| **`bootstrap()` büyüyor.** Artık dil, ilk kurulum kapısı, `anon_map` bildirimi ve kimlik bilgisi taşıması + üç bildirimi yapıyor. `config.init()`'e ikinci bir yıkıcı iş yüklememe gerekçesi burada geçerli değil — `bootstrap()` zaten kurulum akışının sahibi ve bunlar aynı sınıftan iş — ama fonksiyon bölünme sınırına yaklaşıyor | Tetikleyici: **`bootstrap()`'a dördüncü bir sorumluluk eklendiğinde** |
| **`make_baseline.py` migration tetikliyor.** Araç `config.init()` çağırıyor ve pytest dışında elle çalıştırıldığında `DRA_BASE_DIR` set değil, yani `anon_map.json` silme işlemi gerçek dosyayı hedefliyor. Gerçek bir çalıştırma için doğru davranış, ama "skor anlık görüntüsü al" diyen bir araçtan beklenmiyor. Docstring'ine yazıldı | Tetikleyici: **`tests/tools/` altına `init()` çağıran ikinci bir araç eklendiğinde** |
| **Sipariş kodu biçimi.** Yeni telefon deseni son grubu 3-4 haneye zorlayarak sayısal referansları (`100-2003-77`) dışarıda bıraktı, ama 3-4-4 biçimli bir sipariş kodu hâlâ telefon sanılıyor. Şekil tek başına ayırt edemiyor | Tetikleyici: **sipariş kodu biçimi olan bir alan bug metnine girdiğinde**; aksi hâlde **v1.1** |

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

**Durum: yazma tarafı Faz 6A'da kapandı.** `set_env_value()` artık bir anahtarın
**son** eşleşen satırını — dotenv'in zaten okuduğu satırı — güncelliyor ve
önceki eşleşmeleri `# [duplicate removed by set_env_value]` işaretiyle
yorumluyor. Silmiyor: `.env` kimlik bilgisi tutuyor ve satır silmek kullanıcının
geri alamayacağı bir işlem. Yazma atomik (aynı dizinde `.env.tmp` +
`os.replace`), kodlama iki tarafta da açıkça UTF-8, satır sonu ve izin bitleri
korunuyor.

**Tarihsel kayıt (6A öncesi):** `set_env_value()` **ilk** eşleşen satırı
güncelliyordu, `python-dotenv` ise **sonuncusunu** kazandırıyor. Mükerrer satırı
olan bir dosyada yeni değer üstteki satıra yazılıyor, alttaki eski satır olduğu
yerde kalıyor ve `reload()` sonrasında yine o kazanıyordu. Ayarlar'daki "API Key
Yenile" butonu başarılı görünüyor ama bir sonraki `reload()`'da eski anahtara
dönüyordu. Sessiz geri alma.

Bu depodaki geliştirici makinesinin canlı `.env`'i tam olarak bu şekildeydi: iki
`API_KEY=` satırı, ikisi de dolu ve birbirinden farklı (ölçüldü — ham değerler
değil, uzunluk ve SHA-256 öneki karşılaştırıldı). **Satır numaraları o dosyaya
özgüdür, genel bir olgu değildir**; başka bir kurulumda mükerrer satırlar başka
yerlerde olur ya da hiç olmaz.

**Mükerrer üreteci de kapandı:** `BASLAT.bat` her taze kurulumda `.env` sonuna
bir `USE_MOCK_DATA=True` satırı ekliyordu. Kontrol hiç tutmuyordu çünkü
`.env.example` `USE_MOCK_DATA=False` gönderiyor ve `findstr /C:` harfe duyarlı
(ölçüldü). O satır ayrıca `is_first_run()`'ı False yapıp ilk kurulum sihirbazını
atlatıyordu (ölçüldü). Append bloğu kaldırıldı.

**Kalan iş:** kullanıcının mevcut `.env`'i kendiliğinden düzelmiyor —
implementasyon kullanıcı dosyasına dokunmuyor. İlk kayıtta (ör. API anahtarı
yenileme) tekilleşir; o ana kadar bugünkü davranış sürer, son satır etkin.

**Planned fix (Faz 6B):** kimlik bilgileri `keyring`'e taşınırken `API_KEY` de
`.env`'den çıkacak; yorumlanmış eski sır satırları da o sırada temizlenecek.

---

## `.env` yazıcısının 6A sonrası bıraktıkları

**Where:** [`config.py`](../src/defect_risk_analyzer/config.py)
(`set_env_value`, `_atomic_write_lines`),
[`ui/service.py`](../src/defect_risk_analyzer/ui/service.py), `BASLAT.bat`

Hiçbiri bugün bir kullanıcıyı vurmuyor; hepsi 6A'nın kapsamı dışında bırakılmış
bilinçli sınırlar.

| Borç | İşaret |
|---|---|
| Yorumlanmış eski sır satırları `.env`'de düz metin kalıyor | **6B** — keyring taşımasıyla birlikte temizlenecek |
| `export KEY=v` ve `KEY = v` biçimleri yazıcı tarafından görülmüyor (dotenv okuyor). Yazma bunları eşleştiremez, sona yeni satır ekler; etkin değer doğru olur ama bayat satır kalır | Tetikleyici: **`.env`'e üçüncü parti bir araç yazmaya başladığında**; aksi hâlde **v1.1** |
| Tırnaklama: boşluk ya da `#` içeren bir değer tırnaksız yazılıyor | Tetikleyici: **6B sonrası `.env`'de kalan bir ayar tırnak gerektiren değer aldığında**; aksi hâlde **v1.1** |
| `save_multiple_env` her anahtar için ayrı atomik yazma yapıyor — tek tek atomik, bütün olarak değil; yarıda çökerse anahtarların bir kısmı kaydedilmiş olur | Tetikleyici: **Ayarlar kaydetme yolu bir daha değiştiğinde**; aksi hâlde **v1.1** |
| `save_multiple_env` yolunda `OSError` UI'da ham traceback olarak yüzeye çıkıyor (`ui.service.call()` ile sarmalı değil) | **6E** |
| `BASLAT.bat` fallback'i (`.env.example` yokken) 19 anahtardan 1'ini üretiyor. İşlevsel kayıp yok — 19'unun da modül default'u var ve yazılan tek değer default'una eşit — ama `.env.example`'ın 49 satırlık dokümantasyonu kayboluyor | Tetikleyici: **`.env.example` olmadan dağıtılan bir paket üretildiğinde**; aksi hâlde **v1.1** |

---

## `config.init()` çağrılmadan okuma hâlâ sessiz

**Where:** [`config.py`](../src/defect_risk_analyzer/config.py),
[`tests/test_entry_points.py`](../tests/test_entry_points.py)

Faz 6A bir AST bekçisi ekledi: sevk edilen sekiz giriş noktası `config.init()`'e
ulaşmak zorunda — doğrudan, ya da tek sıçramada (`bootstrap()`, ve sıçramanın
kendisi de AST ile doğrulanıyor, sabit bir isim listesine güvenilmiyor). Bu,
tehdidi **sevk öncesi** yakalıyor.

Çalışma zamanında hâlâ hiçbir şey tutmuyor: `init()` çağrılmadan okunan her
değer sessizce modül default'una düşüyor. `tests/test_config_init.py` bu
davranışı belgeliyor ve 6A'da değiştirilmedi.

| Borç | İşaret |
|---|---|
| `init()` çağrılmadan değer okumaları sessizce default dönüyor; bekçi bunu yalnız sevk öncesi yakalıyor | Tetikleyici: **config erişim yoluna bir daha dokunulduğunda** (`_initialized` etrafındaki her dokunuş 5C'de hata üretti) |
| `is_first_run()` semantiği denetlenmedi. Ölçüldü: `USE_MOCK_DATA=True` → `is_first_run()` False → sihirbaz atlanıyor. Kusur `is_first_run()`'da değildi, kullanıcı adına yapılandırma yazan kurulumdaydı; 6A onu kapattı | Tetikleyici: **ilk kurulum akışı bir daha değiştiğinde**; aksi hâlde **v1.1** |
| Bekçinin beyan edilmiş kör noktaları: dolaylı config kullanıcıları, koşullu `init()` (çağrıyı görür, yolu görmez), dinamik dispatch, `__main__`'sız `python -m`, repo dışı tüketici | Tetikleyici: **`src/` dışına yeni bir çalıştırılabilir araç eklendiğinde** |

---

## `tests/tools/` araçlarının bıraktıkları

**Where:** [`tests/tools/chroma_cleanup.py`](../tests/tools/chroma_cleanup.py),
[`tests/tools/make_baseline.py`](../tests/tools/make_baseline.py)

Faz 6A'nın giriş noktası bekçisi bu iki aracı incelemiyor: `chroma_cleanup`
`config`'i doğrudan import etmiyor, `make_baseline` ise zaten `init()`
çağırıyor. Aşağıdakiler bekçinin konusu değil, araçların kendi borçları.

| Borç | İşaret |
|---|---|
| `chroma_cleanup` bugün zararsız ama yapısal olarak değil: `vector_store`'dan yalnız iki modül sabiti alıyor ve iki koleksiyonu da koruyor. "Şu anki koleksiyon"u sormaya başlarsa `USE_MOCK_DATA`'yı `init()`'siz okur ve default `False` → `COLLECTION_LIVE` görür. ChromaDB yolu (`CHROMA_DB_DIR`) import sabiti olduğu için yanlış yol riski yok — ölçüldü | **6E**, tetikleyici: **`chroma_cleanup` mevcut koleksiyonu sormaya başladığında** |
| `make_baseline.py:120` `config.get_risk_level` çağırıyor; `config.py`'de böyle bir fonksiyon yok (`core/scoring.py`'de var). Dosya kendi docstring'inde (20-23) dalın çalışamaz olduğunu yazıyor — belgelenmiş ölü dal, ama yine de mayın | **6E**, tetikleyici: **`make_baseline` bir daha çalıştırıldığında** |

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

**Faz 5C eki:** aynı boşluk `GET /patterns`'te de vardı ve aynı şekilde
kapatıldı — `PatternResponse` + `response_model=`, dolu payload'la round-trip
(`tests/test_pattern_contract.py`). 5C `summary` alanını `code`/`params` ile
değiştirdiği için kırılma yine olacaktı; bu kez model kırılmadan önce eklendi.
5A'nın bıraktığı fallback sorusu — "çalışma zamanı locale dosyalarına geçerken
eksik anahtar çökme mi hak eder" — `ui/i18n.py::UnknownMessageKey`'de
kapandı: bir locale'de eksik anahtar kaynak dile düşüyor ve log'a uyarı
yazıyor, her iki locale'de de eksik anahtar fırlıyor. Birinci yol sevk edilen
üründe erişilemez, çünkü `test_locale_key_sets_match` iki dosyanın anlaşmasını
zorunlu kılıyor.

---

## Görünen metinle karşılaştırma — üçüncü kez çıkan kalıp hatası

**Where:** [`src/defect_risk_analyzer/ui/setup_wizard.py`](../src/defect_risk_analyzer/ui/setup_wizard.py),
[`src/defect_risk_analyzer/ui/pages/analiz.py`](../src/defect_risk_analyzer/ui/pages/analiz.py),
[`src/defect_risk_analyzer/ci_analyzer.py`](../src/defect_risk_analyzer/ci_analyzer.py)

Bu depoda üç kez aynı hata yapıldı: bir dalın kararı, kullanıcıya **gösterilen**
dizeye bağlandı. Gösterilen dize sunum katmanının çıktısıdır — dile,
biçimlendirmeye, emoji'ye, kısaltmaya göre değişir. Karar her zaman sabit bir
anahtara bağlanmalı. Üçü de düzeltildi; kayıt düzeltme için değil, **nasıl
bulundukları** için.

| nerede | ne yapıyordu | nasıl bulundu |
|---|---|---|
| `ci_analyzer.infer_modules_from_files` (Faz 4(b) A) | yol içinde çıplak alt dizge: `auth` ∈ `docs/probe/auth-probe.md` | iki probe PR'ıyla ölçülerek |
| `setup_wizard.py` — `if "Demo" in mode:` | görünen radio etiketinde alt dizge arıyordu | i18n taşıması |
| `pages/analiz.py` — `if analysis_type == "Bug Key ile":` | Türkçe literal ile karşılaştırma | i18n taşıması |

**Impact:** ikincisi İngilizce'de **tesadüfen** çalışmaya devam ediyordu —
"Demo Mode" da "Demo" içeriyor — yani bir sonraki locale bütün dalı kazara
belirlerdi. Üçüncüsü İngilizce arayüzde **her zaman** `False` verirdi: tekli
analiz sekmesi sessizce serbest metin moduna düşer, kullanıcı Bug Key alanını
hiç göremezdi. Hiçbiri istisna atmıyor, hiçbiri loglamıyor.

**İkisi de i18n taşıması olmadan görünmezdi.** Türkçe tek dil olduğu sürece
literal her zaman eşleşiyordu; hatayı ortaya çıkaran şey testler değil, ikinci
bir dilin var olmasıydı. Bu, fazın beklenmedik kazancı ve kaydın asıl sebebi.

**Planned fix:** yok — üçü de kapalı. Kural ileriye dönük: `if <widget değeri>
== <literal>` görüldüğünde literalin bir locale değeri olup olmadığına
bakılmalı. Öyleyse ya sabit anahtarlı `options` + `format_func` kullanılmalı, ya
da karşılaştırma `t(...)` çağrısının kendisiyle yapılmalı. 5C ikincisini seçti,
çünkü birincisi `at.radio.set_value()` ile sürülen 5B testlerini kırardı.

---

## ~~`common_keywords` sırası her süreçte değişiyor — kullanıcı iki farklı kök neden görüyor~~ — 6D-6b'de kapatıldı

**Where:** [`src/defect_risk_analyzer/pattern_detector.py`](../src/defect_risk_analyzer/pattern_detector.py)

`_extract_common_keywords` kelimeleri `set(words)` üzerinden sayıyor ve
`Counter.most_common` eşit sayıdaki kelimeleri **ekleme sırasına** göre
sıralıyor. Ekleme sırası set yineleme sırasıdır, o da string hash
randomizasyonuna bağlıdır. Yani eşit sıklıktaki anahtar kelimeler her süreçte
farklı sırada çıkıyor.

**Ölçüm** (aynı girdi, altı ayrı süreç, `tests/test_pattern_detector.py`
fixture'larıyla aynı bug kümesi):

```
'3 bug — ortak tema: ödeme, timeout, bağlantı, checkout'
'3 bug — ortak tema: checkout, bağlantı, timeout, ödeme'
'3 bug — ortak tema: bağlantı, ödeme, checkout, timeout'
'3 bug — ortak tema: timeout, ödeme, checkout, bağlantı'
'3 bug — ortak tema: bağlantı, timeout, checkout, ödeme'
'3 bug — ortak tema: ödeme, checkout, bağlantı, timeout'
```

**Impact:** bu bir ürün hatası, test rahatsızlığı değil. Buglar sayfasındaki
"💡 Olası Ortak Neden" önerisi `keywords[0]` ve `keywords[1]`'i adlandırıyor
(`ui/pages/buglar.py`). Kullanıcı aynı bug kümesine iki kez baktığında —
uygulamayı kapatıp açmak yeter — **iki farklı kök neden** öneriliyor. Anahtar
kelime etiketleri de aynı şekilde karışıyor. Hiçbir şey hata vermiyor; öneri
her seferinde makul görünüyor, sadece aynı değil.

**Neden 5C kapsamı dışı:** düzeltme `_extract_common_keywords`'ün sıralamasını
değiştirmek demek — iş mantığı davranışı, ve kullanıcının gördüğü çıktıyı
değiştirir. 5C bir çeviri fazı; taşıdığı cümleyi aynı bırakmakla yükümlü.
Kararsızlık taşımadan önce de vardı.

**Planned fix:** `most_common`'a kararlı bir ikincil ölçüt eklemek —
`sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))` — eşitlikleri
alfabetik olarak çözer ve süreçler arası kararlı hâle getirir. `pattern_detector`
testleriyle birlikte, Faz 6. Testler bunu gizlemiyor: birebir cümle pin'i tek
ortak anahtar kelimesi olan bir kümede kurulu, anahtar kelime listesi ise küme
karşılaştırmasıyla doğrulanıyor.

**Kapandı (6D-6b, 2026-10-10) — planlanandan geniş.** Bu kayıt yalnız anahtar
kelimeleri anıyordu. 6D-6b'nin tarayıcı kontrolünde kullanıcı aynı mekanizmanın
**modülü** de değiştirdiğini gördü: TR örnek verisinde bir pattern'in modülü
yeniden başlatmalarda Frontend → Inventory → Reporting → Inventory oldu, bug
listesi aynı kaldı. Kaynakta üç yer vardı: küme bir `set` olarak yineleniyordu
(`cluster_bugs`), kelimeler `set(words)` üzerinden sayılıyordu, ve
`Counter.most_common` beraberliği ekleme sırasıyla çözüyordu — modülde,
öncelikte ve kelimelerde. Şimdi:
- küme anahtar sırasıyla yineleniyor (`sorted(cluster_keys)`);
- modül ve kelime beraberliği kod noktası sırasıyla çözülüyor. ç ğ ı ö ş ü
  z'den sonra gelir; yerele duyarlı sıralama cevabı makineye bağlardı
  (kullanıcı kararı);
- öncelik beraberliği `core/scoring.py`'nin `PRIORITY_WEIGHTS` sırasıyla, ağır
  olan önce; tablonun bilmediği öncelikler bilinenlerden sonra ve kendi
  aralarında ada göre (kullanıcı kararı). `DEFAULT_PRIORITY_WEIGHT` bilerek
  kullanılmıyor, bilinmeyeni Medium ile Low arasına koyardı.

Testler `tests/test_pattern_detector.py`'nin sonunda. Biri aynı beraberlikli
girdiyi sabit sekiz `PYTHONHASHSEED` ile sekiz alt süreçte koşuyor; eski kodda
sekiz seed'in sekizi de farklı cevap veriyor, yani kırmızısı şansa bağlı değil.
Mutasyonlar ve mock verideki yeni çıktı: "Faz 6D-6 eki", 6D-6b bölümü. Bir
plotly bump PR'ına kullanıcı kararıyla, ayrı bir commit olarak girdi.

---

## Paket verisi wheel'e giriyor mu — testle görülemeyen sınıf

**Where:** [`pyproject.toml`](../pyproject.toml),
[`src/defect_risk_analyzer/ui/locales/`](../src/defect_risk_analyzer/ui/locales/)

`ui/locales/*.json` bir paket değil (`__init__.py` yok), yani
`packages.find` onları görmüyor ve wheel'e yalnız paket verisi olarak
girebiliyorlar. Faz 5C planı bunu "girdi olmadan wheel locale'siz çıkar" diye
öngörmüştü. **Öncül ölçümle çürüdü.**

**Ölçüm:** setuptools 84.0.0 (izole build ortamının çektiği sürüm) `pyproject.toml`
ile yapılandırılmış projelerde `include_package_data`'yı zaten `True` yapıyor.
Her iki locale dosyası `[tool.setuptools.package-data]` girdisi **olmadan da**
wheel'e giriyor — temiz bir `build/` ile iki kez doğrulandı. İlk ölçüm
geçersizdi: bayat bir `build/` ağacı ikinci build'i bedavaya geçiriyordu.

Girdi yine de duruyor, çünkü kural "paket dizinindeki her şey" değil: aynı
build'de `ui/` altına konan bir `.txt` probe wheel'e **girmedi**. Yani dahil
etme kuralı uzantıya ya da desene bağlı ve bu projenin denetiminde değil.
**Probe deneyi kirliydi** — hem uzantı hem dizin değişti, dolayısıyla kuralın
tam olarak ne olduğu belirlenmedi.

**Impact:** bu sınıfın tamamı testle görülemez. Kaynak checkout'ta dosyalar
zaten oradadır; eksiklik yalnız kurulmuş bir wheel'de ortaya çıkar ve orada
`dra` açılır, sayfa yapılandırmasını çizer, ilk `t()` çağrısında
`FileNotFoundError` fırlatır. Aynı sınıfta iki komşu daha var: `module-map.json`
ve `data/sample_bugs*.json` — ikisi de `src/` dışında, wheel'e **hiç** girmiyor,
`config` onları `BASE_DIR` üzerinden diskten okuyor. Bu bilinçli
(`_resolve_base_dir()` girdisine bakınız) ama aynı görünmezliği paylaşıyor.

**Planned fix:** yok. Doğrulama yöntemi kayıt altında: wheel kurup içeriğini
listelemek, ve **önce `build/` silmek** — bayat bir ağaç kontrolü bedavaya
geçirir. Faz 7'nin "temiz makinede `pipx install`" maddesi bunu doğal olarak
kapsıyor.

---

## `format_pattern_summary`'nin UI'da çağıranı yok

**Where:** [`src/defect_risk_analyzer/ui/messages.py`](../src/defect_risk_analyzer/ui/messages.py)

Faz 5C `pattern_detector`'ın ürettiği cümleyi `ui/messages.py`'ye taşıdı, ama
hiçbir sayfa onu render etmiyor. Bugün yalnız testler çağırıyor.

**Detail:** bu 5C'nin yarattığı bir durum değil, devraldığı bir durum. Taşınan
`summary` alanını da hiçbir UI sayfası okumuyordu — `ui/pages/buglar.py`
`pattern_id`, `bug_count`, `common_component`, `common_keywords`,
`common_priority`, `severity` ve `bug_keys` kullanıyor. Alan yalnızca
`GET /patterns` tarafından dönüyordu ve dönmeye devam ediyor.

Fonksiyon yine de doğru yerde: mimari kural 3 kullanıcıya görünen metnin `ui/`
katmanında üretilmesini istiyor, cümlenin bir sahibi olmak zorunda, ve
`GET /patterns` tüketicisi için referans render bu. Silinseydi locale
anahtarları Python'dan erişilemez kalırdı — ki `test_every_message_is_actually_used`
bunu zaten yakalardı.

**Planned fix:** karar, silmek değil kullanmak yönünde olmalı: pattern
expander'ının içinde tema cümlesini göstermek bugün gösterilmeyen gerçek bir
bilgi eklerdi. Bir UI kararı olduğu için 5C'de yapılmadı (faz metni taşıyor,
eklemiyor). Faz 7'nin vitrin çalışmasıyla birlikte değerlendirilsin.

---

## İstisna metinleri çevrilmiyor — i18n'in sınırı `ui/` katmanında bitiyor

**Where:** [`src/defect_risk_analyzer/ui/service.py`](../src/defect_risk_analyzer/ui/service.py)

Hata sınırı (`call()`) beş `st.error` üretiyor ve hepsi locale'den geliyor —
ama içindeki `{detail}` istisnanın kendi mesajı ve o **İngilizce**. İngilizce
arayüzde fark edilmiyor; Türkçe arayüzde "⚠️ LLM hatası: Rate limit exceeded"
gibi karışık bir cümle çıkıyor.

**Impact:** düşük ama gerçek. Kullanıcı hatayı Türkçe bir çerçeve içinde
İngilizce okuyor. Ayrıca `services/analysis_service.py` ve `adapters/`
katmanlarındaki istisna mesajları da mimari kural 3'ün kapsamına girer:
kullanıcıya ulaşan metin oradan geliyor.

**Neden 5C'de yapılmadı:** düzeltmek istisnaları da yapısal veriye çevirmek
demek — her `raise ValueError("...")`'ın bir `code` + `params` taşıması, yani
5A'nın kalıbının üç modüle daha uygulanması. Kapsam olarak 5C'nin iki katı ve
`core/` saflığına da dokunur. 5C sınırı bilinçli olarak `ui/` katmanının kendi
ürettiği metinde çizdi.

**Planned fix:** 5A/5C kalıbının `services/` ve `adapters/` istisnalarına
uygulanması. Faz 6, `keyring` ve `SECURITY.md` işiyle birlikte —
`llm_provider.py`'nin sağlayıcıya göre değişen hata eşleşmesi
(`per-file-ignores` girdisinde kayıtlı) zaten aynı kodu açıyor.

*6D-4e notu (2026-10-10):* o eşleşme artık yok. İki sağlayıcı da 429'u
SDK'nın `RateLimitError` tipinden tanıyor; Groq'un "rate_limit" ile
OpenAI'nin "rate limit" asimetrisi metin eşleşmesiyle birlikte kalktı (bkz.
"Faz 6D-4e eki"). Bu bölümün asıl borcu — istisna metinlerinin
çevrilmemesi — değişmedi.

---

## Aktif dil bir modül global'i — çok oturumlu kullanımda yarışıyor

**Where:** [`src/defect_risk_analyzer/ui/i18n.py`](../src/defect_risk_analyzer/ui/i18n.py),
[`src/defect_risk_analyzer/ui/language.py`](../src/defect_risk_analyzer/ui/language.py)

`i18n._active` bir modül global'i ve `shell.bootstrap()` her script koşusunda
onu o oturumun `session_state`'inden set ediyor. Streamlit ise eşzamanlı tarayıcı
oturumlarını **aynı süreçte ayrı thread'lerde** koşturuyor. İki oturum farklı
dil seçerse son yazan kazanır ve öteki oturum bir sonraki yeniden çiziminde
yanlış dilde render olabilir.

**Neden böyle:** alternatifi `t()`'nin her çağrıda `st.session_state` okuması.
O da `i18n.py`'yi streamlit'e bağlardı, ki bugün bağlı değil — ve
`tests/test_i18n_locales.py`'nin 40+ testi (anahtar kümeleri, fallback, çıplak
literal taraması) `AppTest` maliyeti olmadan, script bağlamı olmadan koşuyor.
Ayrıca `t()` bir yeniden çizimde birkaç yüz kez çağrılıyor.

**Impact:** yerel, tek kullanıcılı bir masaüstü aracı için sıfır. `dra` tek
kullanıcının makinesinde tek tarayıcı sekmesi açıyor. Streamlit Cloud demosunda
(Faz 7) ise gerçek: aynı anda iki ziyaretçi farklı dil seçerse birbirlerini
etkiler.

**Planned fix:** Faz 7 Streamlit Cloud demosunu kurarken yeniden
değerlendirilmeli. Demo tek dile sabitlenirse (dil seçici gizlenir) sorun
ortadan kalkar; seçici kalacaksa `t()` `session_state`'e taşınmalı ve locale
testleri `AppTest`'e devredilmeli — o takas o zaman ölçülsün.

---

## `DRA_LANGUAGE` test izolasyonu dolaylı — `_CONFIG_KEYS` değil, `.env` içeriği koruyor

**Where:** [`tests/test_dashboard_pages.py`](../tests/test_dashboard_pages.py)
(`_CONFIG_KEYS`, `_rewrite_env`, `restorable_env`, `unconfigured`)

`config.set_env_value` `.env`'in yanında `os.environ`'a da yazıyor, dolayısıyla
`.env`'e yazan bir test süreç ortamını da kirletiyor. `_rewrite_env` bunu
`_CONFIG_KEYS` listesindeki anahtarları teardown'da `os.environ`'dan silerek
çözüyor — ama `DRA_LANGUAGE` o listede **yok**, hâlbuki dil seçicisini süren
iki test tam olarak o anahtarı yazıyor.

**Ölçüm:** bir pytest eklentisiyle, izlenen testlerin teardown'ı *bittikten*
sonra durum okundu (`pytest_runtest_logreport(when="teardown")`; ilk denemede
kullanılan `pytest_runtest_teardown` hook'u fixture finalizer'larını sarmaladığı
için onlardan **önce** çalışıyor ve yanıltıcı bir `'en'` gösteriyordu):

```
before test_choosing_a_lan os.environ='tr'  config.LANGUAGE='tr'  sample=sample_bugs.json
after  test_choosing_a_lan os.environ='tr'  config.LANGUAGE='tr'  sample=sample_bugs.json
session end                os.environ='tr'  config.LANGUAGE='tr'  sample=sample_bugs.json
```

Yani **bugün sızıntı yok.** Anahtar `_CONFIG_KEYS`'e eklenmedi, çünkü ölçüm
gerekmediğini gösterdi.

**Neden çalışıyor:** `_CONFIG_KEYS` sayesinde değil. Teardown'daki
`config.reload()` → `load_dotenv(ENV_FILE, override=True)`, geri yazılan
`CONFIGURED_ENV` bloğu `DRA_LANGUAGE=tr` satırını **içerdiği** için değeri
`os.environ`'a geri basıyor. Koruma, silme listesinden değil, dosya
içeriğinden geliyor.

**Impact:** bugün sıfır; latent. `load_dotenv` yalnız dosyada adı geçen
anahtarları override ettiği için, boş `.env` yazan bir fixture (`unconfigured`
→ `_rewrite_env("")`) ile `DRA_LANGUAGE` yazan bir test birleşirse anahtar
`os.environ`'da hayatta kalır ve sonraki testler yanlış dilde koşar. Bugünkü
`unconfigured` testleri dil yazmıyor, o yüzden birleşim hiç oluşmuyor —
ölçüldü, o yol da `'tr'` gösteriyor.

**Planned fix:** bir faza bağlanmadı. Tetikleyicisi net: `unconfigured` (ya da
boş `.env` yazan başka bir fixture) kullanan bir teste dil yazımı eklenirse,
aynı commit'te `DRA_LANGUAGE` `_CONFIG_KEYS`'e girmeli. Asıl kalıcı çözüm
`_CONFIG_KEYS`'i elle bakımdan çıkarmak — silinecek anahtarları
`CONFIGURED_ENV`'den türetmek — ama bu, listenin bugünkü ikinci işini (ilk
çalıştırma denetiminin baktığı anahtarları temizlemek) de kapsayacak şekilde
ayrıca ölçülmeli.

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
- ~~**`pip-audit`** — ROADMAP hem `requirements-dev.txt` hem CI için istiyor;
  ikisinde de yok. Faz 3 CI'a `pytest` + `ruff` ekledi, bunu eklemedi.~~
  **Kapandı (6D-4d-2, 2026-10-07):** `pip-audit==2.10.1`
  `requirements-dev.txt`'te, CI'da ignore'suz rapor ve iki yönlü bir kapı.
  Aşağıdaki "Faz 6D-4d-2 eki".
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
`pyproject.toml`'daki her satırın üstünde hangi fazda kalkacağı yazıyor.
Faz 3'te api.py → Faz 6, llm_provider.py → Faz 6, kalanlar sahipsizdi; Faz
6D-4e'den beri hepsinin sahibi **Faz 7'nin temizlik kuyruğu**, tetikleyici
**Faz 7 başladığında** (aşağıdaki bakiye cümlesi). Silinmek için konuldular,
büyütülmek için değil.

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
düzeltilmiyor — tarihsel kayıt. Bugünkü bakiye ayrı bir sayıdır: **22 açık**
(9 E501 + 13 B904). Sahibi **Faz 7'nin temizlik kuyruğu** (kullanıcı kararı,
2026-10-10), tetikleyici: **Faz 7 başladığında**.

Ölçüm karantinasız alınır — bakiye, karantinada *duran* ihlallerin sayısıdır,
CI'ın gördüğü değil (`ruff check .` bugün temiz):

```
ruff check . --config "lint.per-file-ignores={}" --statistics
```

Döküm: `api.py` 9 + `llm_provider.py` 4 → 13 `B904`; `api_models.py` 4,
`prompt_templates.py` 3, `pattern_detector.py` 2 → 9 `E501`.
`llm_provider.py`'nin iki 429 dalı Faz 6D-4e'de `raise … from e` ile
zincirlendi (6 → 4); kalan 22'nin hepsi yukarıdaki sahibe, Faz 7'ye bağlı.

`anonymizer.py` bu dökümden düştü: dosya Faz 6B'de yeniden yazıldığında uzun
satır ortadan kalktı ve arkasında hiçbir şey kalmayan karantina girdisi aynı
PR'da silindi (`53bb845`, PR #14). Faz 5B'nin `--isolated --line-length 100
--select E501,F841 src` komutu artık bu sayıyı vermiyor, o yüzden yukarıdaki
komutla değiştirildi.

Bu cümlenin doğruluğunu artık `tests/test_known_debt_tally.py` tutuyor: sayı
ölçümden ayrıldığında paket kırmızıya döner. Bekçi yalnız bu bakiye cümlesini
denetler — yukarıdaki tarihsel sayılara ve dosya bazındaki döküme dokunmaz.

---

## `risk_level_label` tanınmayan seviyeyi ham HTML'e geçiriyor

**Where:** [`ui/theme.py`](../src/defect_risk_analyzer/ui/theme.py) (`:38-47`),
[`ui/results.py`](../src/defect_risk_analyzer/ui/results.py) (`:19-25`)

`risk_level_label()` tanımadığı bir seviyeyi olduğu gibi geri veriyor — kasıtlı,
docstring'i söylüyor: "it is data from outside, and a stored analysis result
carrying something unexpected should still render". O değer `results.py`'de
`unsafe_allow_html=True` taşıyan bir `st.markdown`'a giriyor ve kaçırılmıyor.

Bugün ulaşılabilir değil: `risk_level` `core/scoring.py::get_risk_level()`'den
geliyor ve dört sabitten biri oluyor, `api_models.py:74` de yoldan geçerken
`Field(ge=0, le=100)` ile skoru sabitliyor. Tek savunma **`data/analysis_results.json`
dosyasının güvenilir olduğu varsayımı** — dosyaya yazan her şey bugün bu depodan.

Faz 6C kapsamı dışında bırakıldı. Kapsam `buglar.py` ve `app.py`'deki üç ham
Jira alanıydı; `results.py`'yi açmak farklı bir dosyayı ve farklı bir güven
sınırını ele almak demekti. Sonuç görünür bir asimetri: `app.py` `color`
ifadesini kaçırıyor, `results.py` aynı ifadeyi kaçırmıyor. Asimetri
`tests/test_html_escaping.py`'nin beyaz listesinde gerekçesiyle duruyor —
"tutarlı olsun" diye `results.py`'yi sarmak bir kapsam genişletmesidir, düzeltme
değil.

| Borç | İşaret |
|---|---|
| Tanınmayan bir risk seviyesi `results.py:19-25`'te kaçırılmadan HTML'e giriyor | Tetikleyici: **`analysis_results.json`'a dışarıdan yazan bir yol açıldığında**; aksi hâlde **v1.1** |

---

## Markdown-link yüzeyi — `transformLinkUri` ezilmiş, LLM çıktısı düz `st.markdown`'da

**Where:** [`ui/results.py`](../src/defect_risk_analyzer/ui/results.py)
(`:30`, `:39`, `:45`, `:52`)

`reasoning`, `affected_modules`, `test_scenarios` ve `recommended_actions` LLM'den
gelip düz `st.markdown` ile basılıyor — `unsafe_allow_html` yok, yani ham HTML
parse edilmiyor. Ama markdown'ın kendisi render oluyor: `[metin](javascript:…)`
ve `![](https://…)` çalışır durumda.

Sebep bundle'da ölçüldü (streamlit 1.41.1, `static/static/js/index.Phesr84n.js`):
Streamlit, react-markdown'ın `javascript:` URI'lerini temizleyen varsayılan
dönüşümünü kimlik fonksiyonuyla eziyor — `function transformLinkUri(tt){return tt}`.
React 18.3.1 prod build'i `javascript:` href'lerini bloklamıyor. Ayrıca hiçbir
katmanda `Content-Security-Policy` yok.

**Bir yanlış çıkarım burada düzeltiliyor:** Faz 6 keşfi "bundle'da DOMPurify 3.1.7
var, yani script çalıştırma muhtemelen engelli" demişti. DOMPurify gerçekten
gömülü ama yalnız `stHtml` chunk'ında (`index.CbuYSrVP.js`), yani `st.html()`
API'sinde — bu proje onu hiç çağırmıyor. `st.markdown` yolunda sanitizer yok;
script'in çalışmaması React 18.3.1'den geliyor (`<script>` parser-inserted olarak
üretiliyor, `on*` nitelikleri attribute yazıcısında düşüyor). Koruma var ama
kaynağı başka, ve link yüzeyini kapsamıyor.

Faz 6C'ye çekilmedi: kapsamı iki katına çıkarır ve içerik olarak farklı bir konu
— HTML kaçışı değil, prompt injection yüzeyi.

| Borç | İşaret |
|---|---|
| LLM çıktısı `javascript:` bağlantısı ya da dış kaynaklı bir görsel üretirse render oluyor | Tetikleyici: **LLM çıktısının render yolu bir daha değiştiğinde**; aksi hâlde **v1.1** |

---

## `Content-Security-Policy` hiçbir katmanda ayarlanmıyor

**Where:** dağıtım yüzeyi — [`Dockerfile`](../Dockerfile),
[`docker-compose.yml`](../docker-compose.yml), streamlit'in kendi sunucusu

Ölçüldü: `Content-Security-Policy` ne streamlit 1.41.1'in Python sunucusunda, ne
servis edilen `static/index.html`'de, ne de `src/` altında geçiyor. CSP olmadan,
`unsafe_allow_html` taşıyan bir gövdeye giren `<img src="https://…">` sayfa
render olur olmaz dış istek atar — Faz 6C'nin kaçış çalışması bunu üretecek yolu
kapattı, ama katman savunması olarak CSP yine yok.

Faz 6C kapsamı dışında: uygulama kodu değil, dağıtım hijyeni.

**6D'de de yapılmadı, ve nedeni ölçüldü.** Streamlit 1.41.1'de CSP başlığı
eklemenin desteklenen bir yolu yok: 55 yapılandırma seçeneğinin hiçbiri
başlıklara dokunmuyor (`server.headless` yalnız ad benzerliği), `_create_app`
sabit bir Tornado route listesi kuruyor ve middleware kancası sunmuyor, ve
servis edilen `static/index.html`'in tek `<meta>`'sı `charset`. Başlığı
uygulayabilecek tek yer bir ters proxy — bugünkü `docker-compose.yml` ise iki
servisi doğrudan yayınlıyor, araya hiçbir şey girmiyor. Proxy eklemek yeni bir
servis, imaj ve sağlık kontrolü demek, ve masaüstü yolunda (`BASLAT.bat`,
`streamlit run`) hiç uygulanmayacağı için korumanın yalnız Docker'da var olduğu
bir güvenlik iddiası üretirdi. Yani bu bir hijyen kalemi değil, altyapı kararı;
6D'nin kapsamından bu yüzden çıkarıldı.

| Borç | İşaret |
|---|---|
| Enjekte edilen bir dış kaynak isteğini durduracak ikinci bir katman yok | **v1.1**, tetikleyici: **dağıtım yoluna bir ters proxy girdiğinde** |
---

## `config.py` ve `__init__.py` kasten `module-map.json`'da yok

**Where:** [`module-map.json`](../module-map.json),
[`ci_analyzer.py`](../src/defect_risk_analyzer/ci_analyzer.py)

Ölçüm — 2026-08-30, `python tests/tools/module_map_report.py`:

| | |
|---|---|
| izlenen dosya | 109 |
| `exclude` ile elenen | 59 |
| kapsamda kalan | 50 |
| bir modüle eşleşen | 36 |
| kapsamda ama eşleşmeyen | 14 |
| `src/**/*.py` kapsamı | 34/36 = **%94,4** |

Araç aynı ölçümü `36 of 50 analyzable (34 of 77 tracked .py)` diye de yazıyor;
77, `tests/` altındakiler dahil bütün `.py` dosyaları. Yukarıdaki %94,4 yalnız
`src/` paketinin kapsamı.

Bu sayılar anlık fotoğraf ve dosya eklendikçe bayatlıyor: **bu kaydı ekleyen PR**
izlenen sayısını 106'dan 109'a, elenen sayısını 56'dan 59'a taşıdı — üç yeni
dosyanın üçü de `exclude`'a düştüğü için `analyzable` 50'de kaldı. Onun için sayı
değil komut yazılı: araç salt okunur, dökümü de basar, ve okuyan kişi güncel
hâlini kendisi üretebilir. Bir bekçiyle tutulmuyor: lint
bakiyesi tek bir cümleydi, bu tablo altı satır ve kapsamı belgenin çoğunu
ilgilendiriyor; her dosya eklemesinde kırmızıya dönen bir bekçi belgeyi
güncellemeyi değil belgeden kaçınmayı öğretir.

Haritasız kalan iki `src` dosyası: `__init__.py` (paket işaretçisi) ve
`config.py`.

**Karar.** `config.py` her modülü besliyor ve tek bir Jira bileşenine ait
değil. Onu bir modüle bağlamak, Faz 4(b)'nin kaldırdığı dosya-adı tahmininin
elle yapılmış hâli olurdu: harita "şu yol şu bileşene aittir" diye bir cümle
kurar, `config.py` için ise böyle bir cümle yok. `module-map.json`'un kendi
`_comment`'i "eşleme yok" cevabının dürüst bir cevap olduğunu zaten söylüyor;
burası o kuralın uygulandığı yer. Bu bir borç değil, kalıcı bir karar.

**Karşı okuma, kayda geçiyor.** %94,4 kapsam ve boşluğun tam olarak bu iki
dosyaya düşmesi, bir kararın sonucu değil desen dokumasından kalan bir delik
gibi de okunur — hele `config.py` deponun en çok dokunulan dosyalarından
biriyken. Bu kaydın yazılması o okumanın dayanağını kaldırmıyor; yalnız
"karar hiçbir yerde yazılı değil" argümanını kaldırıyor.

**Kapsamın iki katmanı var ve boşluk ikisinde de.** Katman 1 `exclude`,
katman 2 `modules`. Dört PR ölçüldü:

```
PR #17  fix/desktop-extra   3 dosya -> kapsamda 0                 Katman 1
PR #18  docs/roadmap        1 dosya -> kapsamda 0                 Katman 1
PR #13  Faz 6A              8 dosya -> kapsamda 3 -> eşleşme 0    Katman 2
6D-1    bu PR               5 dosya -> kapsamda 1 -> eşleşme 0    Katman 2
```

Dördü de `NOT ASSESSED`. Katman 1'dekiler uzantıyla eleniyor (`**/*.toml`,
`**/*.txt`, `docs/**`, `tests/**`). Katman 2'dekiler ise kapsama **giriyor** ve
hiçbir desene uymuyor: 6A'da `.gitignore`, `BASLAT.bat` ve `config.py`; bu PR'da
`module-map.json`'un kendisi. `exclude` listesi uzantıya göre yazıldığı için
uzantısız ve tekil dosyalar birinci ağdan geçiyor, `modules` deseni de onları
tutmuyor — 14 UNMATCHED tam olarak bu artık.

Her iki eleme de tek tek doğru davranış. Bedeli şu: PR #17 gerçek bir paketleme
hatasını düzeltti ve risk raporunda hiç görünmedi, **ve bu kaydı ekleyen PR da
görünmüyor.**

**Neden yeniden ölçülemez bir sayı burada duruyor.** Faz 4(b), token
yaklaşımının en pahalı yanlış pozitifini `api_auth.py` üzerinden ölçmüştü: tek
satırlık bir değişiklik `auth` token'ı üzerinden Authentication'ı ateşleyip
`79/100 HIGH RISK` veriyordu (ölçüm: `ROADMAP-v2.md:237-239`, PR #3). Bugün
yeniden ölçülemez — onu üreten kod (`MODULE_KEYWORDS`, `_path_tokens`,
`_matched_token`) 4(b) Bölüm B'de silindi ve `module-map.json` kasten
`sample_bugs.json` ile örtüşmüyor. Kaynağıyla birlikte duruyor; kaynaksız
yazılsaydı doğrulanamaz bir iddia olurdu.

| Borç | İşaret |
|---|---|
| `config.py` ve `__init__.py`'nin haritasız kalması kalıcı karar — ama kapsam ağının ikinci katmanında 14 dosyalık bir artık var ve bunların hangisinin karar, hangisinin gözden kaçma olduğu dosya bazında yazılı değil | Tetikleyici: **`module-map.json` bir daha genişletildiğinde** |

---

## `anyio==4.14.2` — bir uyarıyı kaldırmak için konmuş transitif pin

**Where:** [`requirements-dev.txt`](../requirements-dev.txt),
bekçi: [`tests/test_dependency_pins.py`](../tests/test_dependency_pins.py)

Faz 6D-3a. `anyio` bu projede hiçbir yerde doğrudan istenmiyor; `chromadb →
fastapi → starlette` zincirinden ve ayrıca `groq`, `openai`, `httpx`,
`watchfiles`'tan geliyor — altısı da üst sınır koymuyor (en dar tavan `<5`).
2026-09-05'te CI'ın çözdüğü sürüm `anyio==4.15.1` idi.

4.15.0 `anyio` ve `anyio.abc` modüllerini tembel importa çevirdi ve geriye-uyum
re-export'larını uyaran alias'lara dönüştürdü. `starlette 1.6.0`
`testclient.py:53`'te modül düzeyinde `anyio.abc.BlockingPortal`'a dokunuyor, ve
CI'ın `pytest` çıktısında `The anyio.abc.BlockingPortal alias is deprecated`
beliriyordu. 4.14.2'de aynı ad düz bir re-export, uyarı orada imkânsız.

**Ölçümler (2026-09-05).** Geçici bir venv'de, `starlette` 1.6.0'da sabit,
yalnız `anyio` değiştirilerek:

| | yakalanan uyarı | bekçi testi |
|---|---|---|
| `anyio==4.15.1` | 2 (httpx→httpx2 **ve** anyio alias) | **kırmızı** |
| `anyio==4.14.2` | 1 (yalnız httpx→httpx2) | yeşil |

`pip install --dry-run -r requirements-dev.txt anyio==4.14.2` → exit 0,
**118 paket** (pinsiz de 118), 13 doğrudan; `starlette`, `fastapi`, `uvicorn`,
`httpx`, `chromadb` kıpırdamadı. Pin paket eklemiyor, hiçbir paketi geri
çekmiyor.

**Uyarı yalnız test yolunda — ölçüldü, varsayılmadı.** `anyio.abc`'nin uyaran
alias'larını (`BlockingPortal`, `CapacityLimiter`, `Condition`, `Event`, `Lock`,
`Semaphore`, `CancelScope`) izleyen bir probe modülü altında import edildiğinde
yalnız `starlette.testclient` `BlockingPortal`'a dokunuyor; paketin **35
modülünün tamamı**, `uvicorn.main`, `defect_risk_analyzer.api`, `cli`,
`ci_analyzer`, `fastapi` ve `chromadb` dokunmuyor. Bu yüzden pin
`requirements.txt`'te değil `requirements-dev.txt`'te: uvicorn ile çalışan
webhook, dashboard ve CLI bu uyarıyı üretmiyor, ve son kullanıcının çözüm
uzayını daraltmak için sebep yok.

**Kabul edilen sonuç:** `pr-risk-analysis.yml` yalnız `requirements.txt` kuruyor
ve `anyio 4.15.x` çözmeye devam edecek — orada uyarı yok, çünkü o yol
`ci_analyzer`'ı çalıştırıyor. `Dockerfile` da bu dosyayı hiç `pip install`
etmiyor. İki iş akışının farklı çözünürlük test etmesi zaten **6D-3b**'nin
maddesi; bu, o listeye bir paket daha ekliyor. (Bu cümle 6D-4d-1'e kadar
depoda olmayan bir maddeye atıf yapıyordu; madde artık aşağıda, "Transitif
sürüklenme — 6D-3b'nin kısıt dosyası ertelendi" bölümünde.)

**İkinci uyarı bu fazın değil.** `StarletteDeprecationWarning: Using 'httpx'
with 'starlette.testclient' is deprecated; install 'httpx2' instead.`
(`testclient.py:40-51`) 6D-3a'dan sonra da duruyor ve durması bekleniyor.
Sahibi **6D-4**. Yukarıdaki tablo bunu gösteriyor: 4.14.2'de bile bir uyarı
kalıyor, yani bekçi testi "hiç uyarı yok" diye boş yere geçmiyor.

**İki bekçi, iki ayrı iş — ve biri ötekinin yerini tutmuyor.**

- `test_requirements_dev_still_carries_the_expected_anyio_pin` = **mutasyon
  bekçisi**. İki mutasyon denendi, ikisi de kırmızı: satırın silinmesi (M1) ve
  satırın `anyio==4.15.1` yapılması (M2). M2 ayrıca testin "satır var mı"
  testine indirgenmediğini gösteriyor.
- `test_starlette_testclient_emits_no_anyio_alias_deprecation` = **gerekçe
  bekçisi**. Uyarının yokluğunu tutar; elemesi mesaj bazında dar tutuldu, geniş
  bir "DeprecationWarning'leri yok say" filtresi 6D-4 httpx2'yi çözdüğünde ya
  da üçüncü bir uyarı çıktığında testi sessizce izin verici yapardı.
- **Gerekçe bekçisi geliştirici makinesinde mutasyon-geçirmez.** "Pini sil"
  mutasyonu yalnız bir metin dosyasını değiştirir; kurulu `anyio` yerinde kalır
  ve 4.15 öncesiyse kırmızı fiziksel olarak imkânsızdır. Kırmızısı bu yüzden
  yukarıdaki geçici venv'de gözlendi. Birleşik takım mutasyon protokolünü
  **yalnız birinci test sayesinde** geçiyor; gizlenirse "iki testimiz var,
  korunuyoruz" yanılgısı üretir.

| Borç | İşaret |
|---|---|
| ~~Bir üst-akış uyarısını susturmak için tutulan transitif pin; `anyio` bu pin durdukça 4.14.2'de donuyor~~ — **Kapandı (6D-4d, 2026-10-06):** tetikleyici ateşlendi (starlette 1.7.0, aşağıdaki 6D-4d-1 eki); pin kaldırıldı, literal bekçi silindi, gerekçe bekçisi kaldı ve artık starlette'in 1.7.0 altına inmesini bekliyor (aşağıdaki 6D-4d eki) | — |
| `chromadb` 1.x `fastapi`yi runtime'dan `dev` extra'sına taşıyor (1.5.9'da ölçüldü); 6D-4b 0.6.3'te durdu ve `starlette` kapanışta kaldı (6D-4b'de kontrol edildi, tetiklenmedi). 1.x'e geçişte `starlette` `requirements-dev.txt`'in kapanışından düşerse gerekçe bekçisi **kırmızıya döner**: 6D-4d'den beri ölçemeyen bekçi skip değil kırmızı (kullanıcı kararı 2026-10-06). Kırmızı bir kusur değil, sinyal: testin koruyacağı şey kalmamıştır | Tetikleyici: **6D-5**, chromadb 1.x geçişiyle. O PR testi bilerek siler ya da `starlette`'in yeni kaynağına göre günceller; skip'e çevirmez |
| `tests/test_dependency_pins.py` adı genel; dosya bir yığınak değil | Tetikleyici: **dosyaya yeniden bir pin eklendiğinde** (6D-4d'den beri dosyada pin yok, yalnız bir gerekçe bekçisi var) — her yeni pin kendi mutasyonunu gerektirir |

**Faz 6D-3c eki — anyio'nun bump PR'ı tasarım gereği kırmızıdır.** pip
ekosistemi açıldığına göre Dependabot bu pini 4.15.x'e yükseltmek için PR
açacak, ve yukarıdaki iki bekçi o PR'ı kırmızıya çevirecek: mutasyon bekçisi
literal değiştiği için, gerekçe bekçisi uyarı geri geldiği için. **Bu istenen
sinyaldir, yanlış yapılandırma değil** — ilk gelişinde öyle sanılmasın diye
buraya yazıldı. `dependabot.yml`'de `exclude-patterns: ["anyio"]` ile gruptan
çıkarıldı, çünkü grup içinde bu kırmızı, birleştirilemeyecek bir PR'a bağlı
olarak bütün patch/minor bump'ları rehin alırdı. PR kapatılırsa Dependabot onu
aynı sürüm için yeniden açmaz; bir sonraki `anyio` sürümünde yeni bir PR gelir.

**DAMGASIZ — ve 6D-4c'de kısmen bile kapanmadı.** Yukarıdaki son cümle
ölçülmedi. 6D-4c'de üç PR'ın kapanışı API'den tek tek çekildi
(`merged`, `closed_by`, kapanış yorumu) ve **iki kip ölçüldü**:

| kip | gözlem | yorum |
|---|---|---|
| (i) main'in pini hedefe ulaştı | #24, 2026-09-09 17:18:09Z, `closed_by=dependabot[bot]`, `merged=false` | *"Looks like these dependencies are no longer updatable, so this is no longer needed."* |
| (ii) supersede — PR açıkken daha yeni sürüm çıktı | #26, 2026-09-12 14:47:59Z, aynı alanlar | *"Superseded by #35."* — ve #35 aynı sürüm için değil, **daha yenisi** için açıldı (3.8.0 → 3.10.0) |
| (iii) **insanın düz `Close`'u** | **hiç gözlenmedi** | — |
| (iv) **yerinde yeniden yazma** — 2026-09-24'te eklendi | #35, 20:55:38Z `renamed` + 20:55:39Z `head_ref_force_pushed` (`30fc1ae → 501adf9`); #33 aynı dakikada | **yorum yok, kapanış yok.** Başlık "1.58.1 to 3.10.0" → "3.13.0 to 3.16.2"; PR numarası ve dal adı (`openai-3.10.0`) aynı kaldı |

Yukarıdaki cümlenin **her iki yarısının da öncülü "PR kapatılırsa"**. Ölçülen
iki kipte de PR'ı kapatan insan değil botun kendisiydi, ve #26 kapalı değil
**açıkken** ezildi. Yani gözlem (ii) cümlenin ikinci yarısını *makul* kılıyor
ama ölçmüyor; birinci yarısına hiç dokunmuyor.

**Damga (iii) için duruyor.** Deney #25 üzerinde yapılmadı, çünkü #25 kasıtlı
kırmızı sinyalin taşıyıcısı ve harcanmak istenmedi. Tetikleyici: **bir sonraki
gereksiz Dependabot PR'ı** — düz `Close`, sonra bir sonraki taramada aynı
sürümün geri gelip gelmediği gözlenir.

**Yan ölçüm — supersede limite tabi değil.** #35 14:47:58Z'de açıldı, #26
14:48:01Z'de kapandı. O üç saniye boyunca açık pip PR sayısı **6**, yani
`open-pull-requests-limit: 5`'in üstünde. Sıra: önce yeni PR, sonra yorum,
sonra kapatma — yuva boşaltılıp doldurulmuyor.

**Kip (iv), ve (ii) ile (iv)'ü ayıran şey hâlâ bilinmiyor.** #36 (6D-4c)
2026-09-24 20:53:26Z'de merge edildi; 84 saniye sonra `pip in / for openai` ve
`pip in / for plotly` işleri koştu, ikisi de `success`. #35 kapatılmadı, supersede
edilmedi — **aynı numarayla yeniden yazıldı**. #33 de öyle (plotly 7.0.0 →
7.1.0). Açık PR sayısı hiç 6'ya çıkmadı.

Sınanmamış bir hipotez kuruldu ve aynı olayda çürüdü: "09-12'de yalnız hedef
sürüm değişti → supersede; 09-24'te başlangıç sürümü de değişti (main'in pini
1.58.1 → 3.13.0) → yerinde yazma." **#33 buna doğrudan karşı örnek:** #26 ile
aynı biçimdeydi — başlangıç 5.24.1 sabit, yalnız hedef 7.0.0 → 7.1.0 — ama
yerinde yazıldı. Yani başlangıç sürümünün değişmesi belirleyici değişken değil, ya
da tek değişken değil. Açık adaylar, hiçbiri sınanmadı: 09-12'deki yenileme bir
config push'unun tam taramasının hemen ardından geldi, 09-24'teki config'siz bir
push'tan; ya da Dependabot'un davranışı iki tarih arasında değişti.

**Pratik sonuç: dal adı bir PR'ın hedefinin kanıtı değil.** Yerinde yazmada dal
adı eskisi gibi kalıyor — #35 `openai-3.10.0` dalında 3.16.2 taşıyor, #33
`plotly-7.0.0` dalında 7.1.0. Hedefi PR başlığından ya da dosya farkından oku.

---

## Satır sonu normalizasyonu depoda değil, her klonun kendi ayarında

**Where:** deponun kökü — `.gitattributes` **yok**

Faz 6D-3a sırasında yol üstünde görüldü, kapsam kuralı gereği kaydedildi ve
düzeltilmedi.

**Ölçüm — 2026-09-05, `git cat-file -p HEAD:<dosya>` ile blob, ayrıca disk:**

| dosya | HEAD blob | çalışma kopyası (bu makine) |
|---|---|---|
| `requirements.txt` | LF=30 | CRLF=30 |
| `requirements-dev.txt` | LF=17 | **LF=53** |
| `requirements-webhook.txt` | LF=29 | CRLF=29 |
| `docs/KNOWN-DEBT.md` | LF=1197 | **CRLF=1197 + LF=76** |
| `pyproject.toml`, `CONTRIBUTING.md`, `tests.yml` | LF | CRLF |

**Deponun içeriği bugün temiz: her blob LF.** Sorun kaydedilmiş içerikte değil,
onu üreten mekanizmanın nerede durduğunda. Karışıklık yalnız çalışma
kopyasında, ve `core.autocrlf=true` onu diff'te tamamen maskeledi — 6D-3a'nın
`requirements-dev.txt` değişikliği **36 ekleme, 0 silme** olarak göründü, oysa
dosya diskte tamamen LF'e dönmüştü.

**Borç maskenin kendisi.** `core.autocrlf` **makine ayarıdır, depo ayarı
değil**; depoda `.gitattributes` olmadığı için normalizasyonun yapılıp
yapılmayacağına her klon kendi başına karar veriyor. `autocrlf=false` ile
klonlayan biri (git'in Linux/macOS varsayılanı) CRLF yazan bir editörle tek
satır değiştirdiğinde **tam dosya farkı** üretir; inceleme o PR'da imkânsız
hale gelir ve `git blame` tarihi kopar. Bu makinede görünmüyor olması, olmadığı
anlamına gelmiyor — tam tersi, görünmemesi tanımın kendisi.

Aynı PR'da düzeltilmedi: `.gitattributes` eklemek deponun tamamına dokunan bir
normalizasyon commit'i demek, ve 6D-3a tek satırlık bir pin fazı.

| Borç | İşaret |
|---|---|
| `.gitattributes` yok; satır sonu normalizasyonu her klonun `core.autocrlf` ayarına bırakılmış, yani depo kendi biçim sözleşmesini taşımıyor | **Faz 7**, tetikleyici: **depoda `.gitattributes` yok VE bir PR'da tek satırlık bir değişiklik tam-dosya farkı üretiyor** — hangisi önce gelirse. Faz 7'nin temiz makine denemesi ("indir, 5 dakikada çalıştır") bunu yüzeye çıkaracak doğal yer |

---

## Bot PR'larında risk analizi bilerek koşmuyor

**Where:** [`.github/workflows/pr-risk-analysis.yml`](../.github/workflows/pr-risk-analysis.yml)

Faz 6D-3c'nin keşfinde yol üstünde bulundu ve **ayrı, tek satırlık bir PR
olarak** düzeltildi — 6D-3c'nin kendisinden önce, çünkü kusur 6D-3c olmadan da
var: `dependabot.yml`'nin `github-actions` ekosistemi 2026-09-03'ten beri açık
ve ilk aksiyon bump'ında aynı şey olurdu.

**İki gerekçe, biri belgeden biri ölçümden.**

- **İş kırılırdı.** GitHub Docs, *Troubleshooting Dependabot on GitHub Actions*:
  bot tetiklediğinde workflow'lar *"receive a read-only `GITHUB_TOKEN` and do
  not have access to any secrets"*. Dosyadaki `permissions: pull-requests:
  write` bunu değiştirmiyor, yani "Post report as PR comment" adımı 403 alırdı.
- **İş zaten hiçbir şey söylemezdi.** Dependabot yalnız manifest dosyalarına
  dokunuyor; `module-map.json`'un `exclude` listesi `**/*.txt` ve `**/*.toml`
  taşıyor, dolayısıyla `select_analyzable_files()`
  (`ci_analyzer.py:335-357`) boş liste döndürür ve rapor `NOT ASSESSED —
  changed files did not map to any known module` olur.

**Adım değil job atlanıyor.** Yalnız yorum adımını atlamak analizi koşturmaya
devam ederdi; bu workflow'da `cache: pip` **yok** (`tests.yml`'de var), yani her
bot PR'ında 112 paketlik tam bir çözümleme okunmayacak bir rapor için ödenirdi.
Ölçülen kayıp sıfır.

**GÖZLENMEDİ — çıkarımla düzeltildi.** 403'ün alındığı görülmedi, çünkü bu
depoda hiç Dependabot PR'ı olmadı. Actions API'sinde `dependabot[bot]` aktörlü
tek çalışma 2026-09-03'teki `github_actions in /.` taraması
(`event: dynamic`, success); `pull_request` olayıyla tetiklenmiş bir bot
çalışması yok ve son 50 çalışmanın hiçbiri başarısız değil. `pulls?state=all`
de tek bir bot PR'ı göstermiyor. Negatif kontrol bu yüzden beklemede: ilk
Dependabot PR'ında job'ın atlandığı Actions'ta görülecek.

| Borç | İşaret |
|---|---|
| Bot PR'larında bu iş akışı hiç koşmuyor; bugün kaybı sıfır ama bu, raporun bugün boş olmasına bağlı | Tetikleyici: **`module-map.json`'un `exclude` listesinden `**/*.txt` çıkarıldığında** — o an bot PR'ının analiz edilecek içeriği olur ve `if` gerekçesinin yarısını kaybeder |
| `if` koşulu belgeden okunan bir davranışa dayanıyor, gözlenen bir 403'e değil | Tetikleyici: **ilk Dependabot PR'ı** — job'ın atlandığı görüldüğünde bu satır ölçüme dönüşür. Ayrıca depo ayarı bot workflow'larına yükseltilmiş izin verirse koşul kalkabilir |

---

## `chromadb` 1.x Dependabot'ta ertelendi — düzeltmesi olmayan bir CRITICAL yüzünden

**Where:** [`.github/dependabot.yml`](../.github/dependabot.yml),
bekçi: [`tests/test_dependabot_config.py`](../tests/test_dependabot_config.py)

Faz 6D-3c pip ekosistemini açtı ama iki paketi `ignore` ile 6D-4'e erteledi.
**Faz 6D-4a `streamlit` yarısını kapattı; `chromadb` duruyor.** Gerekçe
ölçüldü: `chromadb` 0.5.23 → 1.5.9 `fastapi`yi runtime'dan `dev` extra'sına
taşıyor ve `tests.yml` `requirements-webhook.txt`'i kurmuyor, yani mekanik bir
bump CI'da hiçbir botun çözemeyeceği bir nedenle kırmızı olur — ölçüldü, ve
görünüşü "8 test kırmızı" değil: `tests/test_api_auth.py` import edilemediği
için `pytest` **bütün koşuyu** bir collection error'la durduruyor.

**Ad bazlı, semver seviyesi bazlı değil.** `streamlit`'in sıçraması semver'e
göre **minor**; `update-types: [version-update:semver-major]` filtresi onu
yakalamazdı. `chromadb`'nin sıradaki adımı da minor, yani gerekçe duruyor.

**KABUL EDİLEN BEDEL, ÖLÇÜLDÜ.** `ignore` yalnız sürüm güncellemelerini değil
güvenlik güncellemelerini de kesiyor — GitHub Docs, *Controlling which
dependencies are updated by Dependabot*: *"You can configure Dependabot to
ignore those dependencies when it opens pull requests for version updates and
security updates."* `applies-to: security-updates` grubu bunu telafi etmez:
grup yalnız PR'ların nasıl paketlendiğini belirler, `ignore` güncellemenin
kendisini engeller.

**BEDEL TEORİK DEĞİLDİ — 6D-4a'da ölçüldü.** `ignore: streamlit` durduğu sürece
`streamlit 1.41.1`'in **iki gerçek advisory'sini** susturuyordu:
CVE-2026-33682 (Windows'ta kimliksiz SSRF / NTLM sızıntısı, MODERATE, düzeltme
1.54.0) ve CVE-2026-10804 (`st.cache_data` hash çakışması, LOW, düzeltme
1.53.1). Yani bu madde "olabilir" değil "oluyordu" diyordu.

**VE ÖNCEKİ RİSK DEĞERLENDİRMESİ YANLIŞTI, DÜZELTİLİYOR.** Bu madde daha önce
şöyle diyordu: *"`pillow`'un 18 CVE'si bu maddeden etkilenmiyor … Risk
`streamlit`'in ya da `chromadb`'nin kendi olası bir CVE'si."* Mekanizma kısmı
doğruydu — `pillow` hiçbir manifest'te beyan edilmiyor, lock dosyası yok, yani
`pillow` için zaten güvenlik PR'ı üretilemezdi. **Ama risk okuması yanlıştı.**
`streamlit 1.41.1`'in `pillow<12` tavanı, `pillow`'u 11.3.0'da tutan **tek**
kısıttı; `ignore: streamlit` o tavanı dondurduğu için 18 CVE'yi de dolaylı
olarak donduruyordu. 1.63.0 tavanı `pillow<13` yapıyor ve çözüm `pillow 12.3.0`
veriyor: **18 CVE'nin hepsi kapandı.** "Dependabot PR açamaz" ile "risk
etkilenmiyor" iki ayrı iddiaydı; ikincisi ölçülmemişti ve yanlıştı.

Ölçümün tamamı (OSV, 2026-09-09, çözülmüş kümenin tamamı taranarak): bugünkü
kümede 118 paketten 4'ü açıklı, **45 advisory kaydı**. `streamlit` bump'ı
bunların **40'ını** kapatıyor — 36 kayıt `pillow` (= 18 ayrı CVE, GHSA ve PYSEC
ad uzaylarında aynı zafiyetler) ve 4 kayıt `streamlit`. Kalan 5: `chromadb` ×3,
`pytest` ×2.

**Tetikleyici bir yorum değil, bir test — ve ateşlendi.** `.yml` yorumu kendini
hatırlatmıyor; `tests/test_dependabot_config.py` pin oynadığı an kırmızıya
dönüyor ve hata mesajı ne yapılacağını yazıyor. 6D-4a'da tam olarak bu oldu:
`streamlit==1.63.0` yazıldığı an `:121` kırmızı verdi, mesaj `streamlit` adını
ve *"dependabot.yml'deki girdisini de SILIN"* talimatını içeriyordu. Kırmızı
**önce gözlendi**, girdi ve tablo satırı **sonra** silindi. Testin beyan edilmiş
kör noktası da orada: tutulan şey tutarlılık, varlık değil — bir ad `ignore`
listesinden silinirse bekçi görmez (M3 mutasyonu, hayatta kalması beklenen).

### 6D-4b: `chromadb` 0.6.3'te durdu, `ignore` daraltıldı

**Pin 1.5.9'a değil 0.6.3'e taşındı** ve `ignore` girdisi silinmek yerine
`versions: [">=1.0.0"]` ile daraltıldı. Gerekçe tek kalem ve ölçüldü:
**CVE-2026-45829** (GHSA-f4j7-r4q5-qw2c), CRITICAL, exploit kanıtı mevcut —
kimlik doğrulama **öncesi** kod enjeksiyonu, `>=1.0.0`'ı etkiliyor ve
`last_affected` değeri en son yayınlanan sürüm olan 1.5.9, yani gidilecek bir
yer yok.

**`>=1.0.0` sınırı gerçek, tarama artefaktı değil — ölçüldü,** çünkü "eski
sürümler taranmamıştır" bariz alternatifti. Saldırının ihtiyaç duyduğu makine
yapılandırmadan embedding function kuran kayıt: `build_from_config` 1.5.9'da
**42 dosya / 36 EF sınıfında**, 0.5.23'te **0 dosyada**; `known_embedding_functions`
bir koleksiyon yapılandırması JSON'dan çözülürken okunuyor
(`api/collection_configuration.py:93,316,630`, `api/types.py:2917,2967`).
`/api/v2` yolları 0.5.23'te de var (22 v1 + 23 v2), yani sınırı açıklayan şey
API sürümü değil bu kayıt.

**Sunucu iki hatta da kaldırılabiliyor.** `chroma run` 0.5.23'te de (Python/
FastAPI) 1.5.9'da da (fastapi hiç gerektirmeyen bir Rust CLI) var — ilk okumam
"1.x'te fastapi dev extra'sına gittiği için sunucu kalkamaz" demeye
meyilliydi ve **yanlıştı**. Fark "sunucu açılabilir mi" değil, "açılan sunucu
kimliksiz RCE taşıyor mu". Bu depo yalnız `PersistentClient` kuruyor
(`sys.modules`'te server/web modülü yok, ölçüldü), ama paket sunucuyu kuran
herkese sevk ediyor ve bu depo public.

**Kazanılan:** `tokenizers<=0.20.3` tavanı kalktı (0.23.2). **Değişmeyen:**
`fastapi` runtime'da kaldı, yani `tests.yml` bu fazda değişmedi ve
`requirements-webhook.txt` no-op kalmaya devam ediyor. Yapısal yarı — fastapi'nin
`dev` extra'sına geçmesi, `tests.yml`'in webhook dosyasını kurması, −8 paket —
**6D-5**.

**Tetikleyici ikinci kez ateşlendi.** `tests/test_dependabot_config.py` pin
oynadığı an kırmızı verdi ve `chromadb` adını söyledi; kırmızı **önce
gözlendi**, `EXPECTED_IGNORED_PINS` ve `ignore` girdisi **sonra** güncellendi.
6D-4a'da `streamlit` için aynısı olmuştu. Bekçinin çalıştığı artık iki kez
gözlendi.

| Borç | İşaret |
|---|---|
| ~~`streamlit` donmuş durumda~~ — **6D-4a'da kapandı**: pin 1.63.0, `ignore` girdisi ve bekçi tablosu satırı silindi, 40 advisory kaydı kapandı | — |
| ~~`chromadb` tümüyle donmuş durumda~~ — **6D-4b'de daraltıldı**: pin 0.6.3, `ignore` artık yalnız `>=1.0.0`, yani 0.6.x yama güncellemeleri akmaya devam ediyor | — |
| `chromadb` **1.x hattı** ertelenmiş durumda ve o hattaki bir CVE için PR açılmaz | Tetikleyici: **CVE-2026-45829 için bir düzeltme yayınlandığında.** ~~mekanik biçimi 6D-4d'nin haftalık workflow'u: `pip-audit -r` ile `chromadb>=1.0.0` taranır ve GHSA-f4j7-r4q5-qw2c raporlanmayı bıraktığında **öteki üçü hâlâ raporlanıyorsa** kırmızı verir. İki koşul birlikte, çünkü boş sonuç iyi haber değil bozuk taramadır~~ — **6D-4d-3'te değişti (2026-10-07):** "öteki üçü" şartı asıl olayı sessizce "sonuçsuz"a çevirecekti. Dört advisory'nin dördü de kapalı aralıklı, `last_affected: 1.5.9` (OSV, 2026-10-07; 45829 `introduced 1.0.0`, 45830 ve 45833 `0.4.17`, 45831 `0.5.0`); yeni bir 1.x sürümünde dördü birden görünmeyebilir. Yerine pozitif kontrol: [`chromadb-1x-watch.yml`](../.github/workflows/chromadb-1x-watch.yml) her Çarşamba iki tarama yapar, kontrol (`chromadb==` sabit bir sürüm; tek yeri izleyici betiği) ve hedef (`chromadb>=1.0.0`). **Kırmızı "iş var"** = kontrol 45829'u raporluyor, hedef raporlamıyor → bu girdi silinir, 6D-5 başlar. Bozuk tarama kendi başlığıyla kırmızı ("izleyici bozuk"). Ayrıntı: "Faz 6D-4d-3 eki" |
| **CVE-2026-45830** (GHSA-2wm9-hf6c-p5cr), HIGH — tenant yetkilendirme doğrulaması yok; kimlikli her kullanıcı her tenant'ın koleksiyonunu okuyup yazabiliyor. 0.5.23, 0.6.3 ve 1.5.9'un **üçünde de açık**, düzeltme yayınlanmamış. Bu depoda erişilemez: sunucu hiç ayağa kalkmıyor, yalnız `PersistentClient` var | Tetikleyici: **advisory'de bir `fixed` sürümü belirdiğinde** — `last_affected` bugün 1.5.9 |
| **CVE-2026-45833** (GHSA-36p7-vc44-83pf), CRITICAL — kimlikli kod enjeksiyonu, `trust_remote_code` taşıyan bir koleksiyon güncellemesiyle, UPDATE_COLLECTION izni gerekiyor. Üç sürümde de açık, düzeltme yok. 45829'dan farkı kimlik gerektirmesi | Tetikleyici: **advisory'de bir `fixed` sürümü belirdiğinde** |
| **CVE-2026-45831** (GHSA-xph7-9rjv-w5fr), HIGH — `SimpleRBACAuthorizationProvider` izni doğruluyor ama hangi tenant/db/koleksiyona ait olduğunu kontrol etmiyor. `>=0.5.0`, düzeltme yok. Bu depo hiçbir auth provider yapılandırmıyor | Tetikleyici: **advisory'de bir `fixed` sürümü belirdiğinde** |
| ~~`open-pull-requests-limit: 5`, gruplanmış bir PR'ın limite karşı nasıl sayıldığı **belgede yazmıyor** (options reference ve gruplama sayfası arandı); iki okuma iki farklı sonuç veriyor~~ — **Cevaplandı (6D-3c'nin kapanış ölçümü); satır 6D-4d-2'de kapatıldı (2026-10-07).** Grup PR'ı limite karşı **tek PR** sayılıyor: ilk turda beş yuvanın biri grup #24, öteki dördü ayrı PR'lar (aşağıda, "Faz 6D-4c eki"nin yuva tablosu, tur 1). Cevap o gün ölçülmüştü ama bu satır çizilmemişti | ~~Tetikleyici: **6D-3c'nin kapanış ölçümü** — ilk taramadan sonra açılan PR kümesi grup + major'ları içeriyorsa okuma doğrudur; grup tek başına limiti doldurup major'ların hiçbiri açılmıyorsa limit yükseltilir~~ |

---

## Lint bakiyesi bekçisi yalnız iki kuralı sayıyor — üçüncüsü sessizce girebilir

**Where:** [`tests/test_known_debt_tally.py`](../tests/test_known_debt_tally.py),
tuttuğu cümle bu belgede (yukarıda, "Bugünkü bakiye ayrı bir sayıdır")

Kör nokta testin kendi docstring'inde beyan edilmişti ("yalnız toplamlar").
**Ruff 0.8.4 → 0.16.6 bump'ı onu ilk kez gerçek bir sayı değişimiyle
karşılaştırdı, ve ölçüm beyanı doğruladı.**

`ruff check . --config "lint.per-file-ignores={}" --statistics` ile üç durum:

| durum | B904 | E501 | I001 | gerçek izole toplam | bekçi |
|---|---|---|---|---|---|
| ruff 0.8.4 (bump öncesi) | 15 | 9 | — | 24 | yeşil |
| ruff 0.16.6, I001 düzeltilmemiş | 15 | 9 | **1** | **25** | **yeşil** |
| ruff 0.16.6, I001 düzeltilmiş (bu PR) | 15 | 9 | 0 | 24 | yeşil |

**Ortadaki satır borcun kendisi.** Bump düzeltmesiz merge edilseydi belgedeki
cümle "24 açık" derken gerçek izole bakiye 25 olurdu ve **bekçi yine yeşil
kalırdı** — çünkü yalnız `measured.get("E501")` ve `measured.get("B904")`
karşılaştırılıyor, üçüncü bir kural görülmüyor.

Bu PR'da cümle **değiştirilmedi ve değiştirilmemeliydi**: düzeltme bakiyeyi tam
olarak yazılı olduğu yere geri getiriyor. Cümle doğru — ama bunu bekçi değil,
düzeltme sağladı.

| Borç | İşaret |
|---|---|
| Bakiye bekçisi yeni bir kural sınıfını görmüyor; belge eksik kalabilir ve kırmızı vermez | Tetikleyici: **`ruff check . --config "lint.per-file-ignores={}" --statistics` çıktısında E501 ve B904 dışında bir satır belirdiğinde** — o an ya cümle o kuralı da saymalı ya da bekçi ölçülen tüm kuralları karşılaştırmalı |

---

## `pip install -r requirements-dev.txt` UTF-8 olmayan yerelde düşüyor

**Where:** [`requirements-dev.txt`](../requirements-dev.txt) — Faz 6D-3a'nın
Türkçe gerekçe yorumu

Faz 6D-3c'nin grup bump'ı araştırılırken yol üstünde bulundu, bu PR'da
**düzeltilmedi**.

**Ölçüm.** Bu makinede (Windows, `locale.getpreferredencoding()` = `cp1254`,
Python 3.11'in getirdiği `pip 24.0`):

    ERROR: Exception:
    UnicodeDecodeError: 'charmap' codec can't decode byte 0x9e in position 1557

Dosya **geçerli UTF-8**; pip onu yerel kod sayfasıyla okuyor. `PYTHONUTF8=1`
ile aynı komut sorunsuz çalışıyor.

**Tam olarak atfedildi.** `git cat-file -p <rev>:requirements-dev.txt` ile
blob'lar cp1254 ile çözülmeye çalışıldı: `6044157^` (6D-3a öncesi) **okunuyor**,
`6044157` ve sonrası **1521. bayttan düşüyor**. Yani kırılmayı 6D-3a'nın kendi
gerekçe yorumu getirdi — doğru şey, kurulumu bozdu. Diğer üç `requirements*.txt`
bugün hâlâ cp1254 ile okunabiliyor (yalnız `—` gibi cp1254'te tanımlı baytlar
taşıyorlar).

**Kim etkileniyor.** `pip 26.2.1` düşmüyor, `pip 24.0` düşüyor. CI etkilenmiyor:
Linux + UTF-8, üstelik `tests.yml` önce `python -m pip install --upgrade pip`
koşuyor. Etkilenen kitle **UTF-8 olmayan yerelli Windows katkıcısı** — ve
`README.md`'nin Development adımları pip yükseltmesi içermiyor, yani yeni bir
venv'de doğrudan bu hataya çarpar.

**Neden Faz 7.** O fazın hedefi "GitHub'dan indir, 5 dakikada çalıştır" ve bu
hata tam o yolun ilk adımında.

| Borç | İşaret |
|---|---|
| `requirements-dev.txt` UTF-8 olmayan yerelde eski pip ile okunamıyor; README'nin kurulum adımı o makinelerde çalışmıyor | **Faz 7**, mekanik tetikleyici: `python -c "import glob,sys; sys.exit(any(any(c>127 for c in open(f,'rb').read()) for f in glob.glob('requirements*.txt')))"` **sıfırdan farklı dönerse** borç duruyor demektir. Çözüm seçenekleri: yorumları ASCII'ye çevirmek, ya da README'ye `python -m pip install --upgrade pip` adımını eklemek |

---

## Sözleşme bloğu elle koşulan bir araca bağlı — koşulmazsa yine bayatlar

**Where:** [`src/defect_risk_analyzer/adapters/vector_store.py`](../src/defect_risk_analyzer/adapters/vector_store.py)
sözleşme bloğu, araç:
[`tests/tools/chroma_contract_probe.py`](../tests/tools/chroma_contract_probe.py)

**KAYNAK OKUMA YETMEDİ, DAVRANIŞSAL ÖLÇÜM GEREKTİ.** Blok dört chromadb
davranışını 0.5.23'ün kaynağından elle kopyalayarak kaydediyordu. Sözleşme 3
"yinelenen id'de `ValueError` atar" diyordu; gerçek istisna `DuplicateIDError`
ve MRO'su `DuplicateIDError <- ChromaError <- Exception` — **`ValueError`
değil**. Cümle yazıldığı günden beri yanlıştı, **iki tur kaynak okumasından sağ
çıktı**, ve ilk davranışsal probe onu **ilk koşuda** yakaladı. Bu, bloğun kendi
yönteminin sınırıdır; blok metni artık bunu söylüyor.

Davranışsal sonucu yoktu — `vector_store.py`'deki her sarmalayıcı
`except Exception` yakalıyor, hiçbir yerde `except ValueError` yok — ama
sonucu olmaması şans, ölçüm değildi.

**6D-4b ARACI EKLEDİ, TAKIMA TEST OLARAK EKLEMEDİ.** `tests/tools/` altında,
`test_` öneki yok, `chroma_cleanup.py`'nin komşusu. Takıma eklemek gerçek
istemci koşmayı zorunlu kılardı; bu depoda hiç ağ testi yok ve chroma'nın
varsayılan embedding function'ı runner'a bir ONNX modeli indirirdi — yeni bir
CI bağımlılık sınıfı, ve 6D-4'ün kararı değil. Araç bunu sayaçlı bir yapay
embedding function ile aşıyor: **ağ yok, 3.5 saniye, herhangi bir makinede
koşar.** Çıktısı bloğa doğrudan yapıştırılabilir ve 100 kolon sınırına kendisi
sarıyor (`vector_store.py` `E501` karantinasında **değil**, sarmasız çıktı 150+
kolona çıkıyordu ve yapıştırma `ruff check .`'i kırmızıya çevirirdi — ölçüldü).

**KALAN BORÇ, BEYAN EDİLMİŞ.** Araç elle koşuluyor. Pin oynatıldığında kimse
koşmazsa blok yine bayatlar, ve bu sefer `LAST PROBED: chromadb==0.6.3` satırı
da yanlış olur. Bloğun bayatlamasını yakalayan mekanik bir bekçi **yok** —
`tests/test_dependabot_config.py` yalnız `ignore`-pin tutarlılığını tutuyor,
blok metnini görmüyor.

| Borç | İşaret |
|---|---|
| Sözleşme bloğunun tazeliği elle koşulan bir araca bağlı; bloğun `LAST PROBED` sürümü `requirements.txt`'teki pinden ayrılabilir ve hiçbir şey kırmızıya dönmez | Tetikleyici: **chromadb pini her oynadığında** aracı koş ve bloğu güncelle. Mekanikleştirmenin ucuz biçimi önerildi: bloğun `LAST PROBED: chromadb==X` literalini `requirements.txt`'in pini ile karşılaştıran, ağsız, `test_dependabot_config.py` deyimindeki bir bekçi — 6D-4b'nin kapsamı dışında bırakıldı, kararı kullanıcının |
| Araç bir kez koşuldu (0.6.3 ve 0.5.23, bulgular birebir aynı); üçüncü bir sürümde ne olacağı ölçülmedi | Tetikleyici: **1.x'e geçiş** — 6D-5, aracı orada koşmak zorunlu |

---

## Mevcut bir venv'e yükseltme CVE düzeltmesini getirmiyor — README'nin adımı yetersiz

**Where:** [`README.md`](../README.md) Development bölümü (`pip install -r
requirements-dev.txt`), bekçisi **yok**

Faz 6D-4a `streamlit`'i 1.63.0'a taşıdı ve bunun asıl kazancı `pillow`'un 18
CVE'sinin kapanmasıydı: `streamlit 1.41.1`'in `pillow<12` tavanı, `pillow`'u
11.3.0'da tutan tek kısıttı. **Ama o kazanç yalnız taze çözünürlükte geliyor.**

**Ölçüldü.** İki `pip install --dry-run --report` koşusu, aynı pinler:

| kurulum yolu | `pillow` | 18 CVE |
|---|---|---|
| taze venv, tek `pip install -r requirements-dev.txt` (CI'ın yaptığı) | **12.3.0** | kapandı |
| mevcut venv'e `pip install -r requirements-dev.txt` | **11.3.0** | **açık kaldı** |

Yerinde yükseltme planı yalnız dört pakete dokunuyor — `streamlit`,
`itsdangerous`, `python-multipart`, `websockets` — ve `pillow` planda **hiç
yok**: 11.3.0 zaten `pillow<13`'ü sağlıyor, pip onu yükseltmek için bir sebep
görmüyor. Aynı sınıf ikinci bir örnek de ölçüldü: mevcut bir venv'de `chromadb`
1.x'e yükseltilirse `fastapi` **kaldırılmıyor**, çünkü pip artık gereksiz olan
transitif bağımlılıkları temizlemiyor — o yüzden CI'ın taze çözünürlükte
gördüğü kırmızı geliştirici makinesinde hiç görünmüyor.

**Neden sessiz.** Yerinde yükseltmeden sonra takım yeşil, `ruff` temiz, hiçbir
şey uyarmıyor. Katkıcı düzeltmeyi almadığını gösteren tek işaret yok.

**Neden Faz 7.** O fazın hedefi "GitHub'dan indir, 5 dakikada çalıştır".
Yukarıdaki UTF-8 maddesiyle aynı bölge ve aynı satırlar: `README.md`'nin
Development adımları ne `--upgrade` ne taze venv adımı içeriyor.

**Neden pytest bekçisi yok.** Ölçüm ortamın kendisine bağlı: aynı depo, aynı
pinler, iki farklı venv, iki farklı sonuç. Bir takım testi yalnız kendi
çalıştığı ortamı görebilir, dolayısıyla bu iddiayı tutamaz. Yeri doğrulama
protokolü.

| Borç | İşaret |
|---|---|
| `README.md`'nin Development adımı mevcut bir venv'de transitif bir CVE düzeltmesini getirmiyor; 6D-4a'da `pillow` üzerinde ölçüldü | **Faz 7**, mekanik tetikleyici: `pip install --dry-run --report` **`--ignore-installed` ile** ve **onsuz** koşulur, çözülen sürümler karşılaştırılır; tek pakette bile ayrışıyorsa README'nin adımı yetersizdir. Çözüm seçenekleri: taze venv adımı eklemek, ya da `pip install --upgrade -r requirements-dev.txt` yazmak |

---

## httpx2 TLS'i işletim sistemi güven deposundan doğruluyor — groq hâlâ `certifi`'den

**Where:** `openai 3.13.0` → `httpx2 2.12.0` → `truststore 0.10.4`; karşısında
`groq 1.7.0` → `httpx 0.28.1` → `certifi`

Faz 6D-4c'de openai 1.58.1 → 3.13.0 taşınırken yol üstünde görüldü, kapsam
kuralı gereği kaydedildi ve düzeltilmedi.

**Ölçüm — 2026-09-12, iki kütüphanenin kaynağı okundu. Aynı satır numarası,
farklı varsayılan:**

| | `httpx 0.28.1` `_config.py:40` | `httpx2 2.12.0` `_config.py:40` |
|---|---|---|
| `verify=True` (varsayılan) | `ssl.create_default_context(cafile=certifi.where())` | `truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` |

Üç ek ölçüm, çünkü "truststore yalnız kurulu duruyor olabilir" makul alternatifti:

- **`httpx2` `certifi`ye hiç referans vermiyor.** `grep -rn certifi httpx2/`
  yalnız docstring ve CLI sertifika yazdırma satırlarına düşüyor; `import
  certifi` yok.
- **Ne `openai` ne `groq` `verify=` geçiyor.** İkisinin de `_base_client.py`'sinde
  `verify=` / `SSLContext` eşleşmesi yok — ikisi de kütüphane varsayılanını alıyor.
- **Kaçış yolu var ve mekanik.** `httpx2/_config.py:33-38`: `trust_env` açıkken
  `SSL_CERT_FILE` ya da `SSL_CERT_DIR` ortam değişkeni varsa dosya tabanlı
  bağlama dönülüyor.

**Sonuç: bu uygulamada artık iki ayrı TLS güven mekanizması yan yana çalışıyor.**
`openai` işletim sistemi güven deposuna, `groq` `certifi` paketine bakıyor.
`certifi` kümeden düşmedi (chromadb ve groq istiyor), yani kaybolan bir şey yok;
ayrışan şey hangi yolun hangi kök sertifika kümesine baktığı.

**Neden önemli.** `openai` bu aracın üretimdeki **tek gerçek dış HTTP yolu** —
chromadb `PersistentClient` kullanıyor ve dışarı çıkmıyor. Kurumsal proxy veya
özel CA olan bir ortamda `certifi`ye eklenmiş bir kök OS deposunda olmayabilir,
ya da tersi. Davranış sessizce değişir ve iki sağlayıcı farklı davranır.

**Neden düzeltilmedi.** Düzeltmek `verify=` ile bir tarafı zorlamak demek, ve
hangi tarafın doğru olduğu ölçülmedi. Bu depo yalnız geliştirici makinesinde ve
CI runner'ında koştu; ikisinde de iki mekanizma aynı sonucu veriyor, yani
ayrışmanın bedeli burada gözlenemez.

**Neden pytest bekçisi yok.** İddia ortamın kök sertifika kümesi hakkında; bir
takım testi yalnız kendi koştuğu makineyi görebilir.

| Borç | İşaret |
|---|---|
| `openai` OS güven deposundan, `groq` `certifi`den doğruluyor; kurumsal CA olan ortamda ikisi ayrışabilir | **Faz 7**, "temiz makinede çalıştır" denemesi. Orada ölçülecek soru: `SSL_CERT_FILE` set edilmemiş bir ortamda `openai` çağrısı gerçekten OS deposundan mı doğruluyor. Çözüm seçenekleri: her iki istemciye açık bir `verify=` vermek, ya da ayrışmayı belgelemek |
| Mekanik tetikleyici | `httpx2/_config.py`'nin `verify is True` dalında `truststore` adı **geçmez olduğunda** **ve** `certifi` kümeden düştüğünde. İki koşul birlikte: tek başına "truststore gitti", httpx2'nin kümeden düşmesiyle de doğrudur ve tetikleyiciyi yanlışlıkla ateşlenmiş gösterir |

---

## Faz 6D-4c eki — Dependabot yuva kuyruğu, ve ölçümden önce yazılmış üç tahmin

**Where:** `.github/dependabot.yml:171` (`open-pull-requests-limit: 5`)

6D-4c'de `openai` ve `groq` **elle** taşındı, Dependabot PR'ı beklenmedi. Karar
ölçüme dayanıyor.

**Ölçüm — 2026-09-12, GitHub API.** Açık pip PR'ı tam **5**: #25 (anyio), #31
(pytest), #32 (pandas), #33 (plotly), #35 (openai). Limit doygun, `groq` için
PR yok ve olamaz. Ve **#25 tasarım gereği kırmızı** (yukarıdaki `anyio` maddesi),
yani asla merge edilmeyecek bir PR beş yuvanın birini kalıcı işgal ediyor —
**etkin limit 4**.

**Yuva dağıtımı iki kez gözlendi:**

| tur | yuva | açılan PR'lar, sırasıyla |
|---|---|---|
| 1 (09-08 22:21) | 5 | grup (#24) → anyio (#25) → openai (#26) → pytest-cov (#27) → numpy (#28) |
| 2 (09-10 21:49) | 3 | pytest (#31) → pandas (#32) → plotly (#33) |

Sekiz yuva dağıtıldı, **`groq` hiçbirini almadı**. Tur 2'de dört aday bekliyordu
(pytest, pandas, plotly, groq) ve `groq` dördüncü sıraya düştü. Sıralama
`dependabot.yml`'den, dosya sırasından ve alfabeden **türetilemiyor** — üçü de
gözlenen sırayla uyuşmuyor.

**Tetikleyici de öngörülemez.** Şema `weekly / monday`, ama üç PR turu Salı,
Perşembe ve Cumartesi'de geldi; **hiçbiri Pazartesi değil**. Üçü de main'e bir
merge'ün 1-3 dakika ardından geldi. Karşı örnek 09-09: #29 17:15Z'de merge
edildi, üç yuva açıldı ve 25 saat boyunca hiçbir PR gelmedi. **Ve o gün iş
koştu** — #24'ü 17:18:09Z'de o iş kapattı. Yani istisna "tetiklenmedi" değil:
**iş koştu, bir PR kapattı ve üç boş yuvaya rağmen sıfır PR açtı.**

> **Güncelleme (2026-09-24, ölçüldü) — tetikleyici öngörülebilir çıktı, ve
> 09-09 bir istisna değildi.** Dependabot'un koşuları Actions'ta
> `event=dynamic` olarak görünüyor ve public API'den okunuyor
> (`GET /actions/runs`). Koşu adları iki iş türünü ayırıyor: **`pip in /.`**
> (tam tarama, yeni PR açabilen) ve **`pip in / for <paket>`** (tek bir açık
> PR'ı yenileyen). main'e giren altı push'un altısında:
>
> | push (UTC) | `dependabot.yml` | pip işi |
> |---|---|---|
> | 09-08 19:20:25 #23 | **değişti** | 19:20:32 **`pip in /.`** |
> | 09-09 08:45:27 #27 | — | 08:46:50 `for requests, python-dotenv, ruff` |
> | 09-09 08:58:58 #28 | — | 09:00:20 `for requests, python-dotenv, ruff` |
> | 09-09 17:15:32 #29 | — | 17:16:56 `for requests…` (#24'ü kapattı) + 17:16:58 `for openai` |
> | 09-10 18:47:52 #30 | **değişti** | 18:48:00 **`pip in /.`** |
> | 09-12 14:46:35 #34 | **değişti** | 14:46:41 **`pip in /.`** + 14:47:57 `for openai` (#35'i açtı) |
>
> **Tam tarama yalnız `dependabot.yml`'e dokunan push'larda koştu.** 09-09'da
> koşan işler yenileme işleriydi ve yapıları gereği başka paketler için PR
> açmazlar — "iş koştu ama doldurmadı"nın açıklaması bu. Yukarıdaki "merge →
> dolum" kuralı yanlış kurulmuştu; gözlenen kural **config değişikliği → tam
> tarama → dolum**. 6D-4c'nin merge'ü (09-24, config'siz) bunu bir kez daha
> tuttu: 24 saat içinde 0 tam tarama (aşağıda D1′).
>
> **Hedef sürüm seçimi de belgelenmiş bir kurala bağlı: 3 günlük varsayılan
> bekleme.** GitHub Docs, *Dependabot options reference*, `cooldown`: *"Apply a
> default cooldown period of 3 days to version updates, even when `cooldown` is
> not configured … This default cooldown does not apply to security updates."*
> GitHub Changelog 2026-07-14'ten beri github.com'da tüm ekosistemlerde. Önce
> davranıştan ölçülmüştü: yedi tekil PR'da atlanan en yaşlı sürüm 2,97 gün,
> seçilen en genç hedef 3,36 gün; belgelenen 3,00 bu aralığın içinde. Changelog
> pip'i adıyla anmıyor; bu depodaki pip veri noktalarının hepsi 3 günle tutarlı.
> `dependabot.yml`'de `cooldown` yok, varsayılan uygulanıyor.

### Üç tahmin — sonuç görülmeden, 2026-09-12'de yazıldı

- **D1 (yuvayı kim alır).** Bu dal merge edilip #35 kapandığında açılan yuvayı
  **`groq` değil, `python-patch-minor` grup PR'ı** alır. Gerekçe: Tur 1'de grup
  PR'ı sırayı açtı; bugün grupta iki bump bekliyor (numpy 2.4.6 → 2.5.3, ruff
  0.16.6 → 0.16.7); ve `groq` sekiz dağıtımın hiçbirini alamadı.
  **Sayılacak üç sonuç:** grup açılır (doğrulanır) / `groq` açılır (yanlışlanır)
  / **hiçbiri açılmaz** — bu da bir sonuçtur ve 09-09 karşı örneğiyle tutarlı
  olur, o zaman pencere Pazartesi'ye kayar.
- **D2b (#35 nasıl kapanır).** Merge'den sonra Dependabot #35'i kendisi
  kapatacak, `merged=false`, `closed_by=dependabot[bot]`, yorumu **#24 ile aynı
  kalıpta** (*"no longer updatable ... no longer needed"*), merge'den ~1-3 dakika
  sonra. #35 **elle kapatılmıyor** — bilerek, çünkü bu kip (i)'nin ikinci
  ölçümü olacak.
- **D3 (haftalık şema).** 2026-09-14, `dependabot.yml` yerleştiğinden beri ilk
  Pazartesi. Zamanlanmış taramanın PR açıp açmadığı ilk kez gözlenecek.

**Ölçüm pencereleri.** D2b: merge'den sonra ~5 dk (`GET /pulls/35` +
`/issues/35/comments`). D1: merge'den sonra, ilk taramaya kadar
(`git ls-remote --heads origin`). D3: 09-14 gün boyu. D1 ile D3'ü ayırmak için
**09-13 Pazar akşamı bir ara ölçüm** alınır: o an ne varsa D1'in merge-tetikli
cevabıdır, Pazartesi'de değişen her şey D3'ündür.

> **Bayat (2026-10-02).** Bu pencereler aynı gün merge varsayımıyla yazılmıştı.
> 6D-4c 09-12'de değil **09-24**'te merge edildi (#36); 09-13 ara ölçümü hiç
> alınmadı ve 09-14 penceresi merge olmadan geçti. Merge'den önce öncüller
> yeniden ölçüldü, D1 ve D2b yeniden yazıldı — aşağıda.

**Kabul edilen bedel.** numpy 2.4.6 → 2.5.3 ve ruff 0.16.6 → 0.16.7 bu dala
**bilerek alınmadı** ve bu deney için birkaç gün bekletiliyor. Grup PR'ının
konusunu tüketmek D1'i ölçülemez kılardı. Ölçülen sürüklenme ≈1 paket/gün; bu
bilinçli bir gecikmedir, unutulmuş bir kuyruk değil.

> **İki düzeltme (2026-09-24).** (1) **numpy iddiası yanlıştı.** numpy 2.5.x
> `Requires-Python >=3.12`, depo 3.11'de; `pip install --dry-run` 2.5.3'ü
> reddetti. 2.4.6 kurulabilen son sürüm, numpy sürüklenmiyor — PyPI'nin son
> sürümü okunmuştu, çözülebilirlik değil. Dependabot #28'de 2.5.x'i aynı
> sebepten atlamıştı. (2) **"Birkaç gün" yanlıştı.** Yukarıdaki mekanizmaya göre
> tam tarama yalnız config push'unda koşuyor ve pip'in zamanlanmış taraması
> limit doluyken hiç gözlenmedi (aşağıda D3/D4), yani bekleme kendiliğinden
> bitmezdi. Ve tek gerekçesi grup deneyiydi; D1′ bu merge'ün o deneyi
> ölçemeyeceğini gösterdi. **Bekleme hiçbir şey satın almıyordu → `ruff`'ın
> sahibi 6D-4d** (2026-09-24 kararı): 6D-4d zaten `requirements-dev.txt`'e
> dokunuyor (pytest 9.1.1), ruff oraya elle eklenir.

### Sonuçlar — tahminler merge'den önce yazıldı, sonuçlar sonra ölçüldü

**Merge öncesi yeniden ölçüm (2026-09-24).** Açık pip PR'ları 09-12'dekiyle aynı
beşiydi; o günden beri hiçbiri açılmamış, kapanmamış, güncellenmemişti. openai
PyPI'de 3.19.2'ye çıkmıştı. Bu, iki tahminin öncülünü düşürdü:

- **D1 geçersizdi.** Bu PR `groq`'u en son sürüme çıkarıyordu, yani merge sonrası
  `groq` için PR açılması **imkânsızdı** — "groq açılır" dalı 09-12'de de boştu.
  Ve yuvanın açılması #35'in kapanmasına dayanıyordu. Yeniden yazıldı:
  **D1′** — merge sonrası `pip in /.` koşmaz (PR config'e dokunmuyor), grup PR'ı
  açılmaz, açık pip PR sayısı 5'te kalır. Pencere 24 saat.
- **D2b geçersizdi.** Kip (i)'yi öngörmüştü, çünkü 09-12'de merge sonrası main'in
  pini (3.13.0) PyPI'nin sonuncusuydu; artık değildi. Yeniden yazıldı:
  **D2b′** — bir `for openai` işi #35'i supersede eder (kip ii); yeni PR
  `3.13.0 → X`, X = merge anında 3 günlük beklemeyi geçmiş en yeni sürüm
  (merge saatine göre tablolanmıştı; ilk satır X = **3.16.2**). Pencere 30 dk.

| tahmin | yazıldığı an | sonuç | ölçüm |
|---|---|---|---|
| **D1′** | 09-24, merge öncesi | ✅ **doğrulandı** | pencere 09-24 20:53:26Z – 09-25 20:53:26Z: **0** `pip in /.` koşusu, yeni PR numarası yok, pencere sonunda 5 açık pip PR (#25 #31 #32 #33 #35), main'e #36 dışında push yok. Penceredeki 7 koşunun hepsi ilk ~2,5 dakikada |
| **D2b′** | 09-24, merge öncesi | ❌ **yanlışlandı — tahminde olmayan bir sonuç** | merge 20:53:26Z (tablonun 1. satırı). 84 sn sonra `for openai` işi koştu (`success`) ✅; **X = 3.16.2** ✅ (3.17.0 o an 2,76 günlüktü, atlandı). Ama #35 supersede edilmedi, **yerinde yeniden yazıldı** — kip (iv), yukarıda. Sayı 6'ya çıkmadı. Önceden yazılan dört sonuç satırının hiçbiri değil; birine sığdırılmadı |
| **D3** | 09-12 (yönsüz) | ölçüldü | pip'in haftalık taraması **09-14 ve 09-21'de hiç koşmadı**; aynı dosyadaki `github_actions` taraması her Pazartesi ~00:55Z'de koştu. main o günlerde hareketsizdi, yani koşu olsaydı merge-tetikli olamazdı |
| **D4** | 10-02, **09-28 takvimde geçmişken ama hiçbir veriye bakmadan**; iki dal da önceden | ◯ **merge edilmeme dalı: yanlışlanmadı (tutarlı)** — bu dal hipotezi doğrulayamaz, yalnız yanlışlayabilirdi; aşağıdaki paragraf | koşul önce yalnız PR ve git verisinden ölçüldü: #35 09-28T00:55Z anında açıktı, 5/5 dolu, aradaki sürede PR açılıp kapanmadı, main'e push yok. Dal buna göre seçildi, **sonra** Actions okundu: `github_actions` 00:55:15Z'de koştu, **0** `pip in /.` |
| **D5** | 10-02 08:36Z, #37'nin merge'ünden önce (PR gövdesinde) | ✅ **doğrulandı** (önceden yazılan tablonun 1. satırı) | #37 (yalnız docs) 08:55:15Z'de merge edildi. Pencere 08:55:15–09:25:15Z, 120 sn'de bir canlı izlendi: #35'in `title`, `head.sha`, `updated_at`, `state` alanları, olay geçmişi ve `event=dynamic` koşuları. **0** Dependabot koşusu (tek koşu #37'nin kendi `push` Tests'i), #35 değişmedi (`501adf9`), sayı 5. Yoklama son ~23 saniyeyi canlı okuyamadı (arka plan süre sınırı), o aralık zaman damgalarından geriye dönük kapatıldı. Docs'a dokunan bir push yenileme tetiklemedi: tek gözlem, "yenileme manifest değişikliğini izler" okumasıyla tutarlı, mekanizmayı kanıtlamıyor |
| **D6** | 10-02, #35'in merge'ünden önce; D5'ten sonra hiçbir API/PyPI çağrısı yapılmadan | ✅ **her öğede doğrulandı** | Aday kural, aynı verinin üzerine kurulmuş (post-hoc): config'e dokunmayan bir push'tan sonra Dependabot, diff hunk bağlamı (±3 satır) push'un değiştirdiği satırların bağlamıyla örtüşen açık PR'ları yeniler. #35 10:02:25Z'de merge edildi (`requirements.txt:17`, bağlam 14–20), pencere 30 dk canlı izlendi. `pip in /.` yok ✅. Tek Dependabot koşusu `pip in / for plotly`, 10:03:51Z ✅ (#33, satır 13, bağlam 10–16). **#32 pandas yenilenmedi ✅ — ayırıcı öğe**: "aynı dosyaya dokunan her PR yenilenir" kuralı #32'nin yenilenmesini öngörürdü. #31 ve #25 de yenilenmedi ✅. openai koşusu ve yeni PR numarası yok ✅. #33: 7.1.0'dan yeni plotly yoktu, yani **rebase dalı** geçerliydi: bot `head_ref_force_pushed` 10:04:45Z (0857b56→91f9613), `renamed` yok, başlık aynı ✅. Sayı 4 ✅. Aday kural ilk örneklem-dışı testini geçti: bu tek bir test, kanıt değil |
| **D7** | 10-02, #35'in merge'ünden önce; koşul ve dal 10-05'te **Actions okunmadan** sabitlendi | ✅ **doğrulandı — ilk kez yanlışlanabilir dalda**; alt iddia "en fazla 1 yeni PR" ❌ (aşağıda) | Koşul yalnız PR ve git verisinden ölçüldü: 10-05T00:55Z anında 4 açık pip PR (#25 #31 #32 #33); 10-02T10:02:26Z ile 10-05T01:30Z arasında main'e merge yok (HEAD `dc53431`), yani config push'u da yok. Dal (koşu bekleniyor) önce yazıldı, **sonra** Actions okundu: `github_actions in /.` 00:54:22Z, **`pip in /.` 00:54:26Z** (`success`) |

**D3 ve D4'ün gücü sınırlı, ve bu açıkça yazılmalı.** Üç Pazartesi üst üste
(09-14, 09-21, 09-28) zamanlayıcı `github_actions`'ı koşturdu, pip'i atladı.
Görünen tek fark pip limitinin dolu (5/5), `github_actions`'ınkinin boş (0/3)
olması. Ama "dolu limit zamanlanmış taramayı bastırıyor" ile "pip'in zamanlanmış
taraması başka bir sebepten koşmuyor" **aynı sonucu öngörüyor** — D4'ün bu dalı
hipotezi yanlışlayabilirdi, doğrulayamaz. İkisini ayıran ölçüm, açık pip PR
sayısı 5'in altındayken ve arada config push'u yokken bir Pazartesi.

**Sıradaki ayırıcı ölçüm (tahmin, şimdi yazıldı) — bir PR'a değil, bir olaya
bağlı.** Koşul: **açık pip PR sayısı ilk kez 5'in altına düştükten sonra, arada
`dependabot.yml`'e dokunan bir push olmadan gelen ilk Pazartesi.** Hipotez
doğruysa o Pazartesi ~00:55Z'de bir `pip in /.` koşusu görülür; görülmezse
hipotez yanlışlanır. Sayıyı düşürmeye bugün iki aday var: **#35'in merge'ü**
(karar açık) ve **6D-4d'nin pytest merge'ü** (#31 kapanır) — hangisi önce
gelirse. Karıştırıcılar: sayıyı düşüren push'un kendisi config'e dokunursa tam
tarama oradan gelir ve o Pazartesi temiz okunamaz; 6D-4d'nin `pip-audit` işi de
sayıyı değiştirebilir.

> **Sonuç (2026-10-05) — D7: hipotez desteklendi.** Sayıyı ilk düşüren #35'in
> merge'ü oldu (10-02, 5 → 4). Arada config push'u olmadan gelen ilk Pazartesi
> 10-05'te `pip in /.` 00:54:26Z'de koştu. Üç Pazartesi 5/5'te 0 koşu, bir
> Pazartesi 4/5'te 1 koşu: **dolu limit, zamanlanmış taramayı bastırıyor.**
> Tahminin yanlışlanabildiği ilk durumdu ve yanlışlanmadı. Tek gözlem; ama artık
> iki dal da gözlendi.
>
> Taramanın açtığı PR'lar (üçünün de Tests'i `success`, PR Risk Analysis bot
> bekçisiyle `skipped`):
>
> | PR | açıldı | içerik | eski PR |
> |---|---|---|---|
> | #39 | 00:56:17Z | `python-patch-minor` grubu, 4 güncelleme: ruff 0.16.6→0.16.10, streamlit 1.63.0→1.64.0, openai 3.16.2→3.23.0, python-dotenv 1.2.3→1.2.4 | — (yeni) |
> | #40 | 00:56:24Z | pandas 2.2.3→**3.0.6** | #32 (3.0.5), 00:56:27Z'de kapandı: *"Superseded by #40."* |
> | #41 | 00:56:32Z | plotly 5.24.1→7.1.0, **hedef değişmeden** | #33 (7.1.0), 00:56:35Z'de kapandı: *"Superseded by #41."* |
>
> Açık pip PR sayısı 4 → **5** (#25 #31 #39 #40 #41): net +1, tahmindeki gibi.
> **Ama "en fazla 1 yeni PR" alt iddiası numara olarak yanlış**: üç yeni numara
> açıldı. Tahmin, tam taramanın açık PR'ları supersede edebileceğini hesaba
> katmamıştı. Limit yeniden dolu, yani bu mekanizmaya göre bir sonraki Pazartesi
> yine bastırılır.
>
> **Kapanma kipleri, birlikte okununca.** Altı gözlemin hepsine uyan aday
> değişken **turda tam tarama olup olmadığı**. Sürüm değişimi bu değişken
> değil:
>
> | gözlem | turda `pip in /.` var mı | hedef / kaynak değişti mi | kip |
> |---|---|---|---|
> | 09-12 #26→#35 | evet (config push, ardından `for openai`) | hedef evet, kaynak hayır | (ii) supersede |
> | 09-24 #35 | hayır (yalnız `for openai`) | ikisi de evet | (iv) yerinde |
> | 09-24 #33 | hayır (yalnız `for plotly`) | hedef evet | (iv) yerinde |
> | 10-02 #33 | hayır (yalnız `for plotly`) | hiçbiri | rebase |
> | 10-05 #32→#40 | evet (zamanlanmış) | hedef evet | (ii) supersede |
> | 10-05 #33→#41 | evet (zamanlanmış) | **hiçbiri** | (ii) supersede |
>
> En temiz karşıtlık #33'ün son iki satırı: sürüm durumu birebir aynıyken bir
> yenileme işi rebase etti, tam tarama ise supersede etti. Aday post-hoc: aynı
> veriye uydurulmuş, hiçbir zaman önceden tahmin olarak yazılmadı.

**Kontrat testi ilk gerçek girdisini gördü.** Yeniden yazılan #35'in CI'ında
(Tests, 09-24 20:55:43Z → 20:57:02Z, `success`) `tests/test_llm_sdk_contract.py`
**openai 3.16.2**'ye karşı koştu — mutasyon dışında gördüğü ilk gerçek bump.
6D-4c'nin BEYAN'ı geçerli: yeşil, bugüne kadar hiçbir kırılmayı yakalamadı; ama
artık yalnız yazıldığı sürümlere karşı koşmuş bir test değil.

**Ölçüm aracının kendi gürültüsü — bu turun yöntem dersi.** D2b′ penceresi
boyunca bir yoklama betiği 90 saniyede bir #35'in yalnız `state` ve yorum
sayısını okudu. Yerinde yeniden yazma ikisini de değiştirmiyor; betik 30 dakika
"açık, 0 yorum" yazdı ve 20:58Z'de "#35 değişmedi" diye ara rapor verildi —
yanlıştı, #35 20:55:39Z'de değişmişti. `CONTRIBUTING.md:133`'ün kalıbının
üçüncü örneği: ölçüm aracının kendi gürültüsü, ölçümün sonucu sanıldı. Kural:
bir izleyicinin olumsuzu yalnız "okuduğum alanlarda değişiklik yok" demektir; bir
PR için `title`, `head.sha`, `updated_at` ve olay geçmişi (`renamed`,
`head_ref_force_pushed`) izlenir, ara rapor hangi alanların izlendiğini söyler.

| Borç | İşaret |
|---|---|
| ~~pip'in zamanlanmış taramasının dolu limitte koşmaması bir hipotez~~ — **10-05'te tetikleyici ateşlendi, hipotez desteklendi** (D7). Yuva sıralaması hâlâ dışarıdan türetilemiyor; `groq` sekiz dağıtımın hiçbirini alamamıştı | — |
| Limit 5 (#25 kalıcı olarak bir yuvayı tuttuğu için etkin 4) doluyken pip'in zamanlanmış taraması koşmuyor: üç Pazartesi 5/5'te 0 koşu, 10-05'te 4/5'te 1 koşu. O tarama sayıyı yeniden 5'e çıkardı, yani kuyruk kendiliğinden boşalmıyor. **Karar verildi (6D-4d-1'in planı, 2026-10-05): limit 5 kalıyor, `anyio` pini kaldırılıyor.** Pinin tetikleyicisi ateşlendi (aşağıda, 6D-4d-1 eki), yani #25'in kalıcı yuvası kendiliğinden kalkar. Pin kendi PR'ında kaldırılır, 6D-4d-1'den sonra; `dependabot.yml` temizliği (anyio'nun `exclude-patterns`'ı ve yorumu) ayrı ve tek dosyalık bir PR'da, çünkü config push'u tam tarama tetikliyor. Reddedilen seçenekler: limiti yükseltmek (kalıcı kırmızı PR'ı gizler); #25'i elle kapatmak (kip iii belgelenmemiş ve gözlenmemiş); `versions` aralıklı `ignore` (gerekçesi kalmamış bir pini erteler, anyio'nun güvenlik güncellemelerini de susturur). **Doyma kökten çözülmüyor:** #40/#41 6D-6'ya kadar açık, ve tam taramalar boşalan yuvaları dolduruyor. **Sonuç (6D-4d-2'de kaydedildi):** #44'ün merge'ünden sonra #25'i dependabot[bot] 2026-10-06T21:41:39Z'de kapattı, yorumu: *"Looks like anyio is no longer a dependency, so this is no longer needed."* (merge edilmedi). `dependabot.yml` temizliği #45'te (`c0efd4d`, 2026-10-07T08:25:19Z) merge edildi; tam tarama `pip in /.` 08:25:27Z'de koştu ve config hatası olmadan `success` bitti, `github_actions in /.` de koştu, yenileme işi yoktu; yeni grup PR'ı #46 08:27:11Z'de açıldı, açık pip PR sayısı 2 → 3 (#40, #41, #46). #46 11:17:21Z'de merge edildi (`58c2c39`), sayı yeniden 2 | Tetikleyici: **açık `dependabot/pip/` PR sayısı 5'e çıkar ve bir Pazartesi doymuş geçerse** limit kararı yeniden açılır |
| ~~numpy ve ruff bump'ları deney için bekletiliyor~~ — numpy hiç beklemiyordu (`Requires-Python >=3.12`); yalnız `ruff` (0.16.6 → 0.16.8, 09-24 itibarıyla) | **Sahibi 6D-4d** (2026-09-24 kararı). Bekletmenin tek gerekçesi grup deneyiydi ve D1′ ile düştü; bump kendiliğinden de gelmeyecekti. 6D-4d `requirements-dev.txt`'e elle ekler, o anki son sürümü yeniden ölçerek. **10-05:** D7'nin taraması ruff 0.16.10'u grup PR'ı #39'a koydu; #39'un kaderi 6D-4d-1'in planında ele alınır. **Kapandı (2026-10-06):** #39 bütün olarak merge edildi (`ec197ae`); ruff 0.16.10 main'de. Merge'den önce #39'un head'i taze bir venv'de yerelde ölçüldü: `ruff check .` temiz, izole bakiye 24, pytest 592 + 1 |
| ~~Kapanma kipleri (ii) ile (iv)'ü ayıran değişken kanıtlanmadı. Aday (post-hoc): **turda tam tarama olup olmadığı**, altı gözlemin altısına da uyuyor (yukarıdaki tablo). Sürüm değişimi değişken değil; #33 aynı sürüm durumunda bir kez rebase, bir kez supersede gördü~~ — **Sınanmadan kapatıldı (2026-10-06):** deney dizisi D7 ile kapandı (kullanıcı kararı 2026-10-05); tetikleyici 10-06'da ateşlendi ama aday önceden tahmin olarak yazılmamıştı. 10-06 gözlemleri aşağıdaki 6D-4d ekinde | ~~Tetikleyici: **bir sonraki tam tarama ya da yenileme işi** — aday önceden tahmin olarak yazılır ve o işte sınanır. Yanlışlayıcılar: yerinde yeniden yazan bir tam tarama, ya da supersede eden yalın bir yenileme işi~~ |

---

## Transitif sürüklenme — 6D-3b'nin kısıt dosyası ertelendi

**Where:** `requirements.txt`, `requirements-dev.txt`,
[`.github/workflows/tests.yml`](../.github/workflows/tests.yml) (`pip freeze`
adımı), [`.github/workflows/pr-risk-analysis.yml`](../.github/workflows/pr-risk-analysis.yml)

12 doğrudan `==` pinin üstünde 107 transitif paket alt sınırla, üst sınırsız
çözülüyor ve koşudan koşuya sürükleniyor (6D-4d'ye kadar 13 / 106; `anyio`
pini kalktı, paket transitif olarak kümede kaldı). **6D-4d-2'den beri, ölçüm
2026-10-07 (CI, #47): 13 doğrudan, 136 paket, 123 transitif** — aşağıdaki
ikinci örnek. 6D-2 bunu görünür kıldı
(`pip freeze` adımı), ama dondurmadı. Dondurma mekanizması **6D-3b**: bir
kısıt dosyası (`-c constraints.txt`).

**Bu bölüm 6D-4d-1'de yazıldı, faz 2026-09-03'te ertelendiği hâlde.** O günden
beri tasarımı ve ölçülmüş ön koşulları yalnız oturum hafızasında duruyordu;
depodaki tek iz yukarıdaki `anyio` bölümünde, var olmayan bir maddeye atıf
yapan bir cümleydi. Bir fazın bütün tasarımının depo dışında durması sahipsiz
borç sayıldı. Aşağıdaki ölçümler oradan **olduğu gibi** taşındı; yeni bir şey
eklenmedi.

**Neden ertelendi — sıra, evet/hayır değil (2026-09-03).** O gün 13 doğrudan
pinin 12'si gerideydi, çoğu bir major sürüm. Bayat bir tabanın üstüne 106
transitif paketi dondurmak bayatlığı kilitler ve 6D-4'ü tek bir büyük adıma
çevirirdi. **Önce taban güncellenir, sonra dondurulur.**

**Ölçülmüş ön koşullar (6D-3 keşfi, 2026-09-03 ve 09-06; Windows, `pip 26.2.1`):**

- **Mekanizma çalışıyor — kanıtı küme eşitliği değil.** Geçici bir venv'de
  `pip install -c constraints.txt -r requirements.txt`: exit 0, 112 paket.
  Kısıtlar kurulumu zorlamaz, sürümleri sınırlar; `requirements.txt`'in
  kapanışı zaten 112 idi, yani eşitlik beklenen sonuçtu, doğrulama değil.
  Asıl kanıt, kısıtlı kurulumun aynı günün kısıtsız çözümünden ayrıştığı dört
  nokta — kısıtlar sürümleri **geri çekti**: `anyio` 4.15.0 → 4.14.2,
  `uvicorn` 0.52.4 → 0.52.1, `pydantic` 2.13.5 → 2.13.4, `gitpython` 3.1.61 →
  3.1.59.
- **SINIR — bilinçli bir daraltma değil, bir sapma.** Onaylanan plan
  `-r requirements-dev.txt` diyordu; `-r requirements.txt` koşuldu. Dev
  katmanı (pytest, pytest-cov, ruff, coverage ve transitifleri) kısıt altında
  **hiç kurulmadı**. Ölçüm Windows'ta alındı. 6D-3b dev katmanını ölçülmüş
  saymamalı.
- **`--exclude-editable` zorunlu.** Düz `pip freeze > constraints.txt` bu
  depoda düşüyor: `ERROR: Editable requirements are not allowed as
  constraints`, çünkü CI `pip install -e . --no-deps` koşuyor ve freeze bir
  `-e git+https://...#egg=defect_risk_analyzer` satırı üretiyor (113 → 112
  satır).
- **Dosya Linux'ta üretilmeli — CI'da gözlendi.** CI'ın kendi `pip freeze`'i
  (2026-09-06, PR #21): `uvloop==0.22.1` var, `colorama` yok — Windows
  çözümünün tam tersi. Windows'ta üretilen bir dosya CI'a giremez. 6D-4d-1'den
  beri CI `ubuntu-24.04`'e sabit (aşağıdaki ek); dosya o imajda üretilmeli.
- **Dosya `pr-risk-analysis.yml`'e de ulaşmalı.** O iş akışı yalnız
  `requirements.txt` kuruyor ve `cache: pip` taşımıyor; iki iş akışı farklı
  çözünürlük test ediyor. 6D-3a'dan beri `anyio`'da da ayrışıyorlar
  (`tests.yml` pinli 4.14.2, `pr-risk-analysis.yml` o gün `groq` üzerinden
  4.15.1 çözüyordu).

**Mekanizma seçenekleri (malzeme, seçim değil):**

| | yeni bağımlılık | Dependabot |
|---|---|---|
| `pip freeze --exclude-editable` + `-c` | yok | **ölçülmedi** — `constraints.txt` desteklenen manifest listesinde değil |
| pip-tools (`pip-compile`) | pip-tools | **belgelenmiş** |
| `uv pip compile` | uv | iki GitHub Docs sayfası çelişiyor; çözülmedi |

**Ölçülmedi — tahmin edilmez:** Dependabot'un çıplak bir `constraints.txt`'i
okuyup okumadığı; `pip-compile`'ı yeniden koşturup koşturmadığı; `-c`
satırının setuptools'un dinamik okuduğu bir dosyada ne yaptığı.

**Sürüklenmenin somut bir örneği — 6D-4d-1'de ölçüldü.** 2026-09-25'te
`opentelemetry-exporter-otlp-proto-grpc` 1.45.0 yayımlandı ve yeni bir
bağımlılık getirdi: `opentelemetry-exporter-otlp-common==0.66b0`. Zincir:
`chromadb 0.6.3 → opentelemetry-exporter-otlp-proto-grpc>=1.2.0`. Kimse
istemeden çözünürlük 118'den 119'a çıktı — 6D-4c'nin 09-24 ölçümünden bir
gün sonra. CI'da (2026-10-02, ölçüm dalı) ve yerelde birebir aynı 119;
`tests.yml`'in yorumu bu yüzden 6D-4d-1'e kadar yanlış sayıyı söylüyordu.
Bu, kısıt dosyasının gerekçesinin ta kendisi: bir manifest değişmeden küme
değişti.

**İkinci örnek, ve kümeye bilerek eklenen 16 paket — 6D-4d-2'de ölçüldü
(2026-10-07, CI, PR #47, `ubuntu-24.04`).** İki ayrı şey, ikisi de aynı
ölçümde:

- **Sürüklenme.** `kubernetes` 37.0.0 2026-10-07T00:51Z'de yayımlandı ve yeni
  bir bağımlılık getirdi: `aiohttp-retry>=2.9.1` (36.0.3'te yoktu). Zincir:
  `chromadb 0.6.3 → kubernetes>=28.1.0`. pip-audit'siz çözünürlük 119'dan
  120'ye çıktı — aynı gün, hiçbir manifest değişmeden. Ad bazında fark, yerel
  `.venv`'e (119) karşı: yalnız `+aiohttp-retry` (artı bilinen
  `uvloop`/`colorama` platform takası).
- **pip-audit'in getirdiği 16 transitif paket** (`pip-audit==2.10.1`,
  `requirements-dev.txt`, 6D-4d-2): boolean.py, cachecontrol,
  cyclonedx-python-lib, defusedxml, license-expression, msgpack,
  packageurl-python, pip-api, pip-audit, pip-requirements-parser,
  platformdirs, py-serializable, pyparsing, sortedcontainers, tomli, tomli-w.
  Ölçüm: aynı job'da pip-audit'siz bir `--dry-run` çözümüne (120 paket)
  karşı ad farkı; 136 − 16 = 120, yani çıkan ad yok. Sürüm farkı bu ölçümde
  karşılaştırılmadı (2026-10-02'de 0'dı). 2026-10-02'deki ölçümle adları ve
  sayısı aynı. pip-audit ayrıca kendi kurulduğu ortamı da tarıyor, yani bu 16 paket
  denetlenen kümede; hiçbirinde kayıt yok.

Toplam: `pip freeze` 137 satır = 136 `==` satırı + 1 `-e` satırı; 13 doğrudan
pin, 123 transitif. `tests.yml`'in yorumu bu yüzden artık tarihli: sayı bir
ölçümdür, bugün için bir iddia değil.

| Borç | İşaret |
|---|---|
| 123 transitif paket (2026-10-07, #47) dondurulmamış; çözünürlük manifest değişmeden değişebiliyor (09-25'te otlp-common, 10-07'de aiohttp-retry). pip-audit'in 16 transitifi de bu kümede | **6D-6 tamamlandıktan sonra, Faz 7'den önce.** Gerekçe: 6D-6 de tabanı oynatıyor (pandas, plotly majorları); kısıt dosyası ondan önce üretilirse dondurulan küme hemen yeniden açılır — "önce taban güncellensin, sonra dondurulsun" ilkesinin aynısı |

---

## Faz 6D-4d-1 eki — runner sabitlemesi, pytest 9.1.1

**Where:** [`.github/workflows/tests.yml`](../.github/workflows/tests.yml),
[`.github/workflows/pr-risk-analysis.yml`](../.github/workflows/pr-risk-analysis.yml),
[`tests/test_workflow_runners.py`](../tests/test_workflow_runners.py),
`requirements-dev.txt`

**Runner sabitlemesi.** İki iş akışı `ubuntu-latest`'ten `ubuntu-24.04`'e
alındı. GitHub `ubuntu-latest` etiketini 2026-10-19'dan itibaren Ubuntu 26'ya
taşıyor (actions/runner-images#14748); geçiş kademeli olduğu için bir süre
koşular iki imaj arasında düşebilir. Çözülen paket kümesi platforma bağlı
(yukarıdaki 6D-3b bölümü), yani duyurulmamış bir imaj değişikliği freeze
diff'ine gürültü olarak girerdi. Ölçüldü (2026-10-02):
`actions/python-versions` manifest'inde 3.11.15–3.11.17 için 26.04 derlemesi
var — geçiş sert bir kırılma getirmezdi; karar atıf ve gürültü üzerinden
verildi. Sabitleme Python'un yama sürümünü sabitlemiyor: `setup-python`
`3.11` için imajdaki en yeni 3.11.x'i kullanıyor.

**Bekçi: `tests/test_workflow_runners.py`.** "İki iş akışının platformu
ayrışmasın" iddiasını bir yorum söylüyordu ama tutmuyordu. İki test: her
`runs-on:` değeri `ubuntu-24.04` olmalı (`.github/workflows/` altındaki her
dosya, sonradan eklenenler dahil); ve tarama boş dönmemeli — bilinen iki
dosya bulunmalı, her birinde en az bir `runs-on:` yakalanmalı. YAML
ayrıştırıcısı kullanılmıyor: `PyYAML` doğrudan bağımlılık değil.

| Mutasyon | Kırılan iddia | Gözlenen |
|---|---|---|
| (doğal) iki dosya da `ubuntu-latest` — sabitlemeden önce | her `runs-on` sabit değerde | birinci test **kırmızı**, iki dosyayı da adıyla gösterdi |
| M1 `tests.yml` → `ubuntu-latest` | aynı | birinci test **kırmızı** |
| M2 yalnız `pr-risk-analysis.yml` → `ubuntu-26.04` | iki dosya ayrışmaz | birinci test **kırmızı** |
| M3 test deseni `runs_on:` (hiçbir satırı yakalamaz) | tarama boş değil | birinci test **boşuna yeşil**, ikinci test **kırmızı** — ikinci testin varlık sebebi |

**pytest 8.3.4 → 9.1.1, elle.** Dependabot'un #31'i 09-10 tabanlıydı ve o
günden beri hiç güncellenmedi; bump bu PR'da elle yazıldı. Kod değişikliği
gerekmedi. **CVE-2025-71176 kapandı** (pip-audit kimliği PYSEC-2026-1845,
GHSA-6w46-j5rx-g56g; `tmpdir` izinleri; düzeltme 9.0.3). CI'daki pip-audit
ölçümünde (2026-10-02, ölçüm dalı, iki ayrı job) pytest 9.1.1'li ortamda hem
`-s pypi` hem `-s osv` bu kaydı artık raporlamadı; tekil açık sayısı 5'ten
4'e indi. Yukarıdaki "ROADMAP Faz 3'te olup Faz 3'e alınmayanlar"
bölümündeki `pip-audit` maddesi 6D-4d-2'nin işi; burada kapanmadı.

**`anyio` pininin kaldırma tetikleyicisi ateşlendi — bu PR'da değil,
ölçüldü.** `starlette` 1.7.0 (2026-09-23, CI'ın bugün çözdüğü sürüm)
`testclient.py:53`'ü `anyio.from_thread.BlockingPortal`'a çevirdi;
yukarıdaki tetikleyicinin iki koşulu da sağlanıyor. Geçici bir venv'de,
`TestClient` ile, bütün DeprecationWarning'ler kaydedilerek: starlette
1.7.0 + anyio 4.15.1 → **0** uyarı; **kontrol** starlette 1.6.0 + anyio
4.15.1 → **1** uyarı (alias mesajı — prob uyarıyı görebiliyor); starlette
1.7.0 + anyio 4.14.2 → 0. Pin kendi PR'ında kaldırılır, 6D-4d-1'den hemen
sonra ve 6D-4d-2'den önce: pip-audit'in ignore listesi son ortamda
hesaplanır ve anyio'nun sürümü ortamı değiştiriyor.

| Borç | İşaret |
|---|---|
| CI `ubuntu-24.04`'e sabit; Ubuntu 26'ya geçiş bilerek ertelendi | Tetikleyici: **GitHub 24.04 için kullanımdan kaldırma duyurduğunda ya da 6D-3b'nin kısıt dosyası üretilmeden önce — hangisi önce gelirse.** Geçiş kendi PR'ında, freeze diff'i gözlenerek yapılır; `tests/test_workflow_runners.py`'deki `EXPECTED_RUNNER` orada değişir. Aynı PR `tests/test_env_writer.py:335`'in docstring'indeki `ubuntu-latest`'i de günceller (6D-4d-1'den beri bayat; 6D-4d'de kaydedildi, düzeltilmedi) |
| ~~`anyio==4.14.2` pininin gerekçesi starlette 1.7.0 ile kalktı~~ | **Kapandı (6D-4d, 2026-10-06)** — aşağıdaki 6D-4d eki |

---

## Faz 6D-4d eki — `anyio` pini kaldırıldı

**Where:** `requirements-dev.txt`,
[`tests/test_dependency_pins.py`](../tests/test_dependency_pins.py),
[`.github/workflows/tests.yml`](../.github/workflows/tests.yml) (yorum),
[`tests/test_dependabot_config.py`](../tests/test_dependabot_config.py) (mesaj)

**Pin ve literal bekçisi birlikte kalktı.** Yukarıdaki 6D-4d-1 ekinde ölçülen
tetikleyici üzerine `anyio==4.14.2` ve gerekçe bloğu `requirements-dev.txt`'ten
çıktı; `anyio` transitif olarak kümede kalıyor ve serbest çözülüyor.
`test_requirements_dev_still_carries_the_expected_anyio_pin` tutacağı satırı
kaybettiği için silindi. Gerekçe bekçisi
(`test_starlette_testclient_emits_no_anyio_alias_deprecation`) kaldı: aynı
uyarının yokluğunu artık `starlette`'in 1.7.0 altına inmemesi üzerinden
tutuyor; filtresi değişmedi. Bayatlayan sayılar düzeltildi: `tests.yml`'in
yorumu 13 / 106 → 12 / 107, `test_dependabot_config.py`'nin mesajı
Dependabot'un gördüğü `==` pinleri için 14 → 13 (birim: kökteki bütün
`requirements*.txt`, `requirements-desktop.txt`'in `keyring`'i dahil).
`.github/dependabot.yml:68`'deki "14" ve anyio'nun `exclude-patterns`'ı
sıradaki tek dosyalık PR'ın işi. **Yapıldı: #45** (`c0efd4d`, 2026-10-07);
6D-4d-2 `pip-audit`'i eklediği için aynı sayı orada yeniden 13 → 14 oldu.

**Ölçemeyen bekçi geçmez (kullanıcı kararı, 2026-10-06).** Gerekçe bekçisinin
üç dalı skip'ten kırmızıya döndü: alt süreç sıfırdan farklı döner, çıktısı
JSON değildir, `starlette.testclient` import edilemez. Skip'li hâlinde
`starlette` kapanıştan düştüğünde test sessizce atlanır ve CI yeşil kalırdı.
Beklenen tek gerçek durum 6D-5 (yukarıdaki anyio bölümünün borç tablosu): o
PR testi bilerek siler ya da günceller. Pozitif kontrol testi eklenmedi;
filtrenin kör noktası — anyio uyarının metnini "anyio.abc" ve "deprecat"
içermeyecek biçimde değiştirirse test boşuna yeşil geçer — testin modül
docstring'inde beyan edildi. Filtrenin bugünkü mesajı gördüğünü aşağıdaki
M1 bir kez kanıtlıyor.

| Mutasyon | Kırılan iddia | Gözlenen |
|---|---|---|
| M0 (kontrol) taze venv, starlette 1.7.0 + anyio 4.15.1 | — | yeşil |
| M1 depo dışı taze venv, `starlette==1.6.0` + `anyio==4.15.1` (`pip check` temiz) | starlette geri giderse uyarı görünür | **kırmızı**, `:151`: `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.` |
| M2 aynı venv, `pip uninstall starlette` | hedef yoksa geçmez | **kırmızı**, `:138` (`import_error` assert'i): `starlette.testclient import edilemedi (ModuleNotFoundError: No module named 'starlette').` |
| M3 yerel `.venv`, alt süreç komutu `import sys; sys.exit(3)` | alt süreç hatası geçmez | **kırmızı**, `:116`: `olcum alt sureci 3 ile dondu; uyari olculemedi.` |
| M4a aynı, komut `print('not json')` | JSON olmayan çıktı geçmez | **kırmızı**, `:127`: `olcum alt sureci JSON cikti vermedi; uyari olculemedi.` (stdout `not json`) |
| M4b aynı, komut `pass` (boş stdout) | boş çıktı geçmez | **kırmızı**, `:127`, aynı mesaj, stdout boş |

M1–M4b, commit `d2136f4` üzerinde koştu. M3–M4b test dosyasının kendi kodunu
değiştirdi; her biri dosya kopyasıyla geri alındı ve `cmp` ile `HEAD`'e karşı
doğrulandı. Alt süreç ve JSON dallarının doğal bir kırmızısı yok: alt süreci
bozacak bir ortam değişkeni üst pytest sürecini de bozar.

**Taze kurulum (2026-10-06, Windows, depo dışı venv, CI ile aynı adımlar:
`pip install -r requirements-dev.txt`, `pip install -e . --no-deps`).** Python
3.11.9 (`tests.yml`: `python-version: "3.11"`; CI yama sürümü imajdaki en
yeni 3.11.x). Çözülen `anyio` 4.15.1, `starlette` 1.7.0. Paket sayısı **119**
(`pip freeze --exclude-editable` satırı); mevcut `.venv`'den fark iki satır:
`anyio` 4.14.2 → 4.15.1 ve `posthog` 7.63.0 → 7.64.0 (transitif sürüklenme,
bu değişiklikle ilgisiz). `pytest`: 593 passed, 1 skipped
(`test_env_writer.py:333`), uyarı özeti bölümü yok.

**"Kapanma kipleri" tetikleyicisi 2026-10-06'da ateşlendi — gözlem, sınama
değil.** "Faz 6D-4c eki"nin borç tablosundaki "Kapanma kipleri (ii) ile
(iv)" satırının tetikleyicisi "bir sonraki tam tarama ya da yenileme işi" idi. #39'un merge'ünden (08:17:36Z)
sonra `pip in / for plotly` (08:19:01Z) ve `pip in / for pytest` (08:19:02Z)
yenileme işleri koştu; `pip in /.` yoktu. #41 (08:19:50Z) ve #31 (08:19:57Z)
`head_ref_force_pushed` gördü — rebase, supersede yok. **#40 (pandas) hiç olay
görmedi**, oysa #39 `requirements.txt:26`'yı değiştirdi (bağlam 23–29) ve
pandas :30'da (bağlam 27–33): D6'nın post-hoc bağlam kuralıyla çelişiyor;
kaydedildi, analiz edilmedi. #43'ün merge'ünden (10:15:27Z) sonra `pip in /
for pytest` 10:16:49Z'de koştu; dependabot[bot] #31'e 10:17:35Z'de *"Looks
like pytest is up-to-date now, so this is no longer needed."* yazdı ve
10:17:37Z'de kapattı — kip (i). Aday değişken önceden tahmin olarak
yazılmadığı için bu bir sınama sayılmaz; satır bu yüzden sınanmadan kapatıldı.
Kapatılış biçimi aynı tablodaki pip taraması satırından farklı: orada yalnız
ilk hücre çizilip ikincisi "—" yapılmıştı; burada iki hücrenin de metni
korunarak üstü çizildi, tetikleyici metni silinmesin diye.

Bu ek yeni bir borç açmıyor; kapanışları yukarıdaki anyio bölümünde ve
6D-4d-1 ekinin tablosunda.

---

## Faz 6D-4d-2 eki — pip-audit kapısı

**Where:** [`.github/workflows/tests.yml`](../.github/workflows/tests.yml)
(kurulum adımı ve son iki adım),
[`.github/scripts/pip_audit_gate.py`](../.github/scripts/pip_audit_gate.py),
[`.github/pip-audit-ignore.toml`](../.github/pip-audit-ignore.toml),
[`tests/test_pip_audit_gate.py`](../tests/test_pip_audit_gate.py),
`requirements-dev.txt`

**Tasarım — kullanıcının dört koşulu (2026-10-02) ve kararları (10-07).**
pip-audit CI'da Pytest'ten sonra, ignore'suz koşar ve yalnız JSON yazar; adım
düşmez. Kararı doğrulayıcı verir, iki yönde: listede olmayan bir bulgu
("yeni bulgu") ya da listede olup raporlanmayan bir kimlik ("bayat ignore" —
koşul b'nin mekanik tetikleyicisi). Rapor yoksa, boşsa, JSON değilse,
`dependencies` taşımıyorsa, hiç paket taranmamışsa ya da projenin kendisinden
başka bir paket atlanmışsa da kırmızı: boş ya da kısmi bir tarama iyi haber
değil, bozuk taramadır. Kaynak varsayılan (`pypi`), `--skip-editable` yok;
projenin editable kurulumu pypi'de `skip_reason` ile atlanıyor ve atlanmasına
izin verilen tek paket o. Eşleşme kimlik ∪ alias üzerinden (pip-audit kaydı
PYSEC kimliğiyle verir, liste CVE'yi tutar) ve aynı kaydın tekrarları tek
bulguya katlanır. Dağılım her koşuda bir notice annotation'ı olarak basılıyor:
koşul (d) her koşuda yeniden ölçülür. Her iki denetim adımı `!cancelled()`
taşıyor — Ruff ya da Pytest düşse de denetim koşar, ve denetim Pytest'ten
sonra olduğu için gece yayımlanan bir advisory bir PR'ın test kanıtını
silemez (6D-3c'nin dersi).

**Gerekçe bağlantısı — koşul (a) ve (c).** Ignore listesindeki her kimliğin
yukarıdaki chromadb bölümünde kendi satırı var (`| **CVE-…** (GHSA-…) … |
Tetikleyici: … |`); yeni bir gerekçe bölümü açılmadı. Bekçi
(`test_every_ignored_id_has_its_own_known_debt_row`) her kimlik için tam bir
satır, satırda başka ignore kimliği olmamasını ve bir tetikleyiciyi istiyor;
`test_ignore_ids_and_known_debt_rows_are_found` liste ya da desen boş
dönerse kırmızı. Beyan edilmiş kör nokta, testin docstring'inde: bekçi
listede bulunan kimlikler üzerinde döner, silinen bir satırı göremez — ama
sistem kapalı, çünkü silinen satır kapıyı "yeni bulgu" ile kırmızıya çevirir
(aşağıda M1).

**setuptools — ignore değil, yükseltme (kullanıcı kararı, 2026-10-02).**
CI'daki setuptools setup-python'un yorumlayıcısıyla geliyor, bizim pinimiz
değil, ve derleme onu kullanmıyor (`pip install -e .` izole ortamda kendi
`setuptools>=77`'sini kuruyor). `tests.yml` kurulumda `--upgrade pip
setuptools` koşuyor.

**Ölçüm — PR #47, 2026-10-07 (taslak, merge edilmedi, kapatıldı, dal
silindi).** `58c2c39` üstünde iki ayrı job, bu PR'daki kurulum sırasının
aynısı; tek fark setuptools yükseltmesi. Sonuçlar check-run annotation'ı
olarak, kimliksiz API'den okundu. Geçerlilik kontrolü tuttu: önekli
annotation sayısı beklenenle eşit (16, 12), kayıt indeksleri eksiksiz,
kapasite hatası yok, iki rapor da okunabildi, öneksiz annotation yok. Ortak:
Python 3.11.16, pip 26.2.1, websockets 17.2, streamlit 1.65.0, openai 3.24.0,
pip-audit 2.10.1. Birimler: **kayıt** = JSON'daki ham `vulns[]` girdisi
(tekrarlar dahil), **tekil** = bir paket içinde kimlik ∪ alias bileşeni.

| job | setuptools | pypi kayıt | osv kayıt | tekil |
|---|---|---|---|---|
| yükseltmesiz | 79.0.1 | 5 (chromadb 3, setuptools 2) | 8 (chromadb 6, setuptools 2) | 4 |
| `--upgrade pip setuptools` | 84.0.0 | 3 | 6 | **3** |

**Dağılım — koşul (d):**

| pip-audit kimliği | CVE (öteki alias'lar) | paket | düzeltme | nasıl kapanır |
|---|---|---|---|---|
| PYSEC-2026-3813 | CVE-2026-45830 (GHSA-2wm9-hf6c-p5cr) | chromadb 0.6.3 | yok | advisory'de `fixed` sürümü belirdiğinde — ignore'da |
| PYSEC-2026-3814 | CVE-2026-45833 (GHSA-36p7-vc44-83pf) | chromadb 0.6.3 | yok | aynı — ignore'da |
| PYSEC-2026-3815 | CVE-2026-45831 (GHSA-xph7-9rjv-w5fr) | chromadb 0.6.3 | yok | aynı — ignore'da |
| PYSEC-2026-3447 | CVE-2026-59890 (GHSA-h35f-9h28-mq5c, BIT-setuptools-2026-59890) | setuptools 79.0.1 | 83.0.0 | `tests.yml`'in yükseltmesiyle kapandı — ignore'da değil |
| PYSEC-2026-1845 | CVE-2025-71176 (GHSA-6w46-j5rx-g56g) | pytest 8.3.4 | 9.0.3 | 6D-4d-1'in pytest 9.1.1'iyle kapandı |

**Yerel Windows CI'ın yerine geçmiyor.** Python 3.11.9'un `venv`'i
setuptools 65.5.0 kuruyor; depo dışı taze bir venv'de kapı dört setuptools
CVE'si için (CVE-2022-40897, CVE-2024-6345, CVE-2025-47273, CVE-2026-59890;
11 kayıt / 7 tekil) kırmızı. Yerelde kapıyı koşturmak için önce
`python -m pip install --upgrade setuptools`.

**Mutasyonlar.** Rapor ve ignore mutasyonları depo dışı taze bir venv'de
(`py -3.11`, setuptools 84.0.0'a yükseltilmiş, `requirements-dev.txt`
kurulu) gerçek bir pip-audit raporuyla koştu; kod ve belge mutasyonları aynı
venv'in pytest'iyle. Her biri dosya kopyasıyla geri alındı ve `cmp` ile hem
kopyaya hem `git cat-file --filters` çıktısına karşı doğrulandı.

| Mutasyon | Kırılan iddia | Gözlenen |
|---|---|---|
| (doğal) taze venv, setuptools 65.5.0 (yükseltmesiz) | yükseltme olmadan kapı geçmez | **kırmızı**, "yeni bulgu": dört setuptools CVE'si |
| M0 (kontrol) aynı venv, setuptools 84.0.0 | — | **yeşil**: 138 paket, 3 kayıt, 3 tekil, üçü listede |
| M1 ignore'dan CVE-2026-45830 silindi | listede olmayan bulgu geçmez | kapı **kırmızı**, "yeni bulgu: chromadb==0.6.3 CVE-2026-45830"; bekçi **yeşil** (beyan edilmiş kör nokta) |
| M2 ignore'a CVE-2099-00001 eklendi | bayat ignore geçmez | kapı **kırmızı**, "bayat ignore: CVE-2099-00001"; bekçi de **kırmızı** (gerekçe satırı yok) |
| M3a rapor dosyası yok | çöken pip-audit geçmez | **kırmızı**, "rapor yok: …" |
| M3b rapor 0 bayt | boş rapor geçmez | **kırmızı**, "rapor bos" |
| M3c rapor JSON değil | bozuk rapor geçmez | **kırmızı**, "rapor JSON degil (Expecting value …)" |
| M4 rapor `{}` | `dependencies` yoksa geçmez | **kırmızı**, "raporda `dependencies` listesi yok" |
| M5a `dependencies: []` | hiç paket taranmadıysa geçmez | **kırmızı**, "hic paket taranmamis" |
| M5b yalnız proje atlanmış | aynı | **kırmızı**, "hic paket taranmamis" |
| M11a gerçek rapor, `numpy` `skip_reason` ile | kısmi tarama geçmez | **kırmızı**, "tarama eksik: projeden baska atlanan paket(ler): numpy" |
| M11b kodda yabancı-skip kontrolü kaldırıldı | aynı | `test_a_skipped_package_other_than_the_project_fails` **kırmızı** ("DID NOT RAISE") |
| M6 kodda tekilleştirme kaldırıldı | tekrarlar tek bulgu | `test_duplicate_records_fold_into_one_finding` **kırmızı** (`assert 2 == 1`) |
| M7 kodda alias'lar kimliğe katılmıyor | CVE, PYSEC kaydını alias'tan bulur | **6 test kırmızı**: eşleşme, yeni bulgu, bayat, CVE↔PYSEC, GHSA, tekrar |
| M8 KNOWN-DEBT'te CVE-2026-45833 satırı silindi (ayrıca: yalnız kalın kimliği bozuldu) | her kimliğin satırı var | iki biçimde de bekçi **kırmızı**, "CVE-2026-45833: 0 gerekce satiri (tam 1 olmali)" |
| M9 45833 satırı 45831'i de taşıyor | toplu satır yok | bekçi **kırmızı**, "CVE-2026-45833: satir baska ignore kimligi de tasiyor: ['CVE-2026-45831']" |
| M10 bekçinin deseni hiçbir satırı yakalamıyor | bekçi boşuna geçmez | **iki test kırmızı**: üç kimlik için "0 gerekce satiri", ve "hic gerekce satiri bulunamadi" |

**Gözlenmedi — CI'da:** kapının kırmızısı yalnız yerelde gözlendi; CI'da
yalnız yeşil hâli gözlenecek (bu PR'ın kendi koşusu). CI'ın yükseltmesiz
durumu #47'de ölçüldü (setuptools 79.0.1 kaydı), ama kapının kendisi o koşuda
yoktu.

| Borç | İşaret |
|---|---|
| Kapı ağa bağlı: pip-audit PyPI'ye ulaşamazsa rapor yazılmaz ya da bozuk çıkar, kapı kırmızı — ilgisiz bir PR da kırmızı görünür. Bu bilinçli: "sonuçsuz"u yeşil saymak, boş taramayı iyi haber saymak olurdu | Tetikleyici: **ağ kaynaklı ilk kırmızı.** O zaman yeniden deneme mi, ayrı bir "sonuçsuz" durumu mu — karar o gün, gözlenen hata metniyle verilir |
| Gece yayımlanan bir advisory, açık her PR'ı (Dependabot'unkiler dahil) kırmızıya çevirir. Tasarım gereği; yol: aynı PR'da ya bump, ya da kimlik ignore'a ve gerekçesi bu dosyaya | Tetikleyici: **ilk "yeni bulgu" kırmızısı** — yol o gün izlenir ve buraya bir satır yazılır |
| setuptools sabitlenmedi, yükseltiliyor: her koşu o günün en yeni sürümünü alıyor (2026-10-07'de 84.0.0) | Tetikleyici: **6D-3b'nin kısıt dosyası üretildiğinde** — setuptools'un da kısıt altına girip girmeyeceği orada karara bağlanır |
| `pr-risk-analysis.yml` denetlenmiyor. Kurduğu küme `tests.yml`'inkinin alt kümesi, ama çözünürlüğü ayrı (6D-3b'nin bilinen ayrışması) | Tetikleyici: **6D-3b** — iki iş akışı aynı kısıt dosyasını kullandığında bu satır kapanır |
| `tests.yml:56–57`'deki yorum ("installs the runtime deps plus pytest and the pinned ruff") eksik: `pip-audit`'i de, zaten 6D-4d-2'den önce `pytest-cov`'u da saymıyor. Bilerek dokunulmadı: satır C1'in değiştirdiği `--upgrade pip setuptools` satırına bitişik; C2 burayı da değiştirseydi iki hunk arasında değişmemiş satır kalmaz, C1 tek başına temiz revert edilemezdi (bugün aralarında 5 satır var) | Tetikleyici: **`tests.yml`'e dokunan bir sonraki PR** — yorum orada iki paketi de sayacak biçimde düzeltilir |

---

## Faz 6D-4d-3 eki — chromadb 1.x izleyicisi

**Where:** [`.github/workflows/chromadb-1x-watch.yml`](../.github/workflows/chromadb-1x-watch.yml),
[`.github/scripts/chromadb_1x_watch.py`](../.github/scripts/chromadb_1x_watch.py),
[`tests/test_chromadb_1x_watch.py`](../tests/test_chromadb_1x_watch.py),
`tests/test_workflow_runners.py` (`KNOWN_WORKFLOWS`), `.github/dependabot.yml`
(kaldırma tetikleyicisinin yorumu)

**Ne tutuyor.** `dependabot.yml` chromadb'yi `>=1.0.0` için erteliyor, tek
gerekçe CVE-2026-45829 (GHSA-f4j7-r4q5-qw2c): her 1.x'te açık, düzeltmesi
yok. Bu iş akışı haftada bir, en yeni 1.x'in hâlâ taşıyıp taşımadığını sorar.
Yukarıdaki chromadb bölümünün 1.x satırının mekanik tetikleyicisi budur.

**Tasarım değişti — kullanıcı kararları, 2026-10-07.** 6D-4b'nin tarifi
(10-02'de iki ek hücreyle kabul edilmişti) tek tarama, üç durum ve "sonuçsuz
kırmızı değil" idi; kırmızı için 45829'un yokluğu **ve öteki üç kaydın
varlığı** gerekiyordu. 4d-3'ün keşfi bunu ölçtü ve iki kararla değişti:

- **K6 — "öteki üçü" şartı kalktı, yerine pozitif kontrol.** Dört advisory'nin
  dördü de kapalı aralıklı: OSV kayıtlarında 45829 `introduced 1.0.0`,
  45830 ve 45833 `introduced 0.4.17`, 45831 `introduced 0.5.0`, hepsi
  `last_affected: 1.5.9` (OSV'nin `vulns` uç noktası, GET, 2026-10-07). PyPI'de son
  sürüm hâlâ 1.5.9 (2026-05-05). Yeni bir 1.x sürümü — 45829'u düzeltse de
  düzeltmese de — advisory'ler güncellenene kadar dördünün de aralığı
  dışında kalır. Eski şart tam o olayı, yani bu ertelemenin beklediği şeyi,
  sessizce "sonuçsuz"a çevirirdi. Yerine her koşuda iki tarama: **kontrol**
  `chromadb==1.5.9` (45829'un kesin raporlandığı sürüm) tarayıcının ve
  verisinin sağlam olduğunu kanıtlar; **hedef** `chromadb>=1.0.0` asıl
  soruyu sorar. Öteki üç kayıt yalnız dağılım notice'inde yazılır.
- **K1 — "izleyici bozuk" kırmızı, kendi başlığıyla.** "Sonuçsuz kırmızı
  değil" kararının yerine geçer. GitHub yalnız başarısız zamanlanmış koşuyu
  bildirir; yeşil bir haftalık işe kimse bakmaz, yani sessiz bir bozukluk
  alarmın yokluğudur.

**Durumlar — yalnız biri yeşil.**

| durum | koşul | sonuç ve çıkış | annotation başlığı |
|---|---|---|---|
| erteleme haklı | kontrol geçerli, chromadb `1.5.9`, 45829 var; hedef geçerli, chromadb ≥1.0.0, 45829 var | yeşil, 0 | `chromadb 1x izleyici - erteleme hakli` (notice) |
| iş var | kontrol sağlam; hedef ≥1.0.0 ve 45829 yok (öteki üçünün durumu önemsiz) | kırmızı, 1 | `chromadb 1x izleyici - is var` |
| izleyici bozuk | raporlardan biri yok, boş, JSON değil ya da eksik tarama (kapının `ReportError`'ı); bir raporda chromadb yok ya da atlanmış; kontrolün sürümü yanlış ya da 45829'u taşımıyor; hedefin sürümü ayrıştırılamıyor ya da <1.0.0; beklenmedik istisna | kırmızı, 2 | `chromadb 1x izleyici - izleyici bozuk` |

45829 her yerde kimlik ∪ alias üzerinden ve yalnız chromadb'nin bulgularında
aranır. Hedefin <1.0.0 çözülmesi "bozuk" sayılıyor, çünkü pip `>=1.0.0`'ı 0.x'e
çözemez; rapor bunu diyorsa okuma ya da çözümleme bozuktur. Ayrıca 0.6.3'ün
verisi (45829 yok, üçü var) aksi hâlde "iş var" diye okunurdu. Bozukluk
nedenleri iki rapor için ayrı ayrı toplanır ve hepsi tek mesajda yazılır.
`main` beklenmedik bir istisnayı da yakalar; yakalanmasa Python 1 ile çıkardı,
bu da "iş var"ın kodu.

**Yapı.** Kontrol sürümü yalnız betikte (`CONTROL_VERSION`); iş akışı iki
requirements dosyasını betiğe `$RUNNER_TEMP`'te yazdırır, çünkü Dependabot
depodaki her requirements dosyasını toplar
(`test_no_requirements_file_names_chromadb_1x` bunu tutuyor). pip-audit'in
sürümü `requirements-dev.txt`'teki satırdan okunur, yani tek pin iki iş
akışını birlikte taşır. Rapor doğrulaması, mükerrer kayıtların katlanması ve
annotation biçimi `pip_audit_gate.py`'den **değiştirilmeden** import edilir
(kullanıcı kararı K3 A); aynı `ReportError` kapıda kırmızı bir kapı, burada
"izleyici bozuk" demek. `parse_report` açığı olmayan paketleri döndürmediği
için chromadb'nin sürümü JSON'dan ayrıca okunur. Tetikleyiciler: haftalık
`schedule` (Çarşamba 06:00 UTC, Dependabot'un Pazartesi koşusundan ayrı),
`workflow_dispatch`, ve `pull_request` yalnız dört yol için — iş akışı,
izleyici betiği, import ettiği kapı ve pip-audit sürümünü taşıyan
`requirements-dev.txt` (`test_watch_workflow_triggers` dördünü de istiyor).
Runner: `ubuntu-24.04`; `test_workflow_runners.py` her workflow'u tarıyordu,
yeni dosya kod değişikliği olmadan kapsama girdi ve `KNOWN_WORKFLOWS`'a
eklendi.

**İlk gerçek ölçüm — yerel, Windows, 2026-10-07.** Depo dışında taze bir venv
(`py -3.11`, Python 3.11.9), `pip-audit==2.10.1`, iki `pip-audit -r` raporu:

| tarama | süre | çıkış | paket | chromadb | açık taşıyan paket | chromadb kayıtları |
|---|---|---|---|---|---|---|
| kontrol `chromadb==1.5.9` | 67 s | 1 | 80 | 1.5.9 | yalnız chromadb | 5 kayıt / 4 tekil |
| hedef `chromadb>=1.0.0` | 30 s | 1 | 80 | 1.5.9 | yalnız chromadb | 5 kayıt / 4 tekil |

İki raporun paket kümesi ad ve sürüm olarak aynı (80); fark yalnız bir
alias listesinin sırası. 45829 **iki özdeş kayıt** olarak geliyor
(`PYSEC-2026-311`, alias'lar CVE-2026-45829 ve GHSA-f4j7-r4q5-qw2c); öteki
üçü PYSEC-2026-3813/3814/3815, hiçbirinin `fix_versions`'ı yok. GHSA kimlikli
kayıt görülmedi. İzleyicinin bu iki rapora kararı: **erteleme haklı, çıkış
0**. Windows ile Linux farkı: Windows çözümlemesinde `colorama` var, yani
CI'ın ağacı birebir aynı değil; chromadb 1.5.9'un Linux wheel'i
`cp39-abi3-manylinux_2_17_x86_64`. 1.5.9'un ağacında `fastapi` yok (1.x onu
runtime'dan çıkarıyor, 6D-4b'nin ölçümüyle tutarlı). CI'daki ilk ölçüm bu
PR'ın kendi `pull_request` koşusu olacak.

**Mutasyonlar.** Rapor mutasyonları bu iki gerçek rapordan türetildi ve
betiğin komut satırıyla koştu. Kod mutasyonları dosya kopyasıyla yapıldı ve
kopyadan geri alındı; her geri alma `cmp` ile hem kopyaya hem
`git cat-file --filters` çıktısına karşı doğrulandı, `__pycache__` her
seferinde temizlendi.

| Mutasyon | Gözlenen |
|---|---|
| R0 gerçek iki rapor | **yeşil**, erteleme haklı, 0 |
| R1 kontrolden 45829'un iki kaydı silindi | **kırmızı**, izleyici bozuk, 2: "kontrol: chromadb==1.5.9 CVE-2026-45829 raporlamiyor (pozitif kontrol dustu - tarayici ya da verisi bozuk)" |
| R2 hedeften 45829'un iki kaydı silindi | **kırmızı**, iş var, 1 |
| R3 hedeften bütün chromadb kayıtları silindi | **kırmızı**, iş var, 1 (K6'nın hücresi; eski tasarımda sonuçsuz) |
| R4a hedef sürümü 0.6.3, 45829 duruyor | **kırmızı**, izleyici bozuk, 2: "hedef: chromadb>=1.0.0 0.6.3 olarak cozulmus …" |
| R4b hedef 0.6.3, 45829 silindi, üçü kaldı | **kırmızı**, izleyici bozuk, 2 (iş var DEĞİL) |
| R5 her rapor için ayrı: yok / 0 bayt / JSON değil / `{}` / `dependencies: []` / chromadb `skip_reason` (12) | **12'si de kırmızı**, izleyici bozuk, 2; mesajlar kapınınki ("rapor yok", "rapor bos", "rapor JSON degil …", "raporda `dependencies` listesi yok", "hic paket taranmamis", "tarama eksik: projeden baska atlanan paket(ler): chromadb"), önlerinde rapor adı |
| R6 kontrol sürümü 1.5.8 | **kırmızı**, izleyici bozuk, 2: "kontrol: chromadb 1.5.8 cozulmus, beklenen 1.5.9" |
| R7a hedefte 45829'un iki özdeş kaydından biri silindi | **yeşil**, 0 |
| R7b kalan kayıt GHSA kimlikli biçime çevrildi | **yeşil**, 0 |
| K-M1a pozitif kontrol (45829 şartı) kaldırıldı | `test_control_without_45829_is_broken` **kırmızı** |
| K-M1b kontrol raporu tümüyle yok sayılıyor | **10 test kırmızı**: 8'in altı kontrol parametresi, 9'un kontrol parametresi, kontrol sürümü, kontrolde 45829 yok, bütün nedenler |
| K-M2 alias'lar kimliğe katılmıyor (kapının `_fold`'unda, geçici) | **9 test kırmızı** — iş var testleri de, çünkü kontrol 45829'u bulamayıp bozuk diyor |
| K-M3 ≥1.0.0 koşulu kaldırıldı | `test_target_below_1_0_is_broken` iki parametresi **kırmızı** |
| K-M4 kontrol sürümü eşitliği kaldırıldı | `test_control_on_another_version_is_broken` **kırmızı** |
| K-M5 bozukta çıkış 0 | `test_main_exit_code_and_title[dosyalar-yok]` **kırmızı** |
| K-M6 `main`'in istisna yakalaması kaldırıldı | `test_main_unexpected_error_is_broken` **kırmızı** |
| K-M7 yeni workflow `runs-on: ubuntu-latest` | `test_every_workflow_job_runs_on_the_pinned_runner` **kırmızı** |
| K-M8 yeni workflow dosyası silindi | `test_runner_scan_is_not_vacuous` ve `test_watch_workflow_triggers` **kırmızı** |
| K-M9 `paths:`'ten `pip_audit_gate.py` silindi | `test_watch_workflow_triggers` **kırmızı** |
| K-M11 `paths:`'ten `requirements-dev.txt` silindi | `test_watch_workflow_triggers` **kırmızı** |
| K-M10 köke `chromadb>=1.0.0` içeren bir `requirements-x.txt` | `test_no_requirements_file_names_chromadb_1x` **kırmızı**: "chromadb 1.x satiri depodaki bir requirements dosyasinda: ['requirements-x.txt']" |

Planla iki ayrışma. R7, planda "yalnız PYSEC-311 girdisi silinir, GHSA kalır"
diye tanımlanmıştı; gerçek raporda GHSA kimlikli kayıt yok, 45829'un iki
kaydı da PYSEC-311. Aynı iddia (mükerrer ve alias) R7a/R7b olarak sınandı.
K-M2, alias birleştirmesi kapıda olduğu için kapı dosyası üzerinde yapıldı;
geri alındıktan sonra `HEAD` ile bayt bayt aynı.

**Testler: 608 → 643.** `test_chromadb_1x_watch.py`'de 18 fonksiyon, 35 öğe:
haklı 1, iş var 2 (üçü varken, hiç kayıt yokken), yalnız 45829 → haklı 1,
alias biçimleri 3, kontrolde 45829 yok 1, kontrol sürümü 1, bozuk rapor
{kontrol, hedef} × 6 = 12, chromadb eksik 2, ayrıştırılamayan sürüm 1,
<1.0.0 2, bütün nedenler 1, `main` çıkış kodu ve başlık 3, beklenmedik
istisna 1, `write-requirements` 1, başlık biçimi 1, Dependabot toplama
bekçisi 1, iş akışı tetikleyicileri 1. `test_workflow_runners.py`'ye yalnız
`KNOWN_WORKFLOWS` eklendi (+0).

**#48 sonrası Dependabot gözlemi (6D-4d-2'nin açık kalan sorusu).** #48
`dependabot.yml`'i değiştirmişti (`==` sayısı 13 → 14), yani tam bir
`pip in /.` taraması bekleniyordu. Koşu 37647269455 (Dependabot işi
1615530511, 15:50:48Z) `failure` ile bitti; GitHub'ın 2026-10-07
15:06–15:16Z kesintisinin artçısında hiç runner alamadı ("Job is waiting for
a hosted runner to come online") ve "Dependabot encountered an unknown error"
ile kapandı — yapılandırma hiç okunmadı. Ardından koşu 37649949058 (iş
1615562569, 16:10:19Z, `8b21c79` üstünde) `success`, "No PRs affected":
yapılandırma #48'den sonra sağlam. Kaynak: koşu adları ve sonuçları API'den
(GET); günlük metinleri oturum istediği için kullanıcı tarafından okundu.

**Gözlenmedi — CI'da:** kırmızı durumlar yalnız yerelde, mutasyonla gözlendi.
CI'da gözlenecek olan bu PR'ın `pull_request` koşusu (beklenen: erteleme
haklı) ve merge sonrası main'de bir `workflow_dispatch` koşusu. C2'nin
(`dependabot.yml` yorumu) tetikleyeceği tam `pip in /.` taraması da merge
sonrası gözlenir; tahmin yazılmadı.

| Borç | İşaret |
|---|---|
| Kontrol sürümü (1.5.9) PyPI'den silinirse ya da 45829'un advisory'si 1.5.9'u dışlayacak biçimde değişirse kontrol düşer. Yank yetmez: `==` ile sabitlenmiş yanked sürüm yine kurulur (PEP 592; pip-audit'in çözücüsünde ölçülmedi) | Tetikleyici: **izleyicinin "kontrol" nedenli ilk kırmızısı** — `CONTROL_VERSION`, 45829'u taşıyan başka bir sürüme ([1.0.0, 1.5.9]) taşınır |
| İzleyici ağa bağlı: PyPI ya da pip-audit'in veri kaynağına ulaşılamazsa rapor çıkmaz ve zamanlanmış koşu "izleyici bozuk" ile kırmızı olur. Bilinçli (K1); kapının aynı borcu yukarıda, 6D-4d-2 ekinde | Tetikleyici: **ağ kaynaklı ilk "izleyici bozuk" kırmızısı** — yeniden deneme kararı o gün, kapının satırıyla birlikte verilir |
| `pull_request.paths` `requirements-dev.txt`'i içeriyor: o dosyaya dokunan her PR — Dependabot'un grup ve tekil bump'ları dahil — iki tam chromadb 1.x çözümlemesi koşturur (yerelde 67 s + 30 s). Bedeli bilerek kabul edildi (kullanıcı kararı): pip-audit sürüm değişikliği izleyiciyi PR'da sınasın | Tetikleyici: **bir Dependabot PR'ında izleyicinin ilgisiz bir kırmızısı** — o zaman yol daraltılır ya da bot için koşul eklenir |
| İzleyici kapının alt çizgili yardımcılarını (`_fold`, `_annotate`, `_normalize`) import ediyor; kapıdaki bir değişiklik izleyiciyi de değiştirir. `paths:` kapıyı içerdiği için böyle bir PR izleyiciyi de koşturur, ama kapının testleri izleyiciyi sınamaz | Tetikleyici: **kapının imzasını değiştiren ilk PR** — ortak kısım o zaman ayrı bir modüle çıkarılır |
| Zamanlanmış koşunun hiç olmaması hiçbir durumda görünmez. Public bir depoda 60 gün etkinlik olmazsa zamanlanmış iş akışları kapatılıyor (GitHub belgesi; bu depoda doğrulanmadı) | Tetikleyici: **beklenen bir Çarşamba koşusunun Actions'ta görünmemesi** |
| Başarısız zamanlanmış koşunun bildiriminin kime gittiği ölçülmedi (belgeye göre cron satırını en son değiştiren kullanıcıya) | Tetikleyici: **ilk zamanlanmış kırmızı** — e-postayı kimin aldığı o gün yazılır |

`tests.yml:56–57` satırının tetikleyicisi ("`tests.yml`'e dokunan bir sonraki
PR") bu PR'da ateşlenmedi: `tests.yml` değişmedi.

---

## Faz 6D-4e eki — 429, hata metninden değil SDK'nın tipinden

**Where:** [`src/defect_risk_analyzer/llm_provider.py`](../src/defect_risk_analyzer/llm_provider.py),
[`tests/test_llm_provider.py`](../tests/test_llm_provider.py),
[`tests/test_llm_sdk_contract.py`](../tests/test_llm_sdk_contract.py),
`pyproject.toml` (`per-file-ignores` yorumları)

**Ne değişti.** İki sağlayıcı da SDK çağrısını tek bir `except Exception` ile
sarıyor ve `RateLimitError` ile `LLMError` arasında hata metnine bakarak
seçiyordu: `"429"`, Groq'ta `"rate_limit"`, OpenAI'de `"rate limit"`. Artık
`analyze`, SDK'nın kendi sınıfını (`groq.RateLimitError`,
`openai.RateLimitError`) `try`'dan önce import edip tipine göre yakalıyor ve
`raise … from e` ile zincirliyor. İki sınıf da `APIStatusError` alt sınıfı,
`status_code: Literal[429]`; SDK'lar onu yalnız HTTP 429 için kuruyor
(`openai/_client.py:877`, `groq/_client.py:254`; openai 3.24.0, groq 1.7.0).
İkisinin `Exception`'ın altında ortak bir tabanı yok, ve istisnalarını farklı
HTTP kütüphanelerinin yanıtıyla kuruyorlar: openai `httpx2`, groq `httpx`.

Import `__init__`'te değil (kullanıcı kararı): dört yapıcı testi
`sys.modules`'a yalnız `Groq` / `OpenAI` taşıyan bir sahte koyuyor, ve
`__init__`'te bir `RateLimitError` importu onları `LLMError`'a düşürürdü.
Bedeli: `test_llm_provider.py` artık kurulu SDK'lara ve onların HTTP
kütüphanelerine bağlı; docstring'i bunu yazıyor. Groq'un bekleme süresi hâlâ
metinden okunuyor — değişen yalnız tespit.

**Ölçüm — P1–P4, değişiklikten önce ve sonra.** Çevrimdışı bir prob; sahte
istemci `object.__new__` ile kurulan sağlayıcıya veriliyor, P3'te ise gerçek
SDK istemcisi `MockTransport` ve `max_retries=0` ile koşuyor. Yerel `.venv`
(2026-10-10, groq 1.7.0, openai 3.24.0).

| | girdi | önce | sonra |
|---|---|---|---|
| P1 | içerik 429. karakterde bozuk JSON — `Expecting value: line 1 column 430 (char 429)` | `RateLimitError`, iki sağlayıcıda (yanlış pozitif) | `LLMError` |
| P2 | gerçek SDK `RateLimitError("quota gone")` | `LLMError` (yanlış negatif) | `RateLimitError`, `__cause__` SDK hatası |
| P3 | SDK'nın kendi 429 eşlemesi; `str(e)` = `Error code: 429 - {...}` | `RateLimitError`, Groq bekleme 90.5 s | `RateLimitError`, `__cause__` SDK hatası, 90.5 s |
| P4 | `groq.InternalServerError` (500), metninde "429" | `RateLimitError` (yanlış pozitif) | `LLMError` |

Dürüst çerçeve: SDK'nın ürettiği gerçek 429'lar önce de yakalanıyordu (P3),
çünkü SDK'nın mesajı "Error code: 429" ile başlıyor. Değişikliğin kazancı
yanlış pozitiflerin (P1, P4) ve sağlayıcılar arası metin asimetrisinin
kalkması; P2 yalnız elle kurulmuş bir durum.

**Beklenen değerler koddan önce yazıldı** (2026-10-10T09:35:06Z, depo dışı
bir dosyada), ölçülenle:

| | beklenen | ölçülen |
|---|---|---|
| `test_llm_provider.py` | 21 → 31 | 31 |
| `test_llm_sdk_contract.py` | 9 → 11 | 11 |
| C1 / C2 / C3 ağacı, toplanan | 653 / 655 / 655 | 653 / 655 / 655 |
| yerel passed + skipped | 652+1 / 654+1 / 654+1 | 652+1 / 654+1 / 654+1 |
| izole bakiye | 22 (13 B904 + 9 E501) | 22 |

Bir sapma ölçümden önce beyan edildi: plan M1'i "M0 ile aynı küme" diye
tahmin etmişti; koddan önceki dosya bunu 15'e (M0'ın 14'ü + bakiye bekçisi)
düzeltti. Bir sapma da ölçümde çıktı: C1'in ilk ölçümünde `ruff check .`
kırmızıydı — kontrat docstring'ini düzenlerken bir satır birleşmiş, 102
karakter olmuştu (E501; bakiye 23, bekçi kırmızı). Düzeltilmeden durduruldu;
satır sarması kullanıcı onayıyla yapıldı, C1 baştan ölçüldü (653, 652 + 1,
ruff temiz, 22).

**Mutasyonlar** — her biri dosya kopyasıyla; geri yükleme `cmp` ile doğrulandı,
`__pycache__` temizlendi. Koşulan: `test_llm_provider.py` +
`test_llm_sdk_contract.py` + `test_known_debt_tally.py` (43 öğe).

| | mutasyon | beklenen | gözlenen | mesaj |
|---|---|---|---|---|
| M0 | yeni testler eski kodda (doğal kırmızı) | 14 | 14 / 31 | `LLMError: Groq API error: quota gone`; `RateLimitError: … (char 429)`; `RateLimitError: … upstream said 429` |
| M1 | `llm_provider.py` 67d5dd0'daki metin eşleşmesine geri | 15 | 15 | M0'ınkiler + bekçi: `belge: 9 E501 + 13 B904. olculen: 9 E501 + 15 B904`; kontrat testi yeşil |
| M2 | iki `except <SDK>RateLimitError` dalı silindi | 8 | 8 | `LLMError: … Error code: 429 - {...}` (kontrat ×2), `quota gone` ×5, `Please try again in 1m 30s.`; ruff ayrıca 2 F401 |
| M3 | `RateLimitError` yerine `APIStatusError` import edildi | 2 | 2 | `RateLimitError: … upstream said 429`; düz `Exception("500 …")` testi yeşil |
| M4 | iki `from e` silindi | 3 | 3 | `assert None is RateLimitError('quota gone')` ×2 + bekçi (`15 B904`); **`ruff check .` yeşil** — karantina |
| M5 | Groq dalı `openai.RateLimitError` yakaladı | 4 | 4 | yalnız Groq öğeleri, kontrat `[groq]` dahil |
| M6 | `QUIET_MESSAGE`'e "Error code: 429" eklendi | 2 | 2 | `assert '429' not in 'error code: 429 quota gone'` (fabrika bekçisi) |
| M7 | kontrat testinde `max_retries=0` kaldırıldı | 2 | 2 | `groq: 6 istek gitti, 2 bekleniyordu` (openai aynı); 7.35 s |
| M8 | kod değişti, belge 24'te | 1 | 1 | `belge: 9 E501 + 15 B904. olculen: 9 E501 + 13 B904` |

M4 bu turun asıl dersi: `from e`'nin silinmesini `ruff check .` göremez,
çünkü `llm_provider.py` B904 için karantinada. Onu `__cause__` testi ve
bakiye bekçisi görüyor.

**Kapsam genişlemesi (kullanıcı kararı, 2026-10-10).** Kalan 22 lint
bulgusunun sahibi Faz 7'nin temizlik kuyruğu oldu; bu, `pyproject.toml`'un
`api.py` ve E501 yorumlarındaki "no phase of its own yet" / "No phase owns
these" ile bu dosyanın lint bölümündeki "kalanlar sahipsiz" ifadesini
bayatlattı. Üçü de bu PR'da (C1) düzeltildi.

**Gözlenmedi — CI'da:** 655 passed ve boş uyarı özeti bu PR'ın koşusunda
gözlenecek. Sağlayıcıların gerçek bir API'ye karşı 429 alması hiç ölçülmedi;
kontrat testi SDK'nın eşlemesini sahte taşımayla ölçüyor, ağla değil.

| Borç | İşaret |
|---|---|
| İki SDK da 429'u varsayılan olarak iki kez kendisi, bekleyerek yeniden deniyor (`DEFAULT_MAX_RETRIES = 2`; `_base_client.py` "Retry on rate limits", openai :916, groq :797). Sağlayıcılar `max_retries` vermiyor, yani devre kesici 429'u ancak üç istekten sonra görüyor. Bu PR'da değiştirilmedi: tespit değişti, çağrı davranışı değil | **Faz 7'nin v1.1 değerlendirmesi** (Faz 7'deki KNOWN-DEBT v1.1 gözden geçirmesi; v1.0'da mı v1.1'de mi ele alınacağı orada kararlaştırılır — davranış değişikliği, temizlik değil; kullanıcı kararı, 2026-10-10), tetikleyici: **Faz 7 başladığında** — `max_retries` kararı orada verilir |
| Groq'un bekleme süresi hâlâ hata metninden regex'le okunuyor (`_parse_retry_after`); SDK'nın kendisi `retry-after-ms` / `retry-after` başlıklarını okuyabiliyor (`groq/_base_client.py:717`). Metin biçimi değişirse süre sessizce 60 s'ye düşer | **Faz 7'nin v1.1 değerlendirmesi** (yukarıdaki satırla aynı gerekçe: davranış değişikliği, temizlik değil; kullanıcı kararı, 2026-10-10), tetikleyici: **Faz 7 başladığında** |
| `test_llm_provider.py` ve kontrat testi `httpx` / `httpx2`'yi doğrudan import ediyor; ikisi de transitif. Bir SDK HTTP kütüphanesini değiştirirse (openai 3.x'in httpx'ten httpx2'ye geçtiği gibi) testler import ya da kurulum hatasıyla kırmızı olur — görünür, sessiz değil | Tetikleyici: **groq ya da openai'nin `_exceptions.py`'sindeki HTTP importu değiştiğinde** — `SDKS` ve `HTTP_LIBRARY` güncellenir |

---

## Faz 6D-6 eki — pandas 3 / Plotly 7 öncesi değer testi (6D-6a)

**Where:** [`tests/test_dashboard_values.py`](../tests/test_dashboard_values.py)
(yeni), [`ui/app.py`](../src/defect_risk_analyzer/ui/app.py) ve
[`ui/pages/buglar.py`](../src/defect_risk_analyzer/ui/pages/buglar.py) (sınanan,
değişmedi)

6D-6 iki Dependabot majörünü kapsıyor: **#40** pandas 2.2.3 → 3.0.6 ve **#41**
plotly 5.24.1 → 7.1.0. Kullanıcı kararı (2026-10-10): önce kalıcı bir değer
testi (6D-6a), sonra kendi bump PR'larımız, sırayla 6D-6b plotly, 6D-6c pandas.
#40 ve #41'in bizim PR'larımızdan sonra kendiliğinden kapanması bekleniyor;
gözlenecek, tahmin yazılmadı.

**Keşif (2026-10-10, depo dışı taze venv'ler, CI kurulum sırası, py 3.11.9).**
İki PR'ın da tabanı bayat: #40 `dc53431` (main'in 31 commit gerisinde), #41
`58c2c39` (15). İkisinin CI'ı da pip-audit kapısından önce koşmuştu. Her biri
`requirements.txt`'te tek satır.

| | toplanan | pytest | uyarı özeti | freeze (Windows) | kapı |
|---|---|---|---|---|---|
| main | 655 | 654 + 1 | yok | 136 | 138 taranan, 3 tekil |
| yalnız pandas 3.0.6 | 655 | 654 + 1 | yok | 135 (−pytz) | 137, 3 |
| yalnız plotly 7.1.0 | 655 | 654 + 1 | yok | 136 | 138, 3 |

plotly 7 yeni paket getirmiyor: `narwhals` altair üzerinden, `tenacity`
chromadb üzerinden zaten kümede. pandas 3 `pytz`'yi bırakıyor, `tzdata`'yı
yalnız win32/emscripten'de istiyor. **Linux için 134 (çıkarım):** kurulu
metadata üzerinde Linux işaretleriyle yürüyüş, main için CI'ın 136'sını
yeniden üretiyor; pandas 3 ile −pytz −tzdata → 134, kapının taradığı 138 →
136. CI'da gözlenecek. **Ölçüm aracının kendi gürültüsü:** `pip install
--dry-run --platform manylinux…` bir Linux ölçümü DEĞİL — işaretleri hâlâ
çalışan yorumlayıcıya göre değerlendiriyor (Linux kümesinde `colorama` kaldı,
`uvloop` yoktu). O sonuç kullanılmadı.

Keşfin asıl bulgusu: pandas ve plotly'yi kullanan tek yer `ui/app.py` (beş
grafik, üç tablo) ve `ui/pages/buglar.py` (iki tablo), ve onları sınayan
AppTest yürüyüşü hiçbir değer okumuyor. `buglar.py`'nin `render_patterns`'ı
(:128–250) hiç çalışmıyordu. Yeşil bir bump bu yüzden "hata fırlatmadı"dan
fazlasını söylemezdi.

**Test tasarımı.** `tests/test_dashboard_values.py` streamlit'in tarayıcıya
gönderdiği Plotly JSON'unu (`proto.spec`) ve `st.dataframe` satırlarını okuyor:
iz sırası, iz adı, x/y/labels/values/text, satırlar. Veri sahte bir servis
(`ui.service.AnalysisService` yerine); beklenen değerler fikstürden elle
türetildi ve literal yazıldı. Saat yok (`days_open` fikstürden), VectorStore
kurulmuyor. Plotly ≥ 6'nın `{"dtype", "bdata"}` dizileri yalnız standart
kütüphaneyle çözülüyor (numpy bu depoda hiç import edilmiyor); gece yarısı
damgası güne indiriliyor, gerçek bir saat reddediliyor. Bekçiler: sayfa başına
grafik/tablo kümesi birebir; `bdata` varlığı kurulu Plotly majörüne bağlı;
uyarı denetimi ayrı render'da. 655 → 679 (10 okuyucu birim testi + 9 değer
testi + 5 bekçi öğesi).

**Bilerek okunmayan ve kör noktalar:**
- Renk, şablon, hovertemplate, kenar boşluğu, dtype. pandas 3'ün `str`'i
  kullanıcıya görünen bir değişiklik değil.
- Gerçek servisin çıktı ŞEKLİ. O tarafı `test_dashboard_pages.py` (gerçek
  servis) ve skor snapshot'ları tutuyor.
- Tarayıcıda çizim. ~~streamlit 1.65.0'ın paketlediği plotly.js'in 3.8.2 olduğu
  paketteki bir dizgiden çıkarım; plotly.py 7.1 plotly.js 4.1.1'i hedefliyor.~~
  **Düzeltme (6D-6b, 2026-10-10): yanlıştı.** O dizgi aynı paketteki
  `node_modules/@plotly/d3/d3.js`'in sürümü (`version:\`3.8.2\``). plotly.js'in
  kendi sürümü `"src/version.js"(e){e.version=\`4.1.1\`}` — streamlit 1.65.0
  plotly.js **4.1.1** paketliyor (`streamlit/static/static/js/PlotlyChart.Dv4dc5oY.js`;
  repo `.venv` ile venv-6d6b'deki dosya bayt bayt aynı), yani plotly.py 7.1'in
  hedeflediğiyle aynı sürüm. AppTest JavaScript çalıştırmıyor; çizim 6D-6b'nin
  gözle kontrolünde görüldü (aşağıda).
- Pastanın ekrandaki dilim sırası (plotly.js sıralıyor; JSON veri sırasında).
- Uyarı denetimi streamlit'in log tabanlı kullanımdan kaldırma uyarılarını ve
  import anında atılmış uyarıları göremez.

**Uyarılar — ölçüldü (2026-10-10, depo dışı deneme).** AppTest'in betik
iş parçacığında atılan bir FutureWarning/DeprecationWarning pytest'in uyarı
özetine ve `recwarn`'a ulaşıyor. `simplefilter("error")` altında testte
fırlatılmıyor: betiği durduruyor ve AppTest onu `at.exception` olarak
topluyor. Değer testleri bu yüzden ayrı render ediliyor — tek bir uyarı bütün
değer kanıtını silmesin. Önceki turdaki "uyarı özeti boş" ölçümleri de böylece
gerçekten "uyarı yok" anlamına geliyor.

**Doğal kırmızı yok.** 6D-6a davranış değiştirmiyor; dosya main'de yapısı
gereği yeşil. Kırmızısı yalnız mutasyonla gözlendi. Görevi bump'larla başlıyor.

**Beklenen değerler koddan önce yazıldı** (2026-10-10T12:03:59Z, depo dışı bir
dosyada; ikinci koşunun beklentisi 12:27:51Z'de eklendi), ölçülenle:

| | beklenen | ölçülen |
|---|---|---|
| toplanan (repo `.venv`, C1 ağacı) | 679 | 679 |
| düz pytest | 678 + 1, uyarı özeti yok | 678 + 1, uyarı özeti yok |
| `ruff check .` / izole bakiye | temiz / 22 | temiz / 22 |
| M1–M12 | aşağıdaki tablo | 14 koşunun 14'ü tahminle aynı |
| bump ortamları, tam takım | 678 + 1 | ilk koşu **677 + 2**, ikinci koşu 678 + 1 (aşağıda) |

**Mutasyonlar** — repo `.venv`'inde (pandas 2.2.3, plotly 5.24.1), her biri
dosya kopyasıyla; geri yükleme `git cat-file --filters :<yol>` ile `cmp`,
`__pycache__` temizlendi. Koşulan: `tests/test_dashboard_values.py` (24 öğe).

| | mutasyon | beklenen | gözlenen | mesaj |
|---|---|---|---|---|
| M1 | `app.py:86` `sort_values` silindi | `test_risk_map_bars` | aynı (1/24) | `At index 1 diff: ('KRİTİK', ['Ödeme'], …) != ('ORTA', ['Rapor'], …)` |
| M2 | `app.py:123` `reverse=False` | `test_risk_ranking_table` | aynı | `At index 0 diff: {'module': 'Auth', …} != {'module': 'Ödeme', …}` |
| M3 | `app.py:181` hafta başı bir gün kaydı | `test_weekly_trend_lines` | aynı | `('Arama', ['2026-03-01'], [1]) != ('Arama', ['2026-03-02'], [1])` |
| M4a | risk çubuğu verisinden ilk modül düştü | `test_risk_map_bars` | aynı | `('ORTA', ['Rapor'], …) != ('DÜŞÜK', ['Auth'], …)` |
| M4b | pasta verisinden ilk modül düştü | `test_bug_distribution_pie` | aynı | `['Ödeme', 'Rapor', 'Arama'] != ['Auth', 'Ödeme', 'Rapor', 'Arama']` |
| M5 | `app.py:212` açık/kapalı yer değiştirdi | `test_open_closed_stacked_bars` | aynı | `('Kapalı', …) != ('Açık', …)` |
| M6 | `app.py:82` etiket yerine İngilizce seviye | `test_risk_map_bars` | aynı | `('LOW', ['Auth'], …) != ('DÜŞÜK', ['Auth'], …)` |
| M7a | `buglar.py:196` `[:80]` → `[:70]` | `test_pattern_tab` | aynı | özet `…ve mü` ile bitiyor |
| M7b | `buglar.py:197–198` priority/status yer değiştirdi | `test_pattern_tab` | aynı | `'priority': 'In Progress', 'status': 'Medium'` |
| M8 | `_values` `bdata`'yı çözmeden döndürüyor | `test_bdata_is_decoded` ×2 | aynı (2/24) | `assert {'dtype': 'f8', …} == [20.5]` |
| M9 | `_day` her saati kabul ediyor | `test_a_time_of_day_is_refused` | aynı | `DID NOT RAISE ValueError` |
| M10 | `app.py:116` pasta çizilmiyor | pasta + kümeler bekçisi [app] | aynı (2/24) | `expected one pie chart, found 0` |
| M11 | `app.py:172` `if False:` | haftalık, açık/kapalı, kümülatif + kümeler bekçisi [app] | aynı (4/24) | `expected one weekly chart, found 0` |
| M12 | `render_risk_overview` başında `FutureWarning` | uyarı bekçisi [app] | aynı (1/24, değer testleri yeşil) | `AssertionError: ['M12']` |

M8 main'de yalnız çözücünün kendi testlerini kırıyor, çünkü Plotly 5 hiç
`bdata` yazmıyor — iki yardımcının neden ayrıca sınandığının gerekçesi bu.

**Bump ölçümü** — C1'in `git archive` görüntüsünden ortam başına bir kopya,
kopyanın kendi `requirements.txt`'i değiştirildi (editable metadata CI'daki
gibi bump'ı taşıyor), taze venv, CI sırası.

| | pandas / plotly | toplanan | tam takım, 1. koşu | tam takım, 2. koşu | yeni dosya | uyarı özeti | freeze | `pip check` | kapı |
|---|---|---|---|---|---|---|---|---|---|
| (a) | 2.2.3 / 5.24.1 | 679 | 677 + 2 | 678 + 1 | 24/24 | yok | 136 | temiz | rc 0; 138, 3 tekil |
| (b) | 3.0.6 / 5.24.1 | 679 | 677 + 2 | 678 + 1 | 24/24 | yok | 135 (−pytz) | temiz | rc 0; 137, 3 |
| (c) | 2.2.3 / 7.1.0 | 679 | 677 + 2 | 678 + 1 | 24/24 | yok | 136 | temiz | rc 0; 138, 3 |
| (d) | 3.0.6 / 7.1.0 | 679 | 677 + 2 | 678 + 1 | 24/24 | yok | 135 (−pytz) | temiz | rc 0; 137, 3 |

İlk koşunun fazladan atlaması `test_ci_analyzer_inference.py:508` ("git
ls-files unavailable … exit status 128"): `git archive` görüntüsü bir git
deposu değil. Dördünde de aynıydı, yani bump'tan değil yöntemden. Beklenti
bunu öngörmediği için durduruldu; kullanıcı kararıyla görüntülerde depo
dışında `git init` + `git add -A` yapıldı (commit yok; `ls-files` index'i
okur, dosya kümesi C1 ağacıyla aynı, 122), beklenti koşmadan yazıldı ve tuttu.
Tek gerçek belirsizlik — plotly 5.24.1'in pandas 3'ün s/us çözünürlüklü tarih
sütunlarını serileştirmesi — (b)'de çözüldü: haftalık ve kümülatif testler
yeşil.

**Bir sapma daha, araçta:** depo dışındaki mutasyon uygulayıcısı M4a'da durdu
— aradığı alt dizgi `app.py`'de 3 kez geçiyordu (:64 da eşleşiyor), 2
bekliyordu. Assert dosyaya yazmadan önce çalıştı (`app.py` index ile `cmp`
eşit); geçiş sırası araçta düzeltildi, M4a'dan devam edildi.

**Gözlenmedi:** CI'da 679 passed ve boş uyarı özeti bu PR'ın koşusunda
gözlenecek; Linux'taki 134 de 6D-6c'nin CI freeze'inde.

| Borç | İşaret |
|---|---|
| streamlit'in `use_container_width` kullanımdan kaldırma uyarısı her render'da düşüyor; mesaj aynen *"`use_container_width` will be removed after 2025-12-31"* diyor ve **o tarih geçti** — parametre streamlit 1.65.0'da hâlâ çalışıyor. Uyarı Python `warnings` değil, bir log kaydı (`streamlit.deprecation_util`), bu yüzden pytest'in uyarı özetinde hiç görünmüyor; 6D-6a'nın denetimi sırasında görüldü. Depoda 19 çağrı yeri, 5 dosyada (`ui/app.py` 8, `ui/pages/ayarlar.py` 6, `ui/pages/buglar.py` 2, `ui/setup_wizard.py` 2, `ui/shell.py` 1); yerine `width="stretch"` | **Faz 7'nin temizlik kuyruğu**, tetikleyici: **streamlit parametreyi kaldırdığında (sayfa testlerinin kırmızısı) ya da Faz 7 başladığında** |

### 6D-6b: Plotly 5.24.1 → 7.1.0 (2026-10-10)

Kendi bump PR'ımız; ölçü 6D-6a'nın değer testi. Dört commit: C1
`chore(deps)` yalnız `requirements.txt:13`; C2 `test(dashboard)` yığılmış
çubuk testi; C3 `fix(patterns)` — **kapsam genişletmesi**, aşağıda; C4 bu
kayıt. Beklentiler her turda koddan önce, depo dışı zaman damgalı dosyalara
yazıldı (13:23:52Z, 14:34:28Z, 14:42:33Z).

**Ölçüm ortamı.** Depo dışında taze `venv-6d6b` (py 3.11.9, CI sırası, dal
checkout'undan; plotly 7.1.0, narwhals 2.27.1). Her commit ağacı orada
ölçüldü. Repo `.venv` plotly 5.24.1'de kaldı; C2'den itibaren orada tam iki
kırmızı **doğal**, sapma değil.

| | venv-6d6b | repo `.venv` (plotly 5) |
|---|---|---|
| C1 | 679 / 678 + 1, uyarı özeti yok | 679 / 678 + 1 |
| C2 | 681 / 680 + 1 | 2 kırmızı: yığılmış çubuk testi `[risk_map]`, `[open_closed]` |
| C3, C4 | 684 / 683 + 1 | 2 kırmızı, aynı iki test |

Ruff her ağaçta temiz, bakiye 22. venv-6d6b: freeze 136 (Windows), main
ortamına göre tek fark `plotly==5.24.1` → `7.1.0`; `pip check` temiz; kapı rc
0, 138 taranan, 3 kayıt / 3 tekil (chromadb 0.6.3). Bdata bekçisi `>= 6`
dalında: `app.py`'de grafik başına `[8, 1, 3, 2, 1]` = 15 kodlu dizi (Plotly
5'te 0); dosya genelinde 17 dizi gerçekten çözüldü (15 + birim testlerdeki 2
literal).

**Tarayıcı kontrolü (kullanıcı).** İki venv aynı depo `src`'sini çalıştırıyor
(editable); dal main'den yalnız `requirements.txt` ile ayrılıyor ve o dosya
çalışma anında okunmuyor. ÖNCE = repo `.venv` (8501), SONRA = venv-6d6b
(8502); her biri kendi geçici `DRA_BASE_DIR`'ında (örnek bug'lar,
`.streamlit/config.toml`, yalnız `USE_MOCK_DATA=True` içeren bir `.env`),
çalışma dizini o klasör (chromadb ayarları `.env`'i çalışma dizininden
okuyor), `--server.address localhost` (yoksa streamlit dış IP'yi öğrenmek için
dışarı istek atıyor). Kullanıcının gözlemi, madde madde:
- Değerler, tablolar, fareyle üzerine gelme, Kör Nokta sekmesi, dil (TR/EN):
  ÖNCE = SONRA.
- Konsol: SONRA 0 kırmızı hata. ÖNCE 2 kırmızı: `buglar/_stcore/health` ve
  `buglar/_stcore/host-config` 404 — sayfa `/buglar` adresinden doğrudan
  yenilenince; plotly'den bağımsız. İki sekmede yüzlerce sarı
  "Invalid color passed for primaryColor/textColor in theme.sidebar" uyarısı
  (streamlit teması). Plotly ya da trace geçen satır yok. Issues panelinde
  "autocomplete" ve "No label associated with a form field" (streamlit form
  alanları).
- **Görsel fark 1:** "Açık vs Kapalı" ÖNCE yan yana (gruplu), SONRA yığılmış —
  kodun istediği `barmode="stack"`.
- **Görsel fark 2:** "Modül Risk Haritası" ÖNCE ince ve satırın üst kısmına
  kaymış çubuklar, SONRA satırı dolduruyor.
- **Plotly'den bağımsız:** Pattern Tespiti kararsız — aynı ortamda yeniden
  başlatmalarda bir pattern'in modülü Frontend → Inventory → Reporting →
  Inventory; anahtar kelime sırası ve "Olası Ortak Neden" de değişiyor; bug
  listesi aynı.

**İki görsel farkın nedeni — main'deki bir kusur, bump düzeltiyor.** Sahte
servisle her iki ortamda JSON okundu:

| Grafik | Alan | Plotly 5.24.1 | Plotly 7.1.0 |
|---|---|---|---|
| Açık/Kapalı | `barmode` | `stack` | `stack` |
| | `offsetgroup` | `Açık`, `Kapalı` | yok, yok |
| Risk haritası | `barmode` | `relative` | `relative` |
| | `offsetgroup` | `DÜŞÜK`, `ORTA`, `YÜKSEK`, `KRİTİK` | dördü de yok |

Kaynaklar: Plotly 5.24.1'in px'i her bar izine `offsetgroup=trace_name`
koyuyor, barmode ne olursa olsun (`plotly/express/_core.py:2197-2198`); Plotly
7.1.0 yalnız barmode `group` ya da boşken (`_core.py:2616-2621`, yorumu: "Set
'offsetgroup' only in group barmode"). plotly.js 3.0.0'ın #7009'u offsetgroup'u
stack/relative modunda da uyguluyor (plotly.py 6.0.0 CHANGELOG'u aktarıyor);
streamlit 1.65.0 plotly.js 4.1.1 paketliyor (yukarıdaki düzeltme). Yani main'de
plotly.py 5'in JSON'u plotly.js 4'te gruplu çiziliyor; risk haritasında dört
seviye her satırda dört yuva açıyor, biri dolu. Tarayıcıdaki kısım sürüm notu ve
gözlemle tutarlı bir **çıkarım** — plotly.js kodunda izi sürülmedi. plotly.py
CHANGELOG'unda px tarafındaki değişiklik için ayrı bir madde **bulunamadı**.
main'in bu görünüme ne zaman geçtiği **ölçülmedi** (büyük olasılıkla
streamlit'in paketlediği plotly.js 3'e geçtiğinde).

C2'nin testi (`test_bars_in_a_stack_share_one_offset_group`, iki öğe): barmode
stack ya da relative, ve bütün izler tek offset grubunda. Plotly 5'te kırmızı,
7'de yeşil — **bump'ın doğal kırmızısı**. Bu yüzden C1 ile C2 çift olarak
revert edilir, önce C2.

**Kapsam genişletmesi — Pattern beraberlikleri (kullanıcı kararı,
2026-10-10).** Plotly'den bağımsız; bu PR'a ayrı bir commit (C3) olarak girdi,
tek başına geri alınabilir. Kayıt: yukarıdaki `common_keywords` girdisi,
**Kapandı** paragrafı. Ölçüm, gerçek `detect_patterns` ve ChromaDB ile, TR
örnek verisi, `PYTHONHASHSEED` 0–5: kümeler altısında da aynı; eski kodda
Pattern #2'nin modülü 0–3'te Frontend, 4–5'te Reporting (Frontend, Inventory,
Reporting 2'şer — beraberlik), Pattern #1'in kelime **kümesi** değişiyor
(`ödeme`, `sms`, `posta`, `ürün`, `şifre` girip çıkıyor). EN setinde de
Pattern #2 ve #3'ün modülü değişiyordu. Yeni kodda altı seed'in çıktısı TR'de
de EN'de de tek:

| | Modül | Öncelik | Anahtar kelimeler | Olası Ortak Neden |
|---|---|---|---|---|
| TR #1 (8 bug, critical) | Authentication | High | eksik, yanlış, aktif, dönüyor, etkiliyor, posta, sms, ödeme | `eksik` ve `yanlış` |
| TR #2 (8, critical) | Frontend | Medium | görünüyor, işlemi, miktarı, sorunu, stok | `görünüyor` ve `işlemi` |
| TR #3 (3, high) | Authentication | Highest | — | — |
| EN #1 (8, critical) | Authentication | Highest | sign, but, never, active, back, cannot, email, every | `sign` ve `but` |
| EN #2 (8, critical) | Frontend | Medium | and, product, quantity, cart, customer, database, incorrectly, never | `and` ve `product` |
| EN #3 (4, medium) | Frontend | Low | and, cannot, notification, notifications | `and` ve `cannot` |

**Mutasyonlar** — venv-6d6b, dosya kopyası, `cmp` ile geri dönüş,
`__pycache__` temizliği; tahminler koddan önce yazıldı. T1 = sekiz seed'li
alt süreç testi, T2 = modül/öncelik beraberliği, T3 = kelime beraberliği.

| # | Mutasyon | Tahmin | Gözlenen |
|---|---|---|---|
| M1 | ortam: repo `.venv` (plotly 5) | C2'nin 2 öğesi | aynı: `4 offset groups ['DÜŞÜK', 'KRİTİK', 'ORTA', 'YÜKSEK']`, `2 offset groups ['Açık', 'Kapalı']` |
| M2 | Açık/Kapalı izlerine `offsetgroup=ad` | `[open_closed]` | aynı (1/26) |
| M3 | risk haritası izlerine `offsetgroup=ad` | `[risk_map]` | aynı (1/26) |
| M4 | `barmode="stack"` → `"group"` | 3 test | aynı: `expected one open_closed chart, found 0` ×2 + kümeler bekçisi `[app.py]` |
| M5 | `pattern_detector.py` eski hali | T1 deterministik, T2 (gövdede ImportError), T3 rastgele | aynı, üç koşu: T1 hep aynı cevaplar, T2 `cannot import name '_most_common_priority'`, T3 üçünde de kırmızı ama her seferinde başka kelime sırası |
| M6 | kelimelerde `most_common()` | T1, T3 | aynı |
| M7 | modülde `most_common(1)` | T1, T2 | aynı: `Reporting`; `('Rapor', 'Medium')` |
| M8 | öncelikte `most_common(1)` | T1, T2 | aynı: `Low`; `('Arama', 'Low')` |
| M9 | `sorted(cluster_keys)` yok | T1 | aynı: bug sırası `['T-3', 'T-2', 'T-6', …]` |
| M10 | ikincil ölçüt ad azalan | T1, T2, T3 | aynı: `juliet, india, …`; `('Ödeme', 'Medium')` |
| M11 | öncelikte ağırlık yerine ad | T1, T2 | aynı: `Low`; `('Arama', 'Blocker')` |
| M12 | bilinmeyen öncelik önce | T2 | aynı: `('Arama', 'Blocker')` |

**Bir sapma, testin kendisinde.** M5'in ilk koşusunda T1'in kırmızısı hiç
görülmedi: T2 yeni yardımcıyı modül düzeyinde import ediyordu, eski kodda o ad
olmadığı için **bütün dosya toplanamadı** (`ImportError` toplama sırasında, 9
testin hiçbiri koşmadı). Durduruldu; T1'in çocuk betiği eski koda doğrudan
verildi: sekiz seed'in sekizi farklı, iki koşu satır satır aynı. Kullanıcı
kararıyla import T2'nin gövdesine taşındı ve ilke dosyaya yazıldı: modül
düzeyinde yalnız eski kodda da var olan adlar; eksik bir ad tek testi
düşürmeli, bütün dosyayı değil. M5 ve M6–M12 son dosyayla yeniden koşuldu.

**Yan gözlemler.**
- `%TEMP%`'teki `dra-*` klasörleri bu oturumdaki birçok tam koşudan sonra 7'de
  kaldı (6D-6a'da sayılan sayı); normal bitişte conftest temizliği sağlıklı
  görünüyor — çıkarım.
- Tarayıcı kontrolünde her iki sunucunun stderr'i aynı iki gürültüyü taşıyor:
  chromadb 0.6.3'ün posthog telemetrisi ("capture() takes 1 positional argument
  but 3 were given", 6D-5'in konusu) ve yukarıdaki `use_container_width` log
  satırları.
- `analysis_service.py`'deki `most_common(1)` (sorgu için modül tahmini) bu
  sınıftan **değil**: girdi sırası ChromaDB'nin benzerlik sırası, hash sırası
  değil.

| Borç | İşaret |
|---|---|
| EN `STOP_WORDS`'te `and` ve `but` yok (`pattern_detector.py:25–53`; liste "the", "a", "of" gibi edatları içeriyor, bağlaçları içermiyor). EN örnek verisinde "Olası Ortak Neden" `and` ve `product`, `and` ve `cannot`, `sign` ve `but` diyor — anlamsız bir kök neden önerisi. 6D-6b'nin deterministik sıralaması bunu görünür kıldı (artık her seferinde aynı anlamsız kelime); düzeltme bir davranış değişikliği ve bu PR'ın kapsamında değil | **Faz 7'nin v1.1 değerlendirmesi** (kullanıcı kararı, 2026-10-10), tetikleyici: **Faz 7 başladığında** |
