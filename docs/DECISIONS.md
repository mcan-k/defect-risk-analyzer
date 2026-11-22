# Kararlar

Bu dosya projenin yönünü belirleyen kararların tek listesi: hangi iş hangi
fazda ya da sürümde yapılır, hangi süreç kuralı kalıcıdır, hangi soru hâlâ
açıktır. Ayrıntı ve ölçüm kararın uygulandığı yerde kalır —
[bilinen borçlar](KNOWN-DEBT.md), [yol haritası](ROADMAP-v2.md), PR'lar.
Burada yalnız karar, tarihi ve izi var.

**İlke: kararlar kullanıcıya aittir; denetleyici önerir.** Bir öneri,
kullanıcı onaylayana kadar karar değildir. Bu dosyaya kaydı olmayan bir karar
yazılmaz. Tarihi bulunamayan kararda "tarih: —" yazar. K-E9'a uyan sahip
atamaları kuralın uygulamasıdır ve denetleyici tarafından yapılabilir; kurala
uymayan (tartışmalı) kayıtlar kullanıcıya sorulur.

Biçim: **kod** (varsa) · tarih · karar · ilgili PR (biliniyorsa). Koddaki
"(a)" gibi harf, kullanıcıya sunulan seçeneklerden seçileni gösterir.

---

## 6D

- **6D-5** · 2026-10-10 · chromadb 1.x geçişi v1.1'e bırakıldı. v1.0
  chromadb 0.6.3 ile çıkar; paketin üç açık güvenlik kaydı sürüm notlarında
  yazılır.
- **Kısıt dosyası** · 2026-10-11 · CI'ın kısıt dosyası yalnız dolaylı
  paketleri tutar.
- **Kısıt dosyasının bakımı** · 2026-10-12 · Toptan tazeleme her sürümden
  önce ve ihtiyaç olduğunda yapılır; tek paket için `--upgrade-package`.
  Kurulum düşerse güvenlik kapısı ve eşitlik denetimi atlanır. Bir Dependabot
  PR'ı kırmızıysa düzeltme kendi PR'ımızla gelir. Hash kilidi Faz 7'nin v1.1
  değerlendirmesine bırakıldı.

### 6D-7 — gizli bilgi ve e-posta denetimi

6D-7a #62, 6D-7b #64.

- **K1(a)** · 2026-10-16 · İş iki PR'a bölünür.
- **K2(a)** · 2026-10-16 · Commit e-postası bekçisi GitHub'ın genel noreply
  desenini kabul eder.
- **K3(a)** · 2026-10-18 · gitleaks sabit sürümlü ikili olarak kurulur.
- **K4(a)** · 2026-10-16 · Denetimler ayrı bir iş akışında,
  `commit-checks.yml`.
- **K5(a)** · 2026-10-16 · Hesaplanamayan commit aralığı kırmızıdır.
- **K7(a)** · 2026-10-18 · Yanlış alarmlar için yalnız dar istisna.
- **K8(a)** · 2026-10-16 · Bir bekçinin kırmızısı önce yerelde kanıtlanır.
- **K6(a)** · 2026-11-05 · `main` için kural seti: yalnız PR ile
  birleştirme, üç zorunlu kontrol, force push ve silme engelli. Yönetici
  bypass'ı yalnız acil durumda kullanılır ve gerekçesi PR'a yazılır.

## Güvenlik

- **K-G1(a)** · 2026-10-23 · Güvenlik açıkları kendi PR'ımızla, hedefli bir
  tazelemeyle kapatılır. #65, #71, #81.
