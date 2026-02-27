"""
PR Risk Analyzer - GitHub Actions icinde calisir.
PR'daki degisiklikleri analiz eder, risk raporu olusturur
ve PR'a yorum olarak yazar.

Kullanim (GitHub Actions icerisinden):
    python pr_analyzer.py

Gerekli environment variables:
    GROQ_API_KEY     - Groq API anahtari
    GITHUB_TOKEN     - GitHub API tokeni (otomatik saglanir)
    PR_NUMBER        - Pull Request numarasi
    PR_TITLE         - Pull Request basligi
    PR_BODY          - Pull Request aciklamasi
    REPO_FULL_NAME   - Repo adi (ornegin: Kartall01/defect-risk-analyzer)
"""

import os
import sys
import json
import time
import requests
import chromadb
from groq import Groq
from anonymizer import DataAnonymizer


# ===================== KONFIGURASYONLAR =====================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PR_NUMBER = os.getenv("PR_NUMBER")
PR_TITLE = os.getenv("PR_TITLE", "")
PR_BODY = os.getenv("PR_BODY", "")
REPO_FULL_NAME = os.getenv("REPO_FULL_NAME", "")
GROQ_SLEEP = 2


# ===================== CHROMADB SETUP =====================

def setup_chromadb():
    """ChromaDB'yi baslat ve buglari yukle."""
    client = chromadb.PersistentClient(path="./data/chroma_db")
    collection = client.get_or_create_collection(
        name="jira_bugs",
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def load_bugs_to_chromadb(collection, anonymizer):
    """bugs.json'daki buglari ChromaDB'ye yukle."""
    bugs_path = "data/bugs.json"
    if not os.path.exists(bugs_path):
        print("[UYARI] bugs.json bulunamadi, analiz sinirli olacak.")
        return []

    with open(bugs_path, "r", encoding="utf-8") as f:
        bugs = json.load(f)

    existing = collection.get()
    existing_ids = set(existing["ids"])
    new_bugs = [b for b in bugs if b["key"] not in existing_ids]

    if not new_bugs:
        print(f"Tum {len(bugs)} bug zaten ChromaDB'de mevcut.")
        return bugs

    anon_bugs = anonymizer.anonymize_bugs(new_bugs)
    documents, metadatas, ids = [], [], []

    for bug in anon_bugs:
        doc_text = f"""
        Bug: {bug['key']}
        Ozet: {bug['summary']}
        Aciklama: {bug['description']}
        Oncelik: {bug['priority']}
        Durum: {bug['status']}
        Bilesenler: {', '.join(bug['components']) if bug['components'] else 'Belirtilmemis'}
        """.strip()

        documents.append(doc_text)
        metadatas.append({
            "key": bug["key"],
            "priority": bug["priority"],
            "status": bug["status"],
            "assignee": bug["assignee"],
            "created": bug["created"],
        })
        ids.append(bug["key"])

    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    print(f"{len(new_bugs)} bug ChromaDB'ye yuklendi.")
    return bugs


# ===================== PR DEGISIKLIKLERI =====================

def get_pr_changed_files():
    """GitHub API uzerinden PR'daki degisen dosyalari ceker."""
    if not GITHUB_TOKEN or not REPO_FULL_NAME or not PR_NUMBER:
        print("[UYARI] GitHub bilgileri eksik, degisen dosyalar alinamadi.")
        return []

    url = f"https://api.github.com/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}/files"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        files = response.json()

        changed = []
        for f in files:
            changed.append({
                "filename": f["filename"],
                "status": f["status"],  # added, modified, removed
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": f.get("patch", "")[:500],  # Ilk 500 karakter
            })
        return changed
    except Exception as e:
        print(f"[HATA] Degisen dosyalar alinamadi: {e}")
        return []


def build_analysis_query(changed_files):
    """PR bilgileri ve degisen dosyalardan analiz sorgusu olusturur."""
    parts = []

    if PR_TITLE:
        parts.append(f"Degisiklik: {PR_TITLE}")

    if PR_BODY:
        # Cok uzun PR aciklamalarini kisalt
        body = PR_BODY[:500] if len(PR_BODY) > 500 else PR_BODY
        parts.append(f"Aciklama: {body}")

    if changed_files:
        file_summary = []
        for f in changed_files:
            status_map = {"added": "eklendi", "modified": "degistirildi", "removed": "silindi"}
            status_tr = status_map.get(f["status"], f["status"])
            file_summary.append(
                f"  - {f['filename']} ({status_tr}, +{f['additions']}/-{f['deletions']})"
            )
        parts.append("Degisen dosyalar:\n" + "\n".join(file_summary))

    if not parts:
        return "Genel kod degisikligi"

    return "\n\n".join(parts)


# ===================== RISK ANALIZI =====================

def find_similar_bugs(collection, query, n_results=3):
    """ChromaDB'den benzer buglari bul."""
    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, count)
    )

    similar = []
    for i, doc in enumerate(results["documents"][0]):
        similar.append({
            "document": doc,
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return similar


def analyze_risk(query, similar_bugs, anonymizer):
    """Groq + LLaMA ile risk analizi yap."""
    client = Groq(api_key=GROQ_API_KEY)
    anon_query = anonymizer.anonymize_query(query)

    context = "\n\n".join([
        f"[{b['metadata']['key']}] Oncelik: {b['metadata']['priority']}\n{b['document']}"
        for b in similar_bugs
    ])

    # defect_density varsa ekle
    density_context = ""
    density_path = "data/defect_density.json"
    if os.path.exists(density_path):
        with open(density_path, "r", encoding="utf-8") as f:
            density = json.load(f)
        top_areas = list(density.items())[:3]
        density_context = "\n\n=== EN RISKLI ALANLAR ===\n" + "\n".join([
            f"- {alan}: {data['bug_sayisi']} bug, Risk Skoru {data['risk_skoru']}"
            for alan, data in top_areas
        ])

    prompt = f"""
Sen bir kidemli QA Muhendisisin. Gecmis Jira bug kayitlarini analiz ederek yeni kod degisiklikleri icin risk tahmini yapiyorsun.

=== GECMIS BENZER BUGLAR ===
{context}
{density_context}

=== ANALIZ EDILECEK DEGISIKLIK (Pull Request) ===
{anon_query}

Asagidaki formatta yanit ver:

RISK_SKORU: [0-100 arasi sayi]
RISK_SEVIYESI: [Dusuk / Orta / Yuksek / Kritik]
NEDEN: [2-3 cumle aciklama]
TEST_SENARYOLARI:
- [Senaryo 1]
- [Senaryo 2]
- [Senaryo 3]
MODULLER:
- [Modul 1]
- [Modul 2]
- [Modul 3]
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw_result = response.choices[0].message.content
    restored = anonymizer.deanonymize_text(raw_result)
    return restored


def parse_analysis(text):
    """LLM ciktisini parse et."""
    result = {
        "risk_score": 0,
        "risk_level": "Bilinmiyor",
        "reason": "",
        "test_scenarios": [],
        "modules": [],
    }

    lines = text.strip().split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        line_upper = line.upper().replace("\u0130", "I").replace("\u00dc", "U").replace("\u00d6", "O")

        if line_upper.startswith("RISK_SKORU:"):
            try:
                result["risk_score"] = int(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                result["risk_score"] = 0
        elif line_upper.startswith("RISK_SEVIYESI:"):
            result["risk_level"] = line.split(":", 1)[1].strip()
        elif line_upper.startswith("NEDEN:"):
            result["reason"] = line.split(":", 1)[1].strip()
            current_section = "reason"
        elif line_upper.startswith("TEST_SENARYOLARI:"):
            current_section = "test"
        elif line_upper.startswith("MODULLER:"):
            current_section = "modules"
        elif line.startswith("- ") and current_section == "test":
            result["test_scenarios"].append(line[2:])
        elif line.startswith("- ") and current_section == "modules":
            result["modules"].append(line[2:])
        elif current_section == "reason" and line and not line_upper.startswith("TEST"):
            result["reason"] += " " + line

    return result


# ===================== PR YORUM =====================

def get_risk_emoji(score):
    """Risk skoruna gore emoji doner."""
    if score >= 80:
        return "RED_CIRCLE"
    elif score >= 60:
        return "ORANGE_CIRCLE"
    elif score >= 40:
        return "YELLOW_CIRCLE"
    return "GREEN_CIRCLE"


def format_pr_comment(parsed, similar_bugs, changed_files):
    """PR yorumu icin Markdown formatinda rapor olusturur."""
    score = parsed["risk_score"]
    level = parsed["risk_level"]
    emoji = get_risk_emoji(score)

    # Risk gostergesi
    bar_filled = score // 5
    bar_empty = 20 - bar_filled
    risk_bar = f"{'#' * bar_filled}{'.' * bar_empty}"

    comment = f"""## :dart: Defect Risk Analysis Report

| Metrik | Deger |
|--------|-------|
| **Risk Skoru** | **{score}/100** |
| **Risk Seviyesi** | :{emoji}: **{level}** |
| **Degisen Dosya** | {len(changed_files)} |
| **Benzer Bug** | {len(similar_bugs)} |

```
[{risk_bar}] {score}%
```

### :mag: Neden Bu Risk?
{parsed["reason"]}

### :test_tube: Onerilen Test Senaryolari
"""

    for i, scenario in enumerate(parsed["test_scenarios"], 1):
        comment += f"{i}. {scenario}\n"

    if parsed["modules"]:
        comment += "\n### :package: Etkilenen Moduller\n"
        for module in parsed["modules"]:
            comment += f"- `{module}`\n"

    if similar_bugs:
        comment += "\n### :link: Benzer Gecmis Buglar\n"
        comment += "| Bug | Oncelik | Benzerlik |\n"
        comment += "|-----|---------|----------|\n"
        for bug in similar_bugs:
            meta = bug["metadata"]
            sim = round((1 - bug["distance"]) * 100, 1)
            comment += f"| {meta['key']} | {meta['priority']} | %{sim} |\n"

    if changed_files:
        comment += "\n### :page_facing_up: Degisen Dosyalar\n"
        comment += "| Dosya | Durum | Degisiklik |\n"
        comment += "|-------|-------|------------|\n"
        for f in changed_files[:10]:  # En fazla 10 dosya goster
            comment += f"| `{f['filename']}` | {f['status']} | +{f['additions']}/-{f['deletions']} |\n"
        if len(changed_files) > 10:
            comment += f"\n*...ve {len(changed_files) - 10} dosya daha.*\n"

    comment += "\n---\n*Bu rapor Defect Risk Analyzer tarafindan otomatik olusturulmustur.*"

    return comment


def post_pr_comment(comment_body):
    """PR'a yorum olarak yazar."""
    if not GITHUB_TOKEN or not REPO_FULL_NAME or not PR_NUMBER:
        print("[UYARI] GitHub bilgileri eksik, yorum yazilamadi.")
        print("\n=== RAPOR (Terminal Ciktisi) ===")
        print(comment_body)
        return False

    url = f"https://api.github.com/repos/{REPO_FULL_NAME}/issues/{PR_NUMBER}/comments"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        response = requests.post(url, headers=headers, json={"body": comment_body})
        response.raise_for_status()
        print(f"PR #{PR_NUMBER} adresine yorum yazildi.")
        return True
    except Exception as e:
        print(f"[HATA] PR yorumu yazilamadi: {e}")
        print("\n=== RAPOR (Terminal Ciktisi) ===")
        print(comment_body)
        return False


# ===================== MAIN =====================

def main():
    print("=" * 60)
    print("  PR Risk Analyzer Baslatiliyor...")
    print(f"  PR #{PR_NUMBER}: {PR_TITLE}")
    print("=" * 60)

    # 1. Anonymizer
    anonymizer = DataAnonymizer()
    anon_map_path = "data/anon_map.json"
    if os.path.exists(anon_map_path):
        anonymizer.import_map()
    print("[OK] Anonymizer hazirlandi.")

    # 2. ChromaDB
    collection = setup_chromadb()
    load_bugs_to_chromadb(collection, anonymizer)
    print(f"[OK] ChromaDB hazir. Kayit: {collection.count()}")

    # 3. Degisen dosyalari al
    changed_files = get_pr_changed_files()
    print(f"[OK] Degisen dosya sayisi: {len(changed_files)}")

    # 4. Analiz sorgusu olustur
    query = build_analysis_query(changed_files)
    print(f"[OK] Analiz sorgusu olusturuldu.")

    # 5. Benzer buglari bul
    similar_bugs = find_similar_bugs(collection, query, n_results=3)
    print(f"[OK] {len(similar_bugs)} benzer bug bulundu.")

    # 6. Risk analizi
    print("[...] Groq ile risk analizi yapiliyor...")
    raw_analysis = analyze_risk(query, similar_bugs, anonymizer)
    time.sleep(GROQ_SLEEP)
    print("[OK] Analiz tamamlandi.")

    # 7. Parse
    parsed = parse_analysis(raw_analysis)
    print(f"[OK] Risk Skoru: {parsed['risk_score']}/100 ({parsed['risk_level']})")

    # 8. PR yorumu olustur ve yaz
    comment = format_pr_comment(parsed, similar_bugs, changed_files)
    post_pr_comment(comment)

    # 9. GitHub Actions output
    # Yuksek riskli PR'larda workflow'u uyari ile bitirebilirsin
    if parsed["risk_score"] >= 80:
        print(f"\n[UYARI] Yuksek risk tespit edildi: {parsed['risk_score']}/100")
        # sys.exit(1)  # Istersen PR'i bloklayabilirsin

    print("\nAnaliz tamamlandi.")


if __name__ == "__main__":
    main()
