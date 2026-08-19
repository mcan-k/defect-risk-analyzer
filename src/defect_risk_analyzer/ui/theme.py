"""
Colors and styling for the dashboard.

The CSS below used to run at import time in dashboard.py. It is a function now
because a Streamlit page has to call st.set_page_config before anything else
renders, and an import-time st.markdown would make that impossible for any
module that imports this one.

Nothing here moved to .streamlit/config.toml: streamlit 1.41.1 exposes exactly
six [theme] options (base, primaryColor, backgroundColor,
secondaryBackgroundColor, textColor, font) and none of these rules is
expressible as one of them. They hide elements, set geometry, or set
per-element alpha text colors. config.toml pins the dark base these rgba
overlays assume; the rules themselves stay here.
"""

import streamlit as st

RISK_COLORS = {
    "CRITICAL": "#DC2626",
    "HIGH": "#F97316",
    "MEDIUM": "#EAB308",
    "LOW": "#22C55E",
}

CHART_COLORS = [
    "#8B5CF6", "#22C55E", "#F97316", "#3B82F6",
    "#EC4899", "#EAB308", "#06B6D4", "#F43F5E",
]


def inject_css() -> None:
    """Apply the custom stylesheet. Call once, after st.set_page_config."""
    st.markdown("""<style>
    /* Hide Streamlit default elements */
    [data-testid="stStatusWidget"],
    div[data-testid="stDecoration"],
    .stDeployButton,
    #stDecoration,
    iframe[title="streamlit_status_widget"] {
        display: none !important;
    }
    .stApp [data-testid="stHeader"] {
        background: transparent !important;
    }

    /* Metric cards — subtle border, consistent padding */
    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 12px 16px;
    }
    [data-testid="stMetric"] label {
        color: rgba(255, 255, 255, 0.6) !important;
        font-size: 0.85rem !important;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 600 !important;
    }

    /* Sidebar — subtle separator, clean look */
    [data-testid="stSidebar"] {
        border-right: 1px solid rgba(255, 255, 255, 0.06);
    }
    [data-testid="stSidebar"] .stRadio label {
        border-radius: 6px;
        padding: 6px 10px;
        margin: 1px 0;
        transition: background-color 0.15s ease;
    }
    [data-testid="stSidebar"] .stRadio label:hover {
        background-color: rgba(255, 255, 255, 0.05);
    }

    /* Expander cards — consistent border */
    [data-testid="stExpander"] {
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
    }

    /* Buttons — consistent style */
    .stButton > button {
        border-radius: 6px;
        font-weight: 500;
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
    }

    /* DataFrames — cleaner table look */
    [data-testid="stDataFrame"] {
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
    }

    /* Alerts/info boxes — softer look */
    .stAlert {
        border-radius: 8px !important;
    }

    /* Divider line */
    hr {
        border-color: rgba(255, 255, 255, 0.06) !important;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0;
        padding: 8px 16px;
    }

    /* Toggle switch */
    [data-testid="stToggle"] label span {
        font-weight: 400 !important;
    }

    /* Text input — consistent border */
    .stTextInput > div > div {
        border-radius: 6px !important;
    }

    /* Consistent page title sizing */
    .main h1 {
        font-size: 2rem !important;
        font-weight: 600 !important;
        margin-bottom: 0.5rem !important;
    }
    .main h2 {
        font-size: 1.4rem !important;
        font-weight: 500 !important;
        color: rgba(255, 255, 255, 0.85) !important;
    }

    /* Caption text — muted */
    .main .stCaption {
        color: rgba(255, 255, 255, 0.45) !important;
    }
</style>""", unsafe_allow_html=True)


def apply_chart_theme(fig, height: int = 400) -> None:
    """Apply consistent dark theme to a Plotly figure."""
    fig.update_layout(
        height=height,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        title_text="",
        showlegend=True,
        font=dict(color="rgba(255,255,255,0.7)", size=12),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(255,255,255,0.1)",
            font=dict(color="rgba(255,255,255,0.65)", size=11),
        ),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.06)",
            zerolinecolor="rgba(255,255,255,0.06)",
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.06)",
            zerolinecolor="rgba(255,255,255,0.06)",
        ),
        margin=dict(l=40, r=20, t=20, b=40),
    )
