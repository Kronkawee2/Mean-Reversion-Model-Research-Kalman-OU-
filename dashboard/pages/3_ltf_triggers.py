"""
LTF Triggers — default view is the production Composite Confluence Engine
(curated_<symbol>.composite_confluence_signals: SMC multi-timeframe +
Divergence + Liquidity Sweep, CRT dropped from scoring, see
analysis/strategies/composite_confluence_engine.py and docs/DECISIONS.md).
The original single-factor baseline (ltf_trigger_signals, Mode A choch_only
/ Mode B choch_sweep) is kept available as a secondary/comparison system,
selectable via the "Signal System" control.

Separately, and NOT to be confused with the above: ltf_trigger_signals also
has an "Experimental" confluence_zone-sourced path (multi-factor HTF zone
clustering, mode_a_2factor/mode_b_3factor) that is a different, still-
genuinely-experimental system -- it showed materially worse drawdown/skew
in backtesting and has no capital-management layer built for it. That
toggle is unrelated to the Composite Confluence Engine and keeps its
"Experimental" warning banner, only visible when the Baseline system is
selected (it filters ltf_trigger_signals, not composite_confluence_signals).
"""

import os, sys, json
import pymysql, pymysql.cursors
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from dotenv import load_dotenv

DASH = Path(__file__).parent.parent
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))
if str(DASH.parent) not in sys.path:
    sys.path.insert(0, str(DASH.parent))
load_dotenv(DASH.parent / ".env")

from analysis.strategies import composite_confluence_engine as cce  # noqa: E402

