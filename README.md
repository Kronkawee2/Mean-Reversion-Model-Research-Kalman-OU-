# Quant Trader — Mean Reversion Model Research (Kalman/OU family)

XAUUSD, EURUSD และ NDX100 จาก MT5 มาทดสอบสมมติฐานที่ว่าราคาที่เบี่ยงเบนจากค่าเฉลี่ยทางสถิติมีแนวโน้มดึงกลับ (mean reversion) เป็นสิ่งที่ใช้เทรดได้จริงหรือไม่ วิธีทดสอบคือสร้างโมเดลสุ่ม (stochastic process) ที่มาจากการแก้สมการทางคณิตศาสตร์จริง แล้วผ่านการตรวจสอบทางสถิติหลายชั้น ไม่เชื่อผล backtest ที่ดูดี แต่ทุก config ต้องผ่านการทดสอบนัยสำคัญทางสถิติครบทุกด่านก่อนถึงจะนับว่ามี edge จริง

## ผลการทดลอง

ทดสอบครบ 4 โมเดล (OU, CIR, GARCH-OU, Jump-Diffusion OU) กับ 3 สินทรัพย์ (XAUUSD, EURUSD, NDX100) ผ่านการตรวจสอบ 4 ชั้น ได้แก่ backtest, walk-forward optimization, การทดสอบนัยสำคัญทางสถิติ (Bootstrap CI + Monte Carlo permutation test) และ fixed-config walk-forward พร้อมเช็คความทนทาน train/test window

ผลสรุป: **ไม่มี combination ใดพิสูจน์ edge ที่ยืนยันได้ครบทุกด่านสถิติเลยสักตัว** ผลลัพธ์ที่ใกล้เคียงที่สุดคือ GARCH-OU บน XAUUSD M5 ซึ่งผ่าน fixed-config ที่ train/test window 90/30 วันได้ (Bootstrap 82.5%, Monte Carlo 87.6%) เมื่อเปลี่ยนเป็น window 60/20 วัน Bootstrap 55.4% ใกล้เคียงระดับเดาสุ่ม จึงไม่ถือว่าเป็นหลักฐานที่มั่นคงพอ โมเดลและ combination อื่นทั้งหมดพังชัดเจนกว่านี้ (พิสูจน์แล้วว่าเป็น overfitting)

## ข้อมูลที่ใช้มาจาก MT5 (Eightcap)

| สินทรัพย์ | Timeframe |
| :--- | :--- |
| XAUUSD | m5, m15 |
| EURUSD | m5, m15 |
| NDX100 | m5, m15 |

ทุก symbol มีข้อมูล Timeframe 5 นาที หรือ m5 ประมาณ 1.5 ปี เป็นข้อจำกัดของโบรกเกอร์ Eightcap ที่เก็บประวัติละเอียดระดับ M5 สั้นกว่า H1/D1 มาก นี่คือเหตุผลที่ rolling WFO บน timeframe M5 มี fold น้อยกว่า M15 มาก (14-23 fold เทียบกับ 46-48 fold)

## Edge

Edge (ความได้เปรียบทางสถิติ) คือคุณสมบัติของระบบเทรดที่สร้างผลตอบแทนคาดหวังเป็นบวก (Positive Expectancy) ในระยะยาว ซึ่งไม่ใช่แค่เรื่องของการทายถูกบ่อย (Win Rate สูง)

* เมื่อระบบ "ไม่มี Edge":ประสิทธิภาพไม่ต่างจากการโยนเหรียญ 50/50 ในระยะยาวมูลค่าพอร์ตจะเพียงแค่แกว่งขึ้นลงตามความผันผวนของดวง แม้จะมีบางช่วงที่พอร์ตโตจากการชนะติดๆ กัน แต่ก็เป็นเพียงความบังเอิญทางสถิติ (Luck/Variance)
* เมื่อระบบ "มี Edge จริง":ไม่จำเป็นต้องชนะทุกไม้ แต่ค่าเฉลี่ยของผลลัพธ์สุทธิหลังหักลบความเสี่ยงและต้นทุนแล้วมีค่าเป็นบวกอย่างมีนัยสำคัญ เมื่อเทรดต่อเนื่องเป็นจำนวนรอบมากพอ พอร์ตจะเติบโตขึ้นตามกฎจำนวนมาก (Law of Large Numbers)

