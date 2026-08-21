"""
First-run setup wizard.

Not a page: it is not reachable from the navigation and it disappears once
configuration exists. bootstrap() runs it when config.is_first_run() is true
and stops the script, so no page body and no navigation renders behind it.
"""

import time

import streamlit as st

from defect_risk_analyzer.ui.service import save_multiple_env


def render_setup_wizard():
    """First-run setup wizard for new users."""
    st.title("🚀 Defect Risk Analyzer — İlk Kurulum")
    st.markdown("Hoş geldiniz! Uygulamayı kullanmaya başlamak için aşağıdaki adımları tamamlayın.")
    st.markdown("---")

    # Step 1: Choose mode
    st.subheader("Adım 1: Çalışma Modu")
    st.markdown("Jira hesabınız var mı yoksa önce demo olarak denemek mi istiyorsunuz?")

    mode = st.radio(
        "Mod seçin:",
        [
            "🎭 Demo Modu (Jira olmadan örnek verilerle dene)",
            "🔗 Canlı Mod (Gerçek Jira hesabımla kullanacağım)",
        ],
        index=0,
        label_visibility="collapsed",
    )

    if "Demo" in mode:
        st.info(
            "Demo modunda 20 örnek bug ile uygulamayı deneyebilirsiniz. "
            "Jira veya LLM key gerekmez."
        )
        if st.button(
            "✅ Demo Modunu Aktifleştir ve Başla", type="primary", use_container_width=True
        ):
            save_multiple_env({"USE_MOCK_DATA": "True"})
            st.success("Demo modu aktifleştirildi! Sayfa yenileniyor...")
            time.sleep(1)
            st.rerun()
        return

    # Step 2: LLM Provider
    st.markdown("---")
    st.subheader("Adım 2: LLM API Key")
    st.markdown(
        "Risk analizi için bir LLM sağlayıcı gerekiyor. "
        "Groq ücretsiz API key sunuyor — "
        "[console.groq.com/keys](https://console.groq.com/keys) adresinden alabilirsiniz."
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        llm_provider = st.selectbox("Sağlayıcı", ["groq", "openai"], index=0)
    with col2:
        if llm_provider == "groq":
            llm_key = st.text_input(
                "Groq API Key",
                type="password",
                placeholder="gsk_...",
                help="Groq Console'dan ücretsiz API key oluşturun",
            )
        else:
            llm_key = st.text_input(
                "OpenAI API Key",
                type="password",
                placeholder="sk-...",
                help="OpenAI Platform'dan API key oluşturun",
            )

    # Step 3: Jira Connection
    st.markdown("---")
    st.subheader("Adım 3: Jira Bağlantısı")
    st.markdown(
        "Jira API token'ınızı [id.atlassian.com/manage-profile/security/api-tokens]"
        "(https://id.atlassian.com/manage-profile/security/api-tokens) adresinden oluşturun."
    )

    col1, col2 = st.columns(2)
    with col1:
        jira_url = st.text_input(
            "Jira URL",
            placeholder="https://yourcompany.atlassian.net",
            help="Jira Cloud veya Server URL'iniz",
        )
        jira_email = st.text_input(
            "Jira E-posta",
            placeholder="you@company.com",
            help="Jira hesabınızın e-posta adresi",
        )
    with col2:
        jira_token = st.text_input(
            "Jira API Token",
            type="password",
            placeholder="ATATT3x...",
            help="Jira'dan oluşturduğunuz API token",
        )
        jira_project = st.text_input(
            "Proje Key",
            placeholder="AP",
            help="Bug key'lerinin başındaki harfler (örn: AP-101 → AP)",
        )

    # Save and start
    st.markdown("---")
    if st.button("🚀 Kaydet ve Başla", type="primary", use_container_width=True):
        # Validate minimum requirements
        if not llm_key:
            st.error("LLM API Key zorunludur. Groq'tan ücretsiz key alabilirsiniz.")
            return

        if not all([jira_url, jira_email, jira_token, jira_project]):
            st.error("Tüm Jira bilgileri zorunludur.")
            return

        # Save all values
        env_values = {
            "LLM_PROVIDER": llm_provider,
            "USE_MOCK_DATA": "False",
            "JIRA_URL": jira_url.rstrip("/"),
            "JIRA_EMAIL": jira_email,
            "JIRA_API_TOKEN": jira_token,
            "JIRA_PROJECT_KEY": jira_project,
        }

        if llm_provider == "groq":
            env_values["GROQ_API_KEY"] = llm_key
        else:
            env_values["OPENAI_API_KEY"] = llm_key

        save_multiple_env(env_values)

        # Test connections
        st.info("Bağlantılar test ediliyor...")

        # Test Jira
        try:
            from defect_risk_analyzer.jira_client import JiraClient
            client = JiraClient(jira_url, jira_email, jira_token, jira_project)
            if client.test_connection():
                st.success("✅ Jira bağlantısı başarılı!")
            else:
                st.warning(
                    "⚠️ Jira bağlantısı kurulamadı. Bilgileri kontrol edin. "
                    "Yine de kaydedildi."
                )
        except Exception as e:
            st.warning(
                f"⚠️ Jira test hatası: {e}. "
                "Bilgiler kaydedildi, Ayarlar'dan düzeltebilirsiniz."
            )

        # Test LLM
        try:
            from defect_risk_analyzer.llm_provider import create_llm_provider
            llm = create_llm_provider(llm_provider)
            if llm.test_connection():
                st.success(f"✅ {llm_provider.capitalize()} API bağlantısı başarılı!")
            else:
                st.warning(
                    f"⚠️ {llm_provider.capitalize()} bağlantısı kurulamadı. "
                    "Key'i kontrol edin."
                )
        except Exception as e:
            st.warning(
                f"⚠️ LLM test hatası: {e}. "
                "Bilgiler kaydedildi, Ayarlar'dan düzeltebilirsiniz."
            )

        st.success("✅ Kurulum tamamlandı! Sayfa yenileniyor...")
        time.sleep(2)
        st.rerun()