- **K-G2(a)** · 2026-10-23 · Güvenlik düzeltmesinde genç sürüm istisnası dört
  şartın hepsiyle geçerli: kayıt CRITICAL ya da HIGH; alınan sürüm yank'li
  değil ve bilinen açığı yok; üst paket o sürüme izin veriyor; tam CI yeşil.
  Alınan sürüm açığı kapatan EN KÜÇÜK sürümdür. *Not:* yaş eşiği yazılı değil;
  uygulanan emsal 14 gün (oauthlib #71, opentelemetry-api #81).
- **K-G3(a)** · 2026-10-23 · Bir PR'ı yeni `main`'e göre yeniden koşturmak
  için kendi PR'ımız kapatılıp açılır, Dependabot PR'ında "@dependabot
  rebase" yazılır. "Re-run" eski ref'i kullanır.
- **K-G4(a)** · 2026-10-23 · Dependabot'un açtığı PR'a dokunulmaz.

## Ortam

- **K-V** · 2026-11-05 · Bağımlılık değiştiren her merge'ün doğrulamasında
  depodaki `.venv` kontrollü tazelenir: önce yedek `freeze`, sonra CI'ın iki
  kurulum komutu; pip ve setuptools yükseltilmez; artık gerekmeyen bir paket
  yalnız kullanıcı onayıyla kaldırılır; sonra ölçümler.

## Süreç

- 2026-10-12 · Commit geçmişi yeniden yazılmaz. Kişisel e-posta adresi hiçbir
  yere yazılmaz.
- **Orantılılık** · 2026-11-09 · Tören riske göre ölçeklenir. CI'ı yeşil
  Dependabot yama/minör PR'ları ve yalnız belge PR'ları hafif süreçtir.
  Davranışı ya da CI'ı değiştiren işler tam süreçtir. Yalnız test ekleyen
  PR'lar hafif süreçtir, ama her yeni test için mutasyon denetimi zorunludur.
- **Kalıcı kural** · 2026-11-13 · `api.py`'deki herhangi bir HTTP ucunun yanıt
  kodu ya da gövdesi değişecekse iş durur, kullanıcı karar verir.
- **Yerel ölçüm düzeni (a)** · 2026-11-18 · Her PR'ın ilk adımı, merge'ü
  doğrulanmış önceki PR'ın ölçüm klasörünü arşivler ve siler. Kanıt dosyaları
  arşive gider; klon, sanal ortam, sandbox ve ölçüm taban dizinleri gitmez.
  Kopya SHA-256 ile doğrulanır; silmede joker kullanılmaz.
- **3a** · 2026-11-22 · Kararlar tek bir belge PR'ıyla depoya yazılır: sahip
  kayıtları, bayat cümleler ve bu dosya.

## 6E

- **K-E3(a)** · 2026-11-11 · Bir kusur önce `xfail(strict=True)` testi ve
  KNOWN-DEBT kaydıyla belgelenir, düzeltmesi ayrı PR'da gelir.
- **K-E4(a)** · 2026-11-11 · `.env`'e yazan beş çağrı yeri `call()` hata
  sınırından geçer. #75.
- **K-E5(a)** · 2026-11-11 · JiraClient testleri 6E-2'de yazılır; öteki küçük
  test boşlukları KNOWN-DEBT'te sahipli kalır. #74.
- **K-E7(a)** · 2026-11-11 · 6E-2 küçük PR'larla yapılır.
- **K-E8(a)** · 2026-11-09 · Bir kutu yalnız kanıtla işaretlenir.
- **K-E9(a)** · 2026-11-09 · Sahip kuralı: test ve doğrulama → 6E;
  temizlik, belge ve kurulum → Faz 7; yeni yetenek ya da büyük bağımlılık →
  v1.1. Kurala uymayanlar ("tartışmalı") kullanıcıya sorulur.
- **K-E10(a)** · 2026-11-09 · Eski kalıntılar temizlendi.
- **K-E11(a)** · 2026-11-09 · "6E başladı" tarihi, 6E-1'in ilk commit'idir.
  #72.
- **T1(a), T2(a)** · 2026-11-11 · Çok anahtarlı ayar kaydı bütün olarak
  tutarlı kalır ve sır gölgelenmesi düzeltilir (T1); `ensure_api_key`
  `OSError`'da "yalnız bu oturum" uyarısı verir (T2). 6E-2 PR6, #82.

### Tartışmalı kayıtların sahipleri — 2026-11-10

- **Faz 7:** `dra --version`; risk rengi; issue şablonları;
  `calculate_risk_score`'un kullanılmayan `module_name` parametresi.
- **6E:** başarısız sonuç yazımının gösterilmemesi; `calculate_risk_for_query`'nin
  sıfır-skor guard'ı; `_days_since`'in naive saati.
- **v1.1:** istisna metinlerinin çevrilmemesi; kör nokta tazelik penceresi;
  `/blind-spots` `params`'ının ayrımlı birliği; `classify_bugs` kalıcılığı.
- **Açık soru Q-A'ya bağlı:** iki sürecin aynı ChromaDB dizinini paylaşması.
- **tests/tools** · 2026-11-11 · Kapsam ölçümünde %0 görünen
  `tests/tools/` araçları **Faz 7** (denetleyici; kullanıcının 2026-10-11
  "geliştirici araçlarının kusurları Faz 7" kararının uygulanması).

### 6E-2'nin kalanı — 2026-11-22

- **1a** · 2026-11-22 · KNOWN-DEBT'teki dört test boşluğu (`api.py`'nin kalan
  HTTP testleri, `results_repository`, `ui/results.py`, `cli.py`) ve başarısız
  sonuç yazımının gösterilmemesi 6E-2'de yapılır. 6E-2 bunlar bitince kapanır.
- **2a** · 2026-11-22 · Sıfır-skor guard'ı ve `_days_since`'in naive saati
  6E-3a'da (6E planının "deterministik doğruluk" alt fazı) yapılır.