## หลักการทำงานทั้งหมด: 4 ชั้น

ทุกโมเดลผ่านกระบวนการเดียวกันแบบ **4 ชั้นซ้อนกัน** โดยชั้นแรกสร้างสัญญาณเทรด ส่วน 3 ชั้นหลังทำหน้าที่ตรวจสอบความน่าเชื่อถือทางสถิติ (ไม่มีการใช้ Machine Learning เป็นเพียงสมการคณิตศาสตร์เชิงปริมาณและสถิติเชิงตรวจสอบเท่านั้น)

### ชั้น 1 — สูตรโมเดล (Math Models)
* ใช้สมการคณิตศาสตร์ (เช่น OU, CIR, GARCH-OU, Jump-Diffusion OU) คำนวณว่าราคาปัจจุบันเบี่ยงเบนออกจากค่าเฉลี่ยไปมากน้อยเพียงใด (วัดในหน่วย $\sigma$)
* หากราคาเบี่ยงเบนเกินค่าขีดจำกัด $k$ ที่กำหนด จะถือเป็นสภาวะผิดปกติและส่งสัญญาณเปิดสถานะเพื่อเทรดสวนทางกลับเข้าสู่ค่าเฉลี่ย (Mean Reversion)

### ชั้น 2 — การจำลองผลย้อนหลัง (Backtest)
* นำสูตรจากชั้นที่ 1 มารันกับข้อมูลราคาย้อนหลังจริงเพื่อจำลองการเปิดไม้เมื่อมีสัญญาณ พร้อมหักลบต้นทุนค่าธรรมเนียมและสเปรด (Spread)
* ปิดสถานะเมื่อราคาดีดกลับแตะค่าเฉลี่ยหรือชนจุดตัดขาดทุน (Stop Loss) เพื่อบันทึกผลกำไร-ขาดทุนรายไม้ (ทำหน้าที่เป็นเครื่องคำนวณผลลัพธ์ตามพารามิเตอร์)

### ชั้น 3 — การคัดกรองพารามิเตอร์แบบไม่หลอกตัวเอง (Walk-Forward Optimization)
ป้องกันปัญหา Overfitting (ฟลุกแม่นเฉพาะอดีต) จากการปรับจูนค่าตัวเลข เช่น `calib_window` หรือ $k$ โดยใช้หลักการจำลองเวลาเดินหน้าจริง
1. **ค้นหาค่าที่ดีที่สุด (Train):** ใช้ข้อมูลย้อนหลัง 90 วัน ทดสอบทุกชุดพารามิเตอร์ใน Grid เพื่อเลือกชุดที่ทำผลงานได้ดีที่สุด
2. **วัดผลจริงในอนาคต (Test):** นำชุดพารามิเตอร์ที่ชนะ ไปเทรดกับข้อมูล 30 วันถัดไป (ข้อมูล Out-of-Sample ที่ไม่เคยใช้ปรับจูน)
3. **เลื่อนหน้าต่างเวลา (Roll):** ขยับช่วงเวลา Train และ Test ไปข้างหน้า แล้วทำซ้ำขั้นตอน 1–2 ต่อเนื่อง (14–48 รอบ)
4. **ประกอบผลลัพธ์จริง:** รวมผลการเทรดเฉพาะช่วง Test (30 วันของทุกรอบ) มาร้อยเรียงเป็น Track Record สุทธิชุดเดียว

### ชั้น 4 — การทดสอบนัยสำคัญทางสถิติ (Statistical Significance)
พิสูจน์ว่าผลกำไรจากชั้นที่ 3 เกิดจาก Edge จริง ไม่ใช่ความบังเอิญ โดยต้องผ่านบททดสอบทั้ง 3 ด่าน
1. **Bootstrap CI (วัดความสม่ำเสมอ):** สุ่มหยิบไม้เทรดซ้ำ 5,000 รอบเพื่อตรวจว่าผลตอบแทนเฉลี่ยเป็นบวกอย่างมีนัยสำคัญหรือไม่ (ไม่สนลำดับเวลา)
2. **Monte Carlo Permutation Test (เทียบกับการสุ่มเดา):** เปรียบเทียบผลลัพธ์จริงกับระบบสุ่มเข้าไม้แบบไร้กลยุทธ์ (คุมจำนวนไม้และระยะเวลาถือครองให้เท่ากัน) เพื่อดูว่าระบบจริงเอาชนะการสุ่มเดาได้อย่างขาดลอยกี่เปอร์เซ็นต์
3. **Fixed-Config Walk-Forward (ล็อกค่าคงที่ตลอดทาง):** ล็อกค่าพารามิเตอร์ชุดเดียวตลอดทุก Fold โดยไม่ Re-optimize ซ้ำ เพื่อทดสอบความทนทานต่อสภาวะตลาดจริง

