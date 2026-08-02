# Quant Trader — Multi-Asset Quantitative Trading System

ระบบดึงและจัดเตรียมข้อมูลราคาสินทรัพย์หลัก ทองคำ (XAUUSD / GC=F) และ EUR/USD (EURUSD=X) พร้อมด้วยข้อมูลตัวแปรมหภาค (DXY, US10Y, VIX, GDX) แบบ Multi-Timeframe สำหรับการพัฒนา Quant Machine Learning, Algorithmic Trading (SMC / CRT) และการทำ Backtesting

---

## Overview & System Objectives

ระบบสถาปัตยกรรมข้อมูลแบบ 3 ชั้น (Medallion Data Architecture: Bronze, Silver, Gold) ออกแบบสำหรับระบบ Quantitative Trading โดยประมวลผลข้อมูลครอบคลุม 6 กรอบเวลา (5m, 15m, 1h, 4h, 6h, 1d)

### Market Drivers & Inter-Market Relationships

```
                      [US Economic & Market Drivers]
                                    │
          ┌─────────────────────────┴─────────────────────────┐
          │                                                   │
  [DX-Y.NYB (DXY)]                                    [^TNX (US 10Y Yield)]
   ดัชนีดอลลาร์สหรัฐ                                    ผลตอบแทนพันธบัตรรัฐบาล
          │                                                   │
          └─────────────────────────┬─────────────────────────┘
                                    │
                ┌───────────────────┴───────────────────┐
                │                                       │
         [EUR/USD (EURUSD=X)]                   [XAU/USD (GC=F)]
          ยูโรเทียบดอลลาร์                       ทองคำเทียบดอลลาร์
```

---

## Free Data Sources & Ingestion Breakdown

| Category | Assets / Tickers | Source | Method | Cost |
| :--- | :--- | :--- | :--- | :---: |
| Trading Assets | XAUUSD=X / GC=F, EURUSD=X | Yahoo Finance | yfinance | Free |
| US Dollar Index | DX-Y.NYB (DXY) | Yahoo Finance | yfinance | Free |
| 10Y Treasury Yield | ^TNX (US 10Y Yield) | Yahoo Finance | yfinance | Free |
| Volatility Index | ^VIX (CBOE Volatility) | Yahoo Finance | yfinance | Free |
| Gold Miners Index | GDX (VanEck Gold Miners) | Yahoo Finance | yfinance | Free |
| Institutional Position | CFTC COT Report (EUR & Gold) | CFTC.gov | cot_reports | Free |
| Gold ETF Reserve | SPDR Gold Shares (GLD) | SPDR Official | Direct CSV | Free |

---

