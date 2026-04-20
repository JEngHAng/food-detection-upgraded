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
    if (btn) { btn.disabled = true; btn.textContent = "⏳ กำลัง Tare..."; }

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
    }

    if (btn) { btn.disabled = false; btn.textContent = "⚖️ Tare (归零)"; }
}

// ══════════════════════════════════════════════════════
// 1. ถ่ายภาพ
// ══════════════════════════════════════════════════════
async function captureFromPi() {
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
        list.innerHTML = dishes.map(dish => `
            <div class="menu-card" style="background:#6d28d9;border-radius:10px;padding:15px;margin-bottom:10px;color:white;display:flex;justify-content:space-between;align-items:center;">
                <span style="font-weight:600;">${dish.name_th || dish.name}</span>
                <span style="font-weight:bold;">฿${Math.round(dish.price)}</span>
            </div>
        `).join("");
    }

    const total = getEl("total-price-display");
    if (total) total.textContent = Math.round(data.total_price || 0);
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

function goHome() {
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
    startWeightStream();   // เริ่ม SSE weight stream ทันที
};
