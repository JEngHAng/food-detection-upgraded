"use strict";

if (typeof getEl === 'undefined') {
    var getEl = (id) => document.getElementById(id);
}

var piCapturedFilename = null;
var lastDetectionData  = null;

// ══════════════════════════════════════════════════════
// WEIGHT — SSE Realtime Stream
// ══════════════════════════════════════════════════════

var _weightES      = null;   // EventSource instance
var _lastWeightG   = 0.0;    // ค่าน้ำหนักล่าสุด

function startWeightStream() {
    if (_weightES) return;   // ป้องกัน subscribe ซ้ำ

    _weightES = new EventSource("/api/weight/stream");

    _weightES.onmessage = (e) => {
        try {
            const d = JSON.parse(e.data);
            if (d.error) { console.warn("Weight SSE error:", d.error); return; }

            _lastWeightG = d.weight ?? 0.0;

            // อัปเดตทุก element ที่แสดงน้ำหนัก
            document.querySelectorAll(".weight-display").forEach(el => {
                el.textContent = _lastWeightG.toFixed(1);
            });

            // เปลี่ยนสี dot ตามความเสถียร
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

            // แสดง badge mock mode
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

    // แสดง loading overlay
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
            btn.textContent = "⚖️ Tare (归零)";
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
                weight:      _lastWeightG,           // ← ค่าจาก SSE stream
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
// 4. แสดงผลลัพธ์
// ══════════════════════════════════════════════════════
function renderResult(data) {
    const ri = getEl("result-img");
    if (ri) ri.src = data.annotated_image;

    const list = getEl("menu-list");
    if (list) {
        const dishes = data.dishes || [];
        list.innerHTML = dishes.map((dish, idx) => {
            const ingredients = dish.ingredients || [];
            const hasIngredients = ingredients.length > 0;
            const conf = dish.confidence ? Math.round(dish.confidence * 100) : 0;

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
                    <div style="display:flex;flex-direction:column;gap:2px;">
                        <span style="font-weight:700;font-size:1rem;">${dish.name_th || dish.name}</span>
                        ${conf ? `<span style="font-size:0.72rem;opacity:0.75;">ความแม่นยำ ${conf}%</span>` : ''}
                    </div>
                    <div style="display:flex;align-items:center;gap:10px;">
                        <span style="font-weight:bold;font-size:1rem;">฿${Math.round(dish.price)}</span>
                        ${hasIngredients ? `<span id="arrow-${idx}" style="font-size:0.8rem;transition:transform 0.2s;">▼</span>` : ''}
                    </div>
                </div>
                ${ingHtml}
            </div>`;
        }).join("");
    }

    const total = getEl("total-price-display");
    if (total) total.textContent = Math.round(data.total_price || 0);
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
// 5. ตรวจซ้ำ (Rescan) — ใช้รูปเดิม detect ใหม่
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
            showToast("🔄 ตรวจจับใหม่เรียบร้อย", "success");
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
// Init
// ══════════════════════════════════════════════════════
window.onload = () => {
    console.log("✅ ระบบพร้อมใช้งาน");
    startWeightStream();
    checkAutoTare();
};

async function checkAutoTare() {
    // ซ่อนน้ำหนักระหว่าง tare
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
