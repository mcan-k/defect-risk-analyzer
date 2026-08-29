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

## `common_keywords` sırası her süreçte değişiyor — kullanıcı iki farklı kök neden görüyor

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

| Borç | İşaret |
|---|---|
| Enjekte edilen bir dış kaynak isteğini durduracak ikinci bir katman yok | Tetikleyici: **6D (proje hijyeni)** |
