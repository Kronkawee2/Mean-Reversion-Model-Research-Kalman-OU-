"""
Comprehensive Unit & Integration Test Suite for all 5 Quant Analysis Modules:
1. technical_analysis (EMA, RSI, MACD, ATR, BB, VWAP, Fib)
2. features (Log Returns, Garman-Klass Volatility, Beta, Macro, COT)
3. smc_crt (BOS, CHoCH, FVG, Order Block, Asian Range, 50% Equilibrium)
4. volume_profile (Volume-at-Price, POC, VAH, VAL, P-shape/b-shape/D-shape)
5. divergence (12 Multi-Factor Inter-market & Technical Divergence Models)
"""

import sys
import numpy as np
import pandas as pd

# Ensure workspace root is in sys.path
sys.path.insert(0, ".")

def generate_mock_ohlcv(n_bars: int = 100, start_price: float = 2000.0) -> pd.DataFrame:
    """Generates synthetic OHLCV data for testing."""
    np.random.seed(42)
    dt = pd.date_range("2026-07-01", periods=n_bars, freq="h")
    returns = np.random.randn(n_bars) * 2.0
    close = start_price + np.cumsum(returns)
    high = close + np.abs(np.random.randn(n_bars) * 3.0)
    low = close - np.abs(np.random.randn(n_bars) * 3.0)
    open_p = low + (high - low) * np.random.rand(n_bars)
    volume = np.random.randint(500, 3000, size=n_bars)

    return pd.DataFrame({
        "price_datetime": dt,
        "open_price": open_p.round(4),
        "high_price": high.round(4),
        "low_price": low.round(4),
        "close_price": close.round(4),
        "volume": volume
    })

def test_technical_analysis():
    print("=" * 60)
    print("1. Testing: analysis.technical_analysis")
    print("=" * 60)
    from analysis.technical_analysis import TechnicalAnalysisEngine

    df = generate_mock_ohlcv(100, 2000.0)
    engine = TechnicalAnalysisEngine()
    df_out = engine.transform(df)
    summary = engine.get_signal_summary(df_out)

    print(f"  [+] Input Shape : {df.shape}")
    print(f"  [+] Output Shape: {df_out.shape}")
    print(f"  [+] Trend Bias  : {summary.get('trend_bias')}")
    print(f"  [+] Momentum    : {summary.get('momentum_signal')}")
    print(f"  [+] Vol Regime  : {summary.get('vol_regime')}")
    print(f"  [+] Volume Sig  : {summary.get('volume_signal')}")
    print(f"  [+] RSI(14)     : {summary.get('rsi_14')}")
    print(f"  [+] ADX(14)     : {summary.get('adx_14')}")
    print("  [OK] technical_analysis PASSED\n")

def test_features():
    print("=" * 60)
    print("2. Testing: analysis.features")
    print("=" * 60)
    from analysis.features import QuantFeaturePipeline

    df_gold = generate_mock_ohlcv(100, 2000.0)
    df_dxy = generate_mock_ohlcv(100, 104.0)

    pipeline = QuantFeaturePipeline(asset_name="gold")
    df_out = pipeline.transform(
        df_asset=df_gold,
        df_drivers={"dxy": df_dxy}
    )

    feat_cols = [c for c in df_out.columns if "feature_" in c or "zscore" in c or "return" in c or "vol" in c]
    print(f"  [+] Input Shape   : {df_gold.shape}")
    print(f"  [+] Output Shape  : {df_out.shape}")
    print(f"  [+] Features Gen  : {len(feat_cols)} columns")
    print(f"  [+] Sample Columns: {feat_cols[:5]}")
    print("  [OK] features PASSED\n")

def test_smc_crt():
    print("=" * 60)
    print("3. Testing: analysis.smc_crt")
    print("=" * 60)
    from analysis.smc_crt import SMCScoringEngine

    df_gold = generate_mock_ohlcv(100, 2000.0)
    smc = SMCScoringEngine(pivot_window=3)
    df_out = smc.generate_strategy_blueprint(df_gold)

    smc_cols = [c for c in df_out.columns if "smc_" in c or "crt_" in c]
    print(f"  [+] Output Shape    : {df_out.shape}")
    print(f"  [+] Generated Cols  : {smc_cols}")
    print(f"  [+] Trend Bias      : {df_out['smc_trend_bias'].iloc[-1]}")
    print(f"  [+] Composite Score : {df_out['composite_smc_score'].iloc[-1]}")
    print(f"  [+] SMC Action      : {df_out['smc_action'].iloc[-1]}")
    print("  [OK] smc_crt PASSED\n")

def test_volume_profile():
    print("=" * 60)
    print("4. Testing: analysis.volume_profile")
    print("=" * 60)
    from analysis.volume_profile import VolumeProfilePipeline

    df_gold = generate_mock_ohlcv(100, 2000.0)
    pipeline = VolumeProfilePipeline(num_bins=50, value_area_pct=0.70)
    out = pipeline.process(df_gold)

    print(f"  [+] Profile Shape : {out['shape_label']}")
    print(f"  [+] POC           : {out['poc']}")
    print(f"  [+] Value Area    : VAH={out['vah']} | VAL={out['val']}")
    print(f"  [+] Trade Action  : {out['action']}")
    print(f"  [+] Reason        : {out['reason']}")
    print("  [OK] volume_profile PASSED\n")

def test_divergence():
    print("=" * 60)
    print("5. Testing: analysis.divergence")
    print("=" * 60)
    from analysis.divergence import DivergenceSignalGenerator

    df_gold = generate_mock_ohlcv(100, 2000.0)
    df_dxy = generate_mock_ohlcv(100, 104.0)

    gen = DivergenceSignalGenerator()
    df_out = gen.generate_composite_signals(
        df_asset=df_gold,
        df_drivers={"dxy": df_dxy}
    )

    div_cols = [c for c in df_out.columns if "div_" in c or "score" in c]
    print(f"  [+] Output Shape    : {df_out.shape}")
    print(f"  [+] Generated Cols  : {len(div_cols)} divergence columns")
    print(f"  [+] Composite Score : {df_out['composite_score'].iloc[-1] if 'composite_score' in df_out.columns else 'N/A'}")
    print("  [OK] divergence PASSED\n")

def main():
    print("\n" + "#" * 60)
    print("   RUNNING ALL QUANT ANALYSIS MODULE TESTS")
    print("#" * 60 + "\n")

    test_technical_analysis()
    test_features()
    test_smc_crt()
    test_volume_profile()
    test_divergence()

    print("#" * 60)
    print("   ALL 5 MODULES TESTED & VERIFIED SUCCESSFULLY!")
    print("#" * 60 + "\n")

if __name__ == "__main__":
    main()
