"""
Streamlit Dashboard — 5-page UI for the Predictive Defect Analysis Engine.

Pages:
  1. Dashboard    — Risk heatmap, priority distribution, module ranking, alerts
  2. Bug Listesi  — All bugs with filters and search
  3. Canlı Analiz — Single + bulk analysis with progress bar + circuit breaker
  4. Webhook      — Webhook analysis history
  5. Ayarlar      — Self-service configuration panel

All UI text is in Turkish.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
API_BASE = f"http://localhost:{config.API_PORT}"
RISK_COLORS = {
    "CRITICAL": "#DC2626",
    "HIGH": "#F97316",
    "MEDIUM": "#EAB308",
    "LOW": "#22C55E",
}

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Defect Risk Analyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def api_request(method: str, endpoint: str, **kwargs) -> dict | list | None:
    """Make an authenticated API request."""
    url = f"{API_BASE}{endpoint}"
    headers = {"X-API-Key": config.API_KEY}
    try:
        response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"API Hatası ({response.status_code}): {response.json().get('detail', 'Bilinmeyen hata')}")
            return None
    except requests.ConnectionError:
        st.error("⚠️ API sunucusuna bağlanılamıyor. Backend çalıştığından emin olun.")
        return None
    except requests.Timeout:
        st.error("⚠️ API isteği zaman aşımına uğradı.")
        return None


def get_health() -> dict | None:
    """Get API health status (no auth required)."""
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


def save_env_value(key: str, value: str) -> None:
    """Update a single value in the .env file."""
    env_path = config.ENV_FILE
    lines = []

    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Find and replace or append
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break

    if not found:
        lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Also update the running process environment
    os.environ[key] = value


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar():
    """Render sidebar with navigation and status."""
    st.sidebar.title("🔍 Defect Risk Analyzer")

    # Navigation
    page = st.sidebar.radio(
        "Sayfa Seçin",
        ["📊 Dashboard", "🐛 Bug Listesi", "⚡ Canlı Analiz", "🔔 Webhook Sonuçları", "⚙️ Ayarlar"],
        index=0,
    )

    st.sidebar.markdown("---")

    # Health status
    health = get_health()
    if health:
        st.sidebar.success("✅ API Bağlantısı Aktif")
        col1, col2 = st.sidebar.columns(2)
        col1.metric("Yüklü Bug", health.get("bugs_loaded", 0))
        col2.metric("Günlük İstek", f"{health.get('daily_requests_used', 0)}/{health.get('daily_requests_limit', 50)}")

        if health.get("mock_mode"):
            st.sidebar.info("🎭 Mock Data Modu Aktif")
    else:
        st.sidebar.error("❌ API Bağlantısı Yok")

    st.sidebar.markdown("---")

    # Refresh button
    if st.sidebar.button("🔄 Jira'dan Senkronize Et", use_container_width=True):
        with st.spinner("Veriler senkronize ediliyor..."):
            result = api_request("POST", "/refresh")
            if result:
                st.sidebar.success(f"✅ {result.get('bugs_fetched', 0)} bug yüklendi!")
                st.rerun()

    return page


# =============================================================================
# Page 1: Dashboard
# =============================================================================

def page_dashboard():
    """Risk overview dashboard with charts and alerts."""
    st.title("📊 Risk Dashboard")

    risks = api_request("GET", "/risks")
    if not risks:
        st.info("Henüz analiz verisi yok. Önce Jira'dan veri senkronize edin veya mock modu aktifleştirin.")
        return

    module_risks = risks.get("module_risks", {})
    if not module_risks:
        st.info("Modül risk verisi bulunamadı. Önce veri yükleyin.")
        return

    # Top metrics
    total_bugs = risks.get("total_bugs", 0)
    analyzed = risks.get("analyzed_count", 0)
    critical_count = sum(1 for m in module_risks.values() if m.get("level") == "CRITICAL")
    high_count = sum(1 for m in module_risks.values() if m.get("level") == "HIGH")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Toplam Bug", total_bugs)
    col2.metric("Analiz Edilen", analyzed)
    col3.metric("🔴 Kritik Modül", critical_count)
    col4.metric("🟠 Yüksek Risk Modül", high_count)

    # Critical alerts
    critical_modules = [name for name, data in module_risks.items() if data.get("level") == "CRITICAL"]
    if critical_modules:
        st.error(f"⚠️ KRİTİK RİSK: {', '.join(critical_modules)} modüllerinde acil müdahale gerekiyor!")

    st.markdown("---")

    # Charts row
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Modül Risk Haritası")
        df_risk = pd.DataFrame([
            {
                "Modül": name,
                "Risk Skoru": data.get("score", 0),
                "Risk Seviyesi": data.get("level", "LOW"),
                "Bug Sayısı": data.get("bug_count", 0),
            }
            for name, data in module_risks.items()
        ]).sort_values("Risk Skoru", ascending=True)

        fig = px.bar(
            df_risk,
            x="Risk Skoru",
            y="Modül",
            orientation="h",
            color="Risk Seviyesi",
            color_discrete_map=RISK_COLORS,
            text="Risk Skoru",
        )
        fig.update_layout(height=400, showlegend=True)
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Bug Dağılımı (Modül Bazında)")
        df_bugs = pd.DataFrame([
            {"Modül": name, "Bug Sayısı": data.get("bug_count", 0)}
            for name, data in module_risks.items()
        ])
        fig2 = px.pie(
            df_bugs,
            values="Bug Sayısı",
            names="Modül",
            hole=0.4,
        )
        fig2.update_layout(height=400)
        st.plotly_chart(fig2, use_container_width=True)

    # Module risk ranking table
    st.markdown("---")
    st.subheader("Modül Risk Sıralaması")

    table_data = []
    for name, data in sorted(module_risks.items(), key=lambda x: x[1].get("score", 0), reverse=True):
        level = data.get("level", "LOW")
        color = RISK_COLORS.get(level, "#666")
        table_data.append({
            "Modül": name,
            "Risk Skoru": data.get("score", 0),
            "Seviye": level,
            "Toplam Bug": data.get("bug_count", 0),
            "Açık Bug": data.get("open_count", 0),
        })

    st.dataframe(
        pd.DataFrame(table_data),
        use_container_width=True,
        hide_index=True,
    )


# =============================================================================
# Page 2: Bug List
# =============================================================================

def page_bug_list():
    """Bug list with filters and search."""
    st.title("🐛 Bug Listesi")

    bugs = api_request("GET", "/bugs")
    if not bugs:
        st.info("Henüz bug verisi yüklenmemiş.")
        return

    # Filters
    col1, col2, col3 = st.columns(3)

    priorities = sorted(set(b.get("priority", "Medium") for b in bugs))
    statuses = sorted(set(b.get("status", "Open") for b in bugs))
    components = sorted(set(b.get("component", "Unknown") for b in bugs))

    with col1:
        selected_priority = st.multiselect("Öncelik Filtresi", priorities, default=priorities)
    with col2:
        selected_status = st.multiselect("Durum Filtresi", statuses, default=statuses)
    with col3:
        selected_component = st.multiselect("Modül Filtresi", components, default=components)

    # Search
    search = st.text_input("🔍 Ara (bug key veya özet)", "")

    # Filter bugs
    filtered = [
        b for b in bugs
        if b.get("priority") in selected_priority
        and b.get("status") in selected_status
        and b.get("component") in selected_component
        and (not search or search.lower() in b.get("key", "").lower() or search.lower() in b.get("summary", "").lower())
    ]

    st.markdown(f"**{len(filtered)}** / {len(bugs)} bug gösteriliyor")

    # Display as dataframe
    if filtered:
        df = pd.DataFrame([
            {
                "Key": b.get("key", ""),
                "Özet": b.get("summary", ""),
                "Öncelik": b.get("priority", ""),
                "Durum": b.get("status", ""),
                "Modül": b.get("component", ""),
                "Oluşturulma": b.get("created", "")[:10],
            }
            for b in filtered
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("Filtrelere uyan bug bulunamadı.")


# =============================================================================
# Page 3: Live Analysis
# =============================================================================

def page_live_analysis():
    """Single and bulk analysis with progress and circuit breaker display."""
    st.title("⚡ Canlı Analiz")

    tab1, tab2 = st.tabs(["🔍 Tekli Analiz", "📦 Toplu Analiz"])

    # --- Single Analysis ---
    with tab1:
        st.subheader("Tekli Bug / Alan Analizi")

        analysis_type = st.radio("Analiz Türü", ["Bug Key ile", "Serbest Metin ile"], horizontal=True)

        if analysis_type == "Bug Key ile":
            bug_key = st.text_input("Bug Key", placeholder="Örn: AP-101")
            query = None
        else:
            query = st.text_input("Analiz Sorgusu", placeholder="Örn: Authentication modülü güvenlik açıkları")
            bug_key = None

        if st.button("🚀 Analiz Et", key="single_analyze"):
            if not bug_key and not query:
                st.warning("Lütfen bir Bug Key veya sorgu girin.")
            else:
                with st.spinner("Analiz yapılıyor..."):
                    payload = {}
                    if bug_key:
                        payload["bug_key"] = bug_key
                    if query:
                        payload["query"] = query

                    result = api_request("POST", "/analyze", json=payload)

                if result:
                    display_analysis_result(result)

    # --- Bulk Analysis ---
    with tab2:
        st.subheader("Toplu Bug Analizi")
        st.info("⚠️ Toplu analiz LLM API kotanızı kullanır. Rate limit aşılırsa circuit breaker devreye girer ve kalan buglar atlanır.")

        bugs = api_request("GET", "/bugs")
        if bugs:
            bug_keys = [b.get("key", "") for b in bugs if b.get("key")]
            selected_keys = st.multiselect(
                "Analiz edilecek bugları seçin",
                bug_keys,
                default=[],
            )

            if st.button("🚀 Toplu Analiz Başlat", key="bulk_analyze"):
                if not selected_keys:
                    st.warning("En az bir bug seçin.")
                else:
                    with st.spinner(f"{len(selected_keys)} bug analiz ediliyor..."):
                        result = api_request("POST", "/analyze/bulk", json={"bug_keys": selected_keys})

                    if result:
                        st.markdown("---")

                        # Summary metrics
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Toplam", result.get("total", 0))
                        col2.metric("✅ Analiz Edilen", result.get("analyzed", 0))
                        col3.metric("⏭️ Atlanan", result.get("skipped", 0))

                        if result.get("circuit_breaker_triggered"):
                            st.error("🔴 Circuit Breaker Tetiklendi! Rate limit aşıldığı için kalan buglar atlandı.")

                        skipped = result.get("skipped_keys", [])
                        if skipped:
                            st.warning(f"Atlanan buglar: {', '.join(skipped)}")

                        # Show results
                        for r in result.get("results", []):
                            with st.expander(f"{r.get('bug_key', '?')} — Risk: {r.get('risk_score', 0)} ({r.get('risk_level', '?')})"):
                                display_analysis_result(r)
        else:
            st.info("Analiz edilecek bug verisi yok. Önce veri yükleyin.")


def display_analysis_result(result: dict):
    """Display a single analysis result with formatting."""
    risk_level = result.get("risk_level", "LOW")
    risk_score = result.get("risk_score", 0)
    color = RISK_COLORS.get(risk_level, "#666")

    # Risk badge
    st.markdown(
        f"### Risk Skoru: <span style='color:{color}; font-size:1.5em;'>{risk_score}</span> "
        f"<span style='background-color:{color}; color:white; padding:2px 10px; border-radius:4px;'>{risk_level}</span>",
        unsafe_allow_html=True,
    )

    # Reasoning
    reasoning = result.get("reasoning", "")
    if reasoning:
        st.markdown("**Analiz:**")
        st.markdown(reasoning)

    # Modules, scenarios, actions in columns
    col1, col2 = st.columns(2)

    with col1:
        modules = result.get("affected_modules", [])
        if modules:
            st.markdown("**Etkilenen Modüller:**")
            for m in modules:
                st.markdown(f"- {m}")

        scenarios = result.get("test_scenarios", [])
        if scenarios:
            st.markdown("**Test Senaryoları:**")
            for s in scenarios:
                st.markdown(f"- {s}")

    with col2:
        actions = result.get("recommended_actions", [])
        if actions:
            st.markdown("**Önerilen Aksiyonlar:**")
            for a in actions:
                st.markdown(f"- {a}")

    # Metadata
    st.caption(f"Kaynak: {result.get('source', '?')} | Tarih: {result.get('analyzed_at', '?')[:19]}")


# =============================================================================
# Page 4: Webhook Results
# =============================================================================

def page_webhook_results():
    """Display webhook analysis history."""
    st.title("🔔 Webhook Sonuçları")

    results = api_request("GET", "/results/webhook")
    if not results:
        st.info("Henüz webhook analiz sonucu yok. Jira webhook yapılandırıldığında burada otomatik analiz sonuçları görünecek.")

        st.markdown("---")
        st.subheader("Webhook Nasıl Kurulur?")
        st.markdown(f"""
        1. Jira'da **Settings → System → Webhooks** bölümüne gidin
        2. Yeni webhook oluşturun:
           - **URL:** `http://YOUR_SERVER:{config.API_PORT}/webhook/jira`
           - **Events:** Issue created, Issue updated
           - **JQL Filter:** `project = {config.JIRA_PROJECT_KEY or 'YOUR_PROJECT'} AND issuetype = Bug`
        3. Header ekleyin: `X-API-Key: {config.API_KEY[:8]}...`
        """)
        return

    st.markdown(f"**{len(results)}** webhook analiz sonucu")

    for r in reversed(results):  # Most recent first
        level = r.get("risk_level", "LOW")
        color = RISK_COLORS.get(level, "#666")
        with st.expander(
            f"{'🔴' if level == 'CRITICAL' else '🟠' if level == 'HIGH' else '🟡' if level == 'MEDIUM' else '🟢'} "
            f"{r.get('bug_key', '?')} — {r.get('query', '?')[:60]} — Risk: {r.get('risk_score', 0)}"
        ):
            display_analysis_result(r)


# =============================================================================
# Page 5: Settings
# =============================================================================

def page_settings():
    """Self-service configuration panel."""
    st.title("⚙️ Ayarlar")

    # --- Jira Connection ---
    st.subheader("🔗 Jira Bağlantısı")

    with st.form("jira_settings"):
        jira_url = st.text_input("Jira URL", value=config.JIRA_URL, placeholder="https://yourcompany.atlassian.net")
        jira_email = st.text_input("Jira E-posta", value=config.JIRA_EMAIL)
        jira_token = st.text_input("Jira API Token", value=config.JIRA_API_TOKEN, type="password")
        jira_project = st.text_input("Proje Key", value=config.JIRA_PROJECT_KEY, placeholder="AP")

        col1, col2 = st.columns(2)
        save_jira = col1.form_submit_button("💾 Kaydet", use_container_width=True)
        test_jira = col2.form_submit_button("🧪 Bağlantıyı Test Et", use_container_width=True)

    if save_jira:
        save_env_value("JIRA_URL", jira_url)
        save_env_value("JIRA_EMAIL", jira_email)
        save_env_value("JIRA_API_TOKEN", jira_token)
        save_env_value("JIRA_PROJECT_KEY", jira_project)
        st.success("✅ Jira ayarları kaydedildi. Değişikliklerin etkili olması için uygulamayı yeniden başlatın.")

    if test_jira:
        if all([jira_url, jira_email, jira_token]):
            with st.spinner("Jira bağlantısı test ediliyor..."):
                try:
                    from jira_client import JiraClient
                    client = JiraClient(jira_url, jira_email, jira_token, jira_project)
                    if client.test_connection():
                        st.success("✅ Jira bağlantısı başarılı!")
                    else:
                        st.error("❌ Jira bağlantısı başarısız. Bilgileri kontrol edin.")
                except Exception as e:
                    st.error(f"❌ Hata: {e}")
        else:
            st.warning("Lütfen tüm Jira bilgilerini doldurun.")

    st.markdown("---")

    # --- LLM Provider ---
    st.subheader("🤖 LLM Sağlayıcı")

    with st.form("llm_settings"):
        provider = st.selectbox(
            "Sağlayıcı",
            ["groq", "openai"],
            index=0 if config.LLM_PROVIDER == "groq" else 1,
        )
        groq_key = st.text_input("Groq API Key", value=config.GROQ_API_KEY, type="password")
        openai_key = st.text_input("OpenAI API Key", value=config.OPENAI_API_KEY, type="password")

        col1, col2 = st.columns(2)
        save_llm = col1.form_submit_button("💾 Kaydet", use_container_width=True)
        test_llm = col2.form_submit_button("🧪 API Key Test Et", use_container_width=True)

    if save_llm:
        save_env_value("LLM_PROVIDER", provider)
        save_env_value("GROQ_API_KEY", groq_key)
        save_env_value("OPENAI_API_KEY", openai_key)
        st.success("✅ LLM ayarları kaydedildi. Değişikliklerin etkili olması için uygulamayı yeniden başlatın.")

    if test_llm:
        active_key = groq_key if provider == "groq" else openai_key
        if active_key:
            with st.spinner("API key test ediliyor..."):
                try:
                    from llm_provider import create_llm_provider
                    # Temporarily set env var for test
                    if provider == "groq":
                        os.environ["GROQ_API_KEY"] = groq_key
                    else:
                        os.environ["OPENAI_API_KEY"] = openai_key
                    os.environ["LLM_PROVIDER"] = provider

                    llm = create_llm_provider(provider)
                    if llm.test_connection():
                        st.success(f"✅ {provider.capitalize()} API bağlantısı başarılı!")
                    else:
                        st.error(f"❌ {provider.capitalize()} API bağlantısı başarısız.")
                except Exception as e:
                    st.error(f"❌ Hata: {e}")
        else:
            st.warning(f"Lütfen {provider.capitalize()} API key girin.")

    st.markdown("---")

    # --- App Settings ---
    st.subheader("🛠️ Uygulama Ayarları")

    with st.form("app_settings"):
        max_daily = st.number_input(
            "Günlük Maksimum LLM İstek Sayısı",
            min_value=1, max_value=500,
            value=config.MAX_DAILY_REQUESTS,
        )
        groq_sleep = st.number_input(
            "İstekler Arası Bekleme (saniye)",
            min_value=0.0, max_value=30.0,
            value=config.GROQ_SLEEP,
            step=0.5,
        )
        mock_mode = st.toggle("Mock Data Modu (Jira olmadan demo)", value=config.USE_MOCK_DATA)

        save_app = st.form_submit_button("💾 Kaydet", use_container_width=True)

    if save_app:
        save_env_value("MAX_DAILY_REQUESTS", str(max_daily))
        save_env_value("GROQ_SLEEP", str(groq_sleep))
        save_env_value("USE_MOCK_DATA", str(mock_mode))
        st.success("✅ Uygulama ayarları kaydedildi. Değişikliklerin etkili olması için uygulamayı yeniden başlatın.")

    st.markdown("---")

    # --- Status Overview ---
    st.subheader("📋 Sistem Durumu")
    health = get_health()
    if health:
        col1, col2, col3 = st.columns(3)
        with col1:
            if health.get("jira_configured"):
                st.success("✅ Jira: Yapılandırıldı")
            else:
                st.error("❌ Jira: Yapılandırılmamış")
        with col2:
            if health.get("llm_configured"):
                st.success(f"✅ LLM: {config.LLM_PROVIDER.capitalize()}")
            else:
                st.error("❌ LLM: API Key Eksik")
        with col3:
            if health.get("mock_mode"):
                st.info("🎭 Mock Mod: Aktif")
            else:
                st.success("🔴 Mock Mod: Kapalı")

    # API Key display
    st.markdown("---")
    st.subheader("🔑 API Key")
    st.code(config.API_KEY, language=None)
    st.caption("Bu key, API isteklerinde X-API-Key header'ı olarak kullanılır. Jira webhook'a bu key'i ekleyin.")


# =============================================================================
# Main Router
# =============================================================================

def main():
    """Main app entry point — route to selected page."""
    page = render_sidebar()

    # First-run check: if nothing is configured, show settings
    health = get_health()
    if health is None and not config.is_jira_configured() and not config.USE_MOCK_DATA:
        st.warning("⚠️ İlk kurulum: Lütfen Ayarlar sayfasından bağlantı bilgilerinizi girin veya Mock Data modunu aktifleştirin.")
        page_settings()
        return

    if "Dashboard" in page:
        page_dashboard()
    elif "Bug Listesi" in page:
        page_bug_list()
    elif "Canlı Analiz" in page:
        page_live_analysis()
    elif "Webhook" in page:
        page_webhook_results()
    elif "Ayarlar" in page:
        page_settings()


if __name__ == "__main__":
    main()
