import os
import json
import time
from groq import Groq
import os
import json
from groq import Groq
from dotenv import load_dotenv
from anonymizer import DataAnonymizer
from collections import Counter

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ── 1. BUG BAZLI TEST SENARYOSU ÜRET ─────────────────────────────
def generate_test_scenario_for_bug(bug: dict, client: Groq) -> dict:
    prompt = f"""
Aşağıdaki Jira bug kaydını incele. Bu bug'ı yakalamak için hangi test senaryosu yazılmalıydı?

Bug Key   : {bug['key']}
Özet      : {bug['summary']}
Açıklama  : {bug['description']}
Öncelik   : {bug['priority']}
Durum     : {bug['status']}

Aşağıdaki formatta yanıt ver:

ALAN: [Bu bug'ın ait olduğu modül veya alan, örn: Fizik Motoru, İnşaat Sistemi]
TEST_SENARYOSU: [Bu bug'ı yakalayacak test senaryosunun adı]
TEST_ADIMLARI:
- [Adım 1]
- [Adım 2]
- [Adım 3]
BEKLENEN_SONUC: [Test başarılı olsaydı ne görmek gerekirdi]
RISK_ALANI: [Bu alanda gelecekte hata çıkma ihtimali yüksek mi? Evet/Hayır ve kısa gerekçe]

Türkçe yanıt ver.
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )

    raw = response.choices[0].message.content

    # Parse et
    result = {
        "bug_key"        : bug["key"],
        "bug_summary"    : bug["summary"],
        "bug_priority"   : bug["priority"],
        "alan"           : "",
        "test_senaryosu" : "",
        "test_adimlari"  : [],
        "beklenen_sonuc" : "",
        "risk_alani"     : ""
    }

    lines = raw.strip().split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        if line.startswith("ALAN:"):
            result["alan"] = line.replace("ALAN:", "").strip()
        elif line.startswith("TEST_SENARYOSU:"):
            result["test_senaryosu"] = line.replace("TEST_SENARYOSU:", "").strip()
        elif line.startswith("TEST_ADIMLARI:"):
            current_section = "adimlar"
        elif line.startswith("BEKLENEN_SONUC:"):
            result["beklenen_sonuc"] = line.replace("BEKLENEN_SONUC:", "").strip()
            current_section = None
        elif line.startswith("RISK_ALANI:"):
            result["risk_alani"] = line.replace("RISK_ALANI:", "").strip()
            current_section = None
        elif line.startswith("- ") and current_section == "adimlar":
            result["test_adimlari"].append(line[2:])

    return result

# ── 2. ALAN BAZLI HATA YOĞUNLUĞU ─────────────────────────────────
def analyze_defect_density(test_history: list) -> dict:
    alan_counter = Counter()
    priority_by_alan = {}
    bugs_by_alan = {}

    for item in test_history:
        alan = item.get("alan", "Bilinmiyor")
        if not alan:
            alan = "Bilinmiyor"

        alan_counter[alan] += 1

        if alan not in priority_by_alan:
            priority_by_alan[alan] = []
            bugs_by_alan[alan] = []

        priority_by_alan[alan].append(item["bug_priority"])
        bugs_by_alan[alan].append(item["bug_key"])

    # Risk skoru hesapla (bug sayısı + öncelik ağırlığı)
    priority_weights = {
        "Highest": 5, "Critical": 5,
        "High": 4,
        "Medium": 3,
        "Low": 2, "Lowest": 1
    }

    risk_scores = {}
    for alan, count in alan_counter.items():
        weight_sum = sum(
            priority_weights.get(p, 3)
            for p in priority_by_alan[alan]
        )
        risk_scores[alan] = {
            "bug_sayisi"  : count,
            "risk_skoru"  : weight_sum,
            "bug_keys"    : bugs_by_alan[alan],
            "oncelikler"  : priority_by_alan[alan]
        }

    # Risk skoruna göre sırala
    sorted_risks = dict(
        sorted(risk_scores.items(), key=lambda x: x[1]["risk_skoru"], reverse=True)
    )

    return sorted_risks

# ── 3. RAPORU KAYDET ──────────────────────────────────────────────
def save_test_history(test_history: list, density: dict):
    os.makedirs("data", exist_ok=True)

    with open("data/test_history.json", "w", encoding="utf-8") as f:
        json.dump(test_history, f, ensure_ascii=False, indent=2)

    with open("data/defect_density.json", "w", encoding="utf-8") as f:
        json.dump(density, f, ensure_ascii=False, indent=2)

    print("\nVeri kaydedildi: data/test_history.json")
    print("Veri kaydedildi: data/defect_density.json")

# ── 4. MAIN ───────────────────────────────────────────────────────
def main():
    print("Test Gecmisi Analizi Basliyor...\n")

    with open("data/bugs.json", "r", encoding="utf-8") as f:
        bugs = json.load(f)

    anonymizer = DataAnonymizer()
    anonymizer.import_map()

    client = Groq(api_key=GROQ_API_KEY)
    test_history = []

    print(f"Toplam {len(bugs)} bug icin test senaryosu uretiliyor...\n")

    for i, bug in enumerate(bugs, 1):
        print(f"[{i}/{len(bugs)}] {bug['key']} isleniyor...")

        anon_bug = anonymizer.anonymize_bug(bug)
        result   = generate_test_scenario_for_bug(anon_bug, client)

        # Orijinal key'i geri koy
        result["bug_key"]     = bug["key"]
        result["bug_summary"] = anonymizer.deanonymize_text(result["bug_summary"])
        result["alan"]        = anonymizer.deanonymize_text(result["alan"])

        test_history.append(result)
        print(f"   Alan    : {result['alan']}")
        print(f"   Senaryo : {result['test_senaryosu']}")
        print()
        time.sleep(2)  # Groq rate limit için 2 saniye bekle

    # Alan bazlı yoğunluk analizi
    print("\n=== ALAN BAZLI HATA YOGUNLUGU ===")
    density = analyze_defect_density(test_history)

    for alan, data in density.items():
        print(f"\n  Alan       : {alan}")
        print(f"  Bug Sayisi : {data['bug_sayisi']}")
        print(f"  Risk Skoru : {data['risk_skoru']}")
        print(f"  Buglar     : {', '.join(data['bug_keys'])}")

    save_test_history(test_history, density)
    anonymizer.export_map()

    print("\nAnaliz tamamlandi!")

if __name__ == "__main__":
    main()