- **(a)** · 2026-11-22 · Kalan iş dört PR'da, bu sırayla: `results_repository`
  testleri + başarısız yazımın xfail'i; düzeltmesi; `ui/results.py` + `cli.py`
  testleri; `api.py`'nin kalan HTTP testleri.

## Sınıflandırıcı

- **Kural E** · 2026-11-11 · Anahtar tam kelime olarak eşleşir, ardından en
  çok bir ek gelebilir; Türkçe İ/I/ı katlanır; bileşenler arası çakışmada
  uzun eşleşme kazanır; aynı anahtar bir kez sayılır. 6E-2 PR4, #76.
- **Kalıcı kabul ölçütü** · 2026-11-12 · Eski kuralın (`27e45db`) doğru
  bulduğu hiçbir girdi yanlışa dönmez; PR4'ün gerilemesi v1.1'e bırakılmaz.
  #77, #78.
- 2026-11-13 · "ödemeli" ve "slowly" anlam çakışmaları bilinen sınırdır
  (v1.1). Gerileme olmayan biçimler (şifrelen-, tıkla-, doğrula-, hatırlat-,
  "Önbelleğe", "Hesabım kilitlendi") v1.1. #78.

## 6E-2 PR'ları

- **PR5** · 2026-11-13 · #80.
  - K1/K2(a): sayfa hatasında eski veri korunur ve kullanıcıya mesaj
    gösterilir.
  - K3(a): 10.000 kayıt tavanı en küçük biçimde bildirilir; yapılandırılabilir
    sınır yok.
  - K4(a): `OSError` `call()`'a iletilir.
  - `bugs.json` atomik yazılır.
  - A(a): `/refresh` hatada 500 döner, kesik çekimde `"truncated"` alanı
    taşır.
  - B(a): kesik çekim metni JQL tavsiyesi içermez.
  - `.gitignore`'a `data/*.tmp`.
- 2026-11-16 · opentelemetry-api 1.45.2'ye yükseltildi
  (CVE-2026-126360), K-G1 ile. #81.
- 2026-11-17:
  - `/refresh`'in 500 `detail`'i sabit metin. 6E-2 PR6, #82.
  - `api.py`'nin genel 500 dalları ve `LLMError` sabit metin. 6E-2 PR7, #83.
  - Y1 ve Y2 (sır deposu) 6E'de. 6E-2 PR8, #84.
  - `/analyze`'ın 4xx dalları ve webhook'un 429'u v1.1.
  - Gruplama: PR7 kullanıcı mesajları, PR8 sır deposu.
- 2026-11-18:
  - `SECURITY.md`'nin cümlesi PR9'da düzeltilir. #85.
  - Okunamayan depo PR10'da. #86.
  - PR10'un yan bulguları: API key 6E'de (PR11, #87); kurulum sihirbazı,
    durum satırları ve geri koyma sınırı v1.1.
  - PR11: okunamayan depoda sunucu yeni anahtar üretmez ve hiçbir şey yazmaz;
    kimlik doğrulamalı uçlar 503 döner (yeni metin yalnız okunamayan
    durumda); Ayarlar'da üretim onayla yapılır ve düz metin uyarısı
    gösterilir. #87.
- 2026-11-17 · T1'in bilinen sınırı (depo ile `.env` arasında ortak işlem yok)
  v1.1. K-E9 uygulaması (denetleyici).

## Faz 7 ve sonrası

- 2026-10-11 · Sıra: 6E → Faz 7 → v1.1.
- 2026-10-11 · Türkçe dosya adları İngilizceye çevrilir (`BASLAT.bat` →
  `START.bat` vb.), Faz 7'de.
- 2026-10-11 · Geliştirici araçlarının kusurları Faz 7'de.
- 2026-10-11 · Claude'un LLM sağlayıcısı olarak eklenmesi v1.1.
- 2026-11-22 · "Could not store … falling back to .env." `WARNING`'i, depo
  yazmayı kabul edip geri okuyamadığında yanıltıcı; Faz 7 (temizlik). K-E9
  uygulaması, denetleyici.

## Açık sorular

Karar bekliyor. Kullanıcı karar verince madde yukarıdaki ilgili başlığa
taşınır.

- **Q-A (K-E1)** · "5. Ölçek ve dayanıklılık" başlığı doğrulama sorularına
  eklensin mi? 6E-3e ve iki sürecin aynı ChromaDB dizinini paylaşması buna
  bağlı.
- **Q-B (K-E2)** · Altın veri seti (6E-4). Keşifteki öneri: sentetik,
  yaklaşık 80 kayıt. Karar bekliyor.
- **K-E6** · Gerçek API ölçümü, kullanıcının yerelinde (yaklaşık 15 çağrı).
- **K-E6b** · Ağ envanterinin yöntemi.
- **Faz 7** · 7a/7b bölünmesi.
- **Proje sonu** · `LICENSE` ve `pyproject.toml`'daki ad.
