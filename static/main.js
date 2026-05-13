"use strict";

if (typeof getEl === 'undefined') {
    var getEl = (id) => document.getElementById(id);
}

var piCapturedFilename = null;
var lastDetectionData  = null;

// ══════════════════════════════════════════════════════
// WEIGHT — SSE Realtime Stream
// ══════════════════════════════════════════════════════

var _weightES      = null;
var _lastWeightG   = 0.0;

function startWeightStream() {
    if (_weightES) return;

    _weightES = new EventSource("/api/weight/stream");

    _weightES.onmessage = (e) => {
        try {
            const d = JSON.parse(e.data);
            if (d.error) { console.warn("Weight SSE error:", d.error); return; }

            _lastWeightG = d.weight ?? 0.0;

            document.querySelectorAll(".weight-display").forEach(el => {
                el.textContent = _lastWeightG.toFixed(1);
            });

            document.querySelectorAll(".weight-dot").forEach(dot => {
                if (d.mock) {
                    dot.style.background = "#888";
                    dot.style.boxShadow  = "none";
                } else if (!d.stable) {
                    dot.style.background = "#e67e22";
                    dot.style.boxShadow  = "0 0 8px #e67e22";
                } else {
                    dot.style.background = "#2ecc71";
                    dot.style.boxShadow  = "0 0 8px #2ecc71";
                }
            });

            document.querySelectorAll(".weight-mock-badge").forEach(b => {
                b.style.display = d.mock ? "inline" : "none";
            });

        } catch (err) { console.error("Weight parse error:", err); }
    };

    _weightES.onerror = () => {
        console.warn("Weight SSE disconnected — retry in 3s");
        _weightES.close();
        _weightES = null;
        setTimeout(startWeightStream, 3000);
    };
}

/** Tare — POST /api/weight/tare */
async function tareScale() {
    const btn = getEl("btn-tare");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ กำลัง Tare...";
        btn.style.background = "#e67e22";
        btn.style.opacity = "0.7";
    }
    showLoading(true, "⚖️ กำลัง Tare เครื่องชั่ง กรุณารอสักครู่...");
    try {
        const res  = await fetch("/api/weight/tare", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("✅ Tare สำเร็จ — น้ำหนักรีเซ็ตแล้ว", "success");
        } else {
            showToast("⚠️ " + (data.message || "Tare ไม่สำเร็จ"), "error");
        }
    } catch (err) {
        showToast("❌ ติดต่อเซิร์ฟเวอร์ไม่ได้", "error");
    } finally {
        showLoading(false);
        if (btn) {
            btn.disabled = false;
            btn.textContent = "⚖️ Tare";
            btn.style.opacity = "1";
        }
    }
}

// ══════════════════════════════════════════════════════
// 1. ถ่ายภาพ
// ══════════════════════════════════════════════════════
async function captureFromPi() {
    if (piCapturedFilename) {
        try {
            await fetch("/api/cleanup", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename: piCapturedFilename })
            });
        } catch (err) { console.warn("Cleanup error:", err); }
        piCapturedFilename = null;
    }
    showLoading(true, "กำลังบันทึกภาพจากกล้อง...");
    try {
        const res  = await fetch("/api/capture", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            const img = getEl("preview-img");
            if (img) { img.src = data.image_url; img.style.display = "block"; }
            piCapturedFilename = data.filename;
            showToast("📸 ถ่ายภาพสำเร็จ!", "success");
        }
    } catch (err) { console.error(err); }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// 2. ตรวจจับ (Detection)
// ══════════════════════════════════════════════════════
async function startDetection() {
    if (!piCapturedFilename) {
        showToast("⚠️ ต้องถ่ายภาพก่อนครับ", "error");
        return;
    }
    showLoading(true, "AI กำลังวิเคราะห์อาหาร...");
    try {
        const res  = await fetch("/api/detect-captured", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ filename: piCapturedFilename }),
        });
        const data = await res.json();
        if (data.success) {
            lastDetectionData = data;
            renderResult(data);
            showScreen("result-screen");
        }
    } catch (err) { console.error(err); }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// 3. ยืนยันและบันทึกลง DB
