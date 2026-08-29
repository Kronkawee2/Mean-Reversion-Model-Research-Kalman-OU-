# Quant Trader

เก็บและวิเคราะห์ราคาทองคำ (XAUUSD) กับ EURUSD หลาย timeframe พร้อมกัน เอาไปประกอบเป็นแนวทางเทรดเชิงระบบ ไม่ใช่ดูกราฟแล้วเดา

วิธีทำงานคร่าวๆ: ดึงราคาดิบเข้า DB ก่อน (MT5 สำหรับคู่เทรดหลัก, Yahoo/FRED/ECB/COT/SPDR สำหรับข้อมูล macro ที่ broker ไม่มีให้เทรด) แล้วรันสัญญาณต่างๆ ทับข้อมูลนั้น — SMC (order block, FVG, BOS/CHoCH, liquidity sweep), CRT (Asian range, session sweep, range equilibrium), divergence ทั้ง technical และ inter-market, volume profile — สุดท้ายรวมทุกอย่างเป็นคะแนน bias เดียวต่อแท่ง h1 (bullish/neutral/bearish) ที่วัดผลย้อนหลังได้จริงด้วย backtest ไม่ใช่แค่ดูสวยบนกราฟ

จุดยืนของโปรเจกต์คือไม่เชื่ออะไรง่ายๆ จนกว่าจะพิสูจน์ได้ signal ต้องผ่าน backtest และมีข้อมูลมากพอจะเชื่อถือได้ (อ้างอิง Deflated Sharpe Ratio ของ Bailey & López de Prado) เทียบกับกราฟจริงก่อนทุกครั้ง ระหว่างทางเจอบั๊กจริงหลายจุดที่ถ้าไม่เช็คละเอียดจะไม่มีทางรู้เลย เช่น timezone ของแต่ละแหล่งข้อมูลไม่ตรงกัน หรือ zone ที่ไม่มีวันหมดอายุจนสัญญาณค้างเป็นปี — เหตุผลของแต่ละการตัดสินใจอยู่ใน [`docs/DECISIONS.md`](docs/DECISIONS.md)

## ข้อมูลมาจากไหน

| สินทรัพย์ | แหล่ง | Timeframe |
| :--- | :--- | :--- |
| XAUUSD, EURUSD | MT5 (Eightcap) | m5, m15, h1 (h4/h6/d1 resample จาก h1) |
| DXY, VIX, Silver | MT5 (USDX, VIX, XAGUSD) | h1 (d1 resample จาก h1) |
| US10Y, GDX | Yahoo Finance | รายวัน |
| Fed Funds, TIPS, CPI | FRED | รายวัน/รายเดือน |
| EU 10Y yield | ECB | รายวัน |
| Geopolitical Risk Index | matteoiacoviello.com | รายวัน |
| CFTC COT (gold, EUR) | CFTC.gov | รายสัปดาห์ |
| SPDR Gold Shares holdings | SPDR ทางการ | รายวัน |

คู่เทรดหลักกับ DXY/VIX/Silver ใช้ MT5 เพราะ broker มี instrument ให้เทรดจริง ราคาจะตรงกับที่จะได้ในบัญชีจริง ส่วน US10Y กับ GDX ยังต้องพึ่ง Yahoo เพราะไม่มี bond yield หรือ ETF เหมืองทองให้เทรดใน MT5 ที่เหลือเป็นข้อมูล macro/สถิติที่ไม่มีทางเทรดได้อยู่แล้ว เลยดึงจากแหล่งของตัวเองตรงๆ

ข้อมูลเก็บเป็น 3 ชั้น: `raw_*` คือราคาดิบไม่ผ่านการแปลง, `curated_*` คือสัญญาณที่คำนวณแล้ว (zone, CRT, indicator, divergence, volume profile, bias), ส่วน `mart` (ผลลัพธ์พร้อมใช้งาน) ยังไม่ได้เริ่มสร้าง

## เช็คความถูกต้องของข้อมูล

ก่อนเชื่อตัวเลขใน DB ต้องเช็คก่อนเสมอ โดยเฉพาะตอนกราฟหรือตัวเลขบน dashboard ดูแปลกๆ (ประวัติบั๊กจริงที่เคยเจอพร้อมหลักฐานอยู่ใน [`docs/DECISIONS.md`](docs/DECISIONS.md))