## Data Architecture (3-Tier Medallion System)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. BRONZE LAYER (Raw Data — Immutable Storage)              │
│    - Trading Assets:                                        │
│        gold/   -> m5, m15, h1, h4, h6, d1                   │
│        eurusd/ -> m5, m15, h1, h4, h6, d1                   │
│    - Macro Drivers:                                         │
│        dxy/    -> h1, d1                                    │
│        us10y/  -> d1                                        │
│        vix/    -> d1                                        │
│        gdx/    -> d1                                        │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. SILVER LAYER (Processed & Feature Engineering)           │
│    - Indicators: EMA 20/50/200, ATR 14, RSI 14              │
│    - SMC Engine: BOS, CHoCH, FVG, Order Blocks              │
│    - CRT Engine: Asian Range, Session Sweeps, Equilibrium   │
│    - Volume Profile: POC, VAH, VAL, HVN, LVN               │
│    - 12 Divergence Models (Inter-market & Technical)        │
│                                                             │
│    silver_gold/   -> features, smc, crt, vol_profile, divs  │
│    silver_eurusd/ -> features, smc, crt, vol_profile, divs  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. GOLD LAYER (Trading Signals & Dashboard)                 │
│    - Execution Logic: 5m/15m triggers with 1h/4h/6h/1d bias │
│    - Backtest Engine & Trade Logs                           │
│    - Interactive Web Dashboard                              │
│                                                             │
│    signals/ -> trade_signals, backtest_logs, equity_curve   │
└─────────────────────────────────────────────────────────────┘
```

---

## Quant Engines Overview

### 1. Smart Money Concepts (SMC Engine)
* Break of Structure (BOS) & Change of Character (CHoCH): ตรวจจับการทะลุโครงสร้างราคา HH, HL, LH, LL
* Order Blocks (OB): ค้นหาฐานราคาแท่งก่อนหน้าการขยายตัวแรง (High-displacement expansion)
* Fair Value Gaps (FVG): ตรวจจับโซนสภาวะเสียสมดุลราคาแบบ 3 แท่ง (`High[i-2] < Low[i]`)
* Liquidity Sweeps (BSL/SSL): ตรวจจับการกวาดสภาพคล่องเหนือ/ใต้ Swing High/Low

### 2. Candle Range Theory (CRT Engine)
* Asian Range (Accumulation): คำนวณกรอบราคาสูงสุด-ต่ำสุดช่วงตลาดเอเชีย (00:00-06:00 UTC)
* Session Sweep (Manipulation): ตรวจจับการกวาดกรอบราคาเอเชียช่วงตลาดลอนดอน/นิวยอร์ก
* Range Equilibrium: คำนวณจุดสมดุล 50% ของกรอบราคาแท่ง HTF (4h, 6h, 1d)

### 3. Volume Profile Engine
* Point of Control (POC): ระดับราคาที่มีวอลลุ่มการซื้อขายสะสมสูงสุด
* Value Area High (VAH) & Low (VAL): ขอบเขตพื้นที่วอลลุ่ม 70%
* High / Low Volume Nodes (HVN / LVN): โซนรับแนวต้านโครงสร้างวอลลุ่ม และโซนราคาพุ่งเร็ว

### 4. 12 Divergence Models Matrix
* Inter-Market Divergence (7 Models): EUR/USD vs Gold Ratio Z-Score, Gold vs DXY, EUR vs DXY, Gold vs Real Yield, EUR vs Yield Spread, Gold vs GDX Miners, Gold vs SPDR ETF Vault Holdings
* Technical & Volume Divergence (4 Models): RSI Regular, RSI Hidden, Volume & OBV Exhaustion, Stochastic/CCI
* Multi-Timeframe Alignment (1 Model): Confluence ระหว่าง HTF Hidden Divergence กับ LTF Regular Divergence

---

## Systematic Quantitative Divergence Engine (วิธีการคำนวณ ลอจิกการให้คะแนน และแหล่งอ้างอิงทางการ)

ระบบ Divergence Engine ในโฟลเดอร์ `analysis/divergence/` ถูกออกแบบขึ้นตามหลักการ **Quantitative Multi-Factor Model** สำหรับสินทรัพย์ **XAU/USD** และ **EUR/USD** โดยอ้างอิงจากทฤษฎีการเงินและแหล่งข้อมูลทางการ

### 1. โครงสร้างการทำงาน 5 ขั้นตอน (5-Step Pipeline Architecture)

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Data Collection  ──>  ดึงราคา Gold/EURUSD + DXY + VIX + COT Report  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Feature Engine   ──>  คำนวณ Z-Score, Rolling Beta & Linear Slope    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Detector Engine  ──>  ตรวจจับ Technical + Macro + COT Divergence   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. Confirmation     ──>  เช็ก VIX Risk + Correlation Stability Filter  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 5. Signal Generator ──>  ออกคำสั่ง BUY/SELL + คำนวณ ATR Stop-Loss / TP  │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 2. วิธีการและลอจิกการถ่วงน้ำหนักคะแนน (Multi-Factor Scoring Methodology)

ระบบใช้การประมวลผลคะแนนรวม **Composite Score (-100 ถึง +100)** เพื่อการันตีว่าจะออกออเดอร์เมื่อเกิดการยืนยันร่วมกันหลายปัจจัย (Multi-factor Confluence) เท่านั้น:

| ประเภทปัจจัย (Factor Category) | สัญญาณ (Signal Type) | คะแนน (Score Weight) | เหตุผลทางสถิติและการเงิน |
| :--- | :--- | :---: | :--- |
| **Inter-Market Macro Driver** | DXY / Bond Yield Divergence | **+50 / -50** | **ปัจจัยมหภาคชี้ขาด (Fundamental Market Driver)** เงินทุนเคลื่อนย้ายตามดอลลาร์และดอกเบี้ย |
| **Technical Divergence (Reversal)** | RSI Regular Bullish / Bearish | **+40 / -40** | เกิดตรงจุดสิ้นสุดเทรนด์ (Extrema) มีนัยสำคัญทางสถิติสูงในการจับจุดกลับตัวใหญ่ |
| **Technical Divergence (Continuation)** | RSI Hidden Bullish / Bearish | **+25 / -25** | สัญญาณย่อยยืนยันการไปต่อตามเทรนด์เดิม |
| **Volatility Risk Adjustment** | High Volatility Regime ($VIX > 25.0$) | **คะแนนโดนหาร 2 (-50%)** | ป้องกันสัญญาณหลอกในช่วงสภาวะตลาดวิกฤตผันผวนสูง |

#### 🎯 เกณฑ์การออกคำสั่งเทรด (Trade Execution Threshhold Logic):
* **คะแนน $\ge +50$**: สั่ง **`BUY`** (ต้องมี Macro Driver หรือ Technical Reversal + Continuation ร่วมกัน)
* **คะแนน $\le -50$**: สั่ง **`SELL`**
* **คะแนนระหว่าง $-49$ ถึง $+49$**: สั่ง **`HOLD`** (ถือรอ ไม่เปิดออเดอร์เมื่อเห็นสัญญาณอินดิเคเตอร์ตัวเดียว)

---

### 3. ระบบบริหารจัดการความเสี่ยง (ATR Dynamic Risk Management)

ระบบคำนวณจุดตัดขาดทุน (Stop Loss) และจุดทำกำไร (Take Profit) ตามความผันผวนจริงของราคา (J. Welles Wilder's ATR Framework):
* **Long Stop Loss (SL)**: $\text{Entry Price} - (1.5 \times \text{ATR}_{14})$
* **Long Take Profit (TP)**: $\text{Entry Price} + (3.0 \times \text{ATR}_{14})$ *(การันตี Risk:Reward Ratio ที่ 1:2)*
* **Short Stop Loss (SL)**: $\text{Entry Price} + (1.5 \times \text{ATR}_{14})$
* **Short Take Profit (TP)**: $\text{Entry Price} - (3.0 \times \text{ATR}_{14})$ *(การันตี Risk:Reward Ratio ที่ 1:2)*

---

## Systematic Quantitative Feature Engineering Architecture (7 Categories & Python Pipeline)

ระบบ Feature Engineering แบบครบวงจรในโฟลเดอร์ `analysis/features/` ถูกออกแบบมาสำหรับ **XAU/USD** และ **EUR/USD** เพื่อสร้างฟีเจอร์ที่นิ่ง (Stationary) ปราศจาก Look-ahead Bias สำหรับระบบ Quantitative Trading

### 1. หมวดหมู่ฟีเจอร์ทั้ง 7 (7 Feature Categories)

| หมวดหมู่ (Category) | ชื่อฟีเจอร์ (Feature Name) | สูตรคำนวณ (Mathematical Formula) | Inputs | Asset | เหตุผลเชิงการเงินและข้อควรระวัง |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Price / Return** | `feat_log_return` | $r_t = \ln(P_t / P_{t-1})$ | Close Price | ทั้งคู่ | แปลงราคาให้กลายเป็น Stationary Series ลดปัญหา Non-Stationarity |
| **Price / Return** | `feat_price_ema_dist_z` | $\frac{P_t - \text{EMA}_{20}(P)}{\sigma_{60}(P)}$ | Close, EMA | ทั้งคู่ | วัดระยะห่างจากแนวโน้มหลัก เพื่อส่งสัญญาณ Mean-Reversion |
| **Price / Return** | `feat_log_return_slope` | $\text{OLS Slope}_5(r_t)$ | Log Return | ทั้งคู่ | วัดความเร่งของโมเมนตัมราคา (Momentum Acceleration) |
| **Volatility** | `feat_garman_klass_vol` | $\sqrt{\frac{0.5(\ln(H/L))^2 - (2\ln 2 - 1)(\ln(C/O))^2}{N}}$ | OHLC | ทั้งคู่ | แม่นยำกว่า Close-to-Close Volatility 8 เท่า จับสภาวะ Volatility Regime |
| **Volatility** | `feat_parkinson_vol` | $\sqrt{\frac{(\ln(H/L))^2}{4 \ln 2 \cdot N}}$ | High, Low | ทั้งคู่ | วัดความผันผวนจาก High-Low Range |
| **Volatility** | `feat_atr_pct` | $\frac{\text{ATR}_{14}}{P_{\text{Close}}} \times 100$ | OHLC | ทั้งคู่ | Normalized ATR % สำหรับเปรียบเทียบความผันผวนข้ามช่วงราคา |
| **Volatility** | `feat_volatility_ratio` | $\frac{\sigma_{10}(r)}{\sigma_{60}(r)}$ | Log Return | ทั้งคู่ | วัดการบีบตัว (Compression < 0.7) หรือระเบิดตัว (Expansion > 1.3) ของความผันผวน |
| **Correlation/Spread**| `feat_dxy_spread_z` | $\frac{(P_{\text{Asset}} - \beta \cdot P_{\text{DXY}}) - \mu_N}{\sigma_N}$ | Asset, DXY | ทั้งคู่ | Cointegration Residual Spread เทรด Mean-Reversion เมื่อราคาหลุดจากดอลลาร์ |
| **Correlation/Spread**| `feat_gsr_zscore` | $\frac{(P_{\text{Gold}} / P_{\text{Silver}}) - \mu_N}{\sigma_N}$ | Gold, Silver | Gold Only | Gold-Silver Ratio Mispricing สัญญาณ Relative Value สำหรับทองคำ |
| **Macro** | `feat_dxy_return_z` | $\frac{r_{\text{DXY}} - \mu_N(r_{\text{DXY}})}{\sigma_N}$ | DXY Close | ทั้งคู่ | โมเมนตัมของดอลลาร์สหรัฐที่เป็นตัวขับเคลื่อนหลัก |
| **Macro** | `feat_real_yield_proxy` | $r_{\text{US10Y}} - r_{\text{DXY}}$ | US10Y, DXY | ทั้งคู่ | ผลตอบแทนที่แท้จริง (Real Rate Delta) ส่งผลโดยตรงต่อทองคำ |
| **Macro** | `feat_gdx_gold_residual`| $r_{\text{Gold}} - \beta \cdot r_{\text{GDX}}$ | Gold, GDX | Gold Only | หุ้นเหมืองทองคำ (GDX) เป็นตัวนำราคาทองคำแท่ง (Leading Indicator) |
| **Positioning** | `feat_cot_percentile` | $\frac{\text{CommNet}_t - \min_{52w}}{\max_{52w} - \min_{52w}} \times 100$ | CFTC COT | ทั้งคู่ | % Extreme ของนักลงทุนสถาบันรายใหญ่ (Commercial Hedgers) รอบ 52 สัปดาห์ |
| **Positioning** | `feat_cot_zscore` | $\frac{\text{CommNet}_t - \mu_{52w}}{\sigma_{52w}}$ | CFTC COT | ทั้งคู่ | Standardized Position Factor สำหรับสถาบันรายใหญ่ |
| **Positioning** | `feat_cot_delta_4w` | $\text{CommNet}_t - \text{CommNet}_{t-4}$ | CFTC COT | ทั้งคู่ | วัดอัตราการสะสม/กระจายสัญญาของสถาบันรายใหญ่รอบ 4 สัปดาห์ |
| **Filter** | `feat_vix_regime_flag` | $I(\text{VIX}_t > 25.0)$ | VIX Close | ทั้งคู่ | Binary Flag สภาวะวิกฤต (VIX > 25) สำหรับลดการถือครอง Leverage |

---

### 2. โครงสร้างแพ็กเกจ Python Feature Spec (`analysis/features/`)

```
analysis/features/
├── __init__.py                # Master package entry point & re-exports
├── price_return.py            # PriceReturnFeatures (Log return, EMA dist z, Slope)
├── volatility.py              # VolatilityFeatures (Garman-Klass, Parkinson, ATR %, Vol ratio)
├── correlation_beta.py        # CorrelationBetaFeatures (Beta, Cointegration spread z, GSR z)
├── macro.py                   # MacroFeatures (DXY z, Real yield proxy, GDX residual, VIX flag)
├── positioning.py             # PositioningFeatures (COT percentile, COT z-score, COT 4w delta)
└── pipeline.py                # QuantFeaturePipeline (Master Data Transformer & Quant Score)
```

---

### 3. ตัวอย่างการใช้งานใน Python Pipeline

```python
from analysis.features import QuantFeaturePipeline, PriceReturnFeatures, VolatilityFeatures

