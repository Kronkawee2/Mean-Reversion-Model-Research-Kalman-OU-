# Quant Trader

เก็บและวิเคราะห์ราคาทองคำ (XAUUSD) กับ EURUSD หลาย timeframe พร้อมกัน แล้วเอาไปประกอบเป็นแนวทางเทรดเชิงระบบ ไม่ใช่แค่ดูกราฟแล้วเดา

แนวคิดหลักที่ใช้คือ Smart Money Concepts (order block, FVG, BOS/CHoCH, liquidity sweep), Candle Range Theory (Asian range, session sweep, range equilibrium), divergence ทั้งฝั่ง technical และ inter-market, กับ volume profile — เอาทั้งหมดนี้มารวมเป็นคะแนน bias เดียวที่วัดผลย้อนหลังได้จริง

จุดยืนของโปรเจกต์นี้คือไม่เชื่ออะไรง่ายๆ จนกว่าจะพิสูจน์ได้ ทุก signal ต้อง backtest, มีข้อมูลมากพอจะเชื่อถือได้ (อ้างอิงมาตรฐานจาก Deflated Sharpe Ratio ของ Bailey & López de Prado) และเทียบกับกราฟจริงก่อนทุกครั้ง ระหว่างทางเจอบั๊กจริงหลายจุดที่ถ้าไม่เช็คละเอียดจะไม่มีทางรู้ เช่น timezone ของแต่ละแหล่งข้อมูลไม่ตรงกันเลยสักตัว หรือ SMC zone ที่ไม่มีวันหมดอายุจนสัญญาณค้างนิ่งไปนานกว่าปี — เหตุผลของแต่ละการตัดสินใจ พร้อมหลักฐานที่ใช้ประกอบ อยู่ใน [`docs/DECISIONS.md`](docs/DECISIONS.md)

## ข้อมูลมาจากไหน

| หมวด | สินทรัพย์ | แหล่ง | Timeframe |
| :--- | :--- | :--- | :--- |
| เทรดหลัก | XAUUSD, EURUSD | MT5 (Eightcap) | m5, m15, h1 |
| เทรดหลัก | XAUUSD, EURUSD | Yahoo Finance | h4, d1 |
| ดัชนีดอลลาร์ | DXY | Yahoo Finance | h1, d1 |
| ผลตอบแทนพันธบัตร | US10Y | Yahoo Finance | d1 |
| ความผันผวน | VIX | Yahoo Finance | d1 |
| หุ้นเหมืองทอง | GDX | Yahoo Finance | d1 |
| สถานะสถาบัน | CFTC COT (gold, EUR) | CFTC.gov | รายสัปดาห์ |
| ทองสำรอง ETF | SPDR Gold Shares | SPDR ทางการ | รายวัน |

ใช้สองแหล่งสำหรับคู่เทรดหลักเพราะแต่ละที่เก่งคนละเรื่อง — MT5 ให้ราคาตรงกับที่ broker จะให้เทรดจริงในกรอบเวลาสั้น ส่วน Yahoo Finance ครอบคลุมกรอบเวลายาวและมีข้อมูล macro ที่ MT5 ไม่มี

ข้อมูลเก็บเป็น 3 ชั้น:

- `raw_*` — ราคาดิบตรงจากแหล่งต้นทาง ไม่ผ่านการแปลงใดๆ
- `curated_*` — สัญญาณที่คำนวณแล้ว (zone, CRT, indicator, divergence, volume profile, bias)
- `mart` — ผลลัพธ์พร้อมใช้งานจริง (ยังไม่ได้เริ่มสร้างส่วนนี้)

## แนวคิดที่ใช้วิเคราะห์

**SMC (Smart Money Concepts)** — `analysis/smc_crt/` ตรวจจับ Break of Structure / Change of Character จาก swing high-low, Fair Value Gap แบบ 3 แท่ง, Order Block ต้นกำเนิดการเคลื่อนไหวแรง และ Liquidity Sweep (BSL/SSL) แต่ละ zone มีสถานะ active/mitigated/invalidated และนับเฉพาะ zone ที่สร้างภายใน 720 แท่ง h1 ล่าสุด ไม่ใช่สะสมไม่มีที่สิ้นสุด (จุดที่เจอปัญหาจริงและแก้ไปแล้ว รายละเอียดอยู่ใน DECISIONS.md)

