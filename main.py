"""AURIX Streamlit UI — same layout as before; backend loads via cached aurix_core."""
import sys

if sys.platform == "win32":
    import asyncio

    def _install_connection_reset_filter() -> None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        def _handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
            exc = context.get("exception")
            if isinstance(exc, ConnectionResetError) and "_call_connection_lost" in context.get(
                "message", ""
            ):
                return
            loop.default_exception_handler(context)

        loop.set_exception_handler(_handler)

    _install_connection_reset_filter()

import hashlib
import importlib
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*flaml.automl.*", category=UserWarning)

import streamlit as st

from API_unified import AURIX_LOGO_URL


def _aurix_cache_token() -> str:
    """Bust Streamlit cache when backend or .env changes (avoids stale DNS / preflight messages)."""
    root = Path(__file__).resolve().parent
    parts: list[str] = []
    for name in (
        "aurix_core.py",
        "API_unified.py",
        "azure_health.py",
        "azure_openai_endpoint.py",
        "azure_llm_runtime.py",
        ".env",
    ):
        path = root / name
        if path.is_file():
            parts.append(f"{name}:{path.stat().st_mtime_ns}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

st.set_page_config(
    page_title="AURIX – (Affine Unified Retrieval & Intelligence eXecution)",
    layout="wide",
)

st.markdown(
    f"""
    <div style='text-align: center;'>
        <h2 style='font-size: 40px; font-family: Courier New, monospace;'>
            <img src="{AURIX_LOGO_URL}" width="70" height="60">
            <span style='background: linear-gradient(45deg, #ed4965, #c05aaf); -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>
                AURIX – (Affine Unified Retrieval & Intelligence eXecution)
            </span>
        </h2>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown("---")


@st.cache_resource(show_spinner=False)
def _aurix_core(_cache_token: str):
    import API_unified
    import aurix_core

    importlib.reload(API_unified)  # re-read JEV_* and Azure vars from .env
    importlib.reload(aurix_core)
    return aurix_core


_cache_tok = _aurix_cache_token()
if st.session_state.get("_aurix_cache_token") != _cache_tok:
    st.session_state["_aurix_cache_token"] = _cache_tok
    st.session_state.last_output = None

if "last_question" not in st.session_state:
    st.session_state.last_question = ""
if "last_output" not in st.session_state:
    st.session_state.last_output = None

question = st.text_input("🔍 Enter your question:", placeholder="Ask about your data...")

run_query = st.button("🚀 Get Answer") and question

if run_query:
    st.session_state.last_question = question
    with st.spinner("🔍 Fetching insights..."):
        try:
            core = _aurix_core(_aurix_cache_token())
            final_output = core.get_final_answer(question)
            st.session_state.last_output = final_output
        except Exception as exc:  # noqa: BLE001
            st.session_state.last_output = None
            st.error(
                "The pipeline stopped before finishing. Check the terminal for details. "
                f"Error: {exc}"
            )
            st.stop()

final_output = st.session_state.last_output
if final_output:
    if run_query:
        core = _aurix_core(_aurix_cache_token())
        from API_unified import AZURE_SQL_EVAL_LOG_ENABLED

        if AZURE_SQL_EVAL_LOG_ENABLED and not core.log_evaluation_to_sql(final_output, question):
            st.warning(
                "Answer ready — evaluation log could not be saved to Azure SQL (ODBC). Check terminal logs."
            )

        col1, col2 = st.columns([3, 2])

        with col1:
            st.subheader("📋 Final Answer")
            query_answer = final_output.get("query_answer", "").strip()
            llm_answer = final_output.get("llm_answer", "").strip()

            if query_answer:
                st.markdown(
                    f'<div style="color:#3498db; font-size:20px; padding:10px; border-radius:5px;">{query_answer}</div>',
                    unsafe_allow_html=True,
                )
            if llm_answer:
                st.markdown(
                    f'<div style="color:#ed4965; font-size:20px; padding:10px; border-radius:5px;">{llm_answer}</div>',
                    unsafe_allow_html=True,
                )

        with col2:
            with st.expander("🤖 **AI Thought Process**", expanded=False):
                st.markdown(f"**🔧 Analysis Type:** {final_output.get('analysis_type', 'N/A')}")
                st.markdown(f"**🗃️ Database Used:** {final_output.get('database_name', 'N/A')}")
                st.markdown(f"**💡 Reasoning:** {final_output.get('Reasoning', 'N/A')}")

        st.markdown("---")

        if final_output.get("query"):
            with st.expander("📜 Query & Explanation", expanded=False):
                st.code(final_output.get("query", "N/A"), language="sql")
                query_explanation = final_output.get("query_explanation", "").strip()
                if query_explanation and "takes query as input" not in query_explanation.lower():
                    st.markdown(f"**📖 Query Explanation:** {query_explanation}")
                else:
                    st.markdown("**📖 Query Explanation:** No additional details available.")

        if final_output.get("python_code"):
            with st.expander("🐍 Python Code & Execution", expanded=False):
                st.code(final_output.get("python_code", ""), language="python")
                python_code_explanation = final_output.get("python_code_explanation", "").strip()
                if python_code_explanation and "takes query as input" not in python_code_explanation.lower():
                    st.markdown(f"**📚 Code Explanation:** {python_code_explanation}")
                else:
                    st.markdown("**📚 Code Explanation:** No additional details available.")