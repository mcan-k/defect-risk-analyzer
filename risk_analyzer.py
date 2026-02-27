import os
import json
import chromadb
from groq import Groq
from dotenv import load_dotenv
from anonymizer import DataAnonymizer

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ── 1. CHROMADB KURULUM ───────────────────────────────────────────
def setup_chromadb():
    client = chromadb.PersistentClient(path="./data/chroma_db")
    collection = client.get_or_create_collection(
        name="jira_bugs",
        metadata={"hnsw:space": "cosine"}
    )
    return collection

# ── 2. BUGLARI CHROMADB'YE YÜKLE ─────────────────────────────────
def load_bugs_to_chromadb(collection, anonymizer: DataAnonymizer):
    with open("data/bugs.json", "r", encoding="utf-8") as f:
        bugs = json.load(f)

    existing = collection.get()
    existing_ids = set(existing["ids"])
    new_bugs = [b for b in bugs if b["key"] not in existing_ids]

    if not new_bugs:
        print("✅ Tüm buglar zaten ChromaDB'de mevcut.")
        return bugs

    # Anonimleştir
    anon_bugs = anonymizer.anonymize_bugs(new_bugs)

    documents = []
    metadatas = []
    ids = []

    for bug in anon_bugs:
        doc_text = f"""
        Bug: {bug['key']}
        Özet: {bug['summary']}
        Açıklama: {bug['description']}
        Öncelik: {bug['priority']}
        Durum: {bug['status']}
        Bileşenler: {', '.join(bug['components']) if bug['components'] else 'Belirtilmemiş'}
        """.strip()

        documents.append(doc_text)
        metadatas.append({
            "key"      : bug["key"],
            "priority" : bug["priority"],
            "status"   : bug["status"],
            "assignee" : bug["assignee"],
            "created"  : bug["created"],
        })
        ids.append(bug["key"])

    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    print(f"✅ {len(new_bugs)} bug anonimleştirilerek ChromaDB'ye yüklendi.")
    return bugs

# ── 3. BENZER BUGLARI GETİR ───────────────────────────────────────
def find_similar_bugs(collection, query: str, n_results: int = 3):
    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, collection.count())
    )

    similar = []
    for i, doc in enumerate(results["documents"][0]):
        similar.append({
            "document" : doc,
            "metadata" : results["metadatas"][0][i],
            "distance" : results["distances"][0][i]
        })
    return similar

# ── 4. GROQ İLE RİSK ANALİZİ ─────────────────────────────────────
def analyze_risk(query: str, similar_bugs: list, anonymizer: DataAnonymizer) -> dict:
    client = Groq(api_key=GROQ_API_KEY)

    # Sorguyu da anonimleştir
    anon_query = anonymizer.anonymize_query(query)

    context = "\n\n".join([
        f"[{b['metadata']['key']}] Öncelik: {b['metadata']['priority']}\n{b['document']}"
        for b in similar_bugs
    ])

    prompt = f"""
Sen bir kıdemli QA Mühendisisin. Geçmiş Jira bug kayıtlarını analiz ederek yeni değişiklikler için risk tahmini yapıyorsun.

=== GEÇMİŞ BENZER BUGLAR ===
{context}

=== ANALİZ EDİLECEK ALAN/DEĞİŞİKLİK ===
{anon_query}

Aşağıdaki formatta yanıt ver:

RİSK_SKORU: [0-100 arası sayı]
RİSK_SEVİYESİ: [Düşük / Orta / Yüksek / Kritik]
NEDEN: [2-3 cümle açıklama]
TEST_SENARYOLARI:
- [Senaryo 1]
- [Senaryo 2]
- [Senaryo 3]
MODÜLLER:
- [Modül 1]
- [Modül 2]
- [Modül 3]
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )

    # Groq'tan gelen yanıtı geri dönüştür
    raw_result = response.choices[0].message.content
    restored_result = anonymizer.deanonymize_text(raw_result)

    return {
        "query"    : query,
        "analysis" : restored_result,
        "sources"  : [b["metadata"]["key"] for b in similar_bugs]
    }

# ── 5. MAIN ───────────────────────────────────────────────────────
def main():
    print("🚀 Risk Analiz Sistemi Başlatılıyor...\n")

    anonymizer = DataAnonymizer()
    anonymizer.import_map()  # Önceki oturumun haritasını yükle

    collection = setup_chromadb()
    load_bugs_to_chromadb(collection, anonymizer)

    anonymizer.export_map()  # Haritayı kaydet

    print(f"\n📦 ChromaDB'deki toplam kayıt: {collection.count()}\n")
    print("=" * 60)

    test_queries = [
        "İnşaat sistemi ve duvar mekanikleri değiştirildi",
        "Karakter ölüm ve yeniden doğma sistemi güncellendi",
        "Hasar hesaplama ve hitbox sistemi refactor edildi"
    ]

    for query in test_queries:
        print(f"\n🔍 Analiz: {query}")
        print("-" * 60)

        similar = find_similar_bugs(collection, query, n_results=3)
        result  = analyze_risk(query, similar, anonymizer)

        print(f"📎 Kaynak buglar: {', '.join(result['sources'])}")
        print(f"\n{result['analysis']}")
        print("=" * 60)

    # Anonimleştirme raporu
    report = anonymizer.get_mapping_report()
    print(f"\n🔒 Anonimleştirilen toplam değer: {report['total_anonymized']}")

if __name__ == "__main__":
    main()