**CRT (Candle Range Theory)** — Asian range และ session sweep ตรวจจับบน h1 (เพราะ session ผูกกับเวลานาฬิกา UTC ต้องใช้ความละเอียดสูง) ส่วน range equilibrium (จุดกึ่งกลาง premium/discount) คำนวณจาก h4/h6/d1

**Divergence** — เสร็จแล้ว 11 จาก 12 แบบ: technical ครบ 4 indicator (RSI, OBV, Stochastic, CCI ทั้ง regular และ hidden) และ inter-market ครบ (XAU vs DXY, EUR vs DXY, XAU vs US10Y, XAU vs GDX, COT ทั้งสองสินทรัพย์, XAU vs SPDR holdings) เหลือ EUR vs yield-spread ที่ยังไม่มีแหล่งข้อมูลฟรีที่ตรงมาตรฐาน กับ MTF Alignment ที่ต้องรอ LTF trigger logic มาก่อน

**Volume Profile** — `analysis/volume_profile/` คำนวณ POC, VAH/VAL (70% value area), HVN/LVN ต่อ session (แบ่งตามวันปฏิทิน UTC) จากข้อมูล h1

**HTF Bias Engine** — `analysis/strategies/htf_bias_engine.py` รวมทุกอย่างข้างต้นเป็นคะแนน confluence เดียวต่อแท่ง โดย SMC เป็นตัวหลัก (cap ±30) ตามมาด้วย indicator (±20), CRT กับ liquidity sweep (±15 เท่ากัน), volume profile (±10) — hidden divergence เสริมคะแนนทิศทางเดียวกัน (cap ±24 กันไม่ให้แซง SMC) ส่วน regular divergence ลดทอนคะแนนรวมแบบคูณ ไม่ใช่โหวตแข่งกัน (floor ที่ 0.7225 กันไม่ให้ลบล้างสัญญาณโครงสร้างจนหมด) รองรับ session weighting สองแบบ คือ static ตามเวลานาฬิกา (ค่าเริ่มต้น) และ dynamic ตาม liquidity sweep ที่เกิดจริง

ยังไม่ได้สร้าง: LTF trigger logic (จุดเข้าเทรดจริง), risk management, backtester, และ dashboard ตัวเต็ม (มี dashboard พื้นฐานแสดงกราฟราคาอยู่ก่อนแล้ว แต่ยังไม่ได้เพิ่ม overlay ของสัญญาณทั้งหมดข้างต้น)

## โครงสร้างโปรเจกต์

```
mt5-tracker/
├── analysis/
│   ├── smc_crt/            # structure, imbalance, order_block, liquidity, zone_state, crt_engine
│   ├── features/           # EMA, ATR, RSI, Stochastic, CCI, OBV
│   ├── divergence/          # pivot detection + classification, indicator-agnostic
│   ├── volume_profile/      # POC, VAH, VAL, HVN, LVN
│   └── strategies/          # htf_bias_engine.py
├── fetcher/                # MT5 + Yahoo + COT + SPDR clients, timezone_utils
├── scripts/
│   ├── sync/                # ดึงข้อมูลเข้า raw layer
│   ├── detection/           # รัน pipeline คำนวณ curated layer
│   └── diagnostic/          # เครื่องมือตรวจสอบ/แก้ข้อมูลย้อนหลัง
├── storage/                 # schema_raw.sql, schema_curated.sql, schema_mart.sql
├── dashboard/                # Streamlit (พื้นฐาน)
├── tests/
└── docs/
    ├── DECISIONS.md          # เหตุผลของทุกการตัดสินใจสำคัญ พร้อมหลักฐาน
    ├── README-MT5.md          # ติดตั้งและใช้งาน MT5 fetcher
    └── ORIGINAL_PLAN.md       # แผนเดิมก่อนเริ่มสร้างจริง (ไว้เทียบกับของจริง)
```
## เริ่มใช้งาน

ตั้งค่า MT5 ดูรายละเอียดที่ [`docs/README-MT5.md`](docs/README-MT5.md)

```bash
docker-compose up -d # รันครั้งเดียวตอนเริ่มทำงาน/ตอนเปิดคอม
python main.py # รัน pipeline ทั้งหมด: MT5 sync -> Yahoo sync -> detection จะได้ htf_bias ล่าสุด รันได้กี่รอบก็ได้ที่อยากได้ข้อมูลล่าสุด
```