**แถวซ้ำในตาราง raw** เจอสองแบบ: timestamp ซ้ำเป๊ะ (ไม่ควรเกิดเพราะมี unique key กันไว้อยู่แล้ว) กับ OHLC เหมือนกันทุกตัวแต่ timestamp ต่างกัน — แบบหลังนี้เจอบ่อยกว่าและอันตรายกว่า สาเหตุคือ fetcher เก่าเขียน local time ตรงๆ โดยไม่แปลงเป็น UTC พอแก้ bug แล้ว sync รอบใหม่ก็เขียนแถวที่ถูกเข้าไปอีกแถวคนละ timestamp เจอครั้งแรกที่ `raw_gold.d1` (~6,500 แถว) แล้วเจอซ้ำอีกทีเกือบทั้งตารางใน `raw_dxy/us10y/vix/gdx.d1` (รวม ~44,500 แถว)

เช็คด้วย `LAG()` เทียบ OHLC กับแถวก่อนหน้าเรียงตามเวลา (เร็วกว่า self-join บนตารางใหญ่มาก) แล้วดู gap ระหว่างสองแถว — ถ้าตรง 2-8 ชั่วโมงพอดีให้สงสัยว่าเป็น timezone bug ไม่ใช่แท่งราคานิ่งช่วงตลาดเงียบ แถวที่เวลาเป็น `00:00` เป๊ะมักเป็นแถวผิด (local midnight ที่ลืมแปลง) แต่ก่อนลบต้องเช็คกับแหล่งข้อมูลจริงก่อนทุกครั้งว่าแถวไหนถูกจริงๆ อย่าเดาจาก pattern อย่างเดียว

สองจุดที่พลาดมาแล้วตอน cleanup: อย่า diff กับข้อมูลที่ fetch สดใหม่ถ้า fetcher มีการ re-calibrate ทุกครั้งที่เรียก (timestamp จะคลาดกันไม่กี่วินาทีทำให้ diff เข้าใจผิดว่าทุกแถวไม่ตรงแล้วลบทั้งตาราง) กับตอนสร้าง set ของ timestamp มาเทียบให้ใช้ `.dt.strftime()` ไม่ใช่ `.astype(str)` — ตัวหลัง pandas จะตัดเวลาทิ้งถ้าทุกค่าเป็นเที่ยงคืนพอดี ทำให้ diff ผิดทั้งชุด ถ้า cleanup script รายงานว่าลบเกือบทั้งหมดทั้งที่ควรลบแค่บางส่วน ให้หยุดเช็ค diff logic ก่อนเสมอ

ถ้าตารางควรมีแค่แถวเดียวต่อวัน ให้เพิ่ม unique key บน `price_date` ไปด้วยเลย กันไม่ให้เกิดซ้ำได้อีกแม้ fetcher จะพังแบบเดิมซ้ำ

**เทียบกับแหล่งจริง** สุ่มแท่งจากวันที่ต่างกัน (รวมช่วง DST ด้วย) มาเทียบกับ Yahoo Finance หรือ MT5 terminal ตรงๆ ถ้าไม่ตรงคือบั๊กของเรา แต่ถ้าตรงกับแหล่งจริงเป๊ะแล้วแหล่งจริงเองมีค่าแปลกๆ (เจอจริงที่ `raw_eurusd.d1` วันที่ 2012-01-27) แปลว่าปัญหาอยู่ต้นทาง แก้ด้วยมือแทนเพราะ re-fetch ก็ไม่ช่วย

**เช็ค downstream ก่อนแก้ raw table** grep หาว่าอะไรอ่านตารางนั้นต่อ แต่ต้องเช็คด้วยว่า path นั้นถูกเรียกจริงใน pipeline (`run_detection.py`) หรือแค่ script รองรับไว้เฉยๆ (เจอจริงว่า `run_crt_detection.py` รองรับ `--timeframe d1` แต่ pipeline จริงไม่เคยสั่ง) แก้ raw แล้ว re-run detection ต้องเก็บกวาดแถว orphan เองด้วย เพราะ upsert ไม่ลบแถวเก่าที่ตอนนี้ไม่มีต้นทางแล้วให้

**ที่ดูเหมือนบั๊กแต่ไม่ใช่** — EURUSD volume=0 ใน `h4`/`d1` เป็นเรื่องปกติ (forex ไม่มีตลาดกลาง Yahoo เลยไม่มี volume จริงให้) ส่วน zone ที่ดูกว้างเต็มจอทันทีที่เปลี่ยน timeframe อาจเป็นเพราะ origin ของ zone อยู่นอกช่วงข้อมูลที่โหลด ไม่ใช่ error

## แนวคิดที่ใช้วิเคราะห์

