"""
Run Pipeline — button that runs main.py (MT5 sync x2 -> Yahoo sync ->
detection pipeline) as a subprocess and streams its stdout live into the
page, so refreshing the underlying data doesn't require a separate
terminal. Confirmed feasible during the dashboard survey: Streamlit
supports incremental UI updates mid-script-execution (each st.write/code
call within the same run streams a delta to the browser as it happens),
so no threading/session-state process tracking is needed -- a single
button-triggered block can loop over the subprocess's stdout and update
the page live.

Progress is tracked against main.py's own known 4-stage structure (MT5
sync XAUUSD, MT5 sync EURUSD, Yahoo sync, Detection pipeline -- see
main.py's run_step() calls) by counting "[OK]"/"[FAIL]" lines, which
main.py prints once per completed stage regardless of outcome.

This blocks the browser tab's Streamlit session for the whole run (a full
run takes real time -- MT5 sync + Yahoo sync + the full detection
pipeline) -- acceptable for a manual "refresh data" action, not meant to
be a background job. New page, nothing to rebuild from.
"""

import sys
import subprocess
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent.parent.parent
MAIN_PY = ROOT / "main.py"

st.set_page_config(
    page_title="Run Pipeline",
    page_icon="P",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  .stApp { background:#000; font-family:'Inter',sans-serif; }
  header[data-testid="stHeader"] { background:#000; }
  .block-container { padding:2.6rem 1rem 0 1rem; max-width:100%; }
  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em; color:#787b86;
    text-transform:uppercase; margin-bottom:10px; border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }
  .warn-box {
    background:#140d0d; border:1px solid #2e1e1e; border-radius:6px;
    padding:14px 16px; margin-bottom:16px; font-size:12px; color:#a08080; line-height:1.6;
  }
  .warn-box b { color:#d4b16a; }
  footer { visibility:hidden; } #MainMenu { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

STAGES = [
    "MT5 sync -- XAUUSD (m5/m15/h1)",
    "MT5 sync -- EURUSD (m5/m15/h1)",
    "Yahoo sync (gold/eurusd h4+d1, DXY/US10Y/VIX/GDX)",
    "Detection pipeline (features -> SMC -> CRT -> sweeps -> volume profile -> divergence -> HTF bias -> Composite Confluence signals + resolution)",
]

st.markdown("""
<div class="warn-box">
  <b>Runs main.py end to end</b> -- MT5 sync (XAUUSD then EURUSD), Yahoo sync, then the full
  detection pipeline. This blocks this browser tab until finished (real time, not a background
  job) and requires an MT5 terminal to be reachable for the sync stages. Stops on the first
  failed stage, same as running <code>python main.py</code> directly.
</div>
""", unsafe_allow_html=True)

no_write = st.checkbox("--no-write (detection stages only: report, skip DB upserts)", value=False)

run_clicked = st.button("Run Pipeline", type="primary", use_container_width=False)

if run_clicked:
    st.markdown('<div class="panel-title">Progress</div>', unsafe_allow_html=True)
    progress_bar = st.progress(0.0)
    stage_label = st.empty()
    status = st.status("Starting main.py...", expanded=True)
    log_area = status.empty()

    cmd = [sys.executable, str(MAIN_PY)]
    if no_write:
        cmd.append("--no-write")

    log_lines = []
    completed_count = 0
    current_stage = None
    # 3-state machine over main.py's own header pattern (blank line, 70
    # '#'s, label, 70 '#'s -- see run_step() in main.py). A 2-state
    # boolean toggle is NOT enough here: it flips on every hash line
    # encountered, so the CLOSING hash line re-arms "awaiting label" and
    # the very next line (e.g. an "[OK] ..." line) gets wrongly captured
    # as the next stage's label -- caught by testing this against a mock
    # stage-emitting script before wiring it to the real subprocess.
    # "idle": normal output. "await_label": just saw the opening hash, the
    # next line is the label. "await_close": consume the closing hash and
    # go back to idle, ignoring everything else in between.
    HASH_LINE = "#" * 70
    state = "idle"

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            stripped = line.rstrip("\n")
            log_lines.append(stripped)
            s = stripped.strip()

            if state == "idle":
                if s == HASH_LINE:
                    state = "await_label"
            elif state == "await_label":
                current_stage = s
                stage_label.markdown(f"**Current stage:** {current_stage}")
                state = "await_close"
            elif state == "await_close":
                if s == HASH_LINE:
                    state = "idle"

            if s.startswith("[OK]") or s.startswith("[FAIL]"):
                completed_count += 1
                progress_bar.progress(min(completed_count / len(STAGES), 1.0))

            log_area.code("\n".join(log_lines[-300:]), language="text")

        returncode = proc.wait()

        if returncode == 0:
            status.update(label="Pipeline completed successfully", state="complete", expanded=False)
            st.success("Done. Cached dashboard data will refresh on next page load / cache clear.")
            st.cache_data.clear()
        else:
            status.update(label=f"Pipeline failed (exit code {returncode})", state="error", expanded=True)
            st.error(f"main.py exited with code {returncode} — see log above for the failing stage.")
    except FileNotFoundError as e:
        status.update(label="Failed to start", state="error")
        st.error(f"Could not start main.py: {e}")

st.markdown("")
st.markdown('<div class="panel-title">Known Stages</div>', unsafe_allow_html=True)
for i, s in enumerate(STAGES, 1):
    st.markdown(f"{i}. {s}")