> **ข้อควรระวังในชั้น 4**
> * **Bootstrap และ Monte Carlo** วัดเพียง "ความน่าจะเป็นทางสถิติ" เท่านั้น ไม่ได้จำลองลำดับเวลาจริง จึงไม่สามารถสะท้อน Drawdown หรือ Equity Curve ได้ (ต้องประเมินแยกจากกราฟและค่า PF ราย Fold)
> * กลยุทธ์ต้อง **ผ่านทั้ง 3 บททดสอบในชั้นที่ 4 พร้อมกัน** จึงจะสรุปได้ว่ามี Edge ทางสถิติรองรับอย่างแท้จริง

## วัดผลด้วยอะไร

โปรเจกต์นี้เลือกใช้มาตรวัดนัยสำคัญทางสถิติ 3 รูปแบบหลักตามโครงสร้างการทดสอบที่ต่างกัน:

| มาตรวัด | บริบทการใช้งาน | คำถามที่ต้องการคำตอบ | เกณฑ์ผ่าน (Pass Criteria) |
|---|---|---|---|
| Deflated Sharpe Ratio (DSR) | Fixed Train/Val/Test Split (เลือก config เดียวจาก Grid ครั้งเดียว) | ผลลัพธ์ที่ดีที่สุด ดีเกินกว่าความบังเอิญจากการทดลองหลายชุด ($N$ trials) หรือไม่? | **DSR > 95%** |
| Bootstrap CI | Rolling WFO (แต่ละ Fold ปรับเลือก config แยกอิสระ) | กำไรเฉลี่ยต่อไม้ (Expectancy) มีค่ามากกว่าศูนย์อย่างมีนัยสำคัญจริงหรือไม่? | ขอบล่างของ CI ($95\%$) $\gt 0$ |
| Monte Carlo Permutation Test | ใช้กับทุกโมเดลตั้งแต่ CIR เป็นต้นไป | กลยุทธ์จริงสร้างผลตอบแทนได้เหนือกว่า "การสุ่มเข้าไม้" มากน้อยเพียงใด? | ชนะผลการสุ่ม $\ge 95\%$ ของจำนวนรอบทดสอบ |

### รายละเอียดและบทบาทของแต่ละเครื่องมือ

**Deflated Sharpe Ratio (DSR)**

หลักการ: อิงงานวิจัยของ Bailey & López de Prado เพื่อหักลบ "บทลงโทษ" จากการทำ Multiple Testing (ยิ่งรัน Grid Search หลายค่า ยิ่งเพิ่มโอกาสฟลุกเหมือนซื้อลอตเตอรี่หลายใบ)

ข้อจำกัด: ตรวจจับได้เฉพาะความบังเอิญจากการลองหลาย Config แต่ไม่ได้การันตีความทนทานในอนาคต (เช่น กรณี XAUUSD M5 ที่ได้ DSR สูงถึง 98.87% แต่สอบตกเมื่อทดสอบด้วยเกณฑ์อื่น)

**Bootstrap CI**

หลักการ: นำมาใช้แทน DSR ในระบบ Rolling WFO (ซึ่งมีการเปลี่ยน Config ทุก Fold จึงไม่ตรงกับสมมติฐานของ DSR)

วิธีทดสอบ: ทำ Resample ข้อมูลไม้เทรด Out-of-Sample ที่ร้อยเรียงข้าม Fold ซ้ำ 5,000 รอบ เพื่อยืนยันว่าผลตอบแทนเฉลี่ย 95% ของการสุ่มยังคงอยู่เหนือศูนย์

**Monte Carlo Permutation Test**