**SMC (Smart Money Concepts)** — `analysis/smc_crt/` ตรวจจับ Break of Structure / Change of Character จาก swing high-low, Fair Value Gap แบบ 3 แท่ง, Order Block ต้นกำเนิดการเคลื่อนไหวแรง และ Liquidity Sweep (BSL/SSL) แต่ละ zone มีสถานะ active/mitigated/invalidated และนับเฉพาะ zone ที่สร้างภายใน 720 แท่ง h1 ล่าสุด ไม่ใช่สะสมไม่มีที่สิ้นสุด (จุดที่เจอปัญหาจริงและแก้ไปแล้ว รายละเอียดอยู่ใน DECISIONS.md)

**CRT (Candle Range Theory)** — Asian range และ session sweep ตรวจจับบน h1 (เพราะ session ผูกกับเวลานาฬิกา UTC ต้องใช้ความละเอียดสูง) ส่วน range equilibrium (จุดกึ่งกลาง premium/discount) คำนวณจาก h4/h6/d1

**Divergence** — เสร็จแล้ว 11 จาก 12 แบบ: technical ครบ 4 indicator (RSI, OBV, Stochastic, CCI ทั้ง regular และ hidden) และ inter-market ครบ (XAU vs DXY, EUR vs DXY, XAU vs US10Y, XAU vs GDX, COT ทั้งสองสินทรัพย์, XAU vs SPDR holdings) เหลือ EUR vs yield-spread ที่ยังไม่มีแหล่งข้อมูลฟรีที่ตรงมาตรฐาน กับ MTF Alignment ที่ต้องรอ LTF trigger logic มาก่อน

**Volume Profile** — `analysis/volume_profile/` คำนวณ POC, VAH/VAL (70% value area), HVN/LVN ต่อ session (แบ่งตามวันปฏิทิน UTC) จากข้อมูล h1 **(ไม่รันอัตโนมัติแล้ว — ดูหัวข้อ "ที่ไม่รันอัตโนมัติแล้ว" ด้านล่าง)**

**HTF Bias Engine** — `analysis/strategies/htf_bias_engine.py` รวมทุกอย่างข้างต้นเป็นคะแนน confluence เดียวต่อแท่ง โดย SMC เป็นตัวหลัก (cap ±30) ตามมาด้วย indicator (±20), CRT กับ liquidity sweep (±15 เท่ากัน), volume profile (±10) — hidden divergence เสริมคะแนนทิศทางเดียวกัน (cap ±24 กันไม่ให้แซง SMC) ส่วน regular divergence ลดทอนคะแนนรวมแบบคูณ ไม่ใช่โหวตแข่งกัน (floor ที่ 0.7225 กันไม่ให้ลบล้างสัญญาณโครงสร้างจนหมด) รองรับ session weighting สองแบบ คือ static ตามเวลานาฬิกา (ค่าเริ่มต้น) และ dynamic ตาม liquidity sweep ที่เกิดจริง **(ไม่รันอัตโนมัติแล้ว — คะแนนนี้ไม่มีอะไรอ่านไปใช้ต่อจริงแล้ว หน้าแดชบอร์ดที่เคยโชว์ก็ archive ไปแล้ว)**

**Composite Confluence Engine** — `analysis/strategies/composite_confluence_engine.py` ระบบสัญญาณหลักของ production ปัจจุบัน แทนที่ baseline เดิม (choch_only/choch_sweep) ให้คะแนนจาก SMC (zone_stack น้ำหนัก multi-timeframe D1>H6>H4>H1) + CHoCH + Liquidity Sweep (คำนวณสดจาก M15 ข้างในสเต็จนี้เอง) + Divergence รวม **4 ปัจจัย** เกณฑ์ผ่าน **3/4** (เดิมมี HTF Bias เป็นปัจจัยที่ 5 ด้วย แต่ตัดออกไปแล้วเพราะทดสอบกับ track record จริงพบว่า signal ที่ผ่านเกณฑ์ได้เพราะ HTF Bias เท่านั้น ขาดทุนสุทธิทั้งสองคู่เงิน — รายละเอียดอยู่ใน DECISIONS.md)

