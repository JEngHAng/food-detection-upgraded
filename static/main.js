"use strict";

if (typeof getEl === 'undefined') {
    var getEl = (id) => document.getElementById(id);
}

var piCapturedFilename  = null;
var lastDetectionData   = null;
var _lastComputedPrice  = 0;

// ══════════════════════════════════════════════════════
// WEIGHT — SSE Realtime Stream
// ══════════════════════════════════════════════════════
var _weightES    = null;
var _lastWeightG = 0.0;

function startWeightStream() {
    if (_weightES) return;
    _weightES = new EventSource("/api/weight/stream");
    _weightES.onmessage = (e) => {
        try {
            const d = JSON.parse(e.data);
            if (d.error) { console.warn("Weight SSE error:", d.error); return; }
            _lastWeightG = d.weight ?? 0.0;
            document.querySelectorAll(".weight-display").forEach(el => el.textContent = _lastWeightG.toFixed(1));
            document.querySelectorAll(".weight-dot").forEach(dot => {
                if (d.mock) { dot.style.background="#888"; dot.style.boxShadow="none"; }
                else if (!d.stable) { dot.style.background="#e67e22"; dot.style.boxShadow="0 0 8px #e67e22"; }
                else { dot.style.background="#2ecc71"; dot.style.boxShadow="0 0 8px #2ecc71"; }
            });
            document.querySelectorAll(".weight-mock-badge").forEach(b => { b.style.display = d.mock ? "inline" : "none"; });
        } catch (err) { console.error("Weight parse error:", err); }
    };
    _weightES.onerror = () => {
        console.warn("Weight SSE disconnected — retry in 3s");
        _weightES.close(); _weightES = null;
        setTimeout(startWeightStream, 3000);
    };
}

async function tareScale() {
    const btn = getEl("btn-tare");
    if (btn) { btn.disabled=true; btn.textContent="⏳ กำลัง Tare..."; btn.style.opacity="0.7"; }
    showLoading(true, "⚖️ กำลัง Tare เครื่องชั่ง กรุณารอสักครู่...");
    try {
        const res  = await fetch("/api/weight/tare", { method:"POST" });
        const data = await res.json();
        showToast(data.success ? "✅ Tare สำเร็จ — น้ำหนักรีเซ็ตแล้ว" : "⚠️ "+(data.message||"Tare ไม่สำเร็จ"),
                  data.success ? "success" : "error");
    } catch (err) { showToast("❌ ติดต่อเซิร์ฟเวอร์ไม่ได้","error"); }
    finally {
        showLoading(false);
        if (btn) { btn.disabled=false; btn.textContent="⚖️ Tare"; btn.style.opacity="1"; }
    }
}

// ══════════════════════════════════════════════════════
// 1. ถ่ายภาพ
// ══════════════════════════════════════════════════════
async function captureFromPi() {
    if (piCapturedFilename) {
        try { await fetch("/api/cleanup",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:piCapturedFilename})}); }
        catch (err) { console.warn("Cleanup error:",err); }
        piCapturedFilename = null;
    }
    showLoading(true,"กำลังบันทึกภาพจากกล้อง...");
    try {
        const res  = await fetch("/api/capture",{method:"POST"});
        const data = await res.json();
        if (data.success) {
            const img = getEl("preview-img");
            if (img) { img.src=data.image_url; img.style.display="block"; }
            piCapturedFilename = data.filename;
            showToast("📸 ถ่ายภาพสำเร็จ!","success");
        }
    } catch (err) { console.error(err); }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// 2. ตรวจจับ
// ══════════════════════════════════════════════════════
async function startDetection() {
    if (!piCapturedFilename) { showToast("⚠️ ต้องถ่ายภาพก่อนครับ","error"); return; }
    showLoading(true,"AI กำลังวิเคราะห์อาหาร...");
    try {
        const res  = await fetch("/api/detect-captured",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:piCapturedFilename})});
        const data = await res.json();
        if (data.success) { lastDetectionData=data; renderResult(data); showScreen("result-screen"); }
    } catch (err) { console.error(err); }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// 3. ยืนยันและบันทึกลง DB
