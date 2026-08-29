# Quant Trader — Mean Reversion Model Research (Kalman/OU family)

โปรเจกต์นี้เก็บราคาทองคำ (XAUUSD), EURUSD และ NDX100 จาก MT5 มาทดสอบสมมติฐานที่ว่าราคาที่เบี่ยงเบนจากค่าเฉลี่ยทางสถิติมีแนวโน้มดึงกลับ (mean reversion) เป็นสิ่งที่ใช้เทรดได้จริงหรือไม่ วิธีทดสอบคือสร้างโมเดลสุ่ม (stochastic process) ที่มาจากการแก้สมการทางคณิตศาสตร์จริง แล้วผ่านการตรวจสอบทางสถิติหลายชั้น ไม่เชื่อผล backtest ที่ดูดีเพียงลำพัง — ทุก config ต้องผ่านการทดสอบนัยสำคัญทางสถิติครบทุกด่านก่อนถึงจะนับว่ามี edge จริง

## สถานะสุดท้าย

ทดสอบครบ 4 โมเดล (OU, CIR, GARCH-OU, Jump-Diffusion OU) กับ 3 สินทรัพย์ (XAUUSD, EURUSD, NDX100) ผ่าน timeframe ที่มีข้อมูลเพียงพอเกือบทั้งหมด รวมการตรวจสอบ 4 ชั้น ได้แก่ backtest, walk-forward optimization, การทดสอบนัยสำคัญทางสถิติ (Bootstrap CI + Monte Carlo permutation test) และ fixed-config walk-forward พร้อมเช็คความทนทานข้าม train/test window

ผลสรุป: **ไม่มี combination ใดพิสูจน์ edge ที่ยืนยันได้ครบทุกด่านสถิติเลยสักตัว** ผลลัพธ์ที่ใกล้เคียงที่สุดคือ GARCH-OU บน XAUUSD M5 ซึ่งผ่าน fixed-config ที่ train/test window 90/30 วันได้ (Bootstrap 82.5%, Monte Carlo 87.6%) แต่พออ่อนลงเหลือ Bootstrap 55.4% เมื่อเปลี่ยนเป็น window 60/20 วัน — ใกล้เคียงระดับเดาสุ่ม จึงไม่ถือว่าเป็นหลักฐานที่มั่นคงพอ โมเดลและ combination อื่นทั้งหมดพังชัดเจนกว่านี้ (พิสูจน์แล้วว่าเป็น overfitting) หรือแย่กว่าการสุ่มเข้าไม้ตั้งแต่แรก