**Nested Zone Drilling** — `analysis/strategies/nested_zone_engine.py` กลไกหาจุดเข้าเทรดของ Composite Confluence Engine ปัจจุบัน แทนที่ H1-touch เดิม (ผู้ใช้เดิมรอราคาแตะ zone h1 เฉยๆ) ด้วยการไล่ "เจาะลึก" จาก zone HTF ที่ผ่านเกณฑ์ (เริ่มได้จาก D1/H6/H4/H1 ตัวไหนก็ได้ ไม่ต้องเริ่มที่ D1) ลงไปหา zone ย่อยที่ซ้อนอยู่ข้างในตามลำดับ D1>H6>H4>H1>M15>M5 ทีละชั้น เลือก zone ที่แคบที่สุดในแต่ละชั้นเสมอ (เป้าหมาย: entry แม่นและ stop loss เล็กที่สุดเท่าที่จะทำได้) ถ้าไล่ลงไปถึง M15/M5 ไม่เจอ zone ย่อยที่ถูกต้องเลย สัญญาณนั้นถูกตัดทิ้งทั้งชุด ไม่ fallback กลับไปใช้ zone HTF แทน — ทดสอบเทียบกับกลไก H1-touch เดิมแบบ side-by-side บนข้อมูลจริง 3 รอบ (60 วัน, 60 วันหลังแก้บั๊ก formation-gate, 180 วัน) ผลออกมาชนะทั้ง win rate และ expectancy สม่ำเสมอทุกรอบทั้งสองคู่เงิน จึงตัดสินใจใช้แทนของเดิมเป็น production เหตุผลและตัวเลขเต็มอยู่ใน DECISIONS.md

**ทำไมไม่ใช้ CRT ในคะแนนนี้** — ทดสอบแยกเดี่ยวแล้วพบว่า CRT ไม่ใช่ตัวบล็อกสัญญาณจริง: ในกลุ่ม candidate ที่ถูกปฏิเสธ (คะแนนไม่ถึงเกณฑ์เดิม 4/6) CRT เป็นปัจจัยที่ขาดแค่ ~61-63% ของเคส เทียบกับ htf_bias ที่ขาดถึง ~97% และ choch ~83-85% — แปลว่า CRT อยู่กลางๆ ไม่ใช่คอขวด พอลองบังคับ CRT เป็นเงื่อนไขบังคับ (gate) แทนที่จะเป็นแค่ 1 ใน 6 คะแนน ผลกลับแย่ลงกว่าทุก config ที่ทดสอบ — win rate ต่ำลง และ expectancy ติดลบที่ EURUSD (-0.126R) พอตัด CRT ออกทั้งหมดแล้วใช้ SMC+Divergence แทน ผลดีขึ้นทุกด้านในทั้งสองคู่เงิน:

| config | XAUUSD qualifying / win% / expectancy | EURUSD qualifying / win% / expectancy |
|---|---|---|
| SMC-only (ไม่มี CRT, ไม่มี divergence) | 169 / 33.7% / +0.223R | 216 / 36.1% / +0.315R |
| CRT-required (บังคับ CRT เป็น gate) | 187 / 28.9% / +0.008R | 273 / 23.8% / -0.126R |
| SMC + Divergence (ตัด CRT ออก, ใช้จริงตอนนี้) | 325 / 40.0% / +0.433R | 455 / 36.3% / +0.327R |

โค้ด CRT (`f_crt`, `crt_eq`) ยังเก็บไว้ในระบบเหมือนเดิม ไม่ได้ลบทิ้ง แค่ไม่เอาเข้าคะแนนรวม เผื่อได้ข้อมูลเพิ่มในอนาคตแล้วอยากทดสอบซ้ำ — รายละเอียดเต็มอยู่ใน DECISIONS.md

สถานะปัจจุบันยังไม่ผ่านเกณฑ์สถิติของโปรเจกต์ (EURUSD ~56.5% ของ floor, XAUUSD ~38.4%) แต่ตัดสินใจใช้ production ต่อเพราะ R:R (median ~2.55-2.58) เป็นโปรไฟล์ที่เทรดได้จริง ต่างจาก baseline เดิมที่ R:R ต่ำเกินไป (~0.28) sample size จะโตขึ้นเองผ่านการติดตามสัญญาณจริงทุกวัน (ตาราง `composite_confluence_signals`) สมมติฐาน lot size คงที่ 0.01 lot เทียบกับทุนเริ่มต้น $300 สำหรับคำนวณสถิติระยะยาว

## ลำดับการทำงานของ pipeline (`run_detection.py`)

`python main.py` รันเรียงเป็น stage ตามนี้ทุกครั้ง (หยุดทันทีถ้า stage ไหน fail ไม่รันสเต็จถัดไป):

