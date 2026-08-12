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

**Where:** [`src/defect_risk_analyzer/dashboard.py`](../src/defect_risk_analyzer/dashboard.py)

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
`data/chroma_db` dizinine bağlanıyor. Bir tam veri yüklemesi
(`load_bugs` → `VectorStore.reset()`) koleksiyonu silip yeniden yarattığı
için, o sırada yükleme yapmayan tarafın elindeki koleksiyon tanıtıcısı
geçersiz kalıyor.

**Detail:** Faz 2 Adım 2 doğrulaması sırasında gerçek bir arıza olarak
görüldü: ikinci bir process veri yükleyince canlı dashboard'un Pattern
sayfası `Collection ... does not exist` verdi ve o oturum boyunca bozuk
kaldı. `VectorStore._run()` artık bu hatayı tanıyıp istemciyi ve tanıtıcıyı
düşürerek bir kez yeniden deniyor, dolayısıyla kullanıcıya yansıyan kalıcı
bozulma giderildi.

**Impact:** artık kurtarılabilir, ama hâlâ bir yarış: iki taraf aynı anda
`reset()` çağırırsa biri diğerinin yeni indekslediği verinin üzerine yazabilir.
Varsayılan `docker-compose up` tek servis çalıştırdığı için normal kullanımda
görülmez; yalnız `webhook` profili açıkken geçerli. SQLite kilit çakışması da
teorik olarak mümkün.

**Workaround until then:** iki profil birlikte çalışıyorken veri
senkronizasyonunu tek taraftan yapın.

**Planned fix (Phase 4):** veri katmanı ele alınırken toptan silme yerine
diff-sync (`collection.get` → karşılaştır → `delete` + `upsert`) ve
`defect_history_mock` / `defect_history_live` ayrı koleksiyonları geliyor;
ikisi de bu yarışı büyük ölçüde ortadan kaldırır.
