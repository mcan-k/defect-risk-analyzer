<!--
Bu depoda içeriği commit gövdesi taşıyor: hangi iddia kuruldu, nasıl ölçüldü.
Şablon onu ikinci kez yazdırmıyor — gövdeyi yapıştır, kapanış alanlarını doldur.

Ölçüldü: PR #13-#16'nın gövdesi hiç yoktu, #17-#18'inki commit gövdesinin
kopyasıydı. Boş bir gövde, kaydın PR sayfasında kaybolması demek.
-->

## İddia

<!-- Commit gövdesini yapıştır. Bu bölüm "ne değişti" değil, hangi iddia
     kuruldu: diff zaten ne değiştiğini gösteriyor. Birden çok commit varsa
     her birini ayrı ayrı, ve hangisinin tek başına revert edilebildiğini yaz. -->

## Ölçümler

<!-- Ne ölçüldü ve hangi komutla — okuyan kişi tekrarlayabilsin.
     Ölçülemeyen bir şey varsa "ölçülemedi" yazılır, tahmin yazılmaz. -->

## Mutasyonlar

| Mutasyon | Kırılan iddia | Gözlenen |
|---|---|---|

<!-- Hayatta kalan mutasyon bir bulgudur: ölü dal mı, eksik kapsam mı, ve ne
     yapıldı? Mutasyon uygulanmadıysa nedeni yazılır (örn. yalnız belge
     değişikliği). Boş bırakılmaz. -->

## Kapsam dışı bırakılanlar

<!-- Yol üstünde bulunup bu PR'da düzeltilmeyen her şey, ve işareti: bir faz,
     bir sürüm ya da bir tetikleyici. İşaretsiz kalan "unutulmuş" demektir. -->

## Kapanış ölçümleri

- [ ] `pytest` — ... → ...
- [ ] `ruff check .` temiz
- [ ] izole lint bakiyesi artmadı (`--config "lint.per-file-ignores={}"`)
- [ ] `git status` temiz
- [ ] belge değiştiyse satır sonu korundu (CRLF)