งานวิจัยด้วยแนวทางนี้ถือว่าปิดจบแล้ว รายละเอียดตัวเลขทั้งหมดอยู่ในตาราง [ผลรวมทุกโมเดลที่ทดสอบมา](#ผลรวมทุกโมเดลที่ทดสอบมา) ด้านล่าง และ log แบบเต็มทุก experiment อยู่ใน [`scripts/research/RESULTS.md`](scripts/research/RESULTS.md)

---

## สารบัญ

1. [ข้อมูลมาจากไหน](#ข้อมูลมาจาก-mt5-eightcap)
2. ["Edge" คืออะไร](#edge-คืออะไร)
3. [หลักการทำงานทั้งหมด: 4 ชั้น](#หลักการทำงานทั้งหมด-4-ชั้น)
4. [โมเดลที่ทดสอบ](#โมเดลที่ทดสอบ-ornstein-uhlenbeck-cir-garch-ou-jump-diffusion-ou)
5. [วัดผลด้วยอะไร](#วัดผลด้วยอะไร)
6. [ผลรวมทุกโมเดลที่ทดสอบมา](#ผลรวมทุกโมเดลที่ทดสอบมา)
7. [แนวทางที่ตัดทิ้งไปแล้ว](#แนวทางที่ตัดทิ้งไปแล้ว)
8. [โครงสร้างโปรเจกต์](#โครงสร้างโปรเจกต์)
9. [เริ่มใช้งาน](#เริ่มใช้งาน)

---

## ข้อมูลมาจาก MT5 (Eightcap)

| สินทรัพย์ | Timeframe ที่มี | ความลึกของข้อมูล |
| :--- | :--- | :--- |
| XAUUSD | m5, m15, h1, h4, d1 | M5 เริ่ม มี.ค. 2025 เท่านั้น (~1.5 ปี), H1 ย้อนไปถึง พ.ค. 2003 |
| EURUSD | m5, m15, h1, h4, d1 | M5 เริ่ม เม.ย. 2025 เท่านั้น (~1.5 ปี), H1 ย้อนไปถึง ก.ค. 2010 |
| NDX100 | m5, m15, h1 | M5 เริ่ม มี.ค. 2025 (~1.5 ปี เท่ากับ XAU/EUR M5), M15 เริ่ม พ.ค. 2022 (~4 ปี) |

ทุก symbol มีข้อมูล M5 ลึกแค่ราว 1.5 ปีเท่ากันหมด เป็นข้อจำกัดของโบรกเกอร์ Eightcap ที่เก็บประวัติละเอียดระดับ M5 สั้นกว่า H1/D1 มาก ยืนยันแล้วว่าไม่ใช่ข้อจำกัดของโค้ด fetcher เอง เพราะขอข้อมูลย้อนหลังกว่านั้นตรงจาก MT5 ได้ 0 แท่งเหมือนกันทั้ง 3 symbol นี่คือเหตุผลที่ rolling WFO บน timeframe M5 มี fold น้อยกว่า M15 มาก (14-23 fold เทียบกับ 46-48 fold)

เก็บเป็น `raw_gold` / `raw_eurusd` / `raw_ndx100` ในฐานข้อมูล MySQL (port 3308) มีคอลัมน์ `price_datetime, open_price, high_price, low_price, close_price, volume` เท่านั้น ทุก timestamp เป็น UTC เสมอ ไม่มี curated/mart layer สำหรับระบบนี้ เพราะการวิเคราะห์ทั้งหมดทำแบบ ad-hoc ผ่าน `scripts/research/`

## "Edge" คืออะไร

Edge คือข้อได้เปรียบทางสถิติที่ทำให้เงินโตได้จริงในระยะยาว ไม่ใช่แค่ทายถูกบ่อย

ไม่มี edge หมายถึงระบบพอ ๆ กับโยนเหรียญ 50/50 ได้เท่ากับเสีย เล่นไปนานๆ เงินจะแกว่งขึ้นลงแต่ไม่โตสุทธิ ถึงบางช่วงจะดูเหมือนกำไรเพราะบังเอิญถูกติดกันหลายไม้ก็ไม่นับเป็น edge มี edge หมายถึงไม่ต้องถูกทุกไม้ แต่ค่าเฉลี่ยผลลัพธ์เป็นบวกจริง เล่นไปนานๆ เงินจะโตขึ้นตาม Law of Large Numbers ต่อให้แต่ละไม้เดี่ยวๆ ยังสุ่มอยู่ก็ตาม

ปัญหาคือกำไรที่เห็นในการทดสอบครั้งเดียวบอกไม่ได้ว่าเป็น edge จริงหรือแค่โชคดีช่วงหนึ่ง นี่คือเหตุผลที่ทั้งโปรเจกต์วนอยู่กับการตรวจสอบซ้ำหลายมุม (ดูหัวข้อ [วัดผลด้วยอะไร](#วัดผลด้วยอะไร)) แทนที่จะเชื่อ backtest ที่ดูดีครั้งเดียวแล้วจบ

หลักการคัดเลือกโมเดลของโปรเจกต์นี้คือทุกโมเดลที่ทดสอบต้อง derive มาจากการแก้สมการทางคณิตศาสตร์จริง (stochastic differential equation ที่มีคนพิสูจน์มาแล้ว) ไม่ใช่กติกาเชิงประจักษ์ที่คิดขึ้นจากการสังเกตแล้วมาทดสอบว่าใช้ได้ แนวทางแบบหลังเคยลองแล้วและถูกตัดทิ้งไป ดูหัวข้อ [แนวทางที่ตัดทิ้งไปแล้ว](#แนวทางที่ตัดทิ้งไปแล้ว)

## หลักการทำงานทั้งหมด: 4 ชั้น

ทุกโมเดลในโปรเจกต์นี้วิ่งผ่านกระบวนการเดียวกัน 4 ชั้นซ้อนกัน ชั้นแรกสร้างผลลัพธ์ ชั้นหลังตรวจสอบว่าผลลัพธ์นั้นเชื่อได้จริงหรือแค่บังเอิญ ไม่มีชั้นไหนเป็น machine learning เลยสักชั้น ทุกอย่างเป็นสมการคณิตศาสตร์ตายตัวบวกกับสถิติเชิงตรวจสอบเท่านั้น

**ชั้น 1 — สูตรโมเดล.** OU/CIR/GARCH-OU/Jump-Diffusion OU เป็นสมการที่คำนวณว่าตอนนี้ราคาเบี่ยงจากค่าเฉลี่ยไปไกลแค่ไหน (หน่วย σ) ถ้าเบี่ยงเกินค่า `k` ที่กำหนดถือว่าผิดปกติพอจะออกสัญญาณเข้าไม้สวนทาง รายละเอียดสมการแต่ละตัวอยู่ในหัวข้อ [โมเดลที่ทดสอบ](#โมเดลที่ทดสอบ-ornstein-uhlenbeck-cir-garch-ou-jump-diffusion-ou)

**ชั้น 2 — Backtest.** เอาสูตรชั้น 1 ไปรันกับราคาย้อนหลังจริง ทุกครั้งที่สัญญาณสั่งเข้าก็จำลองเปิดไม้ (หักค่าธรรมเนียม/สเปรด) พอราคากลับมาแตะค่าเฉลี่ยหรือชนสตอปก็ปิดไม้ นับกำไรขาดทุนของทุกไม้ที่เกิด backtest เป็นแค่เครื่องคิดเลขที่รับ parameter กับข้อมูลราคาช่วงหนึ่งแล้วคืนผลลัพธ์ ไม่รู้จักคำว่า train/test เลย

**ชั้น 3 — Walk-Forward Optimization.** สูตรชั้น 1 มีตัวเลขให้ปรับ เช่น `calib_window`, `k` ลองสลับได้หลายสิบชุด (grid) ถ้าเลือกชุดที่ดีที่สุดจากข้อมูลชุดเดียวกับที่เอาไปอวดผล จะดูดีเสมอทั้งที่อาจแค่บังเอิญ fit กับ noise ของช่วงนั้น ขั้นตอนนี้ไม่ใช่ ML เรียนรู้อะไร เป็นเพียงการไล่เทียบตัวเลขที่เตรียมไว้แล้วหยิบตัวที่กำไรดีสุด — train/test เป็นแนวคิดสถิติทั่วไปที่ต้องใช้ทุกครั้งที่มีการเลือกจากข้อมูล ไม่ว่าจะเป็น ML หรือไม่ก็ตาม วิธีป้องกันการหลอกตัวเองมีดังนี้:

1. แบ่งข้อมูลเป็นช่วง (fold) เรียงตามเวลา
2. เอาช่วง train (90 วัน) รัน backtest ทุกชุดใน grid แล้วเลือกชุดที่กำไรดีที่สุด
3. เอาชุดที่ชนะไปรัน backtest กับช่วง test (30 วันถัดไป ไม่เคยใช้ตอนเลือก parameter)
4. เลื่อนหน้าต่างไป ทำซ้ำ 14-48 รอบตลอดข้อมูลที่มี
5. เก็บผลเฉพาะฝั่ง test มาต่อกันเป็น track record เดียว รวมทั้งไม้ชนะและไม้แพ้ ไม่ได้เลือกมาแต่ฝั่งดี

**ชั้น 4 — ทดสอบนัยสำคัญทางสถิติ.** ต่อให้ผ่านชั้น 3 ก็ยังมีการเลือก parameter ใหม่ทุก fold อยู่ดี ยังมีโอกาสบังเอิญเลือกได้ดี ต้องมีเครื่องมือวัดความมั่นใจอีกชั้นซ้อนบน track record จากชั้น 3 รายละเอียดเต็มอยู่ในหัวข้อ [วัดผลด้วยอะไร](#วัดผลด้วยอะไร):

- Bootstrap CI — สุ่มดึงไม้จาก track record เดิมซ้ำ 5,000 รอบ ไม่สนใจลำดับเวลาเพราะถามแค่ว่าค่าเฉลี่ยต่างจากศูนย์ไหม
- Monte Carlo Permutation Test — เทียบกับการสุ่มเข้าไม้แบบไม่มีสมองเลือกจังหวะ คุมจำนวนไม้และระยะเวลาถือให้เท่ากัน ดูว่าผลจริงเอาชนะการสุ่มได้กี่เปอร์เซ็นต์
- Fixed-Config Walk-Forward — ด่านสุดท้าย ล็อก parameter ตัวเดียวไม่เปลี่ยนเลยตลอดทุก fold ตัดโอกาสที่จะได้เลือกใหม่ทุกรอบแล้วบังเอิญได้ดี รันตามลำดับเวลาจริงต่อเนื่อง ใกล้เคียงสภาพเทรดจริงที่สุดในบรรดาทุกวิธี

ข้อควรระวัง: Bootstrap และ Monte Carlo เป็นเครื่องมือวัดความมั่นใจทางสถิติของ track record ที่มีอยู่แล้วเท่านั้น ไม่ใช่วิธีเทรดจริงและไม่ได้บอกอะไรเรื่อง drawdown หรือ equity curve ตามลำดับเวลาจริง (ดูจากกราฟ equity curve และ per-fold PF ในไฟล์ PNG แทน) ต้องผ่านทั้ง 3 การทดสอบในชั้น 4 พร้อมกันถึงจะเชื่อได้ว่าเป็น edge จริงไม่ใช่โชค

## โมเดลที่ทดสอบ: Ornstein-Uhlenbeck, CIR, GARCH-OU, Jump-Diffusion OU

ทั้ง 4 โมเดลมีสมมติฐานเรื่องแรงดึงกลับเข้าค่าเฉลี่ย (drift) เหมือนกันทุกตัว สิ่งที่ต่างกันคือ noise/variance รอบเส้นดึงกลับนั้นมีพฤติกรรมแบบไหน

| โมเดล | ไฟล์ | Variance เป็นแบบไหน | ที่มา |
|---|---|---|---|
| Ornstein-Uhlenbeck (OU) | `analysis/strategies/kalman_mean_reversion.py` | คงที่ | โมเดลมาตรฐานที่ใช้กันในการเงินเชิงปริมาณ |
| Cox-Ingersoll-Ross (CIR) | `analysis/strategies/cir_mean_reversion.py` | ขึ้นกับระดับราคาปัจจุบัน | ต้นฉบับใช้ทำโมเดลอัตราดอกเบี้ย (การันตีค่าไม่ติดลบ) |
| GARCH(1,1)-filtered OU | `analysis/strategies/garch_ou_mean_reversion.py` | ขึ้นกับ shock/variance ล่าสุด | Bollerslev (1986) ต่อยอดจาก Engle's ARCH (Nobel Prize 2003) |
| Jump-Diffusion OU | `analysis/strategies/jump_ou_mean_reversion.py` | คงที่ (diffusion) + jump term แยก | Merton (1976) ใช้จริงกับราคาพลังงาน/สินค้าโภคภัณฑ์ (Cartea & Figueroa 2005) |

### 1. Ornstein-Uhlenbeck (OU)

สมการต่อเนื่อง:

$$dX_t = \theta(\mu - X_t)\,dt + \sigma\,dW_t$$

$X_t$ คือราคา, $\mu$ คือจุดสมดุลระยะยาว, $\theta$ คือความแรงของแรงดึงกลับ, $\sigma$ คือความผันผวนคงที่, $dW_t$ คือ Brownian motion

โค้ด fit เป็น AR(1) แบบไม่ต่อเนื่องบนหน้าต่างข้อมูลย้อนหลัง (`estimate_ar1()`): $X_t = c + \phi X_{t-1} + \varepsilon_t$ แล้วแปลงกลับผ่าน $\phi = e^{-\theta}$ ได้ $\theta = -\ln(\phi)$

Stationary std: $\sigma_{stat} = \sigma / \sqrt{2\theta}$ ใช้กำหนดว่าห่างจากจุดสมดุลแค่ไหนถึงผิดปกติ

Half-life: $\ln 2 / \theta$ คือจำนวนแท่งที่คาดว่าราคาจะดึงกลับครึ่งทาง

จุดสมดุล $\mu$ ที่ประมาณจากหน้าต่างข้อมูลเดียวมี noise จึงใช้ Kalman filter แทน moving average เฉยๆ — `KalmanOU` ทำให้ state ของ filter คือตัวจุดสมดุลเอง แล้วอัปเดตทุกแท่งด้วยราคาจริง ผสมค่าที่โมเดลคาดไว้กับค่าที่สังเกตเห็นจริงตาม Kalman gain:

Predict: $\hat{x}_{t|t-1} = \phi\,\hat{x}_{t-1} + (1-\phi)\,\mu_t$, $\ P_{t|t-1} = \phi^2 P_{t-1} + Q$

Update: $K_t = \dfrac{P_{t|t-1}}{P_{t|t-1}+R}$, $\ \hat{x}_t = \hat{x}_{t|t-1}+K_t(z_t-\hat{x}_{t|t-1})$, $\ P_t=(1-K_t)P_{t|t-1}$

โดย $Q = \sigma^2(1-\phi^2) \times$ `q_mult`, $R = \sigma^2 \times$ `obs_noise_scale`

### 2. CIR — variance ขึ้นกับระดับราคา

$$dX_t = \theta(\mu-X_t)\,dt + \sigma\sqrt{X_t}\,dW_t$$

Drift เหมือน OU เป๊ะ ต่างแค่ diffusion term: variance สูงเมื่อราคาสูง ต่ำเมื่อราคาต่ำ แทนที่จะคงที่ตลอดแบบ OU ประมาณ $\sigma^2$ ด้วย conditional least squares (Chan/Karolyi/Longstaff/Sanders 1992): $\sigma^2 = \text{mean}(\varepsilon_t^2 / X_{t-1})$ จาก AR(1) residuals เดียวกับ OU ส่วน Kalman gain ($Q$, $R$) คำนวณใหม่ทุกบาร์ตามระดับราคาปัจจุบัน stationary std จึงเปลี่ยนเป็น $\sigma_{stat,t} = \sqrt{\sigma^2 X_t / (2\theta)}$ แถบกว้างหรือแคบตามราคา

### 3. GARCH(1,1)-filtered OU — variance ตาม volatility clustering

$$\sigma_t^2 = \omega + \alpha\,\varepsilon_{t-1}^2 + \beta\,\sigma_{t-1}^2$$

Drift เหมือน OU/CIR เป๊ะ ต่างแค่ diffusion ที่จับปรากฏการณ์ volatility clustering (ช่วงผันผวนสูงมักตามด้วยผันผวนสูงต่อ ช่วงนิ่งมักตามด้วยนิ่งต่อ เป็นข้อเท็จจริงเชิงสถิติที่มีหลักฐานหนักแน่นในข้อมูลการเงิน) พารามิเตอร์ $(\omega,\alpha,\beta)$ fit ด้วย Maximum Likelihood บน AR(1) residuals ของหน้าต่าง calibration แล้ว $\sigma_t^2$ เป็น live state ที่อัปเดตทุกบาร์จาก innovation ของ Kalman filter เอง ($\varepsilon_t = z_t - \hat{x}_{t|t-1}$) ทำให้แถบกว้างหรือแคบตามความรุนแรงของ shock ล่าสุด ไม่ใช่ตามระดับราคาแบบ CIR หรือคงที่แบบ OU

### 4. Jump-Diffusion OU — แยกจั๊มพ์ (structural break) ออกจาก noise ปกติ

$$dX_t = \theta(\mu-X_t)\,dt + \sigma\,dW_t + J\,dN_t$$

$N_t$ คือ Poisson jump process ความถี่ $\lambda$, $J$ คือขนาดจั๊มพ์ เพิ่มการเปลี่ยนแปลงเชิงโครงสร้างแบบไม่ต่อเนื่องทับบน diffusion แบบ OU (Merton 1976 ใช้จริงกับตลาดที่มี news shock บ่อย) แยก residual เป็น diffusion กับ jump ด้วย threshold `jump_z × std` (ค่าเริ่มต้น 3.5σ) ประมาณ $\sigma$ จาก residual ฝั่ง diffusion เท่านั้นเพื่อไม่ให้ปนเปื้อนจาก jump แบบที่ OU ธรรมดาเจอ แล้วเพิ่มกติกาใหม่สองอย่าง: บล็อกเข้าไม้ถ้าเบี่ยงเบนปัจจุบันเป็น jump เอง (ถือเป็น structural break ไม่ใช่จังหวะ mean-revert) และหยุดไม้ทันทีถ้าเกิด jump ใหม่ระหว่างถือ (`jump_stop`)

ผลทดสอบบน XAUUSD M5 (RESULTS.md exp 35) แย่ที่สุดในบรรดา 4 โมเดล — PF 0.76, Bootstrap 6.2%, Monte Carlo 9.9% แย่กว่าการสุ่มมาก น่าจะเป็นเพราะ `jump_stop` ตัดไม้กำไรทิ้งเร็วเกินไปเมื่อเจอ overshoot ปกติที่ถูกจัดเป็น jump ผิดพลาด

### VolatilityRegimeHMM — กรอง regime แบบ Bayesian (ใช้ร่วมกับทั้ง 4 โมเดล)

Hidden Markov Model 3-state (LOW/MED/HIGH volatility) บล็อกไม่ให้เข้าไม้ตอนตลาดผันผวนสูงผิดปกติ ทำงานแบบ forward filtering ทุกแท่ง:

$$\text{belief}_t(s) \;\propto\; \left[\sum_{s'} A(s',s)\,\text{belief}_{t-1}(s')\right] \times \mathcal{N}\big(v_t;\ \text{mean}_s,\ \text{std}_s\big)$$

เลือก regime ที่ belief สูงสุด แล้วบล็อกการเข้าไม้ใหม่ถ้าอยู่ใน `hmm_block_states` (ค่าเริ่มต้นคือ HIGH เท่านั้น) พิสูจน์แล้วจาก ablation ว่าช่วยจริงใน 5 จาก 6 กรณีที่ทดสอบ

### กติกาเข้า/ออกไม้ (เหมือนกันทั้ง 4 โมเดล)

เข้าไม้เมื่อราคาห่างจากจุดสมดุลเกิน $k$ เท่าของ $\sigma_{stat}$: short ถ้า $price > \hat{x}_t + k\sigma_{stat}$, long ถ้า $price < \hat{x}_t - k\sigma_{stat}$ ปิดไม้ปกติเมื่อราคากลับมาแตะ $\hat{x}_t$ หรือชน risk control

| พารามิเตอร์ | ความหมาย |
|---|---|
| `calib_window` | จำนวนแท่งย้อนหลังที่ใช้ fit พารามิเตอร์ใหม่ |
| `k` | ความห่างขั้นต่ำ (หน่วย $\sigma_{stat}$) ที่นับว่าผิดปกติพอจะเข้าไม้ |
| `z_stop` | ตัดขาดทุนถ้า $\lvert price-\hat{x}_t\rvert/\sigma_{stat} \ge$ ค่านี้ คำนวณใหม่ทุกแท่ง |
| `half_life_mult` | time-stop: ปิดไม้ถ้าถือเกิน `half_life_mult` เท่าของ half-life แท่งแล้วยังไม่กลับ |
| `tau_threshold` | กรองฝั่งเข้า: เข้าได้เฉพาะเมื่อ half-life ปัจจุบัน ≤ ค่านี้ |
| `friction_hurdle_mult`, `spread` | เข้าได้เฉพาะเมื่อเบี่ยงเบน ≥ `friction_hurdle_mult` เท่าของ `spread` (ค่าเริ่มต้น 2.5 เท่า) |
| `side` | `"both"` / `"long_only"` / `"short_only"` |

## วัดผลด้วยอะไร

โปรเจกต์นี้ใช้มาตรวัดนัยสำคัญทางสถิติ 3 แบบ คนละแบบสำหรับคนละสถานการณ์:

| มาตรวัด | ใช้ตอนไหน | ตอบคำถามอะไร | เกณฑ์ผ่าน |
|---|---|---|---|
| Deflated Sharpe Ratio (DSR) | Fixed train/val/test split (`kalman_walkforward.py`) เลือก config เดียวจาก grid ครั้งเดียว | ผลดีที่สุดที่เจอเกินกว่าที่คาดจะเจอโดยบังเอิญจากการลอง N config ไหม | DSR > 95% |
| Bootstrap Confidence Interval | Rolling WFO ทุกโมเดล แต่ละ fold เลือก config แยกกัน | กำไรเฉลี่ยต่อไม้ต่างจากศูนย์อย่างมีนัยสำคัญไหม | ขอบล่างของ CI > 0 |
| Monte Carlo Permutation Test | ใช้กับทุกโมเดลตั้งแต่ CIR เป็นต้นไป | ผลจริงดีกว่าการสุ่มเข้าไม้ (จำนวนและระยะเวลาถือเท่ากัน) แค่ไหน | เอาชนะสุ่มได้อย่างน้อย 95% ของรอบ |

DSR (Bailey & López de Prado, `analysis/backtester/deflated_sharpe.py`) อิงหลักที่ว่ายิ่ง grid search ลองหลาย config ยิ่งมีโอกาสที่บางอันจะดูดีเพราะบังเอิญ เหมือนซื้อล็อตเตอรี่หลายใบ DSR หักโทษจำนวน trial และความแปรปรวนของผลลัพธ์ระหว่าง config ก่อนตัดสิน ข้อจำกัดคือเช็คได้แค่ว่าเกินบังเอิญจากการลองหลาย config ไหม ไม่ได้เช็คว่าจะเกิดซ้ำในอนาคตไหม (ดูกรณี XAUUSD M5 ในตารางผลด้านล่าง: DSR 98.87% ตอนแรก แต่ไม่ผ่านเมื่อตรวจด้วยวิธีอื่น)

Bootstrap CI (`bootstrap_expectancy_ci()` ใน `rolling_wfo.py`) เข้ามาแทน DSR เพราะ DSR ตั้งสมมติฐานว่าเลือก config ครั้งเดียว ซึ่งไม่ตรงกับ rolling WFO ที่แต่ละ fold เลือก config แยกกัน วิธีนี้ resample ไม้ out-of-sample ที่ stitch จากทุก fold 5,000 รอบ แล้วดูว่า 95% ของค่าเฉลี่ยที่สุ่มได้อยู่เหนือศูนย์ทั้งหมดไหม

Monte Carlo Permutation Test (`monte_carlo_baseline()` ใน `cir_rolling_wfo.py`) เป็นหลักการมาตรฐานในวงการ อ้างอิงเช่นหนังสือ Permutation and Randomization Tests for Trading System Development ของ Timothy Masters เทียบผลจริงกับการสุ่มเข้าไม้ (ทิศทางและจุดเข้าสุ่ม) ที่คุมจำนวนไม้และระยะเวลาถือให้เหมือนของจริงทุกประการ ทำซ้ำ 1,000 รอบ วัดว่าผลจริงอยู่ที่ percentile เท่าไหร่

การทดสอบเสริมคือ Fixed-Config Walk-Forward ล็อค config ที่ถูกเลือกบ่อยที่สุดข้าม fold ให้เหลือตัวเดียว รันผ่านทุก fold โดยไม่ re-optimize เลย ถ้าผลยังทนอยู่แปลว่าผลจาก re-optimize ไม่ใช่ overfitting การทดสอบนี้เผยให้เห็นว่า CIR overfit จริงในทุก combination ที่ทดสอบ ขณะที่ GARCH-OU บน XAUUSD M5 ทนทานกว่าที่ window เดียวแต่ก็ยังอ่อนลงมากเมื่อเปลี่ยน window (ดูตารางถัดไป)

## ผลรวมทุกโมเดลที่ทดสอบมา

### Fixed-split (DSR) — รอบแรกสุดของโปรเจกต์

| Symbol | TF | PF | Win% | DSR | ผ่านเกณฑ์ 95%? |
|---|---|---|---|---|---|
| XAUUSD | M5 | 5.96 | 54.5% | 98.87% | ผ่านตอนแรก ภายหลังพิสูจน์ว่าไม่จริง |
| XAUUSD | M15 / H1 | 1.26 / 0.61 | 50.0% / 52.9% | 26.4% / 2.3% | ไม่ผ่าน |
| EURUSD | M5 / M15 / H1 | 2.83 / 9.86 / 1.09 | 64.0% / 60.0% / 46.3% | 11.9% / 57.4% / 0.1% | ไม่ผ่าน |
| NDX100 | M5 / M15 / H1 | 1.05 / 1.72 / 0.46 | 60.0% / 53.6% / 39.3% | 11.0% / 38.8% / 0.4% | ไม่ผ่าน |

8 จาก 9 ไม่ผ่านตั้งแต่รอบแรก และ XAUUSD M5 ที่ดูผ่านถูกพิสูจน์ในขั้นต่อมาว่าเป็นความบังเอิญ ไม่ใช่ edge จริง (validation/test correlation ติดลบ, Spearman ρ ตั้งแต่ -0.13 ถึง -0.50)

### Rolling Walk-Forward — ทดสอบ 4 โมเดลข้ามหลายช่วงเวลา

| โมเดล | Symbol/TF | PF รวม | Bootstrap P(mean>0) | Monte Carlo | Fixed-Config |
|---|---|---|---|---|---|
| OU | XAUUSD M5 | 1.43 | 95.1% | 97.0% | พัง (PF→0.92, ติดลบมีนัยสำคัญ) |
| OU | XAUUSD M15 | 0.83 | 9.2% | 6.2% | - |
| OU | EURUSD M5 | 0.83 | 21.9% | 85.4% | - |
| OU | EURUSD M15 | 0.90 | 15.2% | 84.8% | - |
| OU | NDX100 M15 | 1.00 | 49.2% | 70.0% | - |
| CIR | XAUUSD M5 | 1.23 | 80.8% | 85.7% | ไม่ได้ทดสอบ |
| CIR | XAUUSD M15 | 0.81 | 9.1% | 3.0% (แย่กว่าสุ่ม) | ไม่ได้ทดสอบ |
| CIR | EURUSD M5 | 1.23 | 79.1% | 99.6% | พัง (PF→0.79, Bootstrap→10.2%, MC→80.0%) |
| CIR | EURUSD M15 | 0.99 | 47.7% | 98.3% | พัง (PF→0.85, ติดลบมีนัยสำคัญ) |
| CIR | NDX100 M15 | 1.08 | 80.4% | 93.5% | พัง (PF→0.97, Bootstrap→35.1%, MC→58.5%) |
| CIR | NDX100 M5 | 1.01 | 52.8% (เท่าเดาสุ่ม) | 61.8% | - |
| GARCH-OU | XAUUSD M5 | 1.36 | 87.9% | 90.2% | ทนที่ 90/30 (PF→1.28) แต่อ่อนลงมากที่ 60/20 (Bootstrap→55.4%) |
| GARCH-OU | XAUUSD M15 | 1.00 | 50.3% (เท่าเดาสุ่ม) | 51.7% | - |
| GARCH-OU | EURUSD M5 | 0.63 | 1.3% (ลบมีนัยสำคัญ) | 46.6% | - |
| GARCH-OU | EURUSD M15 | 0.70 | 1.5% (ลบมีนัยสำคัญ) | 14.5% (แพ้สุ่ม) | - |
| GARCH-OU | NDX100 M15 | 0.98 | 43.1% (เท่าเดาสุ่ม) | 57.4% | - |
| GARCH-OU | NDX100 M5 | 0.85 | 21.4% | 34.9% (แย่กว่าสุ่ม) | - |
| Jump-Diffusion OU | XAUUSD M5 | 0.76 | 6.2% | 9.9% (แย่กว่าสุ่มมาก) | - |

ทดสอบ fixed-config walk-forward ครบผลลัพธ์ที่ดีที่สุดของทั้ง 3 สินทรัพย์แล้ว (XAUUSD: OU M5 กับ GARCH-OU M5, EURUSD: CIR M5 กับ CIR M15, NDX100: CIR M15) ด้วย window 90/30 วัน ทุกตัวพังหมดยกเว้นตัวเดียวคือ GARCH-OU บน XAUUSD M5 ตัวเลขที่ดูดีตอน re-optimize ทุก fold โดยเฉพาะ Monte Carlo ที่เคยดูใกล้ผ่าน 93-99% ยุบตัวลงเหลือ 58-80% หรือแย่กว่านั้นทันทีที่ล็อค config เดียว

เช็คต่อด้วย window อื่น (60/20 วัน ทำแบบเดียวกับที่เคยพิสูจน์ momentum) พบว่า GARCH-OU บน XAUUSD M5 ก็ไม่ทนทานเท่าที่คิด Bootstrap ตกจาก 82.5% เหลือ 55.4% ใกล้เคียงเดาสุ่ม 50% Monte Carlo ตกจาก 87.6% เหลือ 69.3% ในขณะที่ CIR ทั้ง 2 combination ที่พังไปแล้วยังคงพังสม่ำเสมอทั้งสอง window ยืนยันซ้ำว่าไม่มี edge สรุปสุดท้ายคือไม่มีโมเดล math-derived ตัวไหนในโปรเจกต์นี้ผ่านการทดสอบความทนทานครบทุกมุมได้อย่างสมบูรณ์เลยสักตัว แม้แต่ผลที่ดูดีที่สุดก็ยังไม่มั่นคงพอข้าม train/test window

## แนวทางที่ตัดทิ้งไปแล้ว

Wyckoff Spring pattern filter ถูกตัดตั้งแต่ขั้นเสนอ เพราะเป็น technical-analysis pattern ไม่ใช่โมเดลที่มาจากสมการ

Momentum/Donchian Channel Breakout ทดสอบแล้วได้ผลดีที่สุดในโปรเจกต์ทั้งหมด (XAUUSD M5 fixed-config: PF 1.26, Bootstrap CI ผ่าน 95% จริงที่ `[0.06, 4.71]`) แต่ถูกตัดทิ้งเพราะกติกาทะลุจุดสูงสุด/ต่ำสุดของ N แท่งเป็นกติกาเชิงประจักษ์ ไม่ได้มาจากการแก้สมการทางคณิตศาสตร์ แม้จะมีงานวิจัยวิชาการรองรับปรากฏการณ์ momentum ทางสถิติก็ตาม ยึดมาตรฐานเดียวกับ Wyckoff โค้ดเก็บไว้ที่ `trend_following.py` และ `trend_rolling_wfo.py` เป็นหลักฐาน ไม่พัฒนาต่อ

NDX100 ด้วยทุกวิธี mean-reversion ที่ลอง (symmetric+HMM, trend-aware, long-only+drift-aware) ไม่ผ่านเกณฑ์เลยสักตัว สรุปว่า NDX100 น่าจะเป็น trend-dominant asset ที่ไม่เหมาะกับ mean-reversion

Pairs Trading และ Cointegration ไม่ใช่ scope ของโปรเจกต์นี้ อยู่คนละโปรเจกต์

Risk Management Layer (`analysis/backtester/risk_management.py`) ยังเก็บไว้ใช้ — Inverse Volatility Position Sizing บวก Fixed-Fractional Risk Cap ปรับขนาด position ตาม volatility ปัจจุบันเพื่อคุม dollar risk ต่อไม้ให้คงที่ ช่วยเรื่องความเรียบของ equity curve เท่านั้น ไม่ได้เปลี่ยน expectancy ของสัญญาณ ใช้ได้เมื่อมี edge ที่พิสูจน์แล้วเท่านั้น ไม่ใช่ทางลัดให้กลยุทธ์ไม่มี edge กลายเป็นมี edge

## โครงสร้างโปรเจกต์

```
mt5-tracker/
├── analysis/
│   ├── strategies/
│   │   ├── kalman_mean_reversion.py        # OU: KalmanOU, VolatilityRegimeHMM, run_mean_reversion()
│   │   ├── cir_mean_reversion.py           # CIR: KalmanCIR, run_cir_mean_reversion()
│   │   ├── garch_ou_mean_reversion.py      # GARCH-OU: KalmanGARCH, run_garch_mean_reversion()
│   │   ├── garch_ou_var_mean_reversion.py  # GARCH-OU + VaR-threshold variant, ไม่ผ่าน
│   │   ├── jump_ou_mean_reversion.py       # Jump-Diffusion OU: KalmanJumpOU
│   │   └── trend_following.py              # Donchian breakout, ตัดทิ้งแล้ว
│   └── backtester/
│       ├── deflated_sharpe.py              # DSR, Sharpe, trade_metrics
│       └── risk_management.py              # Inverse-vol sizing + fixed-fractional risk cap
├── dashboard/
│   ├── 1_Chart.py                          # Candlestick chart + model mean/bands overlay
│   └── pages/2_Results.py                  # ตารางสรุปผลทุก experiment
├── fetcher/                                # Yahoo/market fetcher, ไม่ใช้กับระบบนี้โดยตรง
├── scripts/
│   ├── sync/                               # MT5 -> MySQL sync
│   └── research/                           # walk-forward evaluator ต่อโมเดล ดูตารางด้านล่าง
└── storage/                                 # schema SQL, raw layer เท่านั้นสำหรับระบบนี้
```

### `scripts/research/` — ไฟล์ที่ใช้งานจริง

| ไฟล์ | ทำอะไร |
|---|---|
| `kalman_walkforward.py` | OU: train/val/test walk-forward, grid search, DSR ต่อ symbol/timeframe |
| `rolling_wfo.py` | OU: rolling WFO (train 90 วัน, test 30 วัน เลื่อนไปเรื่อยๆ), Bootstrap CI, equity curve/per-fold PF plot |
| `cir_rolling_wfo.py` | CIR: rolling WFO, Bootstrap CI, `monte_carlo_baseline()` |
| `garch_rolling_wfo.py` | GARCH-OU: rolling WFO, Bootstrap CI, Monte Carlo |
| `garch_var_rolling_wfo.py` | GARCH-OU + VaR-threshold: grid search entry/stop percentile แทน k×σ ทดสอบแล้วแย่กว่าเดิม |
| `jump_ou_rolling_wfo.py` | Jump-Diffusion OU: rolling WFO, Bootstrap CI, Monte Carlo |
| `risk_sizing_demo.py` | เปรียบเทียบ dynamic กับ flat position sizing บน config OU คงที่ |
| `val_test_correlation.py` | ตรวจว่า validation ทำนาย test ได้จริงไหม |
| `hmm_ablation.py` | เทียบ HMM เปิด/ปิดบน config ที่ชนะแล้ว |
| `ndx100_long_only_drift.py` | NDX100 buy-only แบบ drift-aware เลิกทำต่อแล้ว |
| `trend_following.py`, `trend_rolling_wfo.py` | Momentum/Donchian ตัดทิ้งแล้ว เก็บเป็นหลักฐาน |
| `RESULTS.md` | log ผลการทดลองสะสมทุกรอบ พร้อมตารางสรุปและคำอธิบายแบบละเอียด |

## เริ่มใช้งาน

```bash
# รันครั้งเดียวตอนเริ่มทำงาน
docker-compose up -d

# sync ข้อมูล MT5 ล่าสุด (XAUUSD/EURUSD; NDX100 ต้อง backfill เองถ้ายังไม่มี)
python scripts/sync/scheduler/mt5_sync_service.py --once

# รัน rolling WFO เต็มรูปแบบต่อโมเดล (20-40 นาทีต่อ symbol/timeframe)
python scripts/research/rolling_wfo.py --symbol XAUUSD --timeframe m5          # OU
python scripts/research/cir_rolling_wfo.py --symbol XAUUSD --timeframe m5     # CIR
python scripts/research/garch_rolling_wfo.py --symbol XAUUSD --timeframe m5   # GARCH-OU

# เปิด dashboard ดูกราฟราคาพร้อมเส้นมีนของโมเดล
streamlit run dashboard/1_Chart.py
```