// ══════════════════════════════════════════════════════
async function goToEnd() {
    if (!piCapturedFilename || !lastDetectionData) {
        showToast("❌ ไม่พบข้อมูลการตรวจจับ", "error");
        return;
    }

    showLoading(true, "กำลังบันทึกลงฐานข้อมูล...");
    try {
        const res = await fetch("/api/confirm", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({
                filename:    piCapturedFilename,
                total_price: lastDetectionData.total_price,
                dishes:      lastDetectionData.dishes,
                detections:  lastDetectionData.detections || [],
                weight:      _lastWeightG,
            }),
        });
        const result = await res.json();
        if (result.success) {
            showScreen("end-screen");
            startCountdown(5);
        } else {
            showToast("❌ บันทึกล้มเหลว", "error");
        }
    } catch (err) {
        console.error(err);
        showToast("❌ ติดต่อเซิร์ฟเวอร์ไม่ได้", "error");
    }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// WEIGHT CLASSIFICATION
// ══════════════════════════════════════════════════════

const WEIGHT_THRESHOLDS = {
    "ข้าวหน้าเป็ด":      510,
    "ข้าวหมูกรอบ":       500,
    "ข้าวผัดกะเพรา":     500,
    "ข้าวมันไก่ทอด":     480,
    "ข้าวมันไก่ต้ม":     480,
    "ก๋วยเตี๋ยวไก่ฉีก":  720,
    "ก๋วยเตี๋ยวไก่น่อง": 720,
};
const DEFAULT_THRESHOLD = 500;

function getWeightThreshold(foodName) {
    if (!foodName) return DEFAULT_THRESHOLD;
    for (const [key, val] of Object.entries(WEIGHT_THRESHOLDS)) {
        if (foodName.includes(key)) return val;
    }
    return DEFAULT_THRESHOLD;
}

/**
 * คืน object { level, label, badgeStyle, priceExtra }
 *
 * เกณฑ์:
 *   ปริมาณน้อยกว่าปกติ  → dishWeight < threshold * 0.85
 *   ✅ ปริมาณปกติ           → threshold * 0.85 ≤ dishWeight < threshold
 *   ⭐ พิเศษ               → dishWeight ≥ threshold  (+5 บาท)
 */
function classifyWeight(foodName, dishWeight) {
    if (!dishWeight || dishWeight <= 0) {
        return { level: "unknown", label: "", badgeStyle: "display:none;", priceExtra: 0 };
    }
    const threshold = getWeightThreshold(foodName);
    const low       = threshold * 0.85;

    if (dishWeight >= threshold) {
        return {
            level: "special",
            label: "⭐ พิเศษ",
            badgeStyle: "font-size:0.78rem;font-weight:700;background:#f59e0b;color:#1c1917;border-radius:6px;padding:2px 8px;white-space:nowrap;",
            priceExtra: 5,
        };
    } else if (dishWeight >= low) {
        return {
            level: "normal",
            label: "✅ ปริมาณปกติ",
            badgeStyle: "font-size:0.78rem;font-weight:600;background:rgba(255,255,255,0.18);color:#e2e8f0;border-radius:6px;padding:2px 8px;white-space:nowrap;",
            priceExtra: 0,
        };
    } else {
        return {
            level: "low",
            label: "ปริมาณน้อย",
            badgeStyle: "font-size:0.78rem;font-weight:600;background:#475569;color:#cbd5e1;border-radius:6px;padding:2px 8px;white-space:nowrap;",
            priceExtra: 0,
        };
    }
}

/**
 * แบ่งน้ำหนักรวมให้แต่ละเมนูตาม confidence ratio
 * ถ้าเมนูเดียว → ได้น้ำหนักทั้งหมด
 * ถ้า 2 เมนู confidence 60:40 → แบ่ง 60%:40% ของน้ำหนักรวม
 */
function splitWeightByConfidence(dishes, totalWeight) {
    if (!dishes || dishes.length === 0) return [];
    if (dishes.length === 1) {
        return [{ ...dishes[0], dishWeight: totalWeight }];
    }
    const totalConf = dishes.reduce((sum, d) => sum + (d.confidence || 0), 0);
    return dishes.map(d => {
        const ratio = totalConf > 0 ? (d.confidence || 0) / totalConf : 1 / dishes.length;
        return { ...d, dishWeight: Math.round(totalWeight * ratio * 10) / 10 };
    });
}

