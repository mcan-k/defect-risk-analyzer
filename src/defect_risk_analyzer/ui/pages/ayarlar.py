"""Ayarlar — self-service configuration."""

import os
import time

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui.service import get_service, save_multiple_env
from defect_risk_analyzer.ui.shell import bootstrap

bootstrap()


def render_settings():
    """Self-service configuration panel with live reload."""
    st.title("⚙️ Ayarlar")
    st.caption("Değişiklikler kaydedildiğinde anında uygulanır — yeniden başlatma gerekmez.")

    # --- Jira Connection ---
    st.subheader("🔗 Jira Bağlantısı")

    jira_url = st.text_input("Jira URL", value=config.JIRA_URL, placeholder="https://yourcompany.atlassian.net")
    jira_email = st.text_input(
        "Jira E-posta", value=config.JIRA_EMAIL, placeholder="you@company.com"
    )
    jira_token = st.text_input("Jira API Token", value=config.JIRA_API_TOKEN, type="password",
                               help="[Token oluştur →](https://id.atlassian.com/manage-profile/security/api-tokens)")
    jira_project = st.text_input("Proje Key", value=config.JIRA_PROJECT_KEY, placeholder="AP",
                                 help="Bug key'lerinin başındaki harfler (örn: AP-101 → AP)")

    col1, col2 = st.columns(2)
    if col1.button("💾 Jira Ayarlarını Kaydet", use_container_width=True):
        save_multiple_env({
            "JIRA_URL": jira_url.rstrip("/"),
            "JIRA_EMAIL": jira_email,
            "JIRA_API_TOKEN": jira_token,
            "JIRA_PROJECT_KEY": jira_project,
        })
        st.success("✅ Jira ayarları kaydedildi ve uygulandı!")
        time.sleep(1)
        st.rerun()

    if col2.button("🧪 Jira Bağlantısını Test Et", use_container_width=True):
        if all([jira_url, jira_email, jira_token]):
            with st.spinner("Jira bağlantısı test ediliyor..."):
                try:
                    from defect_risk_analyzer.jira_client import JiraClient
                    client = JiraClient(jira_url.rstrip("/"), jira_email, jira_token, jira_project)
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

    provider = st.selectbox(
        "Sağlayıcı",
        ["groq", "openai"],
        index=0 if config.LLM_PROVIDER == "groq" else 1,
    )

    if provider == "groq":
        llm_key = st.text_input(
            "Groq API Key",
            value=config.GROQ_API_KEY,
            type="password",
            help="[Groq Console →](https://console.groq.com/keys) adresinden ücretsiz key alın",
        )
    else:
        llm_key = st.text_input(
            "OpenAI API Key",
            value=config.OPENAI_API_KEY,
            type="password",
            help="[OpenAI Platform →](https://platform.openai.com/api-keys) adresinden key alın",
        )

    col1, col2 = st.columns(2)
    if col1.button("💾 LLM Ayarlarını Kaydet", use_container_width=True):
        env_values = {"LLM_PROVIDER": provider}
        if provider == "groq":
            env_values["GROQ_API_KEY"] = llm_key
        else:
            env_values["OPENAI_API_KEY"] = llm_key
        save_multiple_env(env_values)
        st.success("✅ LLM ayarları kaydedildi ve uygulandı!")
        time.sleep(1)
        st.rerun()

    if col2.button("🧪 LLM Bağlantısını Test Et", use_container_width=True):
        if llm_key:
            with st.spinner("API key test ediliyor..."):
                try:
                    # Temporarily set for test
                    if provider == "groq":
                        os.environ["GROQ_API_KEY"] = llm_key
                    else:
                        os.environ["OPENAI_API_KEY"] = llm_key
                    os.environ["LLM_PROVIDER"] = provider

                    from defect_risk_analyzer.llm_provider import create_llm_provider
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

    max_daily = st.number_input(
        "Günlük Maksimum LLM İstek Sayısı",
        min_value=1, max_value=500,
        value=config.MAX_DAILY_REQUESTS,
        help="Günlük maliyet kontrolü için LLM çağrı limiti",
    )
    groq_sleep = st.number_input(
        "İstekler Arası Bekleme (saniye)",
        min_value=0.0, max_value=30.0,
        value=config.GROQ_SLEEP,
        step=0.5,
        help="Groq free-tier rate limit'e takılmamak için bekleme süresi",
    )
    mock_mode = st.toggle(
        "Mock Data Modu (Jira olmadan demo)",
        value=config.USE_MOCK_DATA,
        help="Aktifken Jira yerine örnek veriler kullanılır",
    )

    st.markdown("---")

    # --- Data Anonymization ---
    st.subheader("🔒 Veri Anonimleştirme")
    st.markdown("Aktifken, bug verileri LLM'e gönderilmeden önce hassas bilgiler maskelenir.")
    st.markdown(
        """**Maskelenen veriler:**

| Veri Türü | Örnek | Maskelenmiş Hali |
|-----------|-------|-----------------|
| E-posta adresleri | `ahmet@firma.com` | `[EMAIL_001]` |
| IP adresleri | `192.168.1.50` | `[IP_001]` |
| URL'ler | `https://site.com/api` | `[URL_001]` |
| Telefon numaraları | `+90 532 123 4567` | `[PHONE_001]` |
| Bearer Token'lar | `Bearer eyJhbG...` | `[TOKEN_001]` |
| API Key'ler | `gsk_abc123...`, `sk-abc123...` | `[APIKEY_001]` |
"""
    )
    st.caption(
        "Not: Düz metin olarak yazılmış kişi isimleri (ör. 'Ahmet Yılmaz') "
        "yapısal bir formata uymadığı için maskelenmez."
    )

    anonymize = st.toggle(
        "Veri Anonimleştirme",
        value=config.ANONYMIZE_DATA,
        help="LLM'e gönderilen verilerde PII maskeleme",
    )

    if st.button("💾 Uygulama Ayarlarını Kaydet", use_container_width=True):
        save_multiple_env({
            "MAX_DAILY_REQUESTS": str(max_daily),
            "GROQ_SLEEP": str(groq_sleep),
            "USE_MOCK_DATA": str(mock_mode),
            "ANONYMIZE_DATA": str(anonymize),
        })
        st.success("✅ Uygulama ayarları kaydedildi ve uygulandı!")
        time.sleep(1)
        st.rerun()

    st.markdown("---")

    # --- System Status ---
    st.subheader("📋 Sistem Durumu")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Yüklü Bug", len(get_service().get_bugs()))
    with col2:
        if config.is_jira_configured():
            st.success("✅ Jira Bağlı")
        else:
            st.error("❌ Jira Eksik")
    with col3:
        if config.is_llm_configured():
            st.success(f"✅ LLM ({config.LLM_PROVIDER})")
        else:
            st.error("❌ LLM Eksik")
    with col4:
        if config.USE_MOCK_DATA:
            st.info("🎭 Mock Aktif")
        else:
            st.success("🔴 Canlı Mod")

    # API Key — only relevant to the optional webhook server
    st.markdown("---")
    st.subheader("🔑 API Key (webhook servisi için)")

    if config.API_KEY:
        st.code(config.API_KEY, language=None)
        st.caption(
            "Bu key yalnızca opsiyonel webhook/API servisi için gerekir; dashboard "
            "analiz motorunu doğrudan çalıştırır ve bu key'i kullanmaz."
        )
    else:
        st.info(
            "Henüz bir API key üretilmemiş. Webhook kurmayacaksanız gerek yok — "
            "dashboard bu key olmadan da tam olarak çalışır."
        )

    # Generation is explicit: it writes to .env, and merely opening this page
    # must never do that.
    label = "🔄 API Key'i Yenile" if config.API_KEY else "🔑 API Key Üret"
    if st.button(label, use_container_width=True):
        new_key = config.ensure_api_key(rotate=bool(config.API_KEY))
        st.success(f"✅ API key kaydedildi: `{new_key[:8]}…`")
        st.warning(
            "Webhook servisi çalışıyorsa yeni key'i alması için yeniden "
            "başlatılmalı; Jira webhook tanımındaki header da güncellenmeli."
        )
        time.sleep(1)
        st.rerun()
    st.warning(
        "⚠️ Webhook servisi ayrı bir process olarak çalışıyorsa, buradaki "
        "ayarları görmez. Kaydettiğiniz değişikliklerin webhook tarafında da "
        "geçerli olması için o servisi yeniden başlatın."
    )


render_settings()