หลักการ: อ้างอิงแนวทางมาตรฐานจากหนังสือของ Timothy Masters เพื่อตัดข้อสงสัยเรื่องโชคชะตา

วิธีทดสอบ: สร้างบอทสุ่มทิศทางและจุดเข้าเทรด 1,000 รอบ (โดยล็อกจำนวนไม้และระยะเวลาถือครองให้เทียบเท่าของจริง) แล้วดูว่าผลงานจริงติดอยู่ใน Percentile ระดับหัวแถวหรือไม่

**การทดสอบเสริม: Fixed-Config Walk-Forward**

ด่าน Stress-test ขั้นสุดท้าย โดยการคัดเลือก Config ที่ถูกระบบเลือกใช้บ่อยที่สุดเพียงชุดเดียว แล้วล็อกค่านั้นรันยาวตลอดทุก Fold โดย**ไม่ทำ Re-optimization ซ้ำ**

วัตถุประสงค์: พิสูจน์ว่าผลกำไรจาก Rolling WFO เกิดจาก Edge ของตัวแปรจริง หรือเกิดจากการเปลี่ยน Config ไปเรื่อยๆ เพื่อ Overfit ตามสภาวะตลาด

ผลลัพธ์ที่พบ:
- โมเดล CIR เกิด Overfitting ในทุก Combination ที่ทดสอบ
- โมเดล GARCH-OU (XAUUSD M5) ทนทานกว่าบน Window เดิม แต่ประสิทธิภาพลดลงอย่างเห็นได้ชัดเมื่อเปลี่ยนขนาด Window (ดูรายละเอียดในตารางถัดไป)

## โมเดลที่ทดสอบ (Models Under Test)

ทั้ง 4 โมเดลตั้งอยู่บนสมมติฐานเดียวกันคือ **มีแรงดึงกลับเข้าสู่จุดสมดุลระยะยาว (Mean Reversion Drift)** แต่มีความแตกต่างกันอย่างสิ้นเชิงในพฤติกรรมของ Noise และ Variance รอบแกนดึงกลับ

| โมเดล | พฤติกรรมของ Variance ($\sigma_t^2$) | ที่มาและงานวิจัยอ้างอิง |
|---|---|---|
| **Ornstein-Uhlenbeck (OU)** | คงที่ตลอดเวลา (Constant) | โมเดล Mean-Reversion มาตรฐานใน Quantitative Finance (Uhlenbeck & Ornstein, 1930) |
| **Cox-Ingersoll-Ross (CIR)** | ผันแปรตามระดับราคา ($\propto X_t$) | โมเดลอัตราดอกเบี้ยระยะสั้น ออกแบบมาเพื่อป้องกันค่าติดลบ (Cox, Ingersoll & Ross, 1985) |
| **GARCH(1,1)-filtered OU** | ผันแปรตาม Shock และ Variance บาร์ก่อนหน้า (Volatility Clustering) | ต่อยอดจาก ARCH ของ Engle (1982) โดย Bollerslev (1986) |
| **Jump-Diffusion OU** | Diffusion คงที่ผสม Jump Term สำหรับ Shock ฉับพลัน | ขยายจาก Merton (1976) ใช้กับสินค้าโภคภัณฑ์/พลังงาน (Cartea & Figueroa, 2005) |

---

### 1. Ornstein-Uhlenbeck (OU)

สมการ Stochastic Differential Equation (SDE)

$$dX_t = \theta(\mu - X_t)\,dt + \sigma\,dW_t$$

* **คำจำกัดความตัวแปร:** $X_t$ คือราคาปัจจุบัน, $\mu$ คือจุดสมดุลระยะยาว, $\theta$ คือความเร็วของแรงดึงกลับ (Speed of Mean Reversion), $\sigma$ คือ Volatility คงที่, $dW_t$ คือ Standard Brownian Motion
* **การประมาณค่า (Estimation):** Fit ข้อมูลย้อนหลังแบบไม่ต่อเนื่องด้วย Discrete AR(1) (`estimate_ar1()`):
  $$X_t = c + \phi X_{t-1} + \varepsilon_t \implies \theta = -\ln(\phi)$$