// ══════════════════════════════════════════════════════
// 4. แสดงผลลัพธ์
// ══════════════════════════════════════════════════════
function renderResult(data) {
    const ri = getEl("result-img");
    if (ri) ri.src = data.annotated_image;

    const totalWeight = _lastWeightG;
    const rawDishes   = data.dishes || [];

    // แบ่งน้ำหนักตาม confidence ratio
    const dishes = splitWeightByConfidence(rawDishes, totalWeight);

    let newTotalPrice = 0;

    const list = getEl("menu-list");
    if (list) {
        list.innerHTML = dishes.map((dish, idx) => {
            const ingredients    = dish.ingredients || [];
            const hasIngredients = ingredients.length > 0;
            const conf           = dish.confidence ? Math.round(dish.confidence * 100) : 0;
            const foodName       = dish.name_th || dish.name;
            const dishWeight     = dish.dishWeight || 0;

            // วิเคราะห์ปริมาณ
            const wc         = classifyWeight(foodName, dishWeight);
            const finalPrice = Math.round(dish.price) + wc.priceExtra;
            newTotalPrice   += finalPrice;

            // แสดงสัดส่วนน้ำหนักถ้ามีหลายเมนู
            const totalConf  = dishes.reduce((s, d) => s + (d.confidence || 0), 0);
            const ratio      = totalConf > 0 ? Math.round((dish.confidence || 0) / totalConf * 100) : 100;
            const weightLabel = dishes.length > 1
                ? `<span style="font-size:0.72rem;opacity:0.65;">สัดส่วน ${ratio}% → ${dishWeight.toFixed(1)} ก.</span>`
                : `<span style="font-size:0.72rem;opacity:0.65;">${dishWeight.toFixed(1)} ก.</span>`;

            const ingHtml = hasIngredients ? `
                <div id="ing-${idx}" style="display:none;background:rgba(0,0,0,0.3);border-top:1px solid rgba(255,255,255,0.15);padding:10px 14px;">
                    ${ingredients.map(ing => `
                        <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;font-size:0.82rem;color:rgba(255,255,255,0.85);">
                            <span>• ${ing.name_th || ing.name}</span>
                            <span style="font-size:0.75rem;opacity:0.7;">${ing.confidence ? Math.round(ing.confidence*100)+'%' : ''}</span>
                        </div>
                    `).join("")}
                </div>
            ` : '';

            return `
            <div class="menu-card" style="background:#6d28d9;border-radius:10px;margin-bottom:10px;color:white;overflow:hidden;">
                <div style="padding:14px 16px;display:flex;justify-content:space-between;align-items:center;cursor:${hasIngredients?'pointer':'default'};"
                     onclick="${hasIngredients?`toggleIng(${idx})`:''}">
                    <div style="display:flex;flex-direction:column;gap:4px;">
                        <span style="font-weight:700;font-size:1rem;">${foodName}</span>
                        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                            ${conf ? `<span style="font-size:0.72rem;opacity:0.75;">ความแม่นยำ ${conf}%</span>` : ''}
                            ${weightLabel}
                        </div>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
                        <span style="${wc.badgeStyle}">${wc.label}</span>
                        <span style="font-weight:bold;font-size:1rem;">฿${finalPrice}</span>
                        ${wc.priceExtra > 0 ? `<span style="font-size:0.7rem;color:#fde68a;">(+${wc.priceExtra})</span>` : ''}
                        ${hasIngredients ? `<span id="arrow-${idx}" style="font-size:0.8rem;transition:transform 0.2s;">▼</span>` : ''}
                    </div>
                </div>
                ${ingHtml}
            </div>`;
        }).join("");
    }

    const total = getEl("total-price-display");
    if (total) total.textContent = newTotalPrice || Math.round(data.total_price || 0);
}