1. **Feature engineering** (`run_feature_engineering.py`) — คำนวณ EMA20/50/200, ATR14, RSI14, Stochastic, CCI, OBV ต่อแท่ง h1 ของทั้งสองคู่เงิน เก็บลงตาราง `features` — ATR ใช้ตั้ง stop/target โดยตรงในสเต็จ Composite Confluence ด้านล่าง ส่วน RSI/OBV/Stoch/CCI เป็นวัตถุดิบให้สเต็จ Divergence
2. **SMC zones (h1/h4/h6/d1)** (`run_smc_zone_detection.py`) — ตรวจ order block, FVG, swing S/R, BOS/CHoCH ทั้ง 4 timeframe เก็บ `smc_signals` เป็นฐานของแทบทุกอย่างต่อจากนี้: root pool ของ Nested Zone Drilling, ปัจจัย `zone_stack`, และจุดอ้างอิงตั้ง stop loss
3. **CRT (h4, h6)** (`run_crt_detection.py`) — คำนวณ Asian range sweep และจุดกึ่งกลาง (equilibrium) เก็บ `crt_signals` — ใช้เป็นเป้าหมาย (target) ใน TP ladder ของ Composite Confluence เท่านั้น ไม่เข้าคะแนน scoring แล้ว (เหตุผลอยู่ด้านบน "ทำไมไม่ใช้ CRT ในคะแนนนี้")
4. **Divergence** (`run_divergence_detection.py` x4 indicator + `run_intermarket_divergence_detection.py`) — เทียบ swing ของราคากับ indicator และกับสินทรัพย์ข้ามตลาด เก็บ `divergence_signals` ป้อนเข้าปัจจัย `f_div`
5. **Composite Confluence signals** (`run_composite_confluence_detection.py`) — จุดหลักของระบบ: หา zone คุณภาพผ่าน Nested Zone Drilling (D1→H6→H4→H1→M15→M5) แล้วให้คะแนน 4 ปัจจัย (`f_sweep` คำนวณสดจาก M15 ในสเต็จนี้เอง, `f_choch`, `f_zone_stack`, `f_div`) เกณฑ์ผ่าน ≥3/4 คำนวณ stop/target แล้วบันทึกลง `composite_confluence_signals` — สเต็จนี้ช้าที่สุด (~70-80% ของเวลารวมทั้ง pipeline) เพราะต้องเจาะหา M15/M5 zone สดใหม่ทุก root candidate
6. **Composite Confluence resolution** (`run_composite_confluence_resolution.py`) — เช็ค signal เก่าที่ยัง "open" อยู่กับราคาที่เข้ามาใหม่ อัปเดตเป็น win/loss พร้อม R ที่ได้จริง

**ที่ไม่รันอัตโนมัติแล้ว** (เคยเป็น stage ในนี้ แต่ตัดออกเพราะเช็คแล้วไม่มีอะไรอ่านผลลัพธ์ไปใช้จริงอีก — รายละเอียด/หลักฐานเต็มอยู่ใน DECISIONS.md, สคริปต์ยังอยู่ครบรันเองได้เผื่ออนาคต):
- **Liquidity Sweep detection (H1)** (`run_liquidity_sweep_detection.py`) — เคยบันทึกลง `liquidity_sweeps` ไว้โชว์กราฟเก่า ตอนนี้กราฟหลักปิดการโชว์นี้ไปแล้ว และ Composite Confluence เองก็คำนวณ sweep สดจาก M15 แยกต่างหาก ไม่ได้อ่านตารางนี้
- **Volume Profile** (`run_volume_profile.py`) — consumer เดียวคือ HTF Bias Engine ด้านล่าง
- **HTF Bias** (`run_htf_bias_detection.py`) — คะแนนนี้เคยเป็นปัจจัยที่ 5 ของ Composite Confluence แต่ถูกตัดออก (ดูหัวข้อ Composite Confluence Engine ด้านบน) และหน้าแดชบอร์ดที่เคยโชว์ก็ archive ไปแล้ว ไม่มีอะไรอ่านผลลัพธ์นี้อีกเลย

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
# 1.รันครั้งเดียวตอนเริ่มทำงาน/ตอนเปิดคอม
docker-compose up -d

# 2.รัน pipeline ทั้งหมด: MT5 sync -> Yahoo sync -> detection จะได้ Composite Confluence signal ล่าสุด รันได้กี่รอบก็ได้ที่อยากได้ข้อมูลล่าสุด (ใช้เวลา ~20 นาที ส่วนใหญ่หมดไปกับ Nested Zone Drilling)
python main.py

# 3.เปิด dashboard ค้างไว้ใน terminal แยก ( Ctrl + C เพื่อหยุด server)
.\venv\Scripts\activate.ps1
c
```

```
python scripts/research/kalman_walkforward.py --symbol XAUUSD
python scripts/research/kalman_walkforward.py --symbol EURUSD
python scripts/research/kalman_walkforward.py --symbol NDX100
```