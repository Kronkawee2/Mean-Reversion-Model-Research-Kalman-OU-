"""
Unit tests for analysis.divergence.technical_divergence_state:
  - Phase 2e: RSI Regular Bullish/Bearish, then RSI Hidden Bullish/Bearish.
  - Phase 2f: OBV Regular + Hidden, both in one pass — reusing the exact
    same indicator-agnostic pivot-finding/classification proven correct
    by the RSI tests, so these OBV tests exist to confirm the *wiring*
    (indicator_col='obv', divergence_type='obv') works, not to re-derive
    the classification logic again.

find_price_pivots (detection.py) is pre-existing, already-used code
(extracted, not rewritten, from detect_technical_divergence). These tests
exercise what's new: classify_divergence()'s pivot_type-aware
classification (all four labels, plus the exact ambiguity that caused a
real bug during the Regular pass — see test 1) and
TechnicalDivergenceEngine.detect()'s structured pivot-pair output for
both divergence classes, against hand-constructed price+indicator
sequences with a known, verifiable divergence baked in.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.divergence.technical_divergence_state import (  # noqa: E402
    TechnicalDivergenceEngine, classify_divergence, LABEL_TO_CLASS_DIRECTION,
)


def _df(prices, rsis, start="2026-01-01"):
    n = len(prices)
    dt = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({"price_datetime": dt, "close_price": prices, "rsi_14": rsis})


def _df_indicator(prices, values, indicator_col, start="2026-01-01"):
    n = len(prices)
    dt = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({"price_datetime": dt, "close_price": prices, indicator_col: values})


def test_classify_divergence_directly():
    print("=" * 60)
    print("1. classify_divergence(): all four labels + the pivot-side ambiguity bug case")
    print("=" * 60)

    assert classify_divergence(p_prev=95, p_curr=92, i_prev=30, i_curr=37, pivot_type="low") == "REGULAR_BULLISH"
    assert classify_divergence(p_prev=110, p_curr=114, i_prev=75, i_curr=65, pivot_type="high") == "REGULAR_BEARISH"
    assert classify_divergence(p_prev=90, p_curr=95, i_prev=30, i_curr=25, pivot_type="low") == "HIDDEN_BULLISH"
    assert classify_divergence(p_prev=110, p_curr=105, i_prev=60, i_curr=70, pivot_type="high") == "HIDDEN_BEARISH"
    assert classify_divergence(p_prev=100, p_curr=105, i_prev=50, i_curr=55, pivot_type="low") is None  # both up, no divergence

    # The exact ambiguity caught as a real bug in the Regular pass: the
    # same (price up, indicator down) numeric pattern means HIDDEN_BULLISH
    # on a low-pivot pair but REGULAR_BEARISH on a high-pivot pair — the
    # label MUST depend on pivot_type, never on the four numbers alone.
    assert classify_divergence(p_prev=100, p_curr=105, i_prev=60, i_curr=50, pivot_type="low") == "HIDDEN_BULLISH"
    assert classify_divergence(p_prev=100, p_curr=105, i_prev=60, i_curr=50, pivot_type="high") == "REGULAR_BEARISH"
    # And the mirror: (price down, indicator up) means REGULAR_BULLISH on
    # a low-pivot pair but HIDDEN_BEARISH on a high-pivot pair.
    assert classify_divergence(p_prev=105, p_curr=100, i_prev=50, i_curr=60, pivot_type="low") == "REGULAR_BULLISH"
    assert classify_divergence(p_prev=105, p_curr=100, i_prev=50, i_curr=60, pivot_type="high") == "HIDDEN_BEARISH"

    assert LABEL_TO_CLASS_DIRECTION["REGULAR_BULLISH"] == ("regular", "bullish")
    assert LABEL_TO_CLASS_DIRECTION["HIDDEN_BULLISH"] == ("hidden", "bullish")
    assert LABEL_TO_CLASS_DIRECTION["REGULAR_BEARISH"] == ("regular", "bearish")
    assert LABEL_TO_CLASS_DIRECTION["HIDDEN_BEARISH"] == ("hidden", "bearish")

    print("  [+] all four labels correct; pivot_type correctly disambiguates identical numeric patterns")
    print("  [OK] test_classify_divergence_directly PASSED\n")


def test_regular_bullish_divergence_detected():
    print("=" * 60)
    print("2. Regular Bullish: price LL + RSI HL -> reversal, divergence_class='regular'")
    print("=" * 60)

    # Two price low pivots (pivot_window=3): idx5 (price=95, rsi=30) then
    # idx14 (price=92, rsi=37). Price LOWER low (95->92), RSI HIGHER low
    # (30->37) -> Regular Bullish (reversal).
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    rsis   = [ 50,  48,  45,  40,  35,  30,  32,  34,  36,  35,  33,  31,  33,  35,  37,  39,  41,  43]
    df = _df(prices, rsis)

    engine = TechnicalDivergenceEngine(pivot_window=3)
    signals = engine.detect(df, symbol="TEST", timeframe="h1", indicator_col="rsi_14", divergence_type="rsi")

    bullish = signals[signals["direction"] == "bullish"]
    assert len(bullish) == 1, f"expected exactly 1 bullish signal, got {len(bullish)}\n{signals}"
    z = bullish.iloc[0]
    assert z["divergence_class"] == "regular", "must NOT be misclassified as hidden"
    assert z["prev_pivot_price"] == 95 and z["prev_pivot_indicator"] == 30
    assert z["curr_pivot_price"] == 92 and z["curr_pivot_indicator"] == 37
    assert len(signals) == 1, f"no other (hidden/bearish) signals should appear in this sequence, got\n{signals}"

    print(f"  [+] class={z['divergence_class']} direction={z['direction']} "
          f"prev(price={z['prev_pivot_price']}, rsi={z['prev_pivot_indicator']}) -> curr(price={z['curr_pivot_price']}, rsi={z['curr_pivot_indicator']})")
    print("  [OK] test_regular_bullish_divergence_detected PASSED\n")


def test_regular_bearish_divergence_detected():
    print("=" * 60)
    print("3. Regular Bearish: price HH + RSI LH -> reversal, divergence_class='regular'")
    print("=" * 60)

    # Two price high pivots: idx5 (price=110, rsi=75) then idx13
    # (price=114, rsi=65). Price HIGHER high (110->114), RSI LOWER high
    # (75->65) -> Regular Bearish (reversal).
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 108, 110, 112, 114, 112, 110, 108, 106]
    rsis   = [ 50,  55,  60,  65,  70,  75,  72,  68,  65,  66,  68,  70,  68,  65,  62,  59,  56,  53]
    df = _df(prices, rsis)

    engine = TechnicalDivergenceEngine(pivot_window=3)
    signals = engine.detect(df, symbol="TEST", timeframe="h1", indicator_col="rsi_14", divergence_type="rsi")

    bearish = signals[signals["direction"] == "bearish"]
    assert len(bearish) == 1, f"expected exactly 1 bearish signal, got {len(bearish)}\n{signals}"
    z = bearish.iloc[0]
    assert z["divergence_class"] == "regular", "must NOT be misclassified as hidden"
    assert z["prev_pivot_price"] == 110 and z["prev_pivot_indicator"] == 75
    assert z["curr_pivot_price"] == 114 and z["curr_pivot_indicator"] == 65
    assert len(signals) == 1, f"no other (hidden/bullish) signals should appear in this sequence, got\n{signals}"

    print(f"  [+] class={z['divergence_class']} direction={z['direction']} "
          f"prev(price={z['prev_pivot_price']}, rsi={z['prev_pivot_indicator']}) -> curr(price={z['curr_pivot_price']}, rsi={z['curr_pivot_indicator']})")
    print("  [OK] test_regular_bearish_divergence_detected PASSED\n")


def test_hidden_bullish_divergence_detected():
    print("=" * 60)
    print("4. Hidden Bullish: price HL + RSI LL -> continuation, divergence_class='hidden'")
    print("=" * 60)

    # Two price low pivots: idx5 (price=95, rsi=45) then idx11 (price=97,
    # rsi=30). Price HIGHER low (95->97, structurally bullish pullback),
    # RSI LOWER low (45->30, momentum weaker despite the shallower dip)
    # -> Hidden Bullish (continuation), NOT a reversal signal.
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 98, 97, 98, 99, 100, 99, 98, 97]
    rsis   = [ 55,  53,  50,  48,  46,  45,  47,  50,  53,  55,  48,  30,  33,  36,  40,  38,  36,  34]
    df = _df(prices, rsis)

    engine = TechnicalDivergenceEngine(pivot_window=3)
    signals = engine.detect(df, symbol="TEST", timeframe="h1", indicator_col="rsi_14", divergence_type="rsi")

    bullish = signals[signals["direction"] == "bullish"]
    assert len(bullish) == 1, f"expected exactly 1 bullish signal, got {len(bullish)}\n{signals}"
    z = bullish.iloc[0]
    assert z["divergence_class"] == "hidden", f"must NOT be misclassified as regular, got {z['divergence_class']}"
    assert z["prev_pivot_price"] == 95 and z["prev_pivot_indicator"] == 45
    assert z["curr_pivot_price"] == 97 and z["curr_pivot_indicator"] == 30
    assert z["curr_pivot_price"] > z["prev_pivot_price"], "price must be a HIGHER low"
    assert z["curr_pivot_indicator"] < z["prev_pivot_indicator"], "RSI must be a LOWER low"

    print(f"  [+] class={z['divergence_class']} direction={z['direction']} "
          f"prev(price={z['prev_pivot_price']}, rsi={z['prev_pivot_indicator']}) -> curr(price={z['curr_pivot_price']}, rsi={z['curr_pivot_indicator']})")
    print("  [OK] test_hidden_bullish_divergence_detected PASSED\n")


def test_hidden_bearish_divergence_detected():
    print("=" * 60)
    print("5. Hidden Bearish: price LH + RSI HH -> continuation, divergence_class='hidden'")
    print("=" * 60)

    # Two price high pivots: idx5 (price=110, rsi=60) then idx11
    # (price=108, rsi=75). Price LOWER high (110->108, structurally
    # bearish pullback), RSI HIGHER high (60->75, momentum stronger
    # despite the shallower peak) -> Hidden Bearish (continuation).
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 107, 108, 107, 106, 105, 106, 107, 106]
    rsis   = [ 45,  50,  55,  58,  59,  60,  58,  55,  50,  55,  60,  75,  70,  65,  60,  58,  56,  54]
    df = _df(prices, rsis)

    engine = TechnicalDivergenceEngine(pivot_window=3)
    signals = engine.detect(df, symbol="TEST", timeframe="h1", indicator_col="rsi_14", divergence_type="rsi")

    bearish = signals[signals["direction"] == "bearish"]
    assert len(bearish) == 1, f"expected exactly 1 bearish signal, got {len(bearish)}\n{signals}"
    z = bearish.iloc[0]
    assert z["divergence_class"] == "hidden", f"must NOT be misclassified as regular, got {z['divergence_class']}"
    assert z["prev_pivot_price"] == 110 and z["prev_pivot_indicator"] == 60
    assert z["curr_pivot_price"] == 108 and z["curr_pivot_indicator"] == 75
    assert z["curr_pivot_price"] < z["prev_pivot_price"], "price must be a LOWER high"
    assert z["curr_pivot_indicator"] > z["prev_pivot_indicator"], "RSI must be a HIGHER high"

    print(f"  [+] class={z['divergence_class']} direction={z['direction']} "
          f"prev(price={z['prev_pivot_price']}, rsi={z['prev_pivot_indicator']}) -> curr(price={z['curr_pivot_price']}, rsi={z['curr_pivot_indicator']})")
    print("  [OK] test_hidden_bearish_divergence_detected PASSED\n")


def test_hidden_not_confused_with_regular_end_to_end():
    print("=" * 60)
    print("6. End-to-end: on the SAME pivot side (low or high), a Regular-shaped pivot")
    print("   pair is never also labeled Hidden, and vice versa")
    print("=" * 60)
    # (The whole-table signal count isn't required to be pure — a
    # sequence can legitimately contain an unrelated divergence on the
    # opposite pivot side, e.g. a Hidden Bullish low-pivot pair sitting
    # alongside a genuine Regular Bearish high-pivot pair in the same
    # window. What must never happen is the SAME pivot pair being
    # double-labeled or mislabeled across classes.)

    engine = TechnicalDivergenceEngine(pivot_window=3)

    regular_bullish_prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    regular_bullish_rsis   = [ 50,  48,  45,  40,  35,  30,  32,  34,  36,  35,  33,  31,  33,  35,  37,  39,  41,  43]
    out1 = engine.detect(_df(regular_bullish_prices, regular_bullish_rsis), "TEST", "h1")
    bullish1 = out1[out1["direction"] == "bullish"]
    assert len(bullish1) == 1 and bullish1.iloc[0]["divergence_class"] == "regular", \
        "the low-pivot pair in this sequence is Regular-shaped and must not be labeled hidden"

    hidden_bullish_prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 98, 97, 98, 99, 100, 99, 98, 97]
    hidden_bullish_rsis   = [ 55,  53,  50,  48,  46,  45,  47,  50,  53,  55,  48,  30,  33,  36,  40,  38,  36,  34]
    out2 = engine.detect(_df(hidden_bullish_prices, hidden_bullish_rsis), "TEST", "h1")
    bullish2 = out2[out2["direction"] == "bullish"]
    assert len(bullish2) == 1 and bullish2.iloc[0]["divergence_class"] == "hidden", \
        "the low-pivot pair in this sequence is Hidden-shaped and must not be labeled regular"

    print(f"  [+] Regular-shaped low pivot -> class={bullish1.iloc[0]['divergence_class']}  "
          f"Hidden-shaped low pivot -> class={bullish2.iloc[0]['divergence_class']}")
    print("  [OK] test_hidden_not_confused_with_regular_end_to_end PASSED\n")


def test_obv_regular_bullish_and_bearish():
    print("=" * 60)
    print("7. OBV Regular Bullish + Regular Bearish (same price shapes as the RSI")
    print("   tests, OBV-scale values, indicator_col='obv' divergence_type='obv')")
    print("=" * 60)

    engine = TechnicalDivergenceEngine(pivot_window=3)

    # Regular Bullish: price LL (95->92), OBV HL (3000->3700)
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    obv    = [5000, 4800, 4500, 4000, 3500, 3000, 3200, 3400, 3600, 3500, 3300, 3100, 3300, 3500, 3700, 3900, 4100, 4300]
    out1 = engine.detect(_df_indicator(prices, obv, "obv"), "TEST", "h1", indicator_col="obv", divergence_type="obv")
    bullish = out1[out1["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
    assert bullish.iloc[0]["divergence_type"] == "obv"
    assert bullish.iloc[0]["prev_pivot_indicator"] == 3000 and bullish.iloc[0]["curr_pivot_indicator"] == 3700

    # Regular Bearish: price HH (110->114), OBV LH (7500->6500)
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 108, 110, 112, 114, 112, 110, 108, 106]
    obv    = [5000, 5500, 6000, 6500, 7000, 7500, 7200, 6800, 6500, 6600, 6800, 7000, 6800, 6500, 6200, 5900, 5600, 5300]
    out2 = engine.detect(_df_indicator(prices, obv, "obv"), "TEST", "h1", indicator_col="obv", divergence_type="obv")
    bearish = out2[out2["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "regular"
    assert bearish.iloc[0]["divergence_type"] == "obv"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 7500 and bearish.iloc[0]["curr_pivot_indicator"] == 6500

    print(f"  [+] regular/bullish obv: {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")
    print(f"  [+] regular/bearish obv: {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_obv_regular_bullish_and_bearish PASSED\n")


def test_obv_hidden_bullish_and_bearish():
    print("=" * 60)
    print("8. OBV Hidden Bullish + Hidden Bearish")
    print("=" * 60)

    engine = TechnicalDivergenceEngine(pivot_window=3)

    # Hidden Bullish: price HL (95->97), OBV LL (4500->3000)
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 98, 97, 98, 99, 100, 99, 98, 97]
    obv    = [5500, 5300, 5000, 4800, 4600, 4500, 4700, 5000, 5300, 5500, 4800, 3000, 3300, 3600, 4000, 3800, 3600, 3400]
    out1 = engine.detect(_df_indicator(prices, obv, "obv"), "TEST", "h1", indicator_col="obv", divergence_type="obv")
    bullish = out1[out1["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "hidden"
    assert bullish.iloc[0]["prev_pivot_indicator"] == 4500 and bullish.iloc[0]["curr_pivot_indicator"] == 3000

    # Hidden Bearish: price LH (110->108), OBV HH (6000->7500)
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 107, 108, 107, 106, 105, 106, 107, 106]
    obv    = [4500, 5000, 5500, 5800, 5900, 6000, 5800, 5500, 5000, 5500, 6000, 7500, 7000, 6500, 6000, 5800, 5600, 5400]
    out2 = engine.detect(_df_indicator(prices, obv, "obv"), "TEST", "h1", indicator_col="obv", divergence_type="obv")
    bearish = out2[out2["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "hidden"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 6000 and bearish.iloc[0]["curr_pivot_indicator"] == 7500

    print(f"  [+] hidden/bullish obv: {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")
    print(f"  [+] hidden/bearish obv: {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_obv_hidden_bullish_and_bearish PASSED\n")


def test_stochastic_regular_bullish_and_bearish():
    print("=" * 60)
    print("9. Stochastic %K Regular Bullish + Regular Bearish")
    print("=" * 60)

    engine = TechnicalDivergenceEngine(pivot_window=3)

    # Regular Bullish: price LL (95->92), %K HL (18->35)
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    stoch  = [ 60,  55,  48,  40,  28,  18,  22,  26,  30,  28,  25,  22,  26,  29,  35,  40,  45,  50]
    out1 = engine.detect(_df_indicator(prices, stoch, "stoch_k"), "TEST", "h1", indicator_col="stoch_k", divergence_type="stochastic")
    bullish = out1[out1["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
    assert bullish.iloc[0]["divergence_type"] == "stochastic"
    assert bullish.iloc[0]["prev_pivot_indicator"] == 18 and bullish.iloc[0]["curr_pivot_indicator"] == 35

    # Regular Bearish: price HH (110->114), %K LH (88->65)
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 108, 110, 112, 114, 112, 110, 108, 106]
    stoch  = [ 40,  50,  62,  75,  82,  88,  84,  78,  72,  74,  77,  80,  76,  65,  58,  52,  46,  40]
    out2 = engine.detect(_df_indicator(prices, stoch, "stoch_k"), "TEST", "h1", indicator_col="stoch_k", divergence_type="stochastic")
    bearish = out2[out2["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "regular"
    assert bearish.iloc[0]["divergence_type"] == "stochastic"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 88 and bearish.iloc[0]["curr_pivot_indicator"] == 65

    print(f"  [+] regular/bullish %K: {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")
    print(f"  [+] regular/bearish %K: {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_stochastic_regular_bullish_and_bearish PASSED\n")


def test_stochastic_hidden_bullish_and_bearish():
    print("=" * 60)
    print("10. Stochastic %K Hidden Bullish + Hidden Bearish")
    print("=" * 60)

    engine = TechnicalDivergenceEngine(pivot_window=3)

    # Hidden Bullish: price HL (95->97), %K LL (45->20)
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 98, 97, 98, 99, 100, 99, 98, 97]
    stoch  = [ 55,  53,  50,  48,  46,  45,  47,  50,  53,  55,  48,  20,  25,  30,  40,  38,  36,  34]
    out1 = engine.detect(_df_indicator(prices, stoch, "stoch_k"), "TEST", "h1", indicator_col="stoch_k", divergence_type="stochastic")
    bullish = out1[out1["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "hidden"
    assert bullish.iloc[0]["prev_pivot_indicator"] == 45 and bullish.iloc[0]["curr_pivot_indicator"] == 20

    # Hidden Bearish: price LH (110->108), %K HH (60->85)
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 107, 108, 107, 106, 105, 106, 107, 106]
    stoch  = [ 45,  50,  55,  58,  59,  60,  58,  55,  50,  55,  60,  85,  75,  65,  60,  58,  56,  54]
    out2 = engine.detect(_df_indicator(prices, stoch, "stoch_k"), "TEST", "h1", indicator_col="stoch_k", divergence_type="stochastic")
    bearish = out2[out2["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "hidden"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 60 and bearish.iloc[0]["curr_pivot_indicator"] == 85

    print(f"  [+] hidden/bullish %K: {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")
    print(f"  [+] hidden/bearish %K: {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_stochastic_hidden_bullish_and_bearish PASSED\n")


def test_cci_regular_bullish_and_bearish():
    print("=" * 60)
    print("11. CCI Regular Bullish + Regular Bearish")
    print("=" * 60)

    engine = TechnicalDivergenceEngine(pivot_window=3)

    # Regular Bullish: price LL (95->92), CCI HL (-180->-90)
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    cci    = [-20, -60, -100, -140, -160, -180, -150, -120, -90, -110, -130, -150, -130, -110, -90, -60, -30, 0]
    out1 = engine.detect(_df_indicator(prices, cci, "cci_20"), "TEST", "h1", indicator_col="cci_20", divergence_type="cci")
    bullish = out1[out1["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
    assert bullish.iloc[0]["divergence_type"] == "cci"
    assert bullish.iloc[0]["prev_pivot_indicator"] == -180 and bullish.iloc[0]["curr_pivot_indicator"] == -90

    # Regular Bearish: price HH (110->114), CCI LH (180->90)
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 108, 110, 112, 114, 112, 110, 108, 106]
    cci    = [ 20,  60,  100,  140,  160,  180,  150,  120,  90,  110,  130,  150,  130,  90,  60,  30,  0, -30]
    out2 = engine.detect(_df_indicator(prices, cci, "cci_20"), "TEST", "h1", indicator_col="cci_20", divergence_type="cci")
    bearish = out2[out2["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "regular"
    assert bearish.iloc[0]["divergence_type"] == "cci"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 180 and bearish.iloc[0]["curr_pivot_indicator"] == 90

    print(f"  [+] regular/bullish CCI: {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")
    print(f"  [+] regular/bearish CCI: {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_cci_regular_bullish_and_bearish PASSED\n")


def test_cci_hidden_bullish_and_bearish():
    print("=" * 60)
    print("12. CCI Hidden Bullish + Hidden Bearish")
    print("=" * 60)

    engine = TechnicalDivergenceEngine(pivot_window=3)

    # Hidden Bullish: price HL (95->97), CCI LL (-40->-160)
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 98, 97, 98, 99, 100, 99, 98, 97]
    cci    = [ 30,  10, -10, -25, -35, -40, -20,  10,  30,  40,  10, -160, -130, -100, -60, -70, -80, -90]
    out1 = engine.detect(_df_indicator(prices, cci, "cci_20"), "TEST", "h1", indicator_col="cci_20", divergence_type="cci")
    bullish = out1[out1["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "hidden"
    assert bullish.iloc[0]["prev_pivot_indicator"] == -40 and bullish.iloc[0]["curr_pivot_indicator"] == -160

    # Hidden Bearish: price LH (110->108), CCI HH (40->160)
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 107, 108, 107, 106, 105, 106, 107, 106]
    cci    = [ -30, -10,  10,  25,  35,  40,  20, -10, -30, -40, -10, 160, 130, 100,  60,  70,  80,  90]
    out2 = engine.detect(_df_indicator(prices, cci, "cci_20"), "TEST", "h1", indicator_col="cci_20", divergence_type="cci")
    bearish = out2[out2["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "hidden"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 40 and bearish.iloc[0]["curr_pivot_indicator"] == 160

    print(f"  [+] hidden/bullish CCI: {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")
    print(f"  [+] hidden/bearish CCI: {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_cci_hidden_bullish_and_bearish PASSED\n")


def test_all_four_divergence_types_do_not_collide():
    print("=" * 60)
    print("13. All 4 divergence_type values (rsi/obv/stochastic/cci) coexist at the")
    print("    SAME curr_pivot_datetime without unique-key collisions")
    print("=" * 60)

    # Same price sequence (same pivot bars), independently shaped RSI/OBV/
    # Stochastic/CCI series that each trigger Regular Bullish at the
    # identical curr_pivot_datetime -- proving all four persist as
    # distinct rows, not overwriting each other, once divergence_type differs.
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    rsis   = [ 50,  48,  45,  40,  35,  30,  32,  34,  36,  35,  33,  31,  33,  35,  37,  39,  41,  43]
    obv    = [5000, 4800, 4500, 4000, 3500, 3000, 3200, 3400, 3600, 3500, 3300, 3100, 3300, 3500, 3700, 3900, 4100, 4300]
    stoch  = [ 60,  55,  48,  40,  28,  18,  22,  26,  30,  28,  25,  22,  26,  29,  35,  40,  45,  50]
    cci    = [-20, -60, -100, -140, -160, -180, -150, -120, -90, -110, -130, -150, -130, -110, -90, -60, -30, 0]

    dt = pd.date_range("2026-01-01", periods=len(prices), freq="h")
    df = pd.DataFrame({
        "price_datetime": dt, "close_price": prices,
        "rsi_14": rsis, "obv": obv, "stoch_k": stoch, "cci_20": cci,
    })

    engine = TechnicalDivergenceEngine(pivot_window=3)
    all_signals = []
    for indicator_col, divergence_type in [("rsi_14", "rsi"), ("obv", "obv"), ("stoch_k", "stochastic"), ("cci_20", "cci")]:
        sig = engine.detect(df, "TEST", "h1", indicator_col=indicator_col, divergence_type=divergence_type)
        assert len(sig) == 1, f"{divergence_type}: expected 1 signal, got {len(sig)}"
        all_signals.append(sig)

    combined = pd.concat(all_signals, ignore_index=True)
    assert set(combined["divergence_type"]) == {"rsi", "obv", "stochastic", "cci"}
    # All four confirmed at the same bar and same curr_pivot_datetime...
    assert combined["curr_pivot_datetime"].nunique() == 1
    assert combined["bar_datetime"].nunique() == 1
    # ...but the persistence unique key (symbol, timeframe, divergence_type,
    # divergence_class, curr_pivot_datetime) still yields 4 distinct rows.
    key_cols = ["symbol", "timeframe", "divergence_type", "divergence_class", "curr_pivot_datetime"]
    keys = combined[key_cols].apply(tuple, axis=1)
    assert keys.nunique() == 4, f"expected 4 distinct persistence keys, got {keys.tolist()}"

    print(f"  [+] all 4 types confirmed at {combined['bar_datetime'].iloc[0]}, "
          f"same curr_pivot_datetime, 4 distinct persistence keys")
    print("  [OK] test_all_four_divergence_types_do_not_collide PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   TECHNICAL DIVERGENCE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_classify_divergence_directly()
    test_regular_bullish_divergence_detected()
    test_regular_bearish_divergence_detected()
    test_hidden_bullish_divergence_detected()
    test_hidden_bearish_divergence_detected()
    test_hidden_not_confused_with_regular_end_to_end()
    test_obv_regular_bullish_and_bearish()
    test_obv_hidden_bullish_and_bearish()
    test_stochastic_regular_bullish_and_bearish()
    test_stochastic_hidden_bullish_and_bearish()
    test_cci_regular_bullish_and_bearish()
    test_cci_hidden_bullish_and_bearish()
    test_all_four_divergence_types_do_not_collide()

    print("#" * 60)
    print("   ALL DIVERGENCE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
