# Katkı rehberi

Bu depoda uygulanan kurallar. Hiçbiri yeni değil — hepsi kodda, testlerde ya da
commit gövdelerinde zaten yazılıydı; burada tek yerde toplanıyor ve nereden
geldikleri gösteriliyor. Tek istisna **mutasyon protokolü**: uygulanıyordu ama
hiçbir yerde yazılı değildi.

---

## Kurulum ve komutlar

[`README.md` → Development](README.md#development). Burada tekrarlanmıyor;
tekrarlanan bir komut ikisinden biri güncellendiğinde yanlış olur.

Streamlit sayfa yürüyüşü paketin yavaş kısmı: `pytest -m "not slow"` onu atlar.

---

## Testler

**Hiçbir test ağa, ChromaDB'ye, Jira'ya, bir LLM API'sine ya da işletim
sisteminin kimlik deposuna dokunmaz.** `tests/conftest.py` bunun dosya sistemi
yarısını zorluyor ve kimlik deposunu tamamen bloke ediyor; gerisini testler
kendi stub'larıyla hallediyor. Sandbox `DRA_BASE_DIR`'i modül düzeyinde
ayarlıyor — bir fixture çok geç kalırdı, çünkü `config` yolları import anında
bir kez çözüyor. Kaynak: `tests/conftest.py` modül docstring'i.

**Bir modül global'ini patch'lemeden önce, üretim yolunun kaçını yazdığına bak
ve hepsini kaydet.** `monkeypatch` yalnız kaydettiğini geri alır. Bu kural iki
kez ihlal edildi ve **iki seferinde de hata başka bir dosyada göründü**:

- `monkeypatch.delenv(key, raising=False)` zaten yok olan bir anahtarda hiçbir
  şey kaydetmedi, `load_dotenv`'in `os.environ`'a yazdığı değerler teardown'ı
  aştı ve Ayarlar sayfasını "oluştur"dan "döndür"e çevirdi.
- `config.secret_store()` dört global atıyor; bir test ikisini patch'ledi,
  kalan ikisi sahte bir backend adını bir sayfa altyazısına sızdırdı.

Sandbox bunu yakalamaz — yollar sandbox içinde kalıyor — ve hata sebep olduğu
yerde patlamıyor. Kaynak: `tests/conftest.py:15-28`.

---

## Mutasyon protokolü

**Bu belgenin asıl katkısı.** Protokol uygulanıyordu; yazılı değildi. Yeni
katılan biri onu ancak test docstring'lerini okuyarak çıkarabilirdi.

Bir test yazıldığında, geçtiği için doğru sayılmaz. Sıra şu:

1. **Test önce yazılır ve kırmızı gözlenir.** Düzeltmeden önce koşturulmayan
   bir test, neyi tuttuğunu değil yalnız bugün patlamadığını söyler.
2. **Düzeltme yapılır, yeşile döner.**
3. **Mutasyon uygulanır**: üretim kodundaki iddianın taşıyıcısı bilerek
   bozulur — bir dal kaldırılır, bir sarmalayıcı çıkarılır, bir sabit
   değiştirilir. Test **kırmızıya dönmeli**.
4. **Mutasyon geri alınır**, dosya kopyasından geri yükleyerek, ve geri yükleme
   `diff` ile doğrulanır. Elle geri yazmak dördüncü bir mutasyon üretir.
5. **`__pycache__` temizlenir.** Bayat bir `.pyc`, geri alınmış bir mutasyonu
   hayatta tutabilir.

**Hayatta kalan bir mutasyon bir bulgudur, susturulmaz.** İki sonuçtan biri
çıkar, ve ikisi de Faz 6B'de gerçekten çıktı:

- **Dal ölüdür** — mutasyon hiçbir testi kırmıyor çünkü kırılacak davranış
  başka bir yerde zaten kapsanıyor. O zaman dal **silinir**, dekorasyon olarak
  tutulmaz. (6B/M14: `store.set()` başarısızlık dalı; geri okuma onu zaten
  kapsıyordu.)
- **Kapsam eksiktir** — mutasyon geçiyor çünkü kimse bakmıyor. O zaman test
  yazılır. (6B/M17: Ayarlar kaydını `.env`'e geri yönlendiren mutasyon **59
  testi geçti**; her kimlik bilgisi düz metne dönebilirdi ve paket yeşil
  kalırdı.)

Uygulanan mutasyonlar ve sonuçları PR gövdesine yazılır — hangi mutasyonun
hangi iddiayı kırdığı ayrı ayrı görünecek şekilde. İki mutasyon aynı testi
kırıyorsa biri gereksizdir; hiçbirini kırmıyorsa test iddiasını taşımıyordur.

---

## Kayıt biçimi

**Her borç bir faz, bir sürüm ya da bir tetikleyici taşır.** Sahipsiz bir borç
bu depoda "unutulmuş" demek olmuştur. Kaynak: `docs/KNOWN-DEBT.md` başlığı —
*"Each entry names the phase that will address it."*

**Karantina girdileri silinmek için konur, büyütülmek için değil.**
`pyproject.toml`'daki `per-file-ignores` girdilerinin her birinin üstünde hangi
fazda kalkacağı yazılı. Yeni bir ihlali susturmak için girdi genişletmek, o
girdinin gerekçesini ortadan kaldırır.

**Gömülü varsayılan yok: görünmeyen bir kural düzeltilemeyen bir kuraldır.**
`module-map.json` kapsamı da eşlemeyi de dosyaya taşıdı ve arkasında yerleşik
bir denylist bırakmadı. Aynısı yeni yapılandırma için de geçerli.

**Ölçülmemiş bir sayı yazılmaz.** Yazılıyorsa nasıl ölçüldüğü de yazılır, ki
okuyan kendisi üretebilsin. Yeniden ölçülemeyen tarihsel bir sayı kaynağıyla
birlikte durur — kaynaksız yazılan doğrulanamaz bir iddiadır.

---

## Commit, dal ve PR

- **Commit başlığı:** `tip(kapsam): özet`. Kullanılan tipler: `feat`, `fix`,
  `test`, `docs`, `refactor`, `chore`.
- **Commit gövdesi içeriği taşır.** Bu depoda gövde; ne değişti değil, **hangi
  iddia kuruldu ve nasıl ölçüldü**. Büyük harfli başlıklar iddiayı adlandırır.
- **Dal:** `fazNX/konu` (örn. `faz6d/belgeler`) ya da `fix/konu`.
- **Parçalar bağımsız revert edilebilir olmalı.** Bir PR birden çok commit
  taşıyorsa, her biri tek başına geri alınabilir olmalı ve gövdesi bunu
  söylemeli.
- **Kapsam genişletilmez.** Yol üstünde bulunan bir kusur kaydedilir ve
  işaretlenir; aynı PR'da düzeltilmez. "Tutarlı olsun diye" yapılan ikinci bir
  düzeltme kapsam genişletmesidir.

---

## Üç pratik kural

**Belge metninde adı geçen her paketleme artefaktı beyanla karşılaştırılır.**
Bir extra, bir requirements dosyası, bir konsol betiği — belgede adı geçiyorsa
`pyproject.toml`'da (ya da hedef dosyada) gerçekten var olduğu doğrulanır.
`tests/test_packaging_extras.py` extra'ları tutuyor; gerisi bu kural.
Gerekçesi ölçüldü: `desktop` extra'sı 23 yerde yazılıydı, hiç beyan
edilmemişti, ve `pip` sağlanmayan bir extra'da hata vermiyor — çıkış 0, tek
satır WARNING, "Successfully installed".

**Depo kökünde çıplak `grep -r` kullanma.** `.venv` ve `.venv-core` birlikte
59.028 dosya taşıyor; kökten özyinelemeli bir arama iki dakikalık zaman aşımına
takılır ve boş çıktı verir — "eşleşme yok" gibi görünen bir zaman aşımı.
`--exclude-dir=.venv --exclude-dir=.git` ver ya da ripgrep kullan.

**`git log`, `git diff`, `git show` için `--no-pager` kullan.** Sayfalayıcı
etkileşimli olmayan bir kabukta çıktıyı boğar ya da bekletir. Yukarıdaki
kuralla aynı sınıf: ölçüm aracının kendi gürültüsü, ölçümün sonucu sanılıyor.
