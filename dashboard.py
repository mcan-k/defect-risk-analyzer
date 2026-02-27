import os
import json
import streamlit as st
import chromadb
from groq import Groq
from dotenv import load_dotenv
from anonymizer import DataAnonymizer

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ── SAYFA AYARLARI ────────────────────────────────────────────────
st.set_page_config(
    page_title="Defect Risk Analyzer",
    page_icon="🐛",
    layout="wide"
)

st.markdown("""
<style>
    .risk-critical { background-color: #ff4b4b; color: white; padding: 10px; border-radius: 8px; }
    .risk-high     { background-color: #ff8c00; color: white; padding: 10px; border-radius: 8px; }
    .risk-medium   { background-color: #ffd700; color: black; padding: 10px; border-radius: 8px; }
    .risk-low      { background-color: #00c851; color: white; padding: 10px; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ── ANONİMİZER ────────────────────────────────────────────────────
@st.cache_resource
def get_anonymizer():
    anon = DataAnonymizer()
    anon.import_map()
    return anon

# ── CHROMADB ──────────────────────────────────────────────────────
@st.cache_resource
def get_collection():
    client = chromadb.PersistentClient(path="./data/chroma_db")
    return client.get_or_create_collection(
        name="jira_bugs",
        metadata={"hnsw:space": "cosine"}
    )

def load_bugs_from_file():
    with open("data/bugs.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_test_history():
    try:
        with open("data/test_history.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def load_defect_density():
    try:
        with open("data/defect_density.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# ── JİRA'DAN YENİLE ───────────────────────────────────────────────
def refresh_from_jira():
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "jira_fetch.py"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    return result.returncode == 0, result.stdout + result.stderr

def sync_to_chromadb(collection, anonymizer):
    bugs = load_bugs_from_file()
    existing_ids = set(collection.get()["ids"])
    new_bugs = [b for b in bugs if b["key"] not in existing_ids]

    if not new_bugs:
        return 0

    anon_bugs = anonymizer.anonymize_bugs(new_bugs)
    documents, metadatas, ids = [], [], []

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
    anonymizer.export_map()
    return len(new_bugs)

# ── BENZER BUG ARAMA ──────────────────────────────────────────────
def find_similar_bugs(collection, query, n_results=3):
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

# ── RİSK ANALİZİ ─────────────────────────────────────────────────
def analyze_risk(query, similar_bugs, anonymizer, density):
    client = Groq(api_key=GROQ_API_KEY)

    anon_query = anonymizer.anonymize_query(query)

    context = "\n\n".join([
        f"[{b['metadata']['key']}] Öncelik: {b['metadata']['priority']}\n{b['document']}"
        for b in similar_bugs
    ])

    # En riskli alanları bağlama ekle
    top_areas = list(density.items())[:3]
    density_context = "\n".join([
        f"- {alan}: {data['bug_sayisi']} bug, Risk Skoru {data['risk_skoru']}"
        for alan, data in top_areas
    ])

    prompt = f"""
Sen bir kıdemli QA Mühendisisin. Geçmiş Jira bug kayıtlarını ve test geçmişini analiz ederek yeni değişiklikler için risk tahmini yapıyorsun.

=== GEÇMİŞ BENZER BUGLAR ===
{context}

=== EN RİSKLİ ALANLAR (Test Geçmişinden) ===
{density_context}

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

    raw_result = response.choices[0].message.content
    return anonymizer.deanonymize_text(raw_result)

# ── PARSE ANALİZ SONUCU ───────────────────────────────────────────
def parse_analysis(text):
    result = {
        "risk_score"    : 0,
        "risk_level"    : "Bilinmiyor",
        "reason"        : "",
        "test_scenarios": [],
        "modules"       : []
    }

    lines = text.strip().split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        if line.startswith("RİSK_SKORU:"):
            try:
                result["risk_score"] = int(line.split(":")[1].strip())
            except:
                result["risk_score"] = 0
        elif line.startswith("RİSK_SEVİYESİ:"):
            result["risk_level"] = line.split(":")[1].strip()
        elif line.startswith("NEDEN:"):
            result["reason"] = line.replace("NEDEN:", "").strip()
            current_section = "reason"
        elif line.startswith("TEST_SENARYOLARI:"):
            current_section = "test"
        elif line.startswith("MODÜLLER:"):
            current_section = "modules"
        elif line.startswith("- ") and current_section == "test":
            result["test_scenarios"].append(line[2:])
        elif line.startswith("- ") and current_section == "modules":
            result["modules"].append(line[2:])
        elif current_section == "reason" and line and not line.startswith("TEST"):
            result["reason"] += " " + line

    return result

# ── RENKLENDİRME ──────────────────────────────────────────────────
def get_score_color(score):
    if score >= 80: return "#ff4b4b"
    if score >= 60: return "#ff8c00"
    if score >= 40: return "#ffd700"
    return "#00c851"

def get_risk_color(level):
    colors = {
        "Kritik" : "#ff4b4b",
        "Yüksek" : "#ff8c00",
        "Orta"   : "#ffd700",
        "Düşük"  : "#00c851"
    }
    return colors.get(level, "#888888")

# ── ANA ARAYÜZ ────────────────────────────────────────────────────
def main():
    st.title("🐛 Defect Risk Analyzer")
    st.markdown("Geçmiş Jira bug verilerini analiz ederek **aksiyon alınabilir risk raporları** üretir.")
    st.caption("🔒 Tüm veriler Groq'a gönderilmeden önce anonimleştirilir.")
    st.divider()

    anonymizer = get_anonymizer()
    collection = get_collection()
    density    = load_defect_density()

    # ── SEKMELER ──────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "🔍 Risk Analizi",
        "📊 Test Geçmişi",
        "⚙️ Proje Yönetimi"
    ])

    # ══════════════════════════════════════════════════════════════
    # SEKME 1 — RİSK ANALİZİ
    # ══════════════════════════════════════════════════════════════
    with tab1:
        col_left, col_right = st.columns([1, 1], gap="large")

        with col_left:
            st.subheader("🔍 Değişiklik Analizi")
            query = st.text_area(
                "Değişikliği veya analiz edilecek alanı yaz:",
                placeholder="Örn: Karakter hareket sistemi yeniden yazıldı...",
                height=120
            )
            n_results   = st.slider("Kaç benzer bug baz alınsın?", 1, 4, 3)
            analyze_btn = st.button("🚀 Analiz Et", use_container_width=True, type="primary")

        with col_right:
            st.subheader("🗺️ En Riskli Alanlar")
            if density:
                for i, (alan, data) in enumerate(list(density.items())[:5], 1):
                    risk = data["risk_skoru"]
                    max_risk = list(density.values())[0]["risk_skoru"]
                    st.progress(
                        risk / max_risk,
                        text=f"{i}. {alan} — {data['bug_sayisi']} bug | Skor: {risk}"
                    )
            else:
                st.info("Test geçmişi henüz oluşturulmadı. 'test_history_generator.py' çalıştır.")

        st.divider()

        if analyze_btn and query.strip():
            with st.spinner("🤖 AI analiz yapıyor..."):
                try:
                    similar    = find_similar_bugs(collection, query, n_results)
                    raw_result = analyze_risk(query, similar, anonymizer, density)
                    parsed     = parse_analysis(raw_result)

                    score      = parsed["risk_score"]
                    level      = parsed["risk_level"]
                    risk_color = get_risk_color(level)

                    st.subheader("📋 Analiz Sonucu")

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Risk Skoru", f"{score}/100")
                    m2.metric("Risk Seviyesi", level)
                    m3.metric("Kaynak Bug Sayısı", len(similar))

                    st.progress(score / 100)

                    st.markdown("### 🧠 Neden Bu Risk?")
                    st.info(parsed["reason"])

                    c1, c2 = st.columns(2)

                    with c1:
                        st.markdown("### 🧪 Test Senaryoları")
                        for i, scenario in enumerate(parsed["test_scenarios"], 1):
                            st.markdown(f"**{i}.** {scenario}")

                    with c2:
                        st.markdown("### 📦 Odaklanılacak Modüller")
                        for module in parsed["modules"]:
                            st.markdown(
                                f'<span style="background-color:{risk_color};color:white;'
                                f'padding:4px 10px;border-radius:12px;margin:3px;'
                                f'display:inline-block">{module}</span>',
                                unsafe_allow_html=True
                            )

                    st.markdown("### 🔗 Baz Alınan Buglar")
                    for bug in similar:
                        meta       = bug["metadata"]
                        similarity = round((1 - bug["distance"]) * 100, 1)
                        with st.expander(f"📌 {meta['key']} — Benzerlik: %{similarity}"):
                            st.markdown(f"**Öncelik:** {meta['priority']}")
                            st.markdown(f"**Durum:** {meta['status']}")
                            st.markdown(f"**Atanan:** {meta['assignee']}")
                            st.text(bug["document"][:300] + "...")

                    st.divider()
                    st.caption("🔒 Bu analiz, kişisel veriler anonimleştirildikten sonra yapılmıştır.")

                except Exception as e:
                    st.error(f"Analiz sırasında hata: {e}")

        elif analyze_btn:
            st.warning("Lütfen analiz edilecek bir değişiklik yaz.")

    # ══════════════════════════════════════════════════════════════
    # SEKME 2 — TEST GEÇMİŞİ
    # ══════════════════════════════════════════════════════════════
    with tab2:
        st.subheader("📊 Alan Bazlı Hata Yoğunluğu")

        test_history = load_test_history()

        if not test_history:
            st.warning("Test geçmişi bulunamadı. Terminal'de 'python test_history_generator.py' çalıştır.")
        else:
            # Özet metrikler
            m1, m2, m3 = st.columns(3)
            m1.metric("Toplam Analiz Edilen Bug", len(test_history))
            m2.metric("Tespit Edilen Alan Sayısı", len(density))
            if density:
                en_riskli = list(density.keys())[0]
                m3.metric("En Riskli Alan", en_riskli)

            st.divider()

            # Alan bazlı tablo
            st.markdown("### 🗺️ Risk Haritası")
            for alan, data in density.items():
                risk      = data["risk_skoru"]
                max_risk  = list(density.values())[0]["risk_skoru"]
                bar_color = get_score_color(risk * 10)

                with st.expander(
                    f"**{alan}** — {data['bug_sayisi']} bug | Risk Skoru: {risk}"
                ):
                    st.progress(risk / max(max_risk, 1))
                    st.markdown(f"**İlgili Buglar:** {', '.join(data['bug_keys'])}")
                    st.markdown(f"**Öncelikler:** {', '.join(data['oncelikler'])}")

                    # Bu alana ait test senaryoları
                    st.markdown("**Test Senaryoları:**")
                    for item in test_history:
                        if item.get("alan") == alan:
                            st.markdown(f"- [{item['bug_key']}] {item['test_senaryosu']}")
                            if item.get("test_adimlari"):
                                for adim in item["test_adimlari"]:
                                    st.markdown(f"  &nbsp;&nbsp;&nbsp;→ {adim}")

            st.divider()

            # Bug bazlı detay tablosu
            st.markdown("### 📋 Bug Bazlı Test Senaryoları")
            for item in test_history:
                with st.expander(f"📌 {item['bug_key']} — {item['bug_summary'][:60]}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Alan:** {item.get('alan', '-')}")
                        st.markdown(f"**Öncelik:** {item.get('bug_priority', '-')}")
                        st.markdown(f"**Test Senaryosu:** {item.get('test_senaryosu', '-')}")
                    with col2:
                        st.markdown(f"**Beklenen Sonuç:** {item.get('beklenen_sonuc', '-')}")
                        st.markdown(f"**Risk Alanı:** {item.get('risk_alani', '-')}")

                    if item.get("test_adimlari"):
                        st.markdown("**Test Adımları:**")
                        for i, adim in enumerate(item["test_adimlari"], 1):
                            st.markdown(f"{i}. {adim}")

    # ══════════════════════════════════════════════════════════════
    # SEKME 3 — PROJE YÖNETİMİ
    # ══════════════════════════════════════════════════════════════
    with tab3:
        st.subheader("⚙️ Proje Yönetimi")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🔄 Veri Güncelleme")

            if st.button("🔄 Jira'dan Yenile", use_container_width=True):
                with st.spinner("Jira'dan veri çekiliyor..."):
                    success, output = refresh_from_jira()
                    if success:
                        added = sync_to_chromadb(collection, anonymizer)
                        st.cache_resource.clear()
                        if added > 0:
                            st.success(f"✅ {added} yeni bug eklendi!")
                        else:
                            st.info("Yeni bug bulunamadı, veriler güncel.")
                    else:
                        st.error("❌ Jira bağlantısı kurulamadı.")
                        with st.expander("🔍 Hata Detayı"):
                            st.code(output)

            st.caption("Jira'ya yeni bug ekledikten sonra buradan güncelle.")

        with col2:
            st.markdown("### 📈 Sistem İstatistikleri")
            try:
                bugs       = load_bugs_from_file()
                anon_rep   = anonymizer.get_mapping_report()

                st.metric("Toplam Bug", len(bugs))
                st.metric("ChromaDB Kayıt", collection.count())
                st.metric("🔒 Anonimleştirilen Değer", anon_rep["total_anonymized"])
                st.metric("Test Geçmişi Kayıt", len(test_history) if 'test_history' in dir() else 0)

                st.markdown("**Öncelik Dağılımı:**")
                priorities = {}
                for bug in bugs:
                    p = bug.get("priority", "Medium")
                    priorities[p] = priorities.get(p, 0) + 1
                for priority, count in sorted(priorities.items()):
                    st.progress(count / len(bugs), text=f"{priority}: {count}")

            except Exception as e:
                st.error(f"Veri yüklenemedi: {e}")

if __name__ == "__main__":
    main()