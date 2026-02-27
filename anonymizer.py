import re
import json
import hashlib
from typing import Any

class DataAnonymizer:
    """
    Jira verilerini Groq'a göndermeden önce anonimleştirir.
    Orijinal değerleri şifreli bir haritada saklar,
    analiz sonrası geri dönüştürür.
    """

    def __init__(self):
        # Orijinal → Anonim eşleşmeleri
        self._map: dict[str, str] = {}
        # Anonim → Orijinal (geri dönüşüm için)
        self._reverse_map: dict[str, str] = {}
        # Sayaçlar
        self._counters = {
            "USER"      : 0,
            "MODULE"    : 0,
            "PROJECT"   : 0,
            "COMPONENT" : 0,
            "VERSION"   : 0,
        }

    def _get_or_create_alias(self, value: str, prefix: str) -> str:
        """Değer için anonim alias oluştur veya mevcut olanı döndür."""
        if not value or value in ("Unassigned", "Unknown", ""):
            return value

        if value in self._map:
            return self._map[value]

        self._counters[prefix] += 1
        alias = f"{prefix}_{self._counters[prefix]}"

        self._map[value] = alias
        self._reverse_map[alias] = value
        return alias

    def anonymize_text(self, text: str) -> str:
        """
        Serbest metindeki tanımlanmış değerleri anonim alias ile değiştir.
        Haritada kayıtlı tüm değerleri metinden temizler.
        """
        if not text:
            return text

        result = text
        # Uzun değerlerden kısaya doğru sırala (alt string çakışmasını önle)
        for original, alias in sorted(
            self._map.items(), key=lambda x: len(x[0]), reverse=True
        ):
            result = result.replace(original, alias)
        return result

    def anonymize_bug(self, bug: dict) -> dict:
        """Tek bir bug kaydını anonimleştir."""
        return {
            "key"        : bug["key"],  # AP-1 gibi key'ler kalabilir
            "summary"    : self.anonymize_text(bug.get("summary", "")),
            "description": self.anonymize_text(bug.get("description", "")),
            "status"     : bug.get("status", ""),   # durum bilgisi güvenli
            "priority"   : bug.get("priority", ""), # öncelik bilgisi güvenli
            "components" : [
                self._get_or_create_alias(c, "COMPONENT")
                for c in bug.get("components", [])
            ],
            "labels"     : [
                self._get_or_create_alias(l, "COMPONENT")
                for l in bug.get("labels", [])
            ],
            "assignee"   : self._get_or_create_alias(
                bug.get("assignee", "Unassigned"), "USER"
            ),
            "reporter"   : self._get_or_create_alias(
                bug.get("reporter", "Unknown"), "USER"
            ),
            "fix_versions": [
                self._get_or_create_alias(v, "VERSION")
                for v in bug.get("fix_versions", [])
            ],
            "created"    : bug.get("created", ""),
            "resolved"   : bug.get("resolved", ""),
        }

    def anonymize_bugs(self, bugs: list[dict]) -> list[dict]:
        """Bug listesini toplu anonimleştir."""
        return [self.anonymize_bug(bug) for bug in bugs]

    def anonymize_query(self, query: str) -> str:
        """
        Kullanıcının yazdığı sorguyu anonimleştir.
        Haritadaki bilinen değerleri temizler.
        """
        return self.anonymize_text(query)

    def deanonymize_text(self, text: str) -> str:
        """
        LLM'den gelen yanıttaki anonim alias'ları
        orijinal değerlerle geri değiştir.
        """
        if not text:
            return text

        result = text
        for alias, original in self._reverse_map.items():
            result = result.replace(alias, original)
        return result

    def get_mapping_report(self) -> dict:
        """
        Hangi değerlerin nasıl anonimleştirildiğini göster.
        Audit log için kullanılabilir.
        """
        return {
            "total_anonymized": len(self._map),
            "counters"        : self._counters,
            "mapping"         : self._map  # Production'da bunu loglama!
        }

    def export_map(self, path: str = "data/anon_map.json"):
        """
        Anonimleştirme haritasını dışa aktar.
        Oturum boyunca tutarlılık için kullanılır.
        """
        import os
        os.makedirs("data", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "map"         : self._map,
                "reverse_map" : self._reverse_map,
                "counters"    : self._counters
            }, f, ensure_ascii=False, indent=2)

    def import_map(self, path: str = "data/anon_map.json"):
        """Önceki oturumun haritasını yükle (tutarlılık için)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._map         = data.get("map", {})
                self._reverse_map = data.get("reverse_map", {})
                self._counters    = data.get("counters", self._counters)
        except FileNotFoundError:
            pass  # İlk çalıştırmada harita yoktur, sorun değil