// ══════════════════════════════════════════════════════
async function goToEnd() {
    if (!piCapturedFilename || !lastDetectionData) { showToast("❌ ไม่พบข้อมูลการตรวจจับ","error"); return; }
    showLoading(true,"กำลังบันทึกลงฐานข้อมูล...");
    try {
        const res = await fetch("/api/confirm",{
            method:"POST", headers:{"Content-Type":"application/json"},
            body:JSON.stringify({
                filename:    piCapturedFilename,
                total_price: _lastComputedPrice,
                dishes:      lastDetectionData.dishes,
                detections:  lastDetectionData.detections||[],
                weight:      _lastWeightG,
            }),
        });
        const result = await res.json();
        if (result.success) { showScreen("end-screen"); startCountdown(5); }
        else showToast("❌ บันทึกล้มเหลว","error");
    } catch (err) { console.error(err); showToast("❌ ติดต่อเซิร์ฟเวอร์ไม่ได้","error"); }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// WEIGHT CLASSIFICATION
// ══════════════════════════════════════════════════════

/**
 * n   = น้ำหนักมาตรฐาน "ธรรมดา"
 * s   = น้ำหนักมาตรฐาน "พิเศษ"
 * e   = ราคาเพิ่มพิเศษ
 * tol = tolerance ±กรัม รอบ n และ s
 *
 * Zone:
 *  A  w < n-tol              → ธรรมดา น้อยกว่าปกติ    basePrice - discount
 *  B  n-tol ≤ w ≤ n+tol     → ธรรมดา ปกติ             basePrice
 *  C  n+tol < w < s-tol     → ธรรมดา มากกว่าปกติ      basePrice
 *  D  s-tol ≤ w ≤ s+tol     → พิเศษ  ปกติ             basePrice + e
 *  E  w > s+tol              → พิเศษ  มากกว่าปกติ      basePrice + e
 */
const WEIGHT_THRESHOLDS = {
    "ข้าวหน้าเป็ด":  { n: 446, s: 510, e: 5,  tol: 10 },
    "ข้าวเป็ดย่าง":  { n: 446, s: 510, e: 5,  tol: 10 },
    "ข้าวผัดกะเพรา": { n: 434, s: 498, e: 5,  tol: 10 },
    "ข้าวมันไก่":    { n: 420, s: 480, e: 5,  tol: 10 },
    "ก๋วยเตี๋ยวไก่": { n: 631, s: 871, e: 15, tol: 10 },
};
const DEFAULT_THRESHOLD = { n: 420, s: 500, e: 5, tol: 10 };

function getThreshold(foodName) {
    if (!foodName) return DEFAULT_THRESHOLD;
    for (const [key, val] of Object.entries(WEIGHT_THRESHOLDS)) {
        if (foodName.includes(key)) return val;
    }
    console.warn("⚠️ ไม่พบ threshold สำหรับ:", foodName, "→ ใช้ค่า default");
    return DEFAULT_THRESHOLD;
}

function classifyWeight(foodName, dishWeight, basePrice) {
    const t      = getThreshold(foodName);
    const priceN = Math.round(basePrice);
    const priceS = Math.round(basePrice) + t.e;

    const S_NORMAL = "font-size:0.72rem;font-weight:700;border-radius:6px;padding:2px 8px;white-space:nowrap;";
    const mkBadge  = (bg, color, border) =>
        `${S_NORMAL}background:${bg};color:${color};border:1px solid ${border};`;

    const st = {
        normalMenu:  mkBadge("rgba(148,163,184,0.12)", "#cbd5e1", "rgba(148,163,184,0.25)"),
        specialMenu: mkBadge("#f59e0b",                "#1c1917", "#f59e0b"),
        portionLow:  mkBadge("rgba(248,81,73,0.15)",   "#fca5a5", "rgba(248,81,73,0.3)"),
        portionNorm: mkBadge("rgba(34,197,94,0.12)",   "#86efac", "rgba(34,197,94,0.25)"),
        portionHigh: mkBadge("rgba(99,102,241,0.15)",  "#c4b5fd", "rgba(99,102,241,0.3)"),
        notworth:    mkBadge("rgba(248,81,73,0.18)",   "#f87171", "rgba(248,81,73,0.35)"),
    };

    if (!dishWeight || dishWeight <= 0) {
        return { menuType:"—", portionLabel:"—", portionStyle:"display:none;", typeStyle:"display:none;", finalPrice:priceN, priceNote:"" };
    }

    // Zone A — ธรรมดา น้อยกว่าปกติ (w < n-tol)
    if (dishWeight < t.n - t.tol) {
        const shortfall = t.n - dishWeight;
        const discount  = Math.floor(shortfall / 100) * 10;
        const fp        = Math.max(priceN - discount, 0);
        return {
            menuType:     "ธรรมดา",         typeStyle:    st.normalMenu,
            portionLabel: "🔽 น้อยกว่าปกติ", portionStyle: st.portionLow,
            valueBadge:   "❌ ไม่คุ้มค่า",   valueStyle:   st.notworth,
            finalPrice:   fp,
            priceNote:    `${priceN}฿ - ${discount}฿ = ${fp}฿`,
        };
    }
    // Zone B — ธรรมดา ปกติ (n-tol ≤ w ≤ n+tol)
    if (dishWeight <= t.n + t.tol) {
        return {
            menuType:     "ธรรมดา",      typeStyle:    st.normalMenu,
            portionLabel: "✅ ปริมาณปกติ", portionStyle: st.portionNorm,
            valueBadge:   "",             valueStyle:   "display:none;",
            finalPrice:   priceN,
            priceNote:    `${priceN}฿`,
        };
    }
    // Zone C — ธรรมดา มากกว่าปกติ (n+tol < w < s-tol)
    if (dishWeight < t.s - t.tol) {
        return {
            menuType:     "ธรรมดา",         typeStyle:    st.normalMenu,
            portionLabel: "🔼 มากกว่าปกติ", portionStyle: st.portionHigh,
            valueBadge:   "",               valueStyle:   "display:none;",
            finalPrice:   priceN,
            priceNote:    `${priceN}฿`,
        };
    }
    // Zone D — พิเศษ ปกติ (s-tol ≤ w ≤ s+tol)
    if (dishWeight <= t.s + t.tol) {
        return {
            menuType:     "⭐ พิเศษ",     typeStyle:    st.specialMenu,
            portionLabel: "✅ ปริมาณปกติ", portionStyle: st.portionNorm,
            valueBadge:   "",             valueStyle:   "display:none;",
            finalPrice:   priceS,
            priceNote:    `${priceN}฿ + ${t.e}฿ = ${priceS}฿`,
        };
    }
    // Zone E — พิเศษ มากกว่าปกติ (w > s+tol)
    return {
        menuType:     "⭐ พิเศษ",       typeStyle:    st.specialMenu,
        portionLabel: "🔼 มากกว่าปกติ", portionStyle: st.portionHigh,
        valueBadge:   "",              valueStyle:   "display:none;",
        finalPrice:   priceS,
        priceNote:    `${priceN}฿ + ${t.e}฿ = ${priceS}฿`,
    };
}

function splitWeightByConfidence(dishes, totalWeight) {
    if (!dishes || dishes.length === 0) return [];
    if (dishes.length === 1) return [{ ...dishes[0], dishWeight: totalWeight }];
    const totalConf = dishes.reduce((s, d) => s + (d.confidence||0), 0);
    return dishes.map(d => {
        const ratio = totalConf > 0 ? (d.confidence||0)/totalConf : 1/dishes.length;
        return { ...d, dishWeight: Math.round(totalWeight * ratio * 10) / 10 };
    });
}

// ══════════════════════════════════════════════════════
// 4. แสดงผลลัพธ์
// ══════════════════════════════════════════════════════
function renderResult(data) {
    const ri = getEl("result-img");
    if (ri) ri.src = data.annotated_image;

    const dishes = splitWeightByConfidence(data.dishes||[], _lastWeightG);
    let newTotalPrice = 0;

    const list = getEl("menu-list");
    if (list) {
        list.innerHTML = dishes.map((dish, idx) => {
            const ingredients    = dish.ingredients||[];
            const hasIngredients = ingredients.length > 0;
            const conf           = dish.confidence ? Math.round(dish.confidence*100) : 0;
            const foodName       = dish.name_th || dish.name;
            const dishWeight     = dish.dishWeight || 0;

            const wc = classifyWeight(foodName, dishWeight, dish.price);
            newTotalPrice += wc.finalPrice;

            const totalConf  = dishes.reduce((s,d) => s+(d.confidence||0), 0);
            const ratio      = totalConf > 0 ? Math.round((dish.confidence||0)/totalConf*100) : 100;
            const weightLabel = dishes.length > 1
                ? `<span style="font-size:0.72rem;opacity:0.6;">สัดส่วน ${ratio}% → ${dishWeight.toFixed(1)} ก.</span>`
                : `<span style="font-size:0.72rem;opacity:0.6;">${dishWeight.toFixed(1)} ก.</span>`;

            const ingHtml = hasIngredients ? `
                <div id="ing-${idx}" style="display:none;background:rgba(0,0,0,0.3);border-top:1px solid rgba(255,255,255,0.15);padding:10px 14px;">
                    ${ingredients.map(ing => `
                        <div style="display:flex;justify-content:space-between;padding:4px 0;font-size:0.82rem;color:rgba(255,255,255,0.85);">
                            <span>• ${ing.name_th||ing.name}${ing.count?` <span style="opacity:0.6;">x${ing.count}</span>`:''}</span>
                            <span style="opacity:0.7;">${ing.confidence?Math.round(ing.confidence*100)+'%':''}</span>
                        </div>`).join("")}
                </div>` : '';

            return `
            <div class="menu-card" style="background:#6d28d9;border-radius:10px;margin-bottom:10px;color:white;overflow:hidden;">
                <div style="padding:14px 16px;display:flex;justify-content:space-between;align-items:flex-start;cursor:${hasIngredients?'pointer':'default'};"
                     onclick="${hasIngredients?`toggleIng(${idx})`:''}">
                    <div style="display:flex;flex-direction:column;gap:6px;flex:1;">
                        <span style="font-weight:700;font-size:1rem;">${foodName}</span>
                        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                            ${conf?`<span style="font-size:0.72rem;opacity:0.7;">ความแม่นยำ ${conf}%</span>`:''}
                            ${weightLabel}
                        </div>
                        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                            <span style="${wc.typeStyle}">${wc.menuType}</span>
                            <span style="${wc.portionStyle}">${wc.portionLabel}</span>
                            ${wc.valueBadge ? `<span style="${wc.valueStyle}">${wc.valueBadge}</span>` : ''}
                        </div>
                    </div>
                    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:3px;min-width:80px;padding-left:10px;">
                        <span style="font-weight:bold;font-size:1.2rem;">฿${wc.finalPrice}</span>
                        <span style="font-size:0.68rem;opacity:0.65;">${wc.priceNote}</span>
                        ${hasIngredients?`<span id="arrow-${idx}" style="font-size:0.72rem;opacity:0.55;transition:transform 0.2s;margin-top:2px;">▼ ส่วนประกอบ</span>`:''}
                    </div>
                </div>
                ${ingHtml}
            </div>`;
        }).join("");
    }

    _lastComputedPrice = newTotalPrice || Math.round(data.total_price||0);
    const total = getEl("total-price-display");
    if (total) total.textContent = _lastComputedPrice;
}

function toggleIng(idx) {
    const el=document.getElementById(`ing-${idx}`), arrow=document.getElementById(`arrow-${idx}`);
    if (!el) return;
    const isOpen = el.style.display !== 'none';
    el.style.display = isOpen ? 'none' : 'block';
    if (arrow) arrow.style.transform = isOpen ? '' : 'rotate(180deg)';
}

// ══════════════════════════════════════════════════════
// 5. ตรวจซ้ำ
// ══════════════════════════════════════════════════════
async function rescan() {
    if (!piCapturedFilename) { showToast("⚠️ ไม่พบรูปภาพ กรุณาถ่ายใหม่","error"); return; }
    showLoading(true,"AI กำลังวิเคราะห์อาหารใหม่...");
    try {
        const res  = await fetch("/api/detect-captured",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:piCapturedFilename})});
        const data = await res.json();
        if (data.success) { lastDetectionData=data; renderResult(data); showToast("🔄 ตรวจจับใหม่เรียบร้อย","success"); }
        else showToast("❌ ตรวจจับไม่สำเร็จ","error");
    } catch (err) { console.error(err); showToast("❌ ติดต่อเซิร์ฟเวอร์ไม่ได้","error"); }
    showLoading(false);
}