# สร้าง Feature Pipeline สำหรับ XAU/USD (Gold)
pipeline = QuantFeaturePipeline(asset_name="gold")

# รันประมวลผลแปลง Raw Data -> Features -> Composite Quant Score
df_features = pipeline.transform(
    df_asset=df_gold,
    df_drivers={"dxy": df_dxy, "us10y": df_us10y, "vix": df_vix, "gdx": df_gdx, "silver": df_silver},
    df_cot=df_cot_gold
)
```

---

---

## Quantitative Smart Money Concepts (SMC) & Candle Range Theory (CRT) Architecture

ระบบ SMC & CRT Engine แบบเป็นระบบในโฟลเดอร์ `analysis/smc_crt/` ถูกออกแบบมาสำหรับ **XAU/USD** และ **EUR/USD** โดยเปลี่ยนมโนทัศน์เชิงคุณภาพให้กลายเป็นสูตรคณิตศาสตร์และกฎโปรแกรมไร้ Look-ahead bias

### 1. ตารางคุณลักษณะ SMC / CRT (Feature & Detection Matrix)

| หมวดหมู่ (Category) | ชื่อฟีเจอร์ (Feature Name) | สูตร/นิยามทางคณิตศาสตร์ (Rule Definition) | Inputs | การตีความและการนำไปใช้ |
| :--- | :--- | :--- | :--- | :--- |
| **Structure** | `smc_structure_signal` | $\text{Bullish BOS} \iff C_t > \text{SwingHigh}_{\text{prev}}$ in Uptrend | OHLC | ยืนยันการไปต่อของเทรนด์ใหญ่ (Trend Continuation) |
| **Structure** | `smc_choch` | $\text{Bullish CHoCH} \iff C_t > \text{SwingHigh}_{\text{prev}}$ in Downtrend | OHLC | ยืนยันจุดกลับตัวต้นเทรนด์ (Trend Reversal) |
| **Liquidity** | `smc_liquidity_sweep`| $\text{BSL Sweep} \iff H_t > \text{SwingHigh} \land C_t \le \text{SwingHigh}$ | OHLC | ล่าสภาพคล่อง (Stop Hunt / Liquidity Sweep) เตรียมกลับตัว |
| **Liquidity** | `smc_eqh_eql` | $\|H_1 - H_2\| / P \le 0.0005$ | High, Low | สระสภาพคล่อง (Equal Highs/Lows) เป้าหมายของราคา |
| **Imbalance** | `smc_fvg_type` | $\text{Bullish FVG} \iff H_{t-2} < L_t \land (L_t - H_{t-2}) > \theta$ | High, Low | ช่องว่างสภาวะเสียสมดุลราคา โซนรอรับเมื่อราคาย้อนกลับ |
| **Order Flow** | `smc_ob_type` | $\text{Bullish OB} \iff \text{Last Bearish Candle before BOS}$ | OHLC, Vol | ฐานราคาออเดอร์รายใหญ่ (Order Block) โซนเข้าออเดอร์ |
| **CRT Framework** | `crt_session_sweep` | $\text{Sweep of Asian Range High/Low in London/NY}$ | OHLC, Time | Candle Range Theory: การกวาดกรอบราคาเอเชีย (00:00-06:00) |
| **Equilibrium** | `smc_zone` | $\text{Discount} \iff P_t < 0.5(H_{\text{HTF}} + L_{\text{HTF}})$ | High, Low | Buy เฉพาะในโซน Discount ($< 50\%$), Sell ในโซน Premium ($> 50\%$) |

---

### 2. โครงสร้างแพ็กเกจ Python SMC/CRT (`analysis/smc_crt/`)

```
analysis/smc_crt/
├── __init__.py                # Package facade & re-exports
├── structure.py               # SMCStructureEngine (Swing High/Low, BOS, CHoCH)
├── liquidity.py               # SMCLiquidityEngine (EQH/EQL, BSL/SSL Liquidity Sweeps)
├── imbalance.py               # SMCImbalanceEngine (FVG, Liquidity Voids, Active Mitigation)
├── order_block.py             # SMCOrderBlockEngine (Bullish/Bearish Order Blocks)
├── crt_engine.py              # CRTEngine (Asian Range 00:00-06:00, Session Sweeps, 50% Median)
└── scoring.py                 # SMCScoringEngine (Composite Score -100 to +100 & Strategy Blueprint)
```

---

### 3. ตัวอย่างการใช้งาน SMC/CRT Strategy Blueprint

```python
from analysis.smc_crt import SMCScoringEngine

