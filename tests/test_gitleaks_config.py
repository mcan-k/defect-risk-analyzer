"""
`.gitleaks.toml`: gizli bilgi taramasının yapılandırması.

İDDİA (Faz 6D-7b). Tarama gitleaks'in varsayılan kurallarıyla koşar; 6D-7
keşfinin geçmişte bulduğu üç yanlış alarm (2026-10-16) iki dar izin listesiyle
susturulur (kullanıcı kararı K7, 2026-10-18). "Dar"ın üç parçası da tutulur:

  * `test_default_rules_and_two_targeted_allowlists` — `[extend] useDefault =
    true`; kendi kuralı yok, eski biçim tekil `[allowlist]` yok; tam iki
    `[[allowlists]]`, biri yalnız `generic-api-key`'i, öteki yalnız
    `curl-auth-header`'ı hedefliyor. Hedefe üçüncü bir kural eklenirse ya da
    varsayılan kurallar kapanırsa kırmızı.
  * `test_every_allowlist_needs_rule_path_and_shape` — her izin listesinde
    hedef kural, yol ve değerin biçimi (regex) var, ve `condition = "AND"`:
    üçü birden tutmadıkça bulgu susmaz. gitleaks'in varsayılanı "OR"; onunla
    yalnız yol bütün dosyayı, yalnız biçim bütün depoyu susturur (yerelde
    ölçüldü, 2026-10-18: aynı iki sahte değer OR'la 0, AND'le 2 bulgu). Yalnız
    `paths` taşıyan bir izin listesi — bir dizini sessizce kör eden biçim —
    kırmızı.

Regex'lerin kendisi burada test edilmiyor; onların üç yanlış alarmı tam
susturduğunu ve başka bir şeyi susturmadığını gitleaks'in kendisiyle yapılan
yerel ölçüm gösteriyor (PR gövdesi). Bu dosya, ölçülen biçimin bir düzenlemeyle
sessizce gevşemesini tutar.

Ağsız, alt süreçsiz; yalnız `tomllib` (standart kütüphane) ile okur.
"""

import tomllib
from pathlib import Path

# The repo, not the config sandbox — same reason as tests/test_workflow_runners.py.
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".gitleaks.toml"

TARGETS = [("curl-auth-header",), ("generic-api-key",)]
ALLOWED_KEYS = {"description", "targetRules", "condition", "paths", "regexTarget", "regexes"}


def _config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_default_rules_and_two_targeted_allowlists():
    config = _config()
    assert config.get("extend") == {"useDefault": True}, (
        "Varsayilan kurallar acik olmali: `[extend] useDefault = true`."
    )
    assert "rules" not in config, "Yapilandirma kendi kuralini tanimliyor."
    assert "allowlist" not in config, (
        "Eski bicim tekil `[allowlist]` var: hedef kurali yok, butun kurallari susturur."
    )
    targets = sorted(tuple(item.get("targetRules", ())) for item in config.get("allowlists", []))
    assert targets == TARGETS, (
        f"Izin listeleri {TARGETS} disinda bir kurali hedefliyor ya da sayisi degismis: {targets}"
    )


def test_every_allowlist_needs_rule_path_and_shape():
    allowlists = _config().get("allowlists", [])
    assert allowlists, "Hic `[[allowlists]]` yok; test bosuna gecerdi."
    for number, item in enumerate(allowlists, start=1):
        assert set(item) <= ALLOWED_KEYS, (
            f"{number}. izin listesinde beklenmeyen anahtar: {sorted(set(item) - ALLOWED_KEYS)}"
        )
        assert item.get("condition") == "AND", (
            f"{number}. izin listesinde `condition = \"AND\"` yok. Varsayilan OR: yol tek "
            "basina butun dosyayi, bicim tek basina butun depoyu susturur."
        )
        for key in ("targetRules", "paths", "regexes"):
            assert item.get(key), (
                f"{number}. izin listesinde `{key}` yok ya da bos: kural + yol + bicim "
                "uclusu eksik."
            )
        assert item.get("regexTarget") in {"secret", "line"}, (
            f"{number}. izin listesinin `regexTarget`'i tanimsiz: {item.get('regexTarget')!r}"
        )