st.set_page_config(
    page_title="LTF Triggers",
    page_icon="T",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], section[data-testid="stMain"], .main {
    background-color: #000000 !important; background: #000000 !important;
  }
  .block-container { padding:2.6rem 0.8rem 0 0.8rem; max-width:100%; }
  div[data-testid="stStatusWidget"], #MainMenu, footer { display:none !important; visibility:hidden !important; }

  .sig-card {
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:6px;
    padding:12px 14px; cursor:pointer; height:auto !important; min-height:110px;
    box-sizing:border-box; transition:border-color 0.2s ease, background-color 0.2s ease, transform 0.1s ease;
    user-select:none; margin-bottom:12px;
  }
  .sig-card:hover { border-color:#d4b16a; background:#141422; transform:translateY(-1px); }
  .sig-card.selected { border-color:#d4b16a !important; background:#181828; box-shadow:0 0 12px rgba(212,177,106,0.2); }

  .sig-dir-bull { color:#26a69a; font-size:16px; font-weight:700; }
  .sig-dir-bear { color:#ef5350; font-size:16px; font-weight:700; }
  .sig-lbl { color:#555; font-size:10px; }
  .sig-val    { color:#d1d4dc; font-size:13px; font-weight:600; }
  .sig-val-sl { color:#ef5350; font-size:13px; font-weight:600; }
  .sig-val-tp { color:#26a69a; font-size:13px; font-weight:600; }

  .badge { display:inline-block; font-size:9px; font-weight:700; padding:2px 6px; border-radius:3px;
           margin:1px; background:#1a1a2e; color:#787b86; border:1px solid #222; }

  .status-structural       { color:#26a69a; font-size:10px; font-weight:600; }
  .status-stop_too_tight   { color:#d4b16a; font-size:10px; font-weight:600; }
  .status-no_opposing_zone { color:#787b86; font-size:10px; font-weight:600; }
  .status-invalid_geometry { color:#ef5350; font-size:10px; font-weight:600; }
  .status-win  { color:#26a69a; font-size:10px; font-weight:600; }
  .status-loss { color:#ef5350; font-size:10px; font-weight:600; }
  .status-open { color:#787b86; font-size:10px; font-weight:600; }
  .status-wait { color:#ffa726; font-size:10px; font-weight:600; }

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em; color:#787b86;
    text-transform:uppercase; margin-bottom:10px; border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }

  .prod-badge {
    display:inline-block; font-size:9px; font-weight:700; padding:2px 6px; border-radius:3px;
    margin:1px; background:#0e2418; color:#26a69a; border:1px solid #1a4d34;
  }
  .exp-badge {
    display:inline-block; font-size:9px; font-weight:700; padding:2px 6px; border-radius:3px;
    margin:1px; background:#2e1f00; color:#d4b16a; border:1px solid #55420c;
  }
  .prod-banner {
    background:#0a1a12; border:1px solid #1a4d34; border-radius:6px; padding:8px 12px;
    color:#5fc9a4; font-size:12px; margin-bottom:14px;
  }
  .exp-banner {
    background:#1a1400; border:1px solid #55420c; border-radius:6px; padding:8px 12px;
    color:#d4b16a; font-size:12px; margin-bottom:14px;
  }
  .factor-row {
    display:flex; justify-content:space-between; align-items:center;
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:4px;
    padding:6px 10px; margin-bottom:6px; font-size:12px;
  }
  .factor-type { color:#d4b16a; font-weight:600; }
  .factor-detail { color:#787b86; font-size:11px; }
  .factor-on  { color:#26a69a; font-weight:700; }
  .factor-off { color:#444; font-weight:700; }
</style>
""", unsafe_allow_html=True)

DB = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", "3308")),
    "user":    os.getenv("DB_USER", "quant_user"),
    "password":os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
}
ASSETS = {
    "XAUUSD": {"raw_db": "raw_gold",   "curated_db": "curated_gold",   "dec": 2},
    "EURUSD": {"raw_db": "raw_eurusd", "curated_db": "curated_eurusd", "dec": 5},
}
MODE_LABELS = {"choch_only": "Mode A — CHoCH only", "choch_sweep": "Mode B — CHoCH + Sweep"}
CONFLUENCE_MODE_LABELS = {"mode_a_2factor": "2-factor confluence", "mode_b_3factor": "3-factor confluence"}
FACTOR_LABELS = {
    "OB": "Order Block", "FVG": "Fair Value Gap", "SwingSR": "Swing S/R",
    "CHoCH": "CHoCH", "Sweep": "Liquidity Sweep",
}
TF_LABEL = {"d1": "D1", "h6": "H6", "h4": "H4", "h1": "H1", "m15": "M15", "m5": "M5"}
COMPOSITE_FACTOR_LABELS = {
    "f_sweep": "Liquidity Sweep", "f_choch": "CHoCH", "f_zone_stack": "Zone Stack (D1>H6>H4>H1)",
    "f_bias": "HTF Bias", "f_div": "Divergence",
}
SYSTEM_LABELS = {
    "composite": "Composite Confluence Engine (production)",
    "baseline": "Baseline LTF Trigger (single-factor)",
}

# Composite Confluence Engine (composite_confluence_signals) is the adopted
# production system (see docs/DECISIONS.md) -- SMC multi-timeframe
# (zone_stack weighted D1>H6>H4>H1) + Divergence + Liquidity Sweep, CRT
# computed but excluded from scoring after isolation testing showed it
# wasn't the rejection bottleneck and hurt performance as a gate. This is
# the default system on this page.
#
# Baseline = the original single-factor smc_signals path (h1 HTF zones,
# choch_only/choch_sweep LTF confirmation), kept as a secondary/comparison
# view. Its own "Experimental" confluence_zone toggle is a THIRD, unrelated
# system (multi-factor HTF zone clustering) that remains genuinely
# experimental -- worse drawdown/skew, no capital-management layer -- and
# is untouched by the Composite Confluence Engine's production adoption.


def _conn(db_name):
    return pymysql.connect(**DB, database=db_name, cursorclass=pymysql.cursors.DictCursor)


@st.cache_data(ttl=30)
def load_triggers(curated_db: str, symbol: str, mode: str, zone_source: str,
                   target_zone_source: str, confluence_mode: str | None, limit: int = 200) -> list:
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            sql = ("SELECT * FROM ltf_trigger_signals WHERE symbol=%s AND mode=%s "
                   "AND zone_source=%s AND target_zone_source=%s")
            params = [symbol, mode, zone_source, target_zone_source]
            if confluence_mode:
                sql += " AND confluence_mode=%s"
                params.append(confluence_mode)
            sql += " ORDER BY confirmed_at_bar DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        for k in ("htf_zone_top", "htf_zone_bottom", "entry_price", "stop_price", "target_price", "structural_rr"):
            if r.get(k) is not None:
                r[k] = float(r[k])
    return rows


@st.cache_data(ttl=30)
def load_composite_signals(curated_db: str, symbol: str, exit_reason: str | None, limit: int = 200) -> list:
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            sql = "SELECT * FROM composite_confluence_signals WHERE symbol=%s"
            params = [symbol]
            if exit_reason:
                sql += " AND exit_reason=%s"
                params.append(exit_reason)
            sql += " ORDER BY confirmed_at_bar DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        for k in ("entry_price", "stop_price", "risk", "tp1_price", "tp1_rr", "r_outcome"):
            if r.get(k) is not None:
                r[k] = float(r[k])
        if isinstance(r.get("targets"), str):
            r["targets"] = json.loads(r["targets"])
        # normalize onto the same field names the shared card/chart renderers use
        r["target_price"] = r["tp1_price"]
        r["structural_rr"] = r["tp1_rr"]
        r["target_status"] = r["exit_reason"]
        r["htf_zone_type"] = None
        r["sweep_type"] = None
        r["zone_source"] = "composite_confluence"
    return rows


@st.cache_data(ttl=30)
def load_waiting_chains(curated_db: str, raw_db: str, symbol: str, limit: int = 5) -> list:
    """Nested Zone Drilling chains that were found (see docs/DECISIONS.md)
    but whose terminal zone has NEVER been touched by price since it
    formed -- not yet a candidate at all (composite_confluence_signals only
    ever gets a row once a touch happens), so these don't exist anywhere
    else in the dashboard. This is a "here's what to watch" list, not a
    promise: even once price arrives, the touch still has to clear the 5-
    factor composite score (~13-16% of touches do, per the validated
    comparisons) before it becomes a real signal. Sorted by distance from
    the current price, nearest first."""
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT direction, root_timeframe, terminal_timeframe, chain, "
                "zone_type, zone_top, zone_bottom, created_at_bar FROM nested_zone_chains "
                "WHERE symbol=%s ORDER BY created_at_bar DESC",
                (symbol,),
            )
            chains = cur.fetchall()
    finally:
        conn.close()
    if not chains:
        return []

    conn = _conn(raw_db)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT close_price FROM m15 ORDER BY price_datetime DESC LIMIT 1")
            latest = cur.fetchone()
            current_price = float(latest["close_price"]) if latest else None
            earliest_created = min(pd.Timestamp(c["created_at_bar"]) for c in chains)
            cur.execute(
                "SELECT price_datetime, high_price, low_price, close_price FROM m15 "
                "WHERE price_datetime >= %s ORDER BY price_datetime",
                (earliest_created,),
            )
            m15_rows = cur.fetchall()
    finally:
        conn.close()
    if current_price is None or not m15_rows:
        return []
    m15 = pd.DataFrame(m15_rows)
    m15["price_datetime"] = pd.to_datetime(m15["price_datetime"])
    for col in ("high_price", "low_price", "close_price"):
        m15[col] = m15[col].astype(float)

    # Reuse the EXACT production touch-detection logic (build_candidates())
    # rather than a naive high/low overlap check -- a naive check counts a
    # zone's own FORMATION bar as a "touch" (a swing_support zone's defining
    # bar sits exactly at that price by construction), so literally every
    # zone looked pre-touched immediately at creation. build_candidates()
    # already accounts for this via its formation-close gate (one bar of
    # the zone's own timeframe must pass first) -- the same gate that made
    # the production entry mechanism correct in the first place.
    zones_df = pd.DataFrame([{
        "zone_type": c["zone_type"], "zone_top": float(c["zone_top"]), "zone_bottom": float(c["zone_bottom"]),
        "created_at_bar": c["created_at_bar"], "invalidated_at_bar": None, "timeframe": c["terminal_timeframe"],
    } for c in chains])
    touched_candidates = cce.build_candidates(m15, zones_df)
    touched_keys = {(round(r["zone_top"], 5), round(r["zone_bottom"], 5)) for _, r in touched_candidates.iterrows()}

    waiting = []
    for c in chains:
        top, bottom = float(c["zone_top"]), float(c["zone_bottom"])
        if (round(top, 5), round(bottom, 5)) in touched_keys:
            continue
        near_edge = bottom if c["direction"] == "bullish" else top
        far_edge = top if c["direction"] == "bullish" else bottom
        distance = abs(current_price - near_edge)
        levels = json.loads(c["chain"]) if isinstance(c["chain"], str) else c["chain"]
        waiting.append({
            "symbol": symbol, "ltf_timeframe": "m15", "direction": c["direction"],
            "confirmed_at_bar": c["created_at_bar"], "entry_price": near_edge, "stop_price": far_edge,
            "target_price": None, "structural_rr": None, "target_status": "wait", "score": None,
            "risk": None, "f_sweep": 0, "zone_chain": levels,
            "root_timeframe": c["root_timeframe"], "terminal_timeframe": c["terminal_timeframe"],
            "_distance": distance,
        })
    waiting.sort(key=lambda w: w["_distance"])
    return waiting[:limit]


@st.cache_data(ttl=30)
def load_confluence_zone(curated_db: str, zone_id: int) -> dict | None:
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM confluence_zones WHERE id=%s", (zone_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if row and isinstance(row.get("factors"), str):
        row["factors"] = json.loads(row["factors"])
    return row


@st.cache_data(ttl=30)
def load_ohlcv_window(db_name, table, center_dt, bars_before=40, bars_after=40):
    """Bars centered on center_dt, not the most-recent-N-bars -- the old
    approach (load latest 200, then locally search for the signal's
    timestamp inside that window) silently produced an unrelated chart
    whenever a signal's confirmed_at_bar was older than the most recent
    ~2 days of data (200 m15 bars), which happens whenever the detection
    pipeline hasn't re-run since the signal was confirmed -- exactly the
    composite table's current state (latest signal 2026-08-12, raw m15
    data through 2026-08-17). Two bounded queries instead of one
    unbounded DESC scan, since MySQL can't efficiently do a symmetric
    "N rows around this timestamp" in one query without a window function."""
    try:
        conn = _conn(db_name)
        cur = conn.cursor()
        cur.execute(
            f"SELECT price_datetime,open_price,high_price,low_price,close_price,volume "
            f"FROM `{table}` WHERE price_datetime <= %s ORDER BY price_datetime DESC LIMIT %s",
            (center_dt, bars_before),
        )
        before_rows = cur.fetchall()
        cur.execute(
            f"SELECT price_datetime,open_price,high_price,low_price,close_price,volume "
            f"FROM `{table}` WHERE price_datetime > %s ORDER BY price_datetime ASC LIMIT %s",
            (center_dt, bars_after),
        )
        after_rows = cur.fetchall()
        cur.close(); conn.close()
        # pymysql's fetchall() returns () instead of [] when a query
        # matches zero rows -- harmless normally, but list + tuple raises,
        # which only ever surfaced once "wait" entries started centering
        # on the current moment (genuinely zero bars exist AFTER "now").
        df = pd.DataFrame(list(before_rows) + list(after_rows))
        if df.empty: return df
        df["price_datetime"] = pd.to_datetime(df["price_datetime"])
        for c in ["open_price","high_price","low_price","close_price","volume"]:
            df[c] = df[c].astype(float)
        return df.sort_values("price_datetime").reset_index(drop=True)
    except Exception as e:
        st.error(f"DB load error: {db_name}.{table} — {e}")
        return pd.DataFrame()


def render_mini_chart(df_window: pd.DataFrame, trig: dict, dec: int):
    """m15 candles around confirmed_at_bar, with Entry/Stop/Target lines."""
    candles = [{
        "time": int(r["price_datetime"].timestamp()),
        "open": round(float(r["open_price"]), dec), "high": round(float(r["high_price"]), dec),
        "low": round(float(r["low_price"]), dec), "close": round(float(r["close_price"]), dec),
    } for _, r in df_window.iterrows()]

    direction = trig["direction"]
    sig_time = int(pd.Timestamp(trig["confirmed_at_bar"]).timestamp())
    has_target = trig.get("entry_price") is not None and trig.get("stop_price") is not None

    lines_js = ""
    if has_target:
        lines_js += (f"series.createPriceLine({{price:{trig['entry_price']}, color:'#d4b16a', lineWidth:1, "
                     f"lineStyle:0, title:'Entry', axisLabelVisible:true}});")
        lines_js += (f"series.createPriceLine({{price:{trig['stop_price']}, color:'#ef5350', lineWidth:1, "
                     f"lineStyle:2, title:'Stop', axisLabelVisible:true}});")
        if trig.get("target_price") is not None:
            lines_js += (f"series.createPriceLine({{price:{trig['target_price']}, color:'#26a69a', lineWidth:1, "
                         f"lineStyle:2, title:'Target', axisLabelVisible:true}});")

    html = f"""<!DOCTYPE html>
<html><head>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>*{{box-sizing:border-box;margin:0;padding:0;}}body{{background:#000;overflow:hidden;}}#chart{{width:100%;height:400px;}}</style>
</head><body>
<div id="chart"></div>
<script>
try {{
  const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    autoSize:true,
    layout:{{background:{{type:'solid',color:'#000'}}, textColor:'#787b86', fontFamily:'Inter,sans-serif', fontSize:10}},
    grid:{{vertLines:{{color:'#111'}}, horzLines:{{color:'#111'}}}},
    rightPriceScale:{{borderColor:'#1e1e2e'}},
    timeScale:{{borderColor:'#1e1e2e', timeVisible:true, secondsVisible:false}},
    crosshair:{{vertLine:{{color:'#333',style:2}}, horzLine:{{color:'#333',style:2}}}},
  }});
  const series = chart.addCandlestickSeries({{
    upColor:'#d1d4dc', downColor:'#555', borderUpColor:'#d1d4dc', borderDownColor:'#555',
    wickUpColor:'#d1d4dc', wickDownColor:'#555', lastValueVisible:false, priceLineVisible:false,
  }});
  series.setData({json.dumps(candles)});
  {lines_js}
  series.setMarkers([{{
    time: {sig_time},
    position: '{"belowBar" if direction == "bullish" else "aboveBar"}',
    color: '{"#26a69a" if direction == "bullish" else "#ef5350"}',
    shape: '{"arrowUp" if direction == "bullish" else "arrowDown"}',
    text: 'confirmed',
  }}]);
  chart.timeScale().fitContent();
}} catch(e) {{
  document.body.innerHTML = '<div style="color:#ef5350;padding:20px;font-family:monospace;font-size:12px;">Chart error: '+e.message+'</div>';
}}
</script>
</body></html>"""
    components.html(html, height=400, scrolling=False)


@st.fragment
def render_trigger_workspace(filtered: list, curated_db: str, symbol: str, dec: int, raw_db: str, system: str):
    if "sel" in st.query_params:
        try:
            st.session_state.selected_trig_idx = int(st.query_params["sel"])
        except (ValueError, TypeError):
            pass
    if "selected_trig_idx" not in st.session_state:
        st.session_state.selected_trig_idx = 0

    sel_idx = min(st.session_state.selected_trig_idx, max(0, len(filtered) - 1))
    left_col, right_col = st.columns([1, 1.6])

    with left_col:
        st.markdown('<div class="panel-title">Trigger Cards</div>', unsafe_allow_html=True)
        with st.container(height=560, border=False):
            for i, t in enumerate(filtered[:30]):
                dir_class = "sig-dir-bull" if t["direction"] == "bullish" else "sig-dir-bear"
                dir_arrow = "▲ LONG" if t["direction"] == "bullish" else "▼ SHORT"
                status = t["target_status"] or "pending"
                st_class = f"status-{status}"
                selected = "selected" if i == sel_idx else ""
                target_disp = f"{t['target_price']:.{dec}f}" if t.get("target_price") is not None else "—"
                rr_badge = f'<span class="badge">R:R {t["structural_rr"]:.2f}</span>' if t.get("structural_rr") is not None else ""

                if system == "composite":
                    zone_badge = (f'<span class="prod-badge">SCORE {t["score"]}/5</span>' if t.get("score") is not None
                                  else '<span class="badge">not yet scored</span>')
                    sweep_badge = f'<span class="badge">SWEEP</span>' if t.get("f_sweep") else ""
                    exp_badge = ""
                else:
                    zone_badge = f'<span class="badge">{t["htf_zone_type"]}</span>'
                    sweep_badge = f'<span class="badge">{t["sweep_type"].upper()}</span>' if t.get("sweep_type") else ""
                    exp_badge = '<span class="exp-badge">EXPERIMENTAL</span>' if t.get("zone_source") == "confluence_zone" else ""

                st.markdown(f"""
<a href="?sel={i}" target="_self" style="text-decoration:none; color:inherit; display:block;">
  <div class="sig-card {selected}">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span class="{dir_class}">{dir_arrow}</span>
      <span class="{st_class}">{status.replace('_',' ').upper()}</span>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:8px;">
      <div><div class="sig-lbl">Entry</div><div class="sig-val">{t['entry_price']:.{dec}f}</div></div>
      <div><div class="sig-lbl">Stop</div><div class="sig-val-sl">{t['stop_price']:.{dec}f}</div></div>
      <div><div class="sig-lbl">Target</div><div class="sig-val-tp">{target_disp}</div></div>
    </div>
    <div style="margin-top:6px;">{zone_badge}{rr_badge}{sweep_badge}{exp_badge}</div>
    <div style="display:flex;justify-content:space-between;margin-top:6px;">
      <span style="font-size:10px;color:#555;">{t['symbol']} {t['ltf_timeframe']} · {str(t['confirmed_at_bar'])[:16]}</span>
    </div>
  </div>
</a>
""", unsafe_allow_html=True)

    with right_col:
        st.markdown('<div class="panel-title">Trigger Chart Preview</div>', unsafe_allow_html=True)
        if filtered:
            sel = filtered[sel_idx]
            table = sel["ltf_timeframe"]
            if sel.get("target_status") == "wait":
                # Wait entries haven't happened yet -- center on the most
                # recent bars (current price action approaching the zone),
                # not the chain's old drill/creation time.
                sig_dt = pd.Timestamp.utcnow().tz_localize(None)
            else:
                sig_dt = pd.to_datetime(sel["confirmed_at_bar"])
            df_window = load_ohlcv_window(raw_db, table, sig_dt)
            if not df_window.empty:
                render_mini_chart(df_window, sel, dec)
            else:
                st.info("No chart data available for this symbol/timeframe.")

            st.markdown("---")

            if system == "composite" and sel.get("target_status") == "wait":
                d1, d2 = st.columns(2)
                with d1:
                    st.markdown(f"**Status**  \n:orange[WAITING] — price hasn't reached this zone yet")
                with d2:
                    st.markdown(f"**Chain drilled**  \n{str(sel['confirmed_at_bar'])[:16]}  \n"
                                f"root={TF_LABEL.get(sel.get('root_timeframe'), '?')} · "
                                f"terminal={TF_LABEL.get(sel.get('terminal_timeframe'), '?')}")

                st.markdown('<div class="panel-title" style="margin-top:16px;">Nested Zone Chain</div>', unsafe_allow_html=True)
                if sel.get("zone_chain"):
                    breadcrumb = " → ".join(
                        f"{TF_LABEL.get(lvl['timeframe'], lvl['timeframe'].upper())} {lvl['zone_type']}"
                        for lvl in sel["zone_chain"]
                    ) + " → entry"
                    st.markdown(f'<div style="color:#d1d4dc;font-size:13px;margin-bottom:8px;">{breadcrumb}</div>',
                                unsafe_allow_html=True)
                st.caption(
                    "This chain was drilled D1→...→M15/M5 but price hasn't touched the terminal zone "
                    "yet, so it has never been scored. Once price arrives, it still has to clear the "
                    "5-factor composite threshold (≥3/5) to become a real signal — historically only "
                    "~13-16% of touches do. This is a watchlist entry, not a promise."
                )
            elif system == "composite":
                d1, d2, d3 = st.columns(3)
                with d1:
                    st.markdown(f"**Score**  \n{sel['score']}/5  \nrisk {sel['risk']:.{dec}f}")
                with d2:
                    outcome_txt = (f"{sel['exit_reason'].upper()} ({sel['r_outcome']:+.2f}R)"
                                   if sel.get("r_outcome") is not None else sel["exit_reason"].upper())
                    st.markdown(f"**Outcome**  \n{outcome_txt}  \n{sel.get('resolution_method') or '—'}")
                with d3:
                    exit_txt = str(sel["exit_bar_datetime"])[:16] if sel.get("exit_bar_datetime") else "still open"
                    st.markdown(f"**Confirmed / Exit**  \n{str(sel['confirmed_at_bar'])[:16]}  \n{exit_txt}")

                st.markdown('<div class="panel-title" style="margin-top:16px;">Why This Signal Qualified</div>', unsafe_allow_html=True)
                st.markdown(
                    f"Scored **{sel['score']}/5** on the Composite Confluence Engine (SMC + Divergence + "
                    f"Liquidity Sweep — CRT computed but excluded from scoring, see docs/DECISIONS.md), "
                    f"threshold to qualify is 3/5:"
                )
                for col, label in COMPOSITE_FACTOR_LABELS.items():
                    on = bool(sel.get(col))
                    mark = '<span class="factor-on">✓ present</span>' if on else '<span class="factor-off">— absent</span>'
                    st.markdown(
                        f'<div class="factor-row"><span class="factor-type">{label}</span>{mark}</div>',
                        unsafe_allow_html=True,
                    )
                if sel.get("targets"):
                    st.caption("Full target ladder (ranked by distance):")
                    ladder = " → ".join(f"{lv['price']:.{dec}f} ({lv['source']}, {lv['rr']:.2f}R)" for lv in sel["targets"])
                    st.caption(ladder)
            else:
                d1, d2, d3 = st.columns(3)
                with d1:
                    st.markdown(f"**HTF Zone**  \n{sel['htf_zone_type']}  \n[{sel['htf_zone_bottom']:.{dec}f} – {sel['htf_zone_top']:.{dec}f}]")
                with d2:
                    st.markdown(f"**Touch / CHoCH**  \n{str(sel['touch_bar_datetime'])[:16]}  \n{str(sel['choch_bar_datetime'])[:16]}")
                with d3:
                    sweep_txt = f"{str(sel['sweep_bar_datetime'])[:16]} ({sel['sweep_type']})" if sel.get("sweep_bar_datetime") else "—"
                    st.markdown(f"**Sweep**  \n{sweep_txt}")

                st.markdown('<div class="panel-title" style="margin-top:16px;">Why This Zone Qualified</div>', unsafe_allow_html=True)
                if sel.get("zone_source") == "confluence_zone" and sel.get("confluence_zone_id"):
                    zone = load_confluence_zone(curated_db, sel["confluence_zone_id"])
                    if zone:
                        st.markdown(
                            f"This entry comes from a **{CONFLUENCE_MODE_LABELS.get(zone['mode'], zone['mode'])}** "
                            f"zone (confidence {zone['confidence_score']}, {zone['factor_count']} contributing "
                            f"factors), not a single HTF zone. It qualified because these independent signals "
                            f"clustered on the same side of price, within the clustering window:"
                        )
                        for f in zone["factors"]:
                            ftype = f.get("factor_type", "?")
                            label = FACTOR_LABELS.get(ftype, ftype)
                            if f.get("price_top") is not None and f.get("price_bottom") is not None and f["price_top"] != f["price_bottom"]:
                                price_txt = f"[{f['price_bottom']:.{dec}f} – {f['price_top']:.{dec}f}]"
                            elif f.get("price_top") is not None:
                                price_txt = f"@ {f['price_top']:.{dec}f}"
                            else:
                                price_txt = ""
                            extra = f" ({f['sweep_type'].upper()})" if f.get("sweep_type") else (f" ({f['zone_type']})" if f.get("zone_type") else "")
                            formed = str(f.get("formed_at_bar", ""))[:16]
                            st.markdown(
                                f'<div class="factor-row"><span class="factor-type">{label}{extra}</span>'
                                f'<span class="factor-detail">{price_txt} · formed {formed}</span></div>',
                                unsafe_allow_html=True,
                            )
                        st.caption(
                            "Core range = overlap of all ranged factors (tighter stop). Full range = union of all "
                            "factors (wider, used when fewer than 2 ranged factors contributed)."
                        )
                    else:
                        st.caption("Confluence zone detail not found (id may be stale).")
                else:
                    st.markdown(
                        f"This entry comes from a single **{sel['htf_zone_type'].replace('_', ' ')}** zone on the "
                        f"h1 HTF timeframe — the original, validated single-factor path (no multi-factor clustering "
                        f"involved). It qualified because price touched this zone and then produced a "
                        f"{'CHoCH + liquidity sweep' if sel['mode'] == 'choch_sweep' else 'CHoCH'} in the trigger "
                        f"direction on the LTF timeframe."
                    )


# ── Main ──────────────────────────────────────────────────────────────────────

top_c1, top_c2, top_c3, top_c4, _spacer = st.columns([1.2, 2.2, 1.3, 1.6, 3.7])  # trailing
# spacer normalizes to total weight 10, matching every other page's filter
# row (see dashboard/1_Chart.py) so the Symbol dropdown is pixel-aligned
# across pages, not just proportioned relative to this page's own filters.
with top_c1:
    symbol = st.selectbox("Symbol", list(ASSETS.keys()), label_visibility="collapsed")
with top_c2:
    system = st.selectbox("Signal System", list(SYSTEM_LABELS.keys()),
                           format_func=lambda s: SYSTEM_LABELS[s], label_visibility="collapsed")
with top_c3:
    f_dir = st.selectbox("Direction", ["All", "Bullish", "Bearish"], label_visibility="collapsed")
with top_c4:
    if system == "composite":
        f_status = st.selectbox("Status", ["All", "wait", "open", "win", "loss"], label_visibility="collapsed")
    else:
        f_status = st.selectbox("Status", ["structural", "All", "stop_too_tight", "no_opposing_zone", "invalid_geometry"],
                                 label_visibility="collapsed")

dec = ASSETS[symbol]["dec"]
curated_db = ASSETS[symbol]["curated_db"]
raw_db = ASSETS[symbol]["raw_db"]

if system == "composite":
    st.markdown(
        '<div class="prod-banner">Composite Confluence Engine — production. Adopted despite not yet clearing '
        'the project\'s statistical floor (EURUSD ~56.5%, XAUUSD ~38.4% of floor) because its R:R profile '
        '(median ~2.55-2.58, expectancy +0.33R to +0.43R) is what\'s actually tradeable. Sample size grows '
        'automatically through live tracking. See docs/DECISIONS.md.</div>',
        unsafe_allow_html=True,
    )
    if f_status == "wait":
        triggers = load_waiting_chains(curated_db, raw_db, symbol)
    elif f_status == "All":
        # Waiting chains prepended -- "here's what to watch" belongs at the
        # top, ahead of already-resolved history, same reasoning as the
        # dedicated "wait" filter existing at all (see load_waiting_chains).
        triggers = load_waiting_chains(curated_db, raw_db, symbol) + load_composite_signals(curated_db, symbol, None)
    else:
        triggers = load_composite_signals(curated_db, symbol, f_status)
    filtered = triggers
    if f_dir != "All":
        filtered = [t for t in filtered if t["direction"] == f_dir.lower()]
else:
    mode_c1, mode_c2, mode_c3 = st.columns([2.4, 1.6, 1.6])
    with mode_c1:
        mode = st.selectbox("Mode", list(MODE_LABELS.keys()), format_func=lambda m: MODE_LABELS[m])
    with mode_c1:
        show_experimental = st.checkbox(
            "Experimental: show confluence-based signals (multi-factor HTF zones, unrelated to the "
            "Composite Confluence Engine above)",
            value=False,
        )
    if show_experimental:
        with mode_c2:
            confluence_mode = st.selectbox(
                "Confluence mode", list(CONFLUENCE_MODE_LABELS.keys()),
                format_func=lambda m: CONFLUENCE_MODE_LABELS[m], label_visibility="collapsed",
            )
        with mode_c3:
            target_source = st.selectbox(
                "Target source", ["smc_signals", "confluence_zone"],
                format_func=lambda s: "Target: single-factor zones" if s == "smc_signals" else "Target: confluence zones",
                label_visibility="collapsed",
            )
        zone_source, target_zone_source = "confluence_zone", target_source
        st.markdown(
            '<div class="exp-banner">⚠ Experimental — confluence-based signals showed materially worse '
            'drawdown (2-6x baseline) and a skewed, few-big-winners return profile in backtesting, with no '
            'capital-management layer yet built to size positions against that risk. Not validated to the '
            'same bar as the baseline path below, and not the same system as the Composite Confluence Engine '
            '(that one is production). See docs/DECISIONS.md.</div>',
            unsafe_allow_html=True,
        )
    else:
        confluence_mode = None
        zone_source, target_zone_source = "smc_signals", "smc_signals"

    triggers = load_triggers(curated_db, symbol, mode, zone_source, target_zone_source, confluence_mode)
    filtered = triggers
    if f_dir != "All":
        filtered = [t for t in filtered if t["direction"] == f_dir.lower()]
    if f_status != "All":
        filtered = [t for t in filtered if t["target_status"] == f_status]

if not filtered:
    st.markdown(
        '<div style="text-align:center;color:#333;padding:60px 0;font-size:14px;">'
        'No triggers found for this symbol/mode/filter combination.<br>'
        '<span style="font-size:12px;color:#222;">Run the detection pipeline to generate signals.</span>'
        '</div>',
        unsafe_allow_html=True
    )
    st.stop()

if system == "composite":
    st.caption(f"{len(filtered)} of {len(triggers)} loaded signals match this filter — "
               f"Composite Confluence Engine (production)")
else:
    st.caption(f"{len(filtered)} of {len(triggers)} loaded triggers match this filter — {MODE_LABELS[mode]}"
               + (" — EXPERIMENTAL (confluence-based)" if show_experimental else " — baseline (single-factor)"))
render_trigger_workspace(filtered, curated_db, symbol, dec, raw_db, system)