# สร้าง SMC/CRT Engine
smc_engine = SMCScoringEngine(pivot_window=3)

# รันประมวลผลย้อนหลังบน XAU/USD หรือ EUR/USD
df_smc = smc_engine.generate_strategy_blueprint(
    df_asset=df_gold,
    df_drivers={"dxy": df_dxy, "vix": df_vix}
)
```

---

### 4. แหล่งข้อมูลทางการและเอกสารอ้างอิง (Official References & Citations)

1. **GitHub open-source `smart-money-concepts`** (Josh Yattridge)
   - https://github.com/joshyattridge/smart-money-concepts
2. **Equiti News & Trading Ideas** — *What is the Smart Money Concept (SMC) in Forex?*
   - https://www.equiti.com/sc-en/news/trading-ideas/what-is-the-smart-money-concept-smc-in-forex-and-how-can-you-use-it/
3. **Trade The Pool** — *Smart Money Concepts Terminology Guide*
   - https://tradethepool.com/technical-skill/smart-money-concepts-terminology/
4. **DYOR Academy** — *SMC Price Action, Order Blocks, Liquidity & FVG Reference*
   - https://dyor.net/academy/en/price_action/smart-money-concepts
5. **ACY Securities** — *Confirmation Model: OB + FVG + Liquidity Sweep*
   - https://acy.com/en/market-news/education/confirmation-model-ob-fvg-liquidity-sweep-j-o-20251112-094218/
6. **Scribd Guide** — *SMC OrderBlock Strategy Guide*
   - https://www.scribd.com/document/869902609/SMC-OrderBlock-Strategy-Guide
7. **CFTC (U.S. Commodity Futures Trading Commission)** — *Commitment of Traders (COT) Reports*
   - https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
8. **CME Group** — *FX & Precious Metals Session Trading Hours Specifications*
   - https://www.cmegroup.com/market-data/real-time-and-historical-data.html

---

## Quantitative Volume Profile Engine & Profile Shape Classifier Architecture (P-shape, b-shape, D-shape)

ระบบ Volume Profile Engine แบบเป็นระบบในโฟลเดอร์ `analysis/volume_profile/` ถูกออกแบบมาสำหรับ **XAU/USD** และ **EUR/USD** เพื่อคำนวณ Volume-at-Price Histogram, สถิติเชิงรูปทรง (Skewness, Kurtosis, Concentration Ratio), และจำแนกประเภท Profile Shape (P-shape, b-shape, D-shape)

> [!NOTE]
> **ข้อแตกต่างหลักระหว่าง Volume Profile กับ Market Profile**:
> - **Volume Profile (ที่ใช้ในระบบนี้)**: วัดปริมาณการซื้อขายตามระดับราคา (**Volume-at-Price**)
> - **Market Profile (TPO)**: วัดระยะเวลาที่ราคาแช่อยู่ตามระดับราคา (**Time-at-Price**)

### 1. ตารางจำแนกประเภทรูปทรง Volume Profile (Profile Shape Classification Matrix)

| รูปทรง Profile (Profile Shape) | นิยามเชิงสถิติ (Statistical Condition) | ตำแหน่ง POC & Value Area | สภาพแวดล้อมตลาด (Market Regime) | กลยุทธ์การเทรด (Trading Implications) |
| :--- | :--- | :--- | :--- | :--- |
| **D-shape** | $\text{POC}_{\text{norm}} \in [0.40, 0.60] \land \|\gamma_1\| \le 0.5$ | POC อยู่ตรงกลางสมมาตร | Fair Value / Equilibrium; แรงซื้อแรงขายสมดุล | Range Trading (Buy VAL, Sell VAH, Target POC) |
| **P-shape** | $\text{POC}_{\text{norm}} \ge 0.65 \land \text{TopBotRatio} \ge 1.4$ | POC อยู่โซนบน (ใกล้ VAH) | Bullish Short-Covering / Upward Expansion | Bullish Trend Continuation (Buy on Retest POC) |
| **b-shape** | $\text{POC}_{\text{norm}} \le 0.35 \land \text{TopBotRatio} \le 0.70$ | POC อยู่โซนล่าง (ใกล้ VAL) | Bearish Long-Liquidation / Downward Expansion | Bearish Trend Continuation (Sell on Retest POC) |

---

### 2. โครงสร้างแพ็กเกจ Python Volume Profile (`analysis/volume_profile/`)

```
analysis/volume_profile/
├── __init__.py                # Package facade & re-exports
├── calculator.py              # Volume-at-Price Histogram (50 Bins), POC, Value Area (70%), HVN & LVN
├── statistical_features.py    # Skewness, Kurtosis, Concentration Ratio, Top/Bottom Ratio, POC Loc
├── classifier.py              # Profile Shape Classifier (detect_p_shape, detect_b_shape, detect_d_shape)
├── signals.py                 # Rule-based Trading Signals (Trend Continuation, Reversal, Range)
└── pipeline.py                # VolumeProfilePipeline (Master Data Transformer)
```

---

### 3. ตัวอย่างการใช้งาน Volume Profile Pipeline

```python
from analysis.volume_profile import VolumeProfilePipeline