* **ตัวชี้วัดสำคัญ:**
  * **Stationary Standard Deviation:** $\sigma_{stat} = \sigma / \sqrt{2\theta}$ (ใช้กำหนดเกณฑ์เบี่ยงเบนผิดปกติ)
  * **Half-life:** $\ln(2) / \theta$ (จำนวนแท่งที่คาดว่าราคาจะวิ่งกลับครึ่งทาง)
* **Kalman Filter State (`KalmanOU`):** เนื่องจาก $\mu$ มี Noise จึงใช้ Kalman Filter ประมาณค่า State ของจุดสมดุลแบบ Real-time
* **Predict:** x̂ₜ|ₜ₋₁ = φ·x̂ₜ₋₁ + (1-φ)μₜ

  $$P_{t\vert t-1} = \phi^2 P_{t-1} + Q$$

* **Update:** x̂ₜ = x̂ₜ|ₜ₋₁ + Kₜ(zₜ - x̂ₜ|ₜ₋₁)

  $$K_t = \dfrac{P_{t\vert t-1}}{P_{t\vert t-1} + R}$$

  $$P_t = (1-K_t)P_{t\vert t-1}$$
* โดย $Q = \sigma^2(1-\phi^2) \times$ `q_mult` และ $R = \sigma^2 \times$ `obs_noise_scale`

---

### 2. Cox-Ingersoll-Ross (CIR)

$$dX_t = \theta(\mu - X_t)\,dt + \sigma\sqrt{X_t}\,dW_t$$

* **คุณสมบัติ:** Variance จะขยายตัวเมื่อราคาสูงขึ้น และหดตัวเมื่อราคาต่ำลง
* **การประมาณค่า:** ประมาณ $\sigma^2$ ด้วย Conditional Least Squares (CLS, Chan et al., 1992):
  $$\sigma^2 = \text{mean}\left(\frac{\varepsilon_t^2}{X_{t-1}}\right)$$
* **Dynamic Band:** คำนวณ Kalman Gain และค่าเบี่ยงเบนมาตรฐานใหม่ทุกบาร์: $\sigma_{stat,t} = \sqrt{\frac{\sigma^2 X_t}{2\theta}}$ ทำให้ขนาดของ Band ปรับตามระดับราคา

---

### 3. GARCH(1,1)-filtered OU

$$\sigma_t^2 = \omega + \alpha\,\varepsilon_{t-1}^2 + \beta\,\sigma_{t-1}^2$$

* **คุณสมบัติ:** จับปรากฏการณ์ **Volatility Clustering** (ช่วงผันผวนสูงมักตามด้วยความผันผวนสูง)
* **การทำงาน:** พารามิเตอร์ $(\omega, \alpha, \beta)$ ถูก Fit ด้วย Maximum Likelihood Estimation (MLE) บน AR(1) Residuals จาก Calibration Window โดย $\sigma_t^2$ จะอัปเดตทุกแท่งจาก Innovation ของ Kalman Filter ($\varepsilon_t = z_t - \hat{x}_{t\vert t-1}$) ทำให้ Band กว้าง-แคบตามความแรงของ Shock ล่าสุด

---

### 4. Jump-Diffusion OU

$$dX_t = \theta(\mu - X_t)\,dt + \sigma\,dW_t + J\,dN_t$$

* **คุณสมบัติ:** แยก Structural Break ออกจาก Noise ปกติ โดย $N_t$ คือ Poisson Jump Process ความถี่ $\lambda$ และ $J$ คือขนาดของ Jump
* **กลไกการกรอง:** กรอง Residual ด้วย Threshold `jump_z` × std (ค่าเริ่มต้น $3.5\sigma$) โดยคำนวณ $\sigma$ เฉพาะฝั่ง Diffusion เพื่อไม่ให้ค่าความผันผวนปกติถูกบิดเบือน
* **กติกาเพิ่มเติม:** บล็อกการเปิดไม้ทันทีหากการเบี่ยงเบนเกิดจาก Jump (ถือเป็น Breakout ไม่ใช่ Mean Reversion) และปิดไม้ทันทีหากเกิด Jump ใหม่ขณะถือครอง (`jump_stop`)
* **ผลการทดสอบ (XAUUSD M5):** ให้ผลแย่ที่สุดในบรรดาทุกโมเดล (PF = 0.76, Bootstrap = 6.2%, Monte Carlo = 9.9%) เนื่องจาก `jump_stop` ตัดไม้ที่กำลังได้เปรียบทิ้งเร็วเกินไปจาก False Alarm

