"""
LTF Triggers — browses curated_<symbol>.ltf_trigger_signals, Mode A
(choch_only) and Mode B (choch_sweep) as separate, explicitly switchable
views (never blended into one list — no default has been picked between
them, see analysis/strategies/ltf_trigger_engine.py). Card list + mini
chart preview pattern reused from the original page (formerly
1_signal.py), repointed from mart.trade_signals to the real trigger table
and the structural TP fields (entry/stop/target/structural_rr/
target_status) instead of the old ad-hoc entry/stop_loss/take_profit/
confluence score.
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

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em; color:#787b86;
    text-transform:uppercase; margin-bottom:10px; border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }

  .exp-badge {
    display:inline-block; font-size:9px; font-weight:700; padding:2px 6px; border-radius:3px;
    margin:1px; background:#2e1f00; color:#d4b16a; border:1px solid #55420c;
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

# Baseline = the single-factor smc_signals path (h1 HTF zones, choch_only/
# choch_sweep LTF confirmation) -- the only variant validated to date (see
# docs/DECISIONS.md). Confluence-sourced rows (zone_source='confluence_zone'
# and/or target_zone_source='confluence_zone') tested substantially worse
# drawdown/skew properties and are surfaced here only behind an explicit
# "experimental" toggle, never blended into the default view.


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
def load_ohlcv(db_name, table, limit=200):
    try:
        conn = _conn(db_name)
        cur = conn.cursor()
        cur.execute(
            f"SELECT price_datetime,open_price,high_price,low_price,close_price,volume "
            f"FROM `{table}` ORDER BY price_datetime DESC LIMIT {limit}"
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        df = pd.DataFrame(rows)
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
def render_trigger_workspace(filtered: list, curated_db: str, symbol: str, dec: int, raw_db: str):
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
            df = load_ohlcv(raw_db, table, limit=200)
            if not df.empty:
                sig_dt = pd.to_datetime(sel["confirmed_at_bar"])
                idx = df["price_datetime"].searchsorted(sig_dt)
                start, end = max(0, idx - 40), min(len(df), idx + 40)
                render_mini_chart(df.iloc[start:end], sel, dec)
            else:
                st.info("No chart data available for this symbol/timeframe.")

            st.markdown("---")
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

top_c1, top_c2, top_c3, top_c4 = st.columns([1.2, 2.2, 1.3, 1.6])
with top_c1:
    symbol = st.selectbox("Symbol", list(ASSETS.keys()), label_visibility="collapsed")
with top_c2:
    mode = st.selectbox("Mode", list(MODE_LABELS.keys()), format_func=lambda m: MODE_LABELS[m], label_visibility="collapsed")
with top_c3:
    f_dir = st.selectbox("Direction", ["All", "Bullish", "Bearish"], label_visibility="collapsed")
with top_c4:
    f_status = st.selectbox("Status", ["structural", "All", "stop_too_tight", "no_opposing_zone", "invalid_geometry"],
                             label_visibility="collapsed")

exp_c1, exp_c2, exp_c3 = st.columns([2.4, 1.6, 1.6])
with exp_c1:
    show_experimental = st.checkbox(
        "Experimental: show confluence-based signals (multi-factor HTF zones)",
        value=False,
    )
if show_experimental:
    with exp_c2:
        confluence_mode = st.selectbox(
            "Confluence mode", list(CONFLUENCE_MODE_LABELS.keys()),
            format_func=lambda m: CONFLUENCE_MODE_LABELS[m], label_visibility="collapsed",
        )
    with exp_c3:
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
        'same bar as the baseline path below. See docs/DECISIONS.md.</div>',
        unsafe_allow_html=True,
    )
else:
    confluence_mode = None
    zone_source, target_zone_source = "smc_signals", "smc_signals"

dec = ASSETS[symbol]["dec"]
curated_db = ASSETS[symbol]["curated_db"]
raw_db = ASSETS[symbol]["raw_db"]

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

st.caption(f"{len(filtered)} of {len(triggers)} loaded triggers match this filter — {MODE_LABELS[mode]}"
           + (" — EXPERIMENTAL (confluence-based)" if show_experimental else " — baseline (single-factor)"))
render_trigger_workspace(filtered, curated_db, symbol, dec, raw_db)
