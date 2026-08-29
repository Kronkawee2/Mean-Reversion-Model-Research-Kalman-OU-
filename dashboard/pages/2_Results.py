"""
Results -- summary table of every model/symbol/timeframe combination
tested so far (see scripts/research/RESULTS.md for full experiment logs).
Static numbers from the completed research, not a live query.
"""

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Results", page_icon="R", layout="wide")

st.title("Results")

ROWS = [
    ("OU", "XAUUSD", "M5", 1.43, "95.1%", "97.0%", "Overfit"),
    ("OU", "XAUUSD", "M15", 0.83, "9.2%", "6.2%", "-"),
    ("OU", "EURUSD", "M5", 0.83, "21.9%", "85.4%", "-"),
    ("OU", "EURUSD", "M15", 0.90, "15.2%", "84.8%", "-"),
    ("OU", "NDX100", "M15", 1.00, "49.2%", "70.0%", "-"),
    ("CIR", "XAUUSD", "M5", 1.23, "80.8%", "85.7%", "Not tested"),
    ("CIR", "XAUUSD", "M15", 0.81, "9.1%", "3.0%", "Not tested"),
    ("CIR", "EURUSD", "M5", 1.23, "79.1%", "99.6%", "Overfit"),
    ("CIR", "EURUSD", "M15", 0.99, "47.7%", "98.3%", "Overfit"),
    ("CIR", "NDX100", "M15", 1.08, "80.4%", "93.5%", "Overfit"),
    ("CIR", "NDX100", "M5", 1.01, "52.8%", "61.8%", "-"),
    ("GARCH-OU", "XAUUSD", "M5", 1.36, "87.9%", "90.2%", "Holds @90/30, weak @60/20"),
    ("GARCH-OU", "XAUUSD", "M15", 1.00, "50.3%", "51.7%", "-"),
    ("GARCH-OU", "EURUSD", "M5", 0.63, "1.3%", "46.6%", "-"),
    ("GARCH-OU", "EURUSD", "M15", 0.70, "1.5%", "14.5%", "-"),
    ("GARCH-OU", "NDX100", "M15", 0.98, "43.1%", "57.4%", "-"),
    ("GARCH-OU", "NDX100", "M5", 0.85, "21.4%", "34.9%", "-"),
    ("Jump-Diffusion OU", "XAUUSD", "M5", 0.76, "6.2%", "9.9%", "-"),
]

df = pd.DataFrame(ROWS, columns=["Model", "Symbol", "TF", "PF", "Bootstrap", "Monte Carlo", "Fixed-Config"])
st.dataframe(df, use_container_width=True, hide_index=True, height=650)

st.caption("Full experiment logs: scripts/research/RESULTS.md")