function toggleIng(idx) {
    const el    = document.getElementById(`ing-${idx}`);
    const arrow = document.getElementById(`arrow-${idx}`);
    if (!el) return;
    const isOpen = el.style.display !== 'none';
    el.style.display = isOpen ? 'none' : 'block';
    if (arrow) arrow.style.transform = isOpen ? '' : 'rotate(180deg)';
}

// ══════════════════════════════════════════════════════
// 5. ตรวจซ้ำ (Rescan)
// ══════════════════════════════════════════════════════
async function rescan() {
    if (!piCapturedFilename) {
        showToast("⚠️ ไม่พบรูปภาพ กรุณาถ่ายใหม่", "error");
        return;
    }
    showLoading(true, "AI กำลังวิเคราะห์อาหารใหม่...");
    try {
        const res  = await fetch("/api/detect-captured", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ filename: piCapturedFilename }),
        });
        const data = await res.json();
        if (data.success) {
            lastDetectionData = data;
            renderResult(data);
            showToast("ตรวจจับใหม่เรียบร้อย", "success");
        } else {
            showToast("❌ ตรวจจับไม่สำเร็จ", "error");
        }
    } catch (err) {
        console.error(err);
        showToast("❌ ติดต่อเซิร์ฟเวอร์ไม่ได้", "error");
    }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// Utility
// ══════════════════════════════════════════════════════
function startCountdown(seconds) {
    let n = seconds;
    const el    = getEl("countdown-num");
    const timer = setInterval(() => {
        n--;
        if (el) el.textContent = n;
        if (n <= 0) { clearInterval(timer); goHome(); }
    }, 1000);
}

function showScreen(id) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    getEl(id)?.classList.add("active");
}

async function goHome() {
    if (piCapturedFilename) {
        try {
            await fetch("/api/cleanup", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename: piCapturedFilename })
            });
        } catch (err) { console.warn("Cleanup error:", err); }
    }
    piCapturedFilename = null;
    lastDetectionData  = null;
    const img = getEl("preview-img");
    if (img) img.src = "/video_feed";
    showScreen("home-screen");
}

function showLoading(show, text = "") {
    const el = getEl("loading-overlay");
    if (el) {
        if (text) getEl("loader-text").textContent = text;
        el.classList.toggle("show", show);
    }
}

function showToast(msg, type = "") {
    const el = getEl("toast");
    if (el) {
        el.textContent = msg;
        el.className   = `show ${type}`;
        setTimeout(() => el.className = "", 3000);
    }
}

// ══════════════════════════════════════════════════════
// Shutdown
// ══════════════════════════════════════════════════════
async function confirmShutdown() {
    showToast("⏹ กำลังปิดระบบ...", "error");
    setTimeout(async () => {
        await fetch("/api/shutdown", { method: "POST" });
        document.body.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#16172b;color:#e2e8f0;font-family:IBM Plex Sans Thai,sans-serif;flex-direction:column;gap:16px;">
                <div style="font-size:2rem;">⏹</div>
                <div style="font-size:1.2rem;font-weight:700;">ปิดระบบเรียบร้อย</div>
                <div style="font-size:0.85rem;color:#94a3b8;">สามารถปิดหน้าต่างได้แล้ว</div>
            </div>`;
    }, 1000);
}

// ══════════════════════════════════════════════════════
// Init
// ══════════════════════════════════════════════════════
window.onload = () => {
    console.log("✅ ระบบพร้อมใช้งาน");
    startWeightStream();
    checkAutoTare();
};

async function checkAutoTare() {
    document.querySelectorAll(".weight-display").forEach(el => el.textContent = "...");
    showLoading(true, "⚖️ กำลัง Tare เครื่องชั่งอัตโนมัติ...");
    while (true) {
        try {
            const res  = await fetch("/api/tare_status");
            const data = await res.json();
            if (data.status === "done") {
                showLoading(false);
                showToast("✅ ระบบพร้อมใช้งาน", "success");
                break;
            } else if (data.status === "failed") {
                showLoading(false);
                showToast("⚠️ Tare ไม่สำเร็จ กรุณากด Tare ด้วยตนเอง", "error");
                break;
            }
        } catch (e) {
            showLoading(false);
            break;
        }
        await new Promise(r => setTimeout(r, 300));
    }
}