# 1. สร้าง Volume Profile Pipeline
pipeline = VolumeProfilePipeline(num_bins=50, value_area_pct=0.70)

# 2. รันคำนวณและจำแนก Profile Shape บน XAU/USD หรือ EUR/USD
out = pipeline.process(df_gold)
print("Profile Shape:", out["shape_label"])
print("POC:", out["poc"], "VAH:", out["vah"], "VAL:", out["val"])
print("Action:", out["action"], "Reason:", out["reason"])
```

---

### 4. แหล่งข้อมูลทางการและเอกสารอ้างอิง (Official References & Citations)

1. **NinjaTrader Futures Blog** — *Understanding the 4 Common Volume Profile Shapes (D, P, b, B)*
   - https://ninjatrader.com/futures/blogs/trade-futures-understanding-the-4-common-volume-profile-shapes/
2. **Trader-Dale** — *Market Profile Different Profiles and Their Application*
   - https://www.trader-dale.com/market-profile-different-profiles-and-their-application/
3. **Trader-Dale** — *How to Read Volume Profile Shapes: What the Market is Really Telling You*
   - https://www.trader-dale.com/how-to-read-volume-profile-shapes-what-the-market-is-really-telling-you/
4. **CrossTrade Learn** — *Technical Indicators: Market Profile & TPO*
   - https://crosstrade.io/learn/technical-indicators/market-profile-tpo
5. **GoCharting Blog** — *Market Profile Indicator Complete Guide*
   - https://gocharting.com/blog/market-profile-indicator/market-profile-complete-guide
6. **Alchemy Markets** — *Volume Profile Effective Trading Guide*
   - https://alchemymarkets.com/education/indicators/volume-profile/

---

## Database Architecture (รายละเอียดฐานข้อมูล)

### 1. Database: `gold` (XAUUSD / GC=F)
* `m5`: ข้อมูลราคา 5 นาที (ย้อนหลัง 60 วัน)
* `m15`: ข้อมูลราคา 15 นาที (ย้อนหลัง 60 วัน)
* `h1`: ข้อมูลราคา 1 ชั่วโมง (ย้อนหลัง 2 ปี)
* `h4`: ข้อมูลราคา 4 ชั่วโมง (คำนวณจาก 1h)
* `h6`: ข้อมูลราคา 6 ชั่วโมง (คำนวณจาก 1h)
* `d1`: ข้อมูลราคา 1 วัน (ย้อนหลังหลายปี)

### 2. Database: `eurusd` (EURUSD=X)
* `m5`: ข้อมูลราคา 5 นาที (ย้อนหลัง 60 วัน)
* `m15`: ข้อมูลราคา 15 นาที (ย้อนหลัง 60 วัน)
* `h1`: ข้อมูลราคา 1 ชั่วโมง (ย้อนหลัง 2 ปี)
* `h4`: ข้อมูลราคา 4 ชั่วโมง (คำนวณจาก 1h)
* `h6`: ข้อมูลราคา 6 ชั่วโมง (คำนวณจาก 1h)
* `d1`: ข้อมูลราคา 1 วัน (ทศนิยม 5 ตำแหน่ง)

### 3. Database: Macro Indicators
* `dxy`: `h1`, `d1` (US Dollar Index)
* `us10y`: `d1` (US 10-Year Treasury Yield)
* `vix`: `d1` (CBOE Volatility Index)
* `gdx`: `d1` (VanEck Gold Miners ETF)

---

## Project Structure

```
Quant_Trade/
└── yahoo-finance-tracker/
    ├── quant_backend.py          # Core Quant Data Engine (Fetch, Resample 4h/6h, Store)
    ├── fetcher/                  # Yahoo Finance & Market API client
    │   ├── yahoo_finance_client.py
    │   └── symbols.py
    ├── storage/                  # MySQL schema definitions
    │   └── schema_quant.sql      # Bronze layer unified schema
    ├── analysis/                 # Quant Engines & Indicators
    │   ├── technical_analysis.py # Trend Analyzer (EMA 20, 50, 100)
    │   ├── features.py           # Feature Engineering & Resampling
    │   ├── smc_crt.py            # SMC (BOS, CHoCH, FVG, OB) & CRT Engine
    │   ├── volume_profile.py     # Volume Profile Engine (POC, VAH, VAL)
    │   └── divergence/           # Modular Systematic Divergence Package
    │       ├── __init__.py       # Package facade & re-exports
    │       ├── data_collection.py# Data alignment & CFTC COT loader
    │       ├── feature_engineering.py # Rolling Z-Score & Beta Spread
    │       ├── detection.py      # Causal Technical/Macro Divergence Detectors
    │       ├── confirmation.py   # Volatility (VIX) & Correlation filters
    │       └── signal_generator.py# Composite Scoring & ATR Risk SL/TP
    ├── test_quick_divergence.py  # Quick validation test runner script
    ├── dashboard/                # Interactive Web Dashboard
    │   └── app.py                # Streamlit Multi-TF Plotly Dashboard
    ├── docker-compose.yml        # Docker setup (MySQL, phpMyAdmin, Airflow)
    ├── .env.example              # Environment template
    ├── requirements.txt          # Python dependencies
    └── README.md
```

---

## Trend Analysis Indicators

* **EMA 20**: Exponential Moving Average (Short-term trend filter)
* **EMA 50**: Exponential Moving Average (Medium-term trend filter)
* **EMA 100**: Exponential Moving Average (Long-term trend filter)

*(รองรับการเปิด-ปิดคำนวณเพื่อใช้เป็น Trend Filter ให้กับ Quant Model)*