// ══════════════════════════════════════════════════════
// Utility
// ══════════════════════════════════════════════════════
function startCountdown(seconds) {
    setTimeout(goHome, seconds * 1000);
}
function showScreen(id) { document.querySelectorAll(".screen").forEach(s=>s.classList.remove("active")); getEl(id)?.classList.add("active"); }

// ══════════════════════════════════════════════════════
// Theme (light / dark)
// ══════════════════════════════════════════════════════
function applyTheme(mode) {
    const isLight = mode === "light";
    document.body.classList.toggle("light", isLight);
    document.documentElement.classList.toggle("light", isLight);
    const btn = getEl("btn-theme");
    if (btn) btn.textContent = isLight ? "☀️ โทนสว่าง" : "🌙 โทนมืด";
}
function toggleTheme() {
    const next = document.body.classList.contains("light") ? "dark" : "light";
    localStorage.setItem("theme", next);
    applyTheme(next);
}
function initTheme() {
    const saved = localStorage.getItem("theme") || "dark";
    applyTheme(saved);
}
async function goHome() {
    if (piCapturedFilename) {
        try { await fetch("/api/cleanup",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:piCapturedFilename})}); }
        catch (err) { console.warn("Cleanup error:",err); }
    }
    piCapturedFilename=null; lastDetectionData=null; _lastComputedPrice=0;
    const img=getEl("preview-img"); if(img) img.src="/video_feed";
    showScreen("home-screen");
}
function showLoading(show,text="") { const el=getEl("loading-overlay"); if(el){if(text) getEl("loader-text").textContent=text; el.classList.toggle("show",show);} }
function showToast(msg,type="") { const el=getEl("toast"); if(el){el.textContent=msg;el.className=`show ${type}`;setTimeout(()=>el.className="",3000);} }
async function confirmShutdown() {
    showToast("⏹ กำลังปิดระบบ...","error");
    setTimeout(async()=>{
        await fetch("/api/shutdown",{method:"POST"});
        document.body.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#16172b;color:#e2e8f0;font-family:IBM Plex Sans Thai,sans-serif;flex-direction:column;gap:16px;"><div style="font-size:2rem;">⏹</div><div style="font-size:1.2rem;font-weight:700;">ปิดระบบเรียบร้อย</div><div style="font-size:0.85rem;color:#94a3b8;">สามารถปิดหน้าต่างได้แล้ว</div></div>`;
    },1000);
}
window.onload=()=>{ console.log("✅ ระบบพร้อมใช้งาน"); initTheme(); startWeightStream(); checkAutoTare(); };
async function checkAutoTare() {
    document.querySelectorAll(".weight-display").forEach(el=>el.textContent="...");
    showLoading(true,"⚖️ กำลัง Tare เครื่องชั่งอัตโนมัติ...");
    while(true){
        try{
            const res=await fetch("/api/tare_status"); const data=await res.json();
            if(data.status==="done"){showLoading(false);showToast("✅ ระบบพร้อมใช้งาน","success");break;}
            else if(data.status==="failed"){showLoading(false);showToast("⚠️ Tare ไม่สำเร็จ กรุณากด Tare ด้วยตนเอง","error");break;}
        } catch(e){showLoading(false);break;}
        await new Promise(r=>setTimeout(r,300));
    }
}