---

### โมดูลเสริม: VolatilityRegimeHMM (Bayesian Filter)

Hidden Markov Model 3-State (LOW / MED / HIGH Volatility) ใช้กรอง Regime ตลาดแบบ Forward Filtering ทุกแท่ง

$$\text{belief}_t(s) \;\propto\; \left[\sum_{s'} A(s',s)\,\text{belief}_{t-1}(s')\right] \times \mathcal{N}\big(v_t;\ \text{mean}_s,\ \text{std}_s\big)$$

ระบบจะระงับการเปิดสถานะใหม่เมื่อระบบตรวจพบสภาวะตลาดแบบ HIGH Volatility (`hmm_block_states`) ซึ่งจากการทดสอบแบบ Ablation ช่วยเพิ่มประสิทธิภาพใน 5 จาก 6 กรณี

---

### การเข้า/ออกสถานะ (Execution Rules)

**สัญญาณเข้า Short:**

$$X_t \gt \hat{x}_t + k\sigma_{stat}$$

**สัญญาณเข้า Long:**

$$X_t \lt \hat{x}_t - k\sigma_{stat}$$

**สัญญาณออก (Exit):** ปิดทำกำไรเมื่อราคากลับมาแตะจุดสมดุล $\hat{x}_t$ หรือปิดตาม Risk Control

| พารามิเตอร์ | คำอธิบาย |
|---|---|
| `calib_window` | ขนาด Rolling Window (แท่ง) ที่ใช้ Re-calibrate ค่าพารามิเตอร์ |
| `k` | ขีดจำกัดระยะห่างขั้นต่ำ (หน่วย $\sigma_{stat}$) ในการส่งสัญญาณเข้าเทรด |
| `z_stop` | Dynamic Stop Loss: ตัดขาดทุนเมื่อระยะห่างระหว่างราคากับจุดสมดุล (x̂ₜ) เกิน `z_stop` เท่าของค่าเบี่ยงเบนมาตรฐาน (σ_stat) |
| `half_life_mult` | Time Stop: ปิดสถานะหากถือเกิน Multiplier × Half-life แล้วราคายังไม่ Revert |
| `tau_threshold` | Entry Filter: อนุญาตให้เข้าเทรดเฉพาะช่วงที่ Half-life สั้นกว่าค่าที่กำหนด |
| `friction_hurdle_mult` | Slippage/Spread Guard: เข้าเทรดเฉพาะเมื่อระยะเบี่ยงเบน ≥ Multiplier × Spread |
| `side` | กำหนดทิศทาง: `"both"`, `"long_only"`, หรือ `"short_only"` |

---

## สรุปผลการทดสอบทุกโมเดล

### 1. การทดสอบแบบ Fixed-Split (DSR Baseline)

| สินทรัพย์ (Symbol) | Timeframe | Profit Factor (PF) | Win Rate (%) | DSR (%) | สรุปผล (เกณฑ์ $\ge 95\%$) |
|---|---|---|---|---|---|
| **XAUUSD** | M5 | 5.96 | 54.5% | 98.87% | **False Positive** (ตกม้าตายในขั้นตอนถัดไป) |
| **XAUUSD** | M15 / H1 | 1.26 / 0.61 | 50.0% / 52.9% | 26.4% / 2.3% | ไม่ผ่าน |
| **EURUSD** | M5 / M15 / H1 | 2.83 / 9.86 / 1.09 | 64.0% / 60.0% / 46.3% | 11.9% / 57.4% / 0.1% | ไม่ผ่าน |
| **NDX100** | M5 / M15 / H1 | 1.05 / 1.72 / 0.46 | 60.0% / 53.6% / 39.3% | 11.0% / 38.8% / 0.4% | ไม่ผ่าน |

> 8 จาก 9 การทดลองไม่ผ่านเกณฑ์ DSR ทันที ส่วน XAUUSD M5 ที่ดูเหมือนผ่าน ถูกพิสูจน์ในเวลาต่อมาว่าเป็นเพียง Overfitting จาก Validation/Test Correlation ที่ติดลบ (Spearman $\rho = -0.13$ ถึง $-0.50$)

---

### 2. การทดสอบแบบ Rolling Walk-Forward Optimization (WFO)

| โมเดล | สินทรัพย์ / TF | PF รวม | Bootstrap $P(\mu \gt 0)$ | Monte Carlo Percentile | Fixed-Config Walk-Forward |
|---|---|---|---|---|---|
| **OU** | XAUUSD M5 | 1.43 | 95.1% | 97.0% | **ไม่ผ่าน** (PF → 0.92, ลบอย่างมีนัยสำคัญ) |
| **OU** | XAUUSD M15 | 0.83 | 9.2% | 6.2% | — |
| **OU** | EURUSD M5 | 0.83 | 21.9% | 85.4% | — |
| **OU** | EURUSD M15 | 0.90 | 15.2% | 84.8% | — |
| **OU** | NDX100 M15 | 1.00 | 49.2% | 70.0% | — |
| **CIR** | XAUUSD M5 | 1.23 | 80.8% | 85.7% | — |
| **CIR** | XAUUSD M15 | 0.81 | 9.1% | 3.0% (แย่กว่าสุ่ม) | — |
| **CIR** | EURUSD M5 | 1.23 | 79.1% | 99.6% | **ไม่ผ่าน** (PF → 0.79, Boot → 10.2%, MC → 80.0%) |
| **CIR** | EURUSD M15 | 0.99 | 47.7% | 98.3% | **ไม่ผ่าน** (PF → 0.85, ลบอย่างมีนัยสำคัญ) |
| **CIR** | NDX100 M15 | 1.08 | 80.4% | 93.5% | **ไม่ผ่าน** (PF → 0.97, Boot → 35.1%, MC → 58.5%) |
| **CIR** | NDX100 M5 | 1.01 | 52.8% (เทียบเท่าเดาสุ่ม) | 61.8% | — |
| **GARCH-OU** | XAUUSD M5 | 1.36 | 87.9% | 90.2% | **ไม่ทนทาน** (90/30 ทนได้ที่ PF = 1.28 แต่ 60/20 ยวบเหลือ Boot = 55.4%) |
| **GARCH-OU** | XAUUSD M15 | 1.00 | 50.3% (เทียบเท่าเดาสุ่ม) | 51.7% | — |
| **GARCH-OU** | EURUSD M5 | 0.63 | 1.3% (ลบอย่างมีนัยสำคัญ) | 46.6% | — |
| **GARCH-OU** | EURUSD M15 | 0.70 | 1.5% (ลบอย่างมีนัยสำคัญ) | 14.5% (แพ้สุ่ม) | — |
| **GARCH-OU** | NDX100 M15 | 0.98 | 43.1% (เทียบเท่าเดาสุ่ม) | 57.4% | — |
| **GARCH-OU** | NDX100 M5 | 0.85 | 21.4% | 34.9% (แย่กว่าสุ่ม) | — |
| **Jump-Diffusion**| XAUUSD M5 | 0.76 | 6.2% | 9.9% (แย่กว่าสุ่มมาก) | — |

---

### วิเคราะห์ผลการทดสอบ (Key Takeaways)

1. **ภาพลวงตาจากการ Re-optimize:** ตัวเลข Monte Carlo ที่ดูสูง (93–99%) ในระบบ Rolling WFO ยวบลงเหลือเพียง 58–80% ทันทีเมื่อเข้าสู่บททดสอบ **Fixed-Config** (ล็อกค่าคงที่) ซึ่งชี้ชัดว่าเป็นเพียงการ Overfit ข้อมูลราย Fold
2. **ความไม่เสถียรข้าม Window:** เมื่อเปลี่ยน Parameter Window จาก 90/30 วัน เป็น 60/20 วัน โมเดลที่ดูดีที่สุดอย่าง **GARCH-OU (XAUUSD M5)** มีค่า Bootstrap ตกลงจาก $82.5\%$ เหลือเพียง $55.4\%$ (เทียบเท่าการเดาสุ่ม)
3. **ข้อสรุปเชิงประจักษ์:** ไม่มีโมเดลเชิงคณิตศาสตร์บริสุทธิ์ (Math-Derived Models) ตัวใดในโปรเจกต์นี้ที่สามารถผ่านการทดสอบความทนทานทางสถิติได้อย่างสมบูรณ์

---

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
