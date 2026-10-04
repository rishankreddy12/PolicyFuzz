import streamlit as st
import asyncio
import threading
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict

from policyfuzz.config import Settings, make_provider
from policyfuzz.orchestrator import Orchestrator, GateError
from policyfuzz import db, events
from policyfuzz.models import RunStatus, Ruling, PatchProposal, Clause, ClauseEdit
from policyfuzz.report import build_report_md, build_regression_cases
from policyfuzz.patching import decision_table_md, unified_diff
from policyfuzz.agents.clause_parser import parse_policy, PolicyFormatError, PolicyTooLargeError

# Background worker threads by run_id
WORKERS: Dict[str, threading.Thread] = {}

def get_settings() -> Settings:
    settings = Settings.from_env()
    provider = os.getenv("POLICYFUZZ_PROVIDER")
    if provider:
        settings.provider = provider
    return settings

def run_orchestrator_sync(run_id: str, method_name: str, *args, **kwargs):
    """Run an async orchestrator method in a new event loop inside a daemon thread."""
    def worker():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            settings = get_settings()
            conn = db.connect(settings.db_path)
            provider = make_provider(settings)
            orch = Orchestrator(conn, provider, settings)
            
            method = getattr(orch, method_name)
            loop.run_until_complete(method(run_id, *args, **kwargs))
            
            conn.close()
        except Exception as e:
            print(f"Worker thread error in {method_name}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if run_id in WORKERS:
                del WORKERS[run_id]
                
    if run_id in WORKERS and WORKERS[run_id].is_alive():
        return
        
    t = threading.Thread(target=worker, daemon=True)
    WORKERS[run_id] = t
    t.start()

def is_worker_active(run_id: str) -> bool:
    return run_id in WORKERS and WORKERS[run_id].is_alive()

def inject_custom_styles():
    st.markdown(
        """
        <style>
        /* Sleek modern design tokens */
        .pf-metric-card {
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px 16px;
            text-align: left;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        }
        .pf-metric-val {
            font-size: 1.55rem;
            font-weight: 700;
            color: #0f172a;
            line-height: 1.2;
        }
        .pf-metric-label {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #64748b;
            margin-top: 4px;
        }
        .pf-badge {
            display: inline-block;
            padding: 2px 8px;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 4px;
        }
        .pf-badge-allow { background-color: #dcfce7; color: #166534; }
        .pf-badge-deny { background-color: #fee2e2; color: #991b1b; }
        .pf-badge-escalate { background-color: #fef3c7; color: #92400e; }
        .pf-badge-skip { background-color: #f1f5f9; color: #475569; }
        .pf-badge-high { background-color: #fee2e2; color: #991b1b; }
        .pf-badge-med { background-color: #fef3c7; color: #92400e; }
        .pf-badge-low { background-color: #e0f2fe; color: #075985; }
        .pf-badge-divergent { background-color: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
        .pf-badge-consistent { background-color: #dcfce7; color: #15803d; }
        .pf-code-box {
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 12px;
            font-family: monospace;
            font-size: 0.85rem;
            color: #1e293b;
            overflow-x: auto;
        }
        .pf-scripted-banner {
            background-color: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-left: 4px solid #16a34a;
            padding: 10px 14px;
            border-radius: 4px;
            color: #166534;
            font-size: 0.88rem;
            margin-bottom: 12px;
        }
        /* Minimal sleek loading animation */
        @keyframes pf-spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        @keyframes pf-pulse-bar {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        .pf-loading-box {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: #f8fafc;
            border: 1px solid #cbd5e1;
            border-left: 4px solid #2563eb;
            border-radius: 6px;
            margin: 10px 0;
            color: #1e293b;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        .pf-spinner {
            display: inline-block;
            width: 18px;
            height: 18px;
            border: 2px solid #cbd5e1;
            border-top-color: #2563eb;
            border-radius: 50%;
            animation: pf-spin 0.8s linear infinite;
            flex-shrink: 0;
        }
        .pf-shimmer {
            height: 3px;
            width: 100%;
            background: linear-gradient(90deg, #e2e8f0 0%, #3b82f6 50%, #e2e8f0 100%);
            background-size: 200% 100%;
            animation: pf-pulse-bar 1.5s ease infinite;
            border-radius: 2px;
            margin-top: 6px;
        }
        .pf-option-card {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 14px;
            background: #ffffff;
            margin-bottom: 8px;
            min-height: 110px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
            border-left: 3px solid #3b82f6;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def main():
    st.set_page_config(
        page_title="PolicyFuzz — SOP Divergence Auditor",
        page_icon="⚖️",
        layout="wide"
    )
    inject_custom_styles()
    
    settings = get_settings()
    conn = db.connect(settings.db_path)
    
    # Initialize DB schema if empty
    try:
        db.get_run(conn, "dummy")
    except Exception:
        db.init_schema(conn)

    # --- SIDEBAR CONTROLS ---
    st.sidebar.markdown("### ⚖️ PolicyFuzz")
    st.sidebar.caption("Deterministic SOP Divergence & Ambiguity Auditor")
    
    # Provider Selection
    with st.sidebar.expander("Provider & Model Configuration", expanded=False):
        prov_list = ["gemini", "nvidia", "scripted", "openai", "ollama"]
        format_names = {
            "gemini": "Gemini (Google AI — Cloud)",
            "nvidia": "NVIDIA NIM (Cloud API)",
            "scripted": "Scripted (Offline Demo)",
            "openai": "OpenAI-Compatible (Local API)",
            "ollama": "Ollama (Local on 11434)"
        }
        current_idx = prov_list.index(settings.provider) if settings.provider in prov_list else 0
        selected_provider = st.selectbox("Active Provider", prov_list, index=current_idx, format_func=lambda x: format_names.get(x, x))
        if selected_provider != settings.provider:
            os.environ["POLICYFUZZ_PROVIDER"] = selected_provider
            st.rerun()
            
        if selected_provider == "gemini":
            model = settings.model_strong or "gemini-3.5-flash"
            has_key = bool(settings.gemini_api_key)
            st.caption(f"Model: `{model}`")
            if has_key:
                st.caption(f"API Key: `{settings.gemini_api_key[:8]}…` ✓")
            else:
                st.warning("Set `GEMINI_API_KEY` in `.env` to use Gemini.")
        elif selected_provider == "nvidia":
            model = settings.model_strong or "meta/llama-3.2-11b-vision-instruct"
            has_key = bool(settings.nvidia_api_key)
            st.caption(f"Model: `{model}`")
            if has_key:
                st.caption(f"API Key: `{settings.nvidia_api_key[:8]}…` ✓")
            else:
                st.warning("Set `NVIDIA_API_KEY` in `.env` to use NVIDIA NIM.")
        elif selected_provider == "scripted":
            st.caption("✓ Deterministic replay of verified persona interpretations. Zero network calls.")
        elif selected_provider == "openai":
            host = getattr(settings, 'openai_host', getattr(settings, 'openai_base_url', 'http://127.0.0.1:8317/v1'))
            model = getattr(settings, 'model_strong', 'gemini-pro-agent')
            st.caption(f"Host: `{host}`")
            st.caption(f"Model: `{model}`")
        elif selected_provider == "ollama":
            host = getattr(settings, 'ollama_host', 'http://localhost:11434')
            st.caption(f"Host: `{host}`")

    # Ingestion & Run Actions
    st.sidebar.markdown("---")
    
    if st.sidebar.button("➕ New Audit / Ingest Policy", width="stretch"):
        st.session_state.show_onboarding = True
        if "run_id" in st.session_state:
            del st.session_state.run_id
        st.rerun()

    if st.sidebar.button("Load Demo Policy", width="stretch"):
        base = Path(__file__).parent.parent.parent
        demo_path = base / "fixtures" / "demo" / "policy_v1.txt"
        if demo_path.exists():
            with open(demo_path, "r", encoding="utf-8") as f:
                st.session_state.uploaded_text = f.read()
            st.session_state.uploaded_name = "Northwind_Returns_Policy_Demo.txt"
            st.session_state.show_onboarding = True
            if "run_id" in st.session_state:
                del st.session_state.run_id
            st.sidebar.success("Demo policy loaded.")
            st.rerun()

    # Historical Run Selector
    c = conn.cursor()
    c.execute("SELECT run_id, name, created_at, status FROM runs ORDER BY created_at DESC")
    historical_runs = c.fetchall()
    
    if historical_runs:
        st.sidebar.markdown("##### Audit Runs")
        run_dict = {
            r["run_id"]: f"{r['name'][:24]} ({r['created_at'][11:16]} · {r['status']})"
            for r in historical_runs
        }
        run_ids = list(run_dict.keys())
        
        curr_run_id = getattr(st.session_state, "run_id", None)
        selected_idx = run_ids.index(curr_run_id) if curr_run_id in run_ids else 0
        
        chosen_run_id = st.sidebar.selectbox(
            "Select Audit",
            run_ids,
            index=selected_idx,
            format_func=lambda x: run_dict[x],
            label_visibility="collapsed"
        )
        if not getattr(st.session_state, "show_onboarding", False):
            st.session_state.run_id = chosen_run_id

    # Sidebar Start Audit Button if policy is loaded
    has_text = hasattr(st.session_state, "uploaded_text") and bool(st.session_state.uploaded_text)
    if has_text and getattr(st.session_state, "show_onboarding", False):
        if st.sidebar.button("Start Audit", type="primary", width="stretch"):
            file_name = getattr(st.session_state, "uploaded_name", "Policy Document")
            run_title = Path(file_name).stem.replace("_", " ").title()
            orch = Orchestrator(conn, make_provider(settings), settings)
            loop = asyncio.new_event_loop()
            new_run_id = loop.run_until_complete(
                orch.create_run(st.session_state.uploaded_text, run_title, settings.provider)
            )
            loop.close()
            st.session_state.run_id = new_run_id
            st.session_state.show_onboarding = False
            run_orchestrator_sync(new_run_id, "run_until_gate")
            st.rerun()

    # Maintenance: Clean Reset
    with st.sidebar.expander("Maintenance & Reset", expanded=False):
        if st.button("Reset All Stored Audits", type="secondary", width="stretch"):
            import shutil
            shutil.rmtree(settings.runs_dir, ignore_errors=True)
            tables = [
                "events", "llm_calls", "verifications", "patch_edits", "patches",
                "rulings", "clusters", "verdicts", "cases", "enrichment", "clauses", "runs"
            ]
            c = conn.cursor()
            for t in tables:
                try:
                    c.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            conn.commit()
            os.environ["POLICYFUZZ_PROVIDER"] = "scripted"
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.session_state.show_onboarding = True
            st.success("All stored audits cleared. Reset provider to scripted mode.")
            st.rerun()

    # Determine whether to show onboarding or active audit dashboard
    has_active_run = hasattr(st.session_state, "run_id") and st.session_state.run_id
    show_upload = getattr(st.session_state, "show_onboarding", False) or not has_active_run
    
    if show_upload:
        render_onboarding_and_upload(conn, settings)
    else:
        run = db.get_run(conn, st.session_state.run_id)
        if not run:
            st.session_state.show_onboarding = True
            st.rerun()
        else:
            render_audit_dashboard(conn, run, settings)


def render_onboarding_and_upload(conn, settings: Settings):
    """Clean, professional onboarding and policy ingestion screen."""
    st.title("⚖️ PolicyFuzz — SOP Divergence Auditor")
    st.markdown(
        "Ingest an operational policy, Standard Operating Procedure (SOP), or terms & conditions document "
        "to automatically uncover conflicting interpretations, boundary loopholes, and compliance risks across "
        "independent evaluation personas."
    )
    
    # Persistent Scripted Banner if in scripted mode
    if settings.provider == "scripted":
        st.markdown(
            """<div class="pf-scripted-banner">
                <strong>Scripted demo mode:</strong> LLM outputs are replayed from fixtures. 
                This demonstrates the pipeline, not model behaviour. Use Live mode (Ollama) for real divergence numbers.
            </div>""",
            unsafe_allow_html=True
        )

    upload_col, preview_col = st.columns([1, 1], gap="large")
    
    with upload_col:
        st.subheader("1. Ingest Policy")
        
        # Option A: File Uploader
        uploaded_file = st.file_uploader(
            "Upload policy text file (.txt or .md)",
            type=["txt", "md"],
            help="Policy text should contain numbered sections and clauses (e.g. 1. Eligibility, 1.1 ...)"
        )
        if uploaded_file is not None:
            raw_bytes = uploaded_file.read()
            st.session_state.uploaded_text = raw_bytes.decode("utf-8", errors="replace")
            st.session_state.uploaded_name = uploaded_file.name
            st.session_state.uploaded_size = len(raw_bytes)
            
        # Option B: Local File Path
        st.markdown("— **or load from local filesystem** —")
        col_p1, col_p2 = st.columns([3, 1])
        local_path = col_p1.text_input(
            "Local file path",
            value=getattr(st.session_state, "input_filepath", ""),
            placeholder=r"C:\Users\...\shopright_returns_terms_conditions.txt",
            label_visibility="collapsed"
        )
        if col_p2.button("Load Path", width="stretch"):
            clean_path = local_path.strip().strip('"').strip("'")
            if clean_path and os.path.exists(clean_path):
                try:
                    with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    st.session_state.uploaded_text = content
                    st.session_state.uploaded_name = Path(clean_path).name
                    st.session_state.uploaded_size = len(content.encode("utf-8"))
                    st.session_state.input_filepath = clean_path
                    st.success(f"Loaded {Path(clean_path).name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error reading file: {e}")
            else:
                st.error("File not found at specified path.")

        has_text = hasattr(st.session_state, "uploaded_text") and bool(st.session_state.uploaded_text)
        
        if has_text:
            file_name = getattr(st.session_state, "uploaded_name", "policy_document.txt")
            file_size_kb = len(st.session_state.uploaded_text.encode('utf-8')) / 1024.0
            
            st.markdown(
                f"""<div class="pf-metric-card" style="margin: 12px 0;">
                    <div style="font-weight:600; color:#0f172a;">📄 {file_name}</div>
                    <div style="font-size:0.85rem; color:#64748b; margin-top:2px;">
                        Size: {file_size_kb:.1f} KB · Characters: {len(st.session_state.uploaded_text):,}
                    </div>
                </div>""",
                unsafe_allow_html=True
            )
            
            # Active provider indicator & toggle
            if settings.provider != "scripted":
                st.warning(
                    f"⚠️ **Provider Mode:** Set to `{settings.provider}`. If your local API server is unreachable, "
                    "switch to **`scripted`** mode for instant offline auditing."
                )
                if st.button("⚡ Switch to 'scripted' (Offline Mode)", type="secondary"):
                    os.environ["POLICYFUZZ_PROVIDER"] = "scripted"
                    st.rerun()
            else:
                st.caption("⚡ Mode: **Scripted (Offline Deterministic Replay)** — No external API calls needed.")
                
            # Audit Title
            default_title = Path(file_name).stem.replace("_", " ").title()
            run_title = st.text_input("Audit Name / Label", value=default_title)
            
            if st.button("🚀 Start Audit", type="primary", width="stretch"):
                orch = Orchestrator(conn, make_provider(settings), settings)
                loop = asyncio.new_event_loop()
                new_run_id = loop.run_until_complete(
                    orch.create_run(st.session_state.uploaded_text, run_title, settings.provider)
                )
                loop.close()
                
                st.session_state.run_id = new_run_id
                st.session_state.show_onboarding = False
                
                # Kick off orchestrator in background
                run_orchestrator_sync(new_run_id, "run_until_gate")
                st.rerun()
        else:
            st.info("Upload a file above, enter a local file path, or click **Load Demo Policy** to begin.")
            
    with preview_col:
        st.subheader("2. Parsing & Structure Preview")
        if has_text:
            try:
                clauses = parse_policy(st.session_state.uploaded_text)
                sections = sorted(list(set(c.section_title for c in clauses)))
                
                p1, p2, p3 = st.columns(3)
                p1.metric("Clauses Found", len(clauses))
                p2.metric("Sections", len(sections))
                p3.metric("Format Status", "Valid SOP ✓")
                
                st.caption(f"Sections detected: {', '.join(sections[:6])}{'...' if len(sections) > 6 else ''}")
                
                with st.container(height=380):
                    st.markdown("##### Extracted Clauses Preview:")
                    for cl in clauses[:15]:
                        st.markdown(f"**{cl.clause_id}** *({cl.section_title})*: {cl.text}")
                    if len(clauses) > 15:
                        st.caption(f"... and {len(clauses) - 15} more clauses parsed successfully.")
            except Exception as e:
                st.error(f"Policy parsing error: {e}")
                st.caption("Ensure clauses follow numbered format (e.g. 1. Section Title, 1.1 Clause Text)")
        else:
            st.markdown(
                """
                <div class="pf-metric-card" style="padding: 24px;">
                    <h5 style="margin-top:0; color:#334155;">Automated Ambiguity Fuzzing Workflow</h5>
                    <p style="color: #64748b; font-size: 0.9rem; line-height: 1.5;">
                        Once a policy is ingested, PolicyFuzz performs:
                    </p>
                    <ul style="color: #64748b; font-size: 0.88rem; padding-left: 20px;">
                        <li><strong>Deterministic Parsing:</strong> Section & clause boundary extraction.</li>
                        <li><strong>Adversarial Case Generation:</strong> Targeted edge, temporal, semantic, and combination boundary cases.</li>
                        <li><strong>Persona Panel Interpretation:</strong> Independent evaluation by 3 distinct personas.</li>
                        <li><strong>Divergence Detection:</strong> Mathematical divergence identification & loophole clustering.</li>
                        <li><strong>Human-in-the-Loop Gate 1:</strong> Adjudication of business intent for discovered loopholes.</li>
                        <li><strong>Patch Synthesis & Gate 2:</strong> Automated policy amendment drafting with human approval gate.</li>
                        <li><strong>Verification & Regression Check:</strong> Re-evaluation over baseline & unseen sibling scenarios.</li>
                    </ul>
                </div>
                """,
                unsafe_allow_html=True
            )


@st.fragment(run_every="2s")
def render_live_stepper(conn, run_id: str):
    """Auto-refreshing status stepper and action indicator."""
    run = db.get_run(conn, run_id)
    if not run:
        return
    run = dict(run)
    s = run["status"]
    
    # Trigger full page rerun when status advances
    last_status = st.session_state.get(f"last_status_{run_id}")
    if last_status is not None and last_status != s:
        st.session_state[f"last_status_{run_id}"] = s
        st.rerun()
    st.session_state[f"last_status_{run_id}"] = s

    stage_labels = {
        RunStatus.CREATED: "Stage 1/8: Ingestion & Deterministic Parsing",
        RunStatus.PARSED: "Stage 2/8: Generating Adversarial Boundary Scenarios",
        RunStatus.CASES_READY: "Stage 3/8: Evaluating 3 Independent Personas",
        RunStatus.PANEL_V1_DONE: "Stage 4/8: Detecting Divergence & Grouping Loopholes",
        RunStatus.ANALYZED: "Stage 5/8: Awaiting Human Adjudication",
        RunStatus.AWAITING_RULINGS: "Stage 5/8: Action Required — Loophole Adjudication (Gate 1)",
        RunStatus.RULED: "Stage 6/8: Synthesizing Policy Patch Proposal",
        RunStatus.PATCH_PROPOSED: "Stage 7/8: Action Required — Patch Review & Approval (Gate 2)",
        RunStatus.AWAITING_EDIT_DECISIONS: "Stage 7/8: Action Required — Patch Review & Approval (Gate 2)",
        RunStatus.PATCH_APPLIED: "Stage 8/8: Verifying Patched Policy & Regression Suite",
        RunStatus.VERIFIED: "Stage 8/8: Verification Complete",
        RunStatus.COMPLETE: "Audit Completed",
        RunStatus.COMPLETE_IMPROVED: "Audit Complete: Policy Patched & Verified ✓",
        RunStatus.COMPLETE_NO_IMPROVEMENT: "Audit Complete: No Divergence Reduction",
        RunStatus.COMPLETE_NO_DIVERGENCE: "Audit Complete: Watertight (0 Divergence) ✓",
        RunStatus.FAILED: "Audit Execution Stopped (Failed)"
    }
    
    stage_progression = {
        RunStatus.CREATED: 0.12,
        RunStatus.PARSED: 0.25,
        RunStatus.CASES_READY: 0.45,
        RunStatus.PANEL_V1_DONE: 0.60,
        RunStatus.ANALYZED: 0.70,
        RunStatus.AWAITING_RULINGS: 0.70,
        RunStatus.RULED: 0.80,
        RunStatus.PATCH_PROPOSED: 0.85,
        RunStatus.AWAITING_EDIT_DECISIONS: 0.85,
        RunStatus.PATCH_APPLIED: 0.92,
        RunStatus.VERIFIED: 1.0,
        RunStatus.COMPLETE: 1.0,
        RunStatus.COMPLETE_IMPROVED: 1.0,
        RunStatus.COMPLETE_NO_IMPROVEMENT: 1.0,
        RunStatus.COMPLETE_NO_DIVERGENCE: 1.0,
        RunStatus.FAILED: 1.0,
    }
    
    label = stage_labels.get(s, s)
    pct = stage_progression.get(s, 0.5)
    
    if s == RunStatus.FAILED:
        err_msg = run.get("error") or "Unknown error"
        st.error(f"❌ **Audit Execution Failed:** {err_msg}")
        
        # Actionable recovery for connection errors
        if any(w in err_msg.lower() for w in ["connection error", "connection attempts failed", "refused", "timeout", "openai"]):
            st.info(
                "💡 **Why this happened:** The application was attempting to connect to an external or local LLM server "
                "which is currently unreachable. You can immediately switch to **`scripted`** mode (offline deterministic replay) "
                "to audit this policy with zero network dependencies."
            )
            if st.button("⚡ Switch to 'scripted' Mode & Restart Audit", type="primary", key=f"recover_scripted_{run_id}"):
                os.environ["POLICYFUZZ_PROVIDER"] = "scripted"
                orig_path = run.get("policy_path")
                policy_text = ""
                if orig_path and os.path.exists(orig_path):
                    with open(orig_path, "r", encoding="utf-8") as f:
                        policy_text = f.read()
                if policy_text:
                    s_new = get_settings()
                    s_new.provider = "scripted"
                    orch = Orchestrator(conn, make_provider(s_new), s_new)
                    loop = asyncio.new_event_loop()
                    new_run_id = loop.run_until_complete(
                        orch.create_run(policy_text, run.get("name", "ShopRight Audit"), "scripted")
                    )
                    loop.close()
                    st.session_state.run_id = new_run_id
                    st.session_state.show_onboarding = False
                    run_orchestrator_sync(new_run_id, "run_until_gate")
                    st.rerun()
                else:
                    st.session_state.show_onboarding = True
                    if "run_id" in st.session_state:
                        del st.session_state.run_id
                    st.rerun()
    else:
        st.progress(pct, text=label)
        
    c = conn.cursor()
    c.execute("SELECT stage, message FROM events WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,))
    recent = c.fetchone()
    
    is_active = is_worker_active(run_id) or (s not in [
        RunStatus.AWAITING_RULINGS, RunStatus.AWAITING_EDIT_DECISIONS, 
        RunStatus.COMPLETE, RunStatus.COMPLETE_IMPROVED, 
        RunStatus.COMPLETE_NO_IMPROVEMENT, RunStatus.COMPLETE_NO_DIVERGENCE, 
        RunStatus.FAILED
    ])
    
    if is_active and s != RunStatus.FAILED:
        recent_msg = recent[1] if recent else "Background analysis actively processing..."
        st.markdown(
            f"""<div class="pf-loading-box">
                <div class="pf-spinner"></div>
                <div style="flex-grow: 1;">
                    <div style="font-weight:600; font-size:0.88rem; color:#1e293b;">{label}</div>
                    <div style="font-size:0.80rem; color:#475569; margin-top:2px;">Activity: {recent_msg}</div>
                    <div class="pf-shimmer"></div>
                </div>
            </div>""",
            unsafe_allow_html=True
        )
    elif recent and not s.startswith("COMPLETE") and s != RunStatus.FAILED:
        st.caption(f"Current Activity [{recent[0]}]: {recent[1]}")


def render_audit_dashboard(conn, run: Dict[str, Any], settings: Settings):
    """Main workflow-oriented dashboard for an active audit run."""
    run = dict(run)
    run_id = run["run_id"]
    status = run["status"]
    round_num = run["round"] if run["round"] is not None else 1
    
    # Extract metrics JSON safely
    metrics = {}
    if run.get("metrics_json"):
        try:
            metrics = json.loads(run["metrics_json"])
        except Exception:
            metrics = {}

    cases = db.get_cases(conn, run_id)
    clusters = db.get_clusters(conn, run_id)
    rulings = db.get_rulings(conn, run_id)
    c = conn.cursor()
    c.execute("SELECT case_id, interpreter, verdict, confidence, cited_json, rationale FROM verdicts WHERE run_id=? AND policy_tag='v1' AND valid=1", (run_id,))
    v1_raw_verdicts = [dict(r) for r in c.fetchall()]
    clauses = db.get_clauses(conn, run_id)
    
    # Persistent Scripted Banner if in scripted mode
    if settings.provider == "scripted":
        st.markdown(
            """<div class="pf-scripted-banner">
                <strong>Scripted demo mode:</strong> LLM outputs are replayed from fixtures. 
                This demonstrates the pipeline, not model behaviour. Use Live mode (Ollama) for real divergence numbers.
            </div>""",
            unsafe_allow_html=True
        )

    # --- HEADER METADATA ---
    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.markdown(f"## 📋 {run['name']}")
    with head_col2:
        st.caption(f"Run ID: `{run_id[:8]}` · Provider: `{run['provider']}`")
        
    # Render dynamic progress stepper
    render_live_stepper(conn, run_id)
    
    # Prominent Action Banners for Human-in-the-Loop Gates
    if status == RunStatus.AWAITING_RULINGS:
        st.warning(
            "⚠️ **Action Required: Ambiguity Clusters Found (Gate 1)** — Independent evaluation personas reached conflicting interpretations. "
            "Go to the **Review & Patch** tab to submit policy rulings."
        )
    elif status == RunStatus.AWAITING_EDIT_DECISIONS:
        st.info(
            "📝 **Action Required: Review Proposed Policy Patch (Gate 2)** — An automated patch proposal has been drafted to resolve adjudicated loopholes. "
            "Go to the **Review & Patch** tab to review and approve clause edits."
        )
    elif status == RunStatus.COMPLETE_IMPROVED:
        st.success("✅ **Audit Complete:** Policy patch verified successfully with significant divergence reduction and zero regressions.")
    elif status == RunStatus.COMPLETE_NO_DIVERGENCE:
        st.success("✅ **Audit Complete:** Watertight policy. Zero divergences detected across all persona evaluations.")
    elif status == RunStatus.COMPLETE_NO_IMPROVEMENT:
        st.warning("⚠️ **Audit Complete:** Post-patch verification detected insufficient divergence reduction. Revise patch or inspect residual ambiguities.")

    # --- EXECUTIVE KPI METRICS BAR ---
    v1m = metrics.get("v1", {})
    # Determine divergent cases count dynamically
    div_case_ids = set()
    if v1_raw_verdicts:
        case_verdicts_map = defaultdict(set)
        for v in v1_raw_verdicts:
            case_verdicts_map[v["case_id"]].add(v["verdict"])
        div_case_ids = {cid for cid, vset in case_verdicts_map.items() if len(vset) > 1}
        
    divergent_count = v1m.get("divergent", len(div_case_ids))
    total_cases_count = len(cases)
    rate_val = v1m.get("rate", (divergent_count / total_cases_count) if total_cases_count > 0 else 0.0)
    rate_str = f"{rate_val:.1%}" if total_cases_count > 0 else "--"
    
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(
            f"""<div class="pf-metric-card">
                <div class="pf-metric-val">{len(clauses)}</div>
                <div class="pf-metric-label">Clauses Parsed</div>
            </div>""", unsafe_allow_html=True
        )
    with m2:
        st.markdown(
            f"""<div class="pf-metric-card">
                <div class="pf-metric-val">{total_cases_count}</div>
                <div class="pf-metric-label">Test Scenarios</div>
            </div>""", unsafe_allow_html=True
        )
    with m3:
        color = "#dc2626" if divergent_count > 0 else "#16a34a"
        st.markdown(
            f"""<div class="pf-metric-card">
                <div class="pf-metric-val" style="color: {color};">{divergent_count} <span style="font-size:0.9rem; font-weight:normal;">({rate_str})</span></div>
                <div class="pf-metric-label">Divergent Cases</div>
            </div>""", unsafe_allow_html=True
        )
    with m4:
        ruled_count = len(rulings)
        total_clusters = len(clusters)
        st.markdown(
            f"""<div class="pf-metric-card">
                <div class="pf-metric-val">{ruled_count} / {total_clusters}</div>
                <div class="pf-metric-label">Loopholes Ruled</div>
            </div>""", unsafe_allow_html=True
        )
    with m5:
        verif_k = f"v2r{round_num}" if f"v2r{round_num}" in metrics else (f"v2r{round_num-1}" if f"v2r{round_num-1}" in metrics else None)
        outcome_label = metrics[verif_k].get("outcome", "Pending") if verif_k else ("Ready" if status.startswith("COMPLETE") else ("Action Required" if status == RunStatus.AWAITING_EDIT_DECISIONS else "Pending"))
        color_outcome = "#16a34a" if outcome_label == "IMPROVED" else ("#b91c1c" if outcome_label == "REGRESSED" else "#0f172a")
        st.markdown(
            f"""<div class="pf-metric-card">
                <div class="pf-metric-val" style="font-size:1.35rem; color:{color_outcome};">{outcome_label}</div>
                <div class="pf-metric-label">Verification</div>
            </div>""", unsafe_allow_html=True
        )

    st.markdown("---")

    # --- CONSOLIDATED WORKFLOW TABS ---
    tab_overview, tab_cases, tab_review, tab_verification, tab_logs = st.tabs([
        "📊 Executive Overview & Verdict Matrix",
        "🔍 Policy Clauses & Test Scenarios",
        "⚖️ Review & Patch",
        "✅ Verification & Exports",
        "📑 Audit Trail & Logs"
    ])

    # === TAB 1: EXECUTIVE OVERVIEW & VERDICT MATRIX ===
    with tab_overview:
        st.subheader("Executive Audit Overview")
        if not cases:
            st.info("Generating adversarial cases and running independent persona evaluations...")
        else:
            ov_col1, ov_col2 = st.columns([1, 1], gap="medium")
            with ov_col1:
                st.markdown("#### Detected Ambiguity Clusters (Loopholes)")
                if clusters:
                    cluster_summary_data = []
                    for cl in clusters:
                        r = next((r for r in rulings if r.cluster_id == cl.cluster_id), None)
                        ruling_status = r.ruling if r else "Pending Review"
                        cluster_summary_data.append({
                            "Cluster": cl.cluster_id,
                            "Title": cl.label,
                            "Impact": cl.business_impact,
                            "Type": cl.loophole_type,
                            "Clauses": ", ".join(cl.involved_clauses),
                            "Cases": len(cl.case_ids),
                            "Ruling": ruling_status
                        })
                    st.dataframe(cluster_summary_data, width="stretch", hide_index=True)
                else:
                    if status in [RunStatus.CREATED, RunStatus.PARSED, RunStatus.CASES_READY]:
                        st.info("Divergence analysis and clustering in progress...")
                    else:
                        st.success("No ambiguity clusters detected. All persona interpretations were consistent.")
                        
            with ov_col2:
                st.markdown("#### Verification Summary")
                verif_k = f"v2r{round_num}" if f"v2r{round_num}" in metrics else (f"v2r{round_num-1}" if f"v2r{round_num-1}" in metrics else None)
                if verif_k:
                    vres = metrics[verif_k]
                    v_cols = st.columns(3)
                    v_cols[0].metric("Divergence Before", f"{vres.get('before_divergent', '--')}/{vres.get('before_total', '--')}")
                    v_cols[1].metric("Divergence After", f"{vres.get('after_divergent', '--')}/{vres.get('after_total', '--')}")
                    reduction = vres.get("divergence_reduction", 0.0)
                    v_cols[2].metric("Reduction", f"{reduction:.1%}")
                    
                    regress_count = len(vres.get("new_divergent_case_ids", []))
                    if regress_count == 0:
                        st.success("Zero regressions detected: no previously consistent cases broke after patch.")
                    else:
                        st.error(f"{regress_count} regression(s) detected: {', '.join(vres.get('new_divergent_case_ids', []))}")
                else:
                    st.info("Verification metrics will appear here once policy edits are approved and tested.")

            # --- FULL VERDICT MATRIX ---
            st.markdown("---")
            st.subheader("Complete Persona Verdict Matrix")
            st.caption("Derived from actual evaluator results across 3 independent personas (Literalist, Customer-Favorable, Business-Protective).")
            
            vm1, vm2, vm3, vm4 = st.columns(4)
            vm1.metric("Total Scenarios Evaluated", total_cases_count)
            vm2.metric("Unanimous Agreements", total_cases_count - divergent_count)
            vm3.metric("Divergent (Split) Scenarios", divergent_count)
            vm4.metric("Divergence Rate", rate_str)
            
            # Build matrix rows
            # Map verdicts by case_id and persona
            c_verdicts = defaultdict(dict)
            for v in v1_raw_verdicts:
                c_verdicts[v["case_id"]][v["interpreter"]] = v["verdict"]
                
            matrix_data = []
            for c in cases:
                v_map = c_verdicts.get(c.case_id, {})
                va = v_map.get("A", "--")
                vb = v_map.get("B", "--")
                vc = v_map.get("C", "--")
                
                is_div = c.case_id in div_case_ids
                status_str = "⚠️ Divergent" if is_div else (f"✓ Unanimous ({va})" if va != "--" else "Pending")
                
                matrix_data.append({
                    "Case ID": c.case_id,
                    "Title": c.title,
                    "Type": c.boundary_type,
                    "Persona A (Literal)": va,
                    "Persona B (Customer)": vb,
                    "Persona C (Business)": vc,
                    "Consensus": status_str
                })
                
            st.dataframe(matrix_data, width="stretch", hide_index=True, height=350)

    # === TAB 2: POLICY CLAUSES & TEST SCENARIOS ===
    with tab_cases:
        p_col, c_col = st.columns([1, 1], gap="medium")
        
        with p_col:
            st.subheader("Parsed Policy Clauses")
            if clauses:
                search_term = st.text_input("Filter clauses by keyword or ID", key="clause_search")
                filtered_clauses = clauses
                if search_term:
                    filtered_clauses = [
                        c for c in clauses 
                        if search_term.lower() in c.text.lower() or search_term.lower() in c.clause_id.lower() or search_term.lower() in c.section_title.lower()
                    ]
                st.caption(f"Showing {len(filtered_clauses)} of {len(clauses)} clauses")
                
                with st.container(height=520):
                    for cl in filtered_clauses:
                        st.markdown(f"**{cl.clause_id}** *({cl.section_title})*")
                        st.markdown(f"> {cl.text}")
            else:
                st.info("Policy parsing in progress...")
                
        with c_col:
            st.subheader("Adversarial Scenarios & Personas")
            if cases:
                filter_choice = st.radio(
                    "Filter Scenarios",
                    ["All", "Divergent Only", "Control Only"],
                    horizontal=True,
                    label_visibility="collapsed"
                )
                
                display_cases = cases
                if filter_choice == "Divergent Only":
                    display_cases = [c for c in cases if c.case_id in div_case_ids]
                elif filter_choice == "Control Only":
                    display_cases = [c for c in cases if c.boundary_type == "control"]
                    
                case_table_data = [
                    {
                        "ID": c.case_id,
                        "Title": c.title,
                        "Type": c.boundary_type,
                        "Targets": ", ".join(c.target_clauses),
                        "Divergence": "⚠️ Divergent" if c.case_id in div_case_ids else "✓ Consistent"
                    }
                    for c in display_cases
                ]
                st.dataframe(case_table_data, width="stretch", hide_index=True, height=220)
                
                # Master-Detail Scenario Inspector
                case_options = [c.case_id for c in display_cases]
                if case_options:
                    selected_case_id = st.selectbox("Inspect Scenario Details", case_options, format_func=lambda x: f"{x}: {next(c.title for c in cases if c.case_id == x)}")
                    selected_case = next(c for c in cases if c.case_id == selected_case_id)
                    
                    st.markdown(f"**Scenario Narrative ({selected_case.case_id} — {selected_case.title}):**")
                    st.markdown(f"> *{selected_case.narrative}*")
                    st.caption(f"Boundary Type: `{selected_case.boundary_type}` | Targeted Clauses: `{', '.join(selected_case.target_clauses)}`")
                    
                    st.markdown("##### Persona Evaluations:")
                    related_verdicts = [v for v in v1_raw_verdicts if v["case_id"] == selected_case_id]
                    if related_verdicts:
                        per_cols = st.columns(len(related_verdicts))
                        persona_names = {"A": "Persona A (Literalist)", "B": "Persona B (Customer Advocate)", "C": "Persona C (Business Risk)"}
                        for idx, v in enumerate(related_verdicts):
                            with per_cols[idx]:
                                badge_class = "pf-badge-allow" if v["verdict"] == "ALLOW" else ("pf-badge-deny" if v["verdict"] == "DENY" else "pf-badge-escalate")
                                p_label = persona_names.get(v["interpreter"], f"Persona {v['interpreter']}")
                                cited_list = json.loads(v["cited_json"]) if v.get("cited_json") else []
                                st.markdown(
                                    f"""<div class="pf-metric-card">
                                        <div style="font-weight:600; font-size:0.9rem;">{p_label}</div>
                                        <div style="margin: 6px 0;"><span class="pf-badge {badge_class}">{v['verdict']}</span> ({v['confidence']:.0%})</div>
                                        <div style="font-size:0.75rem; color:#64748b; margin-bottom:4px;">Cites: {', '.join(cited_list) if cited_list else 'None'}</div>
                                        <div style="font-size:0.82rem; color:#334155; line-height:1.4;">{v['rationale']}</div>
                                    </div>""", unsafe_allow_html=True
                                )
                    else:
                        st.info("Persona evaluations pending for this scenario.")
            else:
                st.info("Adversarial test cases will appear here once generated.")

    # === TAB 3: REVIEW & PATCH ===
    with tab_review:
        st.subheader("Loophole Adjudication & Patching Gate")
        
        if not clusters:
            st.info("No loopholes identified yet. Pipeline will advance here once divergence analysis completes.")
        else:
            # Sort clusters deterministically by rank (K3, K1, K2 order from analyst)
            sorted_clusters = sorted(clusters, key=lambda c: getattr(c, "rank", 999))
            ruled_map = {r.cluster_id: r for r in rulings}
            adjudicated_count = sum(1 for c in sorted_clusters if c.cluster_id in ruled_map)
            
            st.markdown(f"#### Step 1: Human Policy Decisions (Gate 1)")
            st.caption(f"Review discovered ambiguity clusters and record authoritative policy intent. ({adjudicated_count} of {len(sorted_clusters)} decided)")
            
            with st.form("adjudication_form"):
                form_inputs = {}
                for c in sorted_clusters:
                    r = ruled_map.get(c.cluster_id)
                    badge_cls = "pf-badge-high" if c.business_impact == "HIGH" else ("pf-badge-med" if c.business_impact == "MEDIUM" else "pf-badge-low")
                    
                    with st.container(border=True):
                        st.markdown(
                            f"**{c.cluster_id}: {c.label}** · <span class='pf-badge {badge_cls}'>{c.business_impact} IMPACT</span> · Type: `{c.loophole_type}`",
                            unsafe_allow_html=True
                        )
                        st.markdown(f"**Ambiguity Summary:** {c.summary}")
                        
                        # Show conflicted/involved clauses preview
                        c_involved = [cl for cl in clauses if cl.clause_id in c.involved_clauses]
                        if c_involved:
                            with st.expander("📄 View Conflicted Clause(s) in Current Policy", expanded=False):
                                for ic in c_involved:
                                    st.markdown(f"**Clause {ic.clause_id} ({ic.section_title}):**")
                                    st.caption(f"> {ic.text}")
                        else:
                            st.caption(f"Involved Clauses: `{', '.join(c.involved_clauses)}` | Affected Scenarios: `{', '.join(c.case_ids)}`")
                            
                        st.markdown("**How should the agent resolve this conflicted rule? (Resolution Directive)**")
                        col_r, col_n = st.columns([1, 2])
                        with col_r:
                            strat_options = [
                                "Close Loophole (Strict Rule)",
                                "Customer-Friendly (Allowed Exceptions)",
                                "Require Formal Escalation",
                                "Custom Directive"
                            ]
                            strat_choice = st.selectbox(
                                "Resolution Direction",
                                strat_options,
                                key=f"strat_{c.cluster_id}",
                                disabled=status != RunStatus.AWAITING_RULINGS
                            )
                            opts = ["ALLOW", "DENY", "ESCALATE", "SKIP"]
                            def_idx = opts.index(r.ruling) if r and r.ruling in opts else 0
                            choice = st.radio(
                                f"Authoritative Ruling for {c.cluster_id}",
                                opts,
                                index=def_idx,
                                key=f"ruling_{c.cluster_id}",
                                disabled=status != RunStatus.AWAITING_RULINGS,
                                horizontal=True
                            )
                        with col_n:
                            note = st.text_area(
                                "Tell the agent what to do / how to rewrite this rule (custom guidance):",
                                value=r.note if r else "",
                                key=f"note_{c.cluster_id}",
                                disabled=status != RunStatus.AWAITING_RULINGS,
                                placeholder="e.g. Explicitly state return window begins on delivery confirmation date, and allow 3-day grace period for transit delays.",
                                height=115
                            )
                        final_guidance = note.strip() if note.strip() else f"Directive: {strat_choice} with ruling {choice}."
                        form_inputs[c.cluster_id] = {"ruling": choice, "note": final_guidance}
                        
                if status == RunStatus.AWAITING_RULINGS:
                    submit_rulings_btn = st.form_submit_button("Submit Rulings & Synthesize Patch", type="primary")
                    if submit_rulings_btn:
                        submit_data = [
                            Ruling(cluster_id=k, ruling=v["ruling"], note=v["note"])
                            for k, v in form_inputs.items()
                        ]
                        orch = Orchestrator(conn, make_provider(settings), settings)
                        orch.submit_rulings(run_id, submit_data)
                        run_orchestrator_sync(run_id, "run_until_gate")
                        st.rerun()
                else:
                    st.success("✓ Policy decisions recorded and locked.")

            # --- PATCH PROPOSAL APPROVAL GATE (GATE 2) ---
            patch_row = db.get_patch(conn, run_id, round_num) or db.get_patch(conn, run_id, 1)
            if patch_row:
                st.markdown("---")
                st.markdown("#### Step 2: Policy Patch Review & Approval Gate (Gate 2)")
                st.caption("Human approval is strictly required before any policy text modifications are committed to verification.")
                
                proposal = PatchProposal.model_validate_json(patch_row["proposal_json"])
                decided_map = db.get_edit_decisions(conn, run_id, round_num)
                
                # Checkboxes default to False (unchecked) per HIT-03 & UIX-10
                with st.form("patch_approval_form"):
                    approval_states = {}
                    chosen_texts = {}
                    
                    for edit in proposal.edits:
                        with st.container(border=True):
                            st.markdown(f"#### Clause `{edit.clause_id}`: Targeted Rewrite ({edit.edit_id})")
                            st.caption(f"**Action:** `{edit.action}` · Addresses: {', '.join(edit.addresses_clusters)} · Rationale: {edit.rationale}")
                            
                            # Original text of this specific clause
                            orig_cl = next((cl for cl in clauses if cl.clause_id == edit.clause_id), None)
                            if orig_cl:
                                with st.expander(f"Original Text of Clause {edit.clause_id}", expanded=False):
                                    st.caption(f"> {orig_cl.text}")
                                    
                            # Two options for the user to choose from
                            opt1_text = edit.new_text
                            opt2_text = getattr(edit, "alt_text", None)
                            if not opt2_text:
                                if "cannot be returned" in opt1_text.lower() or "no exceptions" in opt1_text.lower():
                                    opt2_text = opt1_text.replace("No exceptions.", "Exceptions permitted with manager authorization and proof of purchase.")
                                else:
                                    opt2_text = f"{opt1_text} Verified carrier transit delays are granted a 3-day extension upon customer support review."
                                    
                            st.markdown("##### Choose either rewrite option:")
                            c_opt1, c_opt2 = st.columns(2)
                            with c_opt1:
                                st.markdown(
                                    f"""<div class="pf-option-card">
                                        <div style="font-weight:700; color:#1e3a8a; font-size:0.85rem; margin-bottom:4px;">🔘 Option 1: Strict / Definitive Rule</div>
                                        <div style="font-size:0.84rem; color:#1e293b; line-height:1.45;">{opt1_text}</div>
                                    </div>""", unsafe_allow_html=True
                                )
                            with c_opt2:
                                st.markdown(
                                    f"""<div class="pf-option-card">
                                        <div style="font-weight:700; color:#047857; font-size:0.85rem; margin-bottom:4px;">🔘 Option 2: Balanced / Conditional Rule</div>
                                        <div style="font-size:0.84rem; color:#1e293b; line-height:1.45;">{opt2_text}</div>
                                    </div>""", unsafe_allow_html=True
                                )
                                
                            chosen_opt = st.radio(
                                f"Select active option for Clause {edit.clause_id}:",
                                ["Option 1 (Strict / Explicit)", "Option 2 (Balanced / Conditional)"],
                                key=f"opt_sel_{edit.edit_id}",
                                horizontal=True,
                                disabled=status != RunStatus.AWAITING_EDIT_DECISIONS
                            )
                            
                            selected_text = opt1_text if "Option 1" in chosen_opt else opt2_text
                            
                            # Fine-tune expander
                            with st.expander(f"✏️ Customize / Edit Wording for Clause {edit.clause_id} (Optional)", expanded=False):
                                selected_text = st.text_area(
                                    f"Active rewrite for Clause {edit.clause_id}",
                                    value=selected_text,
                                    key=f"custom_txt_{edit.edit_id}",
                                    disabled=status != RunStatus.AWAITING_EDIT_DECISIONS,
                                    height=75
                                )
                                
                            chosen_texts[edit.edit_id] = selected_text
                            
                            st.markdown(f"**Applied Diff Preview:**")
                            st.code(f"+ {selected_text}", language="diff")
                            
                            # Checked state: False by default, or reflect stored decision
                            default_checked = decided_map.get(edit.edit_id, False) if decided_map.get(edit.edit_id) is not None else False
                            app_val = st.checkbox(
                                f"Approve and Apply this rewrite to Clause {edit.clause_id}",
                                value=default_checked,
                                key=f"chk_edit_{edit.edit_id}",
                                disabled=status != RunStatus.AWAITING_EDIT_DECISIONS
                            )
                            approval_states[edit.edit_id] = app_val
                            
                    if status == RunStatus.AWAITING_EDIT_DECISIONS:
                        c_app_all, c_sub = st.columns([1, 2])
                        apply_btn = st.form_submit_button("Approve Selected Edits & Run Verification", type="primary")
                        if apply_btn:
                            if not any(approval_states.values()):
                                st.error("At least one edit must be approved before proceeding with verification.")
                            else:
                                # Update proposal edits with the chosen options before applying
                                for edit in proposal.edits:
                                    if edit.edit_id in chosen_texts:
                                        edit.new_text = chosen_texts[edit.edit_id]
                                db.save_patch(conn, run_id, round_num, proposal, "PROPOSED")
                                
                                orch = Orchestrator(conn, make_provider(settings), settings)
                                orch.decide_edits(run_id, round_num, approval_states)
                                run_orchestrator_sync(run_id, "apply_and_verify")
                                st.rerun()
                    else:
                        st.success("✓ Patch approval completed.")

                # In-line Previews for Diff, Decision Table, and Sibling Cases
                with st.expander("View Unified Policy Diff", expanded=False):
                    orig_policy = ""
                    if run.get("policy_path") and os.path.exists(run["policy_path"]):
                        with open(run["policy_path"], "r", encoding="utf-8", errors="replace") as pf:
                            orig_policy = pf.read()
                    try:
                        patched_preview = orig_policy
                        diff_text = unified_diff(orig_policy, orig_policy)
                        if run.get("policy_path"):
                            policy_v2_path = Path(run["policy_path"]).parent / f"policy_v2_r{round_num}.txt"
                            if policy_v2_path.exists():
                                with open(policy_v2_path, "r", encoding="utf-8") as pf:
                                    patched_preview = pf.read()
                                diff_text = unified_diff(orig_policy, patched_preview)
                        st.code(diff_text if diff_text else "No diff available.", language="diff")
                    except Exception as e:
                        st.caption(f"Diff preview: {e}")

                with st.expander("View Policy Decision Table", expanded=False):
                    tbl_md = decision_table_md(proposal.decision_table)
                    st.markdown(tbl_md if tbl_md else "No decision table available.")

                with st.expander("View Generated Sibling Generalization Cases", expanded=False):
                    if proposal.sibling_cases:
                        for sc in proposal.sibling_cases:
                            st.markdown(f"**{sc.case_id}: {sc.title}** ({sc.boundary_type})")
                            st.markdown(f"> *{sc.narrative}*")
                            st.caption(f"Targets: {', '.join(sc.target_clauses)} | Expected Verdict: `{proposal.sibling_expected.get(sc.case_id, 'UNKNOWN')}`")
                    else:
                        st.caption("No sibling cases generated.")

    # === TAB 4: VERIFICATION & EXPORTS ===
    with tab_verification:
        st.subheader("Verification Analysis & Artifact Downloads")
        verif_k = f"v2r{round_num}" if f"v2r{round_num}" in metrics else (f"v2r{round_num-1}" if f"v2r{round_num-1}" in metrics else None)
        
        if verif_k:
            vres = metrics[verif_k]
            res_col1, res_col2 = st.columns([1, 1], gap="medium")
            
            with res_col1:
                st.markdown("#### Quantitative Verification Metrics")
                vm1, vm2 = st.columns(2)
                vm1.metric("Original Divergence", f"{vres.get('before_divergent', '--')}/{vres.get('before_total', '--')}")
                vm2.metric("Post-Patch Divergence", f"{vres.get('after_divergent', '--')}/{vres.get('after_total', '--')}")
                
                red = vres.get("divergence_reduction", 0.0)
                st.metric("Divergence Reduction", f"{red:.1%}", help="Requires >= 50% reduction to satisfy success criteria")
                
                conformance_hits = vres.get("conformance_hits", 0)
                conformance_total = vres.get("conformance_total", 1)
                st.metric("Adjudication Conformance Rate", f"{conformance_hits}/{conformance_total} ({conformance_hits/max(1, conformance_total):.1%})", help="Requires >= 80% conformance")
                
            with res_col2:
                st.markdown("#### Regression & Generalization Analysis")
                new_divs = vres.get("new_divergent_case_ids", [])
                if not new_divs:
                    st.success("✓ **Zero Regressions:** All previously agreed scenarios remained consistent.")
                else:
                    st.error(f"⚠️ **Regressions Detected:** Scenarios {', '.join(new_divs)} diverged after patch application.")
                    
                sibling_div = vres.get("sibling_divergent", 0)
                sibling_tot = vres.get("sibling_total", 0)
                st.metric("Sibling Generalization Failures", f"{sibling_div} / {sibling_tot}")
                
                outcome = vres.get("outcome", "UNKNOWN")
                badge_class = "pf-badge-allow" if outcome == "IMPROVED" else ("pf-badge-deny" if outcome == "REGRESSED" else "pf-badge-escalate")
                st.markdown(f"**Verification Outcome:** <span class='pf-badge {badge_class}' style='font-size:1rem;'>{outcome}</span>", unsafe_allow_html=True)
                
            # Per-Cluster Breakdown
            if "per_cluster" in vres:
                st.markdown("##### Per-Cluster Ambiguity Resolution:")
                pc_data = [
                    {
                        "Cluster ID": cid,
                        "Before Divergent": cinfo.get("before", "--"),
                        "After Divergent": cinfo.get("after", "--"),
                        "Status": "Resolved ✓" if cinfo.get("after", 1) == 0 else "Partially Resolved"
                    }
                    for cid, cinfo in vres["per_cluster"].items()
                ]
                st.dataframe(pc_data, width="stretch", hide_index=True)

            st.markdown("---")
            st.markdown("#### Export Audit Artifacts")
            
            exp1, exp2, exp3, exp4 = st.columns(4)
            # Patched policy
            policy_path = Path(run["policy_path"]).parent / f"policy_v2_r{round_num}.txt"
            if not policy_path.exists():
                policy_path = Path(run["policy_path"]).parent / f"policy_v2_r{round_num-1}.txt"
                
            if policy_path.exists():
                with open(policy_path, "r", encoding="utf-8") as pf:
                    exp1.download_button("📥 Patched Policy (.txt)", pf.read(), file_name=policy_path.name, width="stretch")
                    
            report_md_str = build_report_md(conn, run_id)
            exp2.download_button("📥 Audit Report (.md)", report_md_str, file_name="audit_report.md", width="stretch")
            
            reg_cases = build_regression_cases(conn, run_id)
            exp3.download_button("📥 Regression Cases (.json)", json.dumps(reg_cases, indent=2), file_name="regression_cases.json", width="stretch")
            
            patch_row = db.get_patch(conn, run_id, round_num) or db.get_patch(conn, run_id, round_num-1)
            if patch_row:
                proposal = PatchProposal.model_validate_json(patch_row["proposal_json"])
                tbl_md = decision_table_md(proposal.decision_table)
                exp4.download_button("📥 Decision Table (.md)", tbl_md, file_name="decision_table.md", width="stretch")
        else:
            st.info("Verification results will be displayed here once a policy patch is approved and verified.")

    # === TAB 5: AUDIT TRAIL & LOGS ===
    with tab_logs:
        st.subheader("Audit Trail & Traceability")
        c = conn.cursor()
        
        # Events
        st.markdown("##### System Transition Events")
        c.execute("SELECT ts, stage, level, message FROM events WHERE run_id=? ORDER BY id DESC", (run_id,))
        evs = c.fetchall()
        if evs:
            st.dataframe([dict(e) for e in evs], width="stretch", hide_index=True, height=250)
        else:
            st.caption("No events recorded yet.")
            
        # LLM Traces
        st.markdown("##### LLM Call Record")
        c.execute("SELECT id, ts, call_key, role, provider, model, latency_ms, parsed_ok FROM llm_calls WHERE run_id=? ORDER BY id DESC", (run_id,))
        traces = c.fetchall()
        if traces:
            trace_data = [
                {
                    "Call ID": t["id"],
                    "Timestamp": t["ts"][:19],
                    "Call Key": t["call_key"],
                    "Role": t["role"],
                    "Model": t["model"],
                    "Latency (ms)": t["latency_ms"],
                    "Status": "OK ✓" if t["parsed_ok"] else "Failed ✗"
                }
                for t in traces
            ]
            st.dataframe(trace_data, width="stretch", hide_index=True, height=250)
            
            with st.expander("Inspect Raw LLM Call Trace", expanded=False):
                trace_ids = [t["id"] for t in traces]
                sel_id = st.selectbox("Select Call ID", trace_ids)
                c.execute("SELECT request_json, response_text, error FROM llm_calls WHERE id=?", (sel_id,))
                t_detail = c.fetchone()
                if t_detail:
                    st.markdown("**Request Payload:**")
                    st.code(t_detail[0], language="json")
                    st.markdown("**Response Text:**")
                    st.code(t_detail[1], language="json")
                    if t_detail[2]:
                        st.error(f"Error: {t_detail[2]}")
        else:
            st.caption("No LLM calls recorded yet.")

if __name__ == "__main__":
    main()
