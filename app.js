/* Hotel Mahesh · front-end controller
   Prices, discounts, availability and payment status are decided by the server.
   This file only displays them. */
(function () {
  "use strict";

  const API_BASE = "https://mahesh-hotel.onrender.com/api";
  const PHONE = "918294817088";
  const FALLBACK_IMG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 4 3'%3E%3Crect width='4' height='3' fill='%230f4a47'/%3E%3C/svg%3E";
  const ALBUM_ON = "album-btn px-4 py-2 rounded-xl text-xs font-bold bg-emerald-800 text-white shadow transition cursor-pointer";
  const ALBUM_OFF = "album-btn px-4 py-2 rounded-xl text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-100 transition cursor-pointer";
  const TAB_ON = "px-4 py-2.5 rounded-xl text-xs sm:text-sm font-bold bg-emerald-800 text-white shadow transition flex items-center gap-2 cursor-pointer";
  const TAB_OFF = "px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 transition flex items-center gap-2 cursor-pointer";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
  const nightsBetween = (a, b) => Math.max(1, Math.round((new Date(b) - new Date(a)) / 864e5));
  const localISO = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const num = (v, fallback) => { const n = Number(v); return v !== "" && Number.isFinite(n) ? n : fallback; };

  function sanitizeImageUrl(url) {
    if (!url) return FALLBACK_IMG;
    url = String(url).trim();
    const m = url.match(/drive\.google\.com.*?(?:\/d\/|[?&]id=)([A-Za-z0-9_-]+)/);
    if (m) return `https://lh3.googleusercontent.com/d/${m[1]}`;
    return /^https:\/\//i.test(url) ? url : FALLBACK_IMG;
  }
  // one delegated handler replaces every inline onerror attribute
  document.addEventListener("error", (e) => {
    const t = e.target;
    if (t && t.tagName === "IMG" && !t.dataset.fb) { t.dataset.fb = "1"; t.src = FALLBACK_IMG; }
  }, true);

  function maskSensitiveRef(str) {
    if (!str) return "Not Provided";
    const parts = String(str).split(":");
    if (parts.length > 1) return `${parts[0].trim()}: •••• ${parts.slice(1).join(":").trim().slice(-4)}`;
    return str.length > 4 ? `•••• ${str.slice(-4)}` : "Verified";
  }

  // ---------------- API ----------------
  function errText(body, status) {
    if (status === 429) return "Too many requests. Please wait a minute and try again.";
    const d = body && body.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0] && d[0].msg) return String(d[0].msg).replace(/^Value error, /, "");
    return `Request failed (code ${status}). Please try again or call the front desk.`;
  }
  async function api(path, opts) {
    const res = await fetch(API_BASE + path, opts);
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON */ }
    if (!res.ok) { const e = new Error(errText(body, res.status)); e.status = res.status; throw e; }
    return body;
  }
  const getAuthHeaders = (extra) => Object.assign({}, extra, { Authorization: "Bearer " + (sessionStorage.getItem("hm_staff_token") || "") });
  const adminOn = () => !!sessionStorage.getItem("hm_staff_token");
  async function withRetry(fn, tries) {
    for (let i = 0; i < (tries || 12); i++) {
      try { return await fn(); } catch (e) { await new Promise((r) => setTimeout(r, 4000)); }
    }
    return null;
  }

  // ---------------- state ----------------
  let cachedRooms = [];
  let cachedGallery = [];
  let cachedConfig = null;
  let stayMode = "night";
  let currentCalculatedPayable = 0;
  let isSubmitting = false;
  let pollCountdownTimer = null;
  let occupancyTimer = null;
  let pollSecondsLeft = 60;

  // ---------------- loaders (database is the only source of truth) ----------------
  async function loadConfig() {
    const c = await withRetry(() => api("/config"));
    if (!c) return;
    cachedConfig = c;
    if ($("cfgUpiId")) $("cfgUpiId").value = c.upi_id || "";
    if ($("cfgDisc2")) $("cfgDisc2").value = c.d2;
    if ($("cfgDisc3")) $("cfgDisc3").value = c.d3;
    if ($("cfgDisc4")) $("cfgDisc4").value = c.d4plus;
    if ($("cfgEvFull")) $("cfgEvFull").value = c.event_full;
    if ($("evFullRateDisplay")) $("evFullRateDisplay").innerHTML = `₹${Number(c.event_full)} <span class="text-xs font-normal text-slate-300">/ guest</span>`;
    if ($("evSixRateDisplay")) $("evSixRateDisplay").textContent = `₹${Number(c.event_six)} / guest`;
    applyDiscText();
    refreshLiveQuote();
  }
  async function loadRooms() {
    const rooms = await withRetry(() => api("/rooms"));
    if (!rooms || !rooms.length) {
      if ($("roomGrid")) $("roomGrid").innerHTML = `<p class="col-span-full text-center text-slate-400 py-12">Rooms could not be loaded right now. Please call +91 82948 17088.</p>`;
      return;
    }
    cachedRooms = rooms;
    renderRoomCards(); renderAdminRooms(); renderHourly(); applyDiscText(); refreshLiveQuote();
  }
  async function loadGallery() {
    const g = await withRetry(() => api("/gallery"));
    if (g) { cachedGallery = g; renderGallery(); }
  }
  async function loadBookings() {
    try {
      const list = await api("/bookings", { headers: getAuthHeaders() });
      window.currentBookingsList = list;
      return list;
    } catch (e) { handleAdminError(e); return window.currentBookingsList || []; }
  }

  // prices/discounts shown on the page always come from the database
  function applyDiscText() {
    if (!cachedConfig) return;
    const c = cachedConfig, d2 = Number(c.d2), d3 = Number(c.d3), d4 = Number(c.d4plus), mx = Math.max(d2, d3, d4);
    const low = cachedRooms.length ? Math.min(...cachedRooms.map((r) => r.h1)) : null;
    const T = {
      full: `Tiered Rates: 2 Nights = ${d2}% OFF | 3 Nights = ${d3}% OFF | 4+ Nights = ${d4}% OFF`,
      top: `Up to ${mx}% OFF multi-night stays!` + (low ? ` Hourly from ${money(low)}` : ""),
      para: `Stay 2 nights for ${d2}% OFF, 3 nights for ${d3}% OFF, and 4+ nights for ${d4}% OFF.`,
    };
    document.querySelectorAll("[data-disc]").forEach((el) => { el.textContent = T[el.getAttribute("data-disc")] || ""; });
  }
  function renderHourly() {
    const g = $("hourlyGrid"); if (!g) return;
    const row = (l, v) => `<div class="flex justify-between"><dt>${l}</dt><dd class="font-bold">${money(v)}</dd></div>`;
    g.innerHTML = cachedRooms.map((r) => `<div class="bg-slate-50 p-6 rounded-2xl border border-slate-200"><h4 class="font-bold text-slate-900 mb-3 text-center">${esc(r.name)}</h4><dl class="text-sm space-y-1 text-slate-700">${row("1 hour", r.h1)}${row("2 hours", r.h2)}${row("3 hours", r.h3)}${row("Whole day (24h)", r.hday)}</dl></div>`).join("");
  }

  // ---------------- rooms ----------------
  function renderRoomCards() {
    const rg = $("roomGrid"), rs = $("rtype"), nR = $("nRoom");
    const prev = rs ? rs.value : "";
    if (rs) rs.innerHTML = ""; if (nR) nR.innerHTML = ""; if (rg) rg.innerHTML = "";
    cachedRooms.forEach((r) => {
      const safeImg = sanitizeImageUrl(r.image_url);
      if (rs) rs.insertAdjacentHTML("beforeend", `<option value="${esc(r.id)}">${esc(r.name)} · ₹${Number(r.price)}/night</option>`);
      if (nR) nR.insertAdjacentHTML("beforeend", `<option value="${esc(r.id)}">${esc(r.name)}</option>`);
      if (rg) rg.insertAdjacentHTML("beforeend", `
        <article class="bg-white rounded-2xl overflow-hidden shadow-sm hover:shadow-xl border border-slate-200 transition-all duration-300 flex flex-col group">
          <div class="relative h-64 overflow-hidden bg-slate-900">
            <img loading="lazy" src="${esc(safeImg)}" alt="${esc(r.name)}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500">
            <div class="absolute top-3 left-3 bg-emerald-950/90 backdrop-blur-md text-amber-300 text-xs font-bold px-3 py-1 rounded-lg border border-amber-400/30">${esc(r.sleeps)}</div>
            <div class="absolute bottom-3 right-3 bg-slate-950/80 backdrop-blur-md text-white text-[11px] px-2.5 py-1 rounded-md">Hourly: 1h: ₹${Number(r.h1)} | 2h: ₹${Number(r.h2)} | Day: ₹${Number(r.hday)}</div>
          </div>
          <div class="p-6 flex-1 flex flex-col justify-between">
            <div>
              <h3 class="font-serif text-2xl font-bold text-slate-900 group-hover:text-emerald-800 transition">${esc(r.name)}</h3>
              <p class="text-slate-600 text-xs sm:text-sm mt-2 leading-relaxed">${esc(r.description)}</p>
            </div>
            <div class="mt-6 pt-5 border-t border-slate-100 flex items-center justify-between">
              <div>
                <span class="text-xs text-slate-400 block font-medium">Nightly Standard Rate</span>
                <span class="text-2xl font-black text-slate-900">${money(r.price)} <span class="text-xs font-normal text-slate-500">/ night</span></span>
              </div>
              <button type="button" data-pick-room="${esc(r.id)}" class="px-4 py-2.5 rounded-xl gold-gradient hover:brightness-110 active:scale-95 text-slate-950 font-bold text-xs transition shadow-md cursor-pointer">Select &amp; Quote</button>
            </div>
          </div>
        </article>`);
    });
    if (rs && prev && cachedRooms.some((r) => r.id === prev)) rs.value = prev;
  }
  if ($("roomGrid")) {
    $("roomGrid").addEventListener("click", (e) => {
      const b = e.target.closest("[data-pick-room]");
      if (!b) return;
      if ($("rtype")) $("rtype").value = b.getAttribute("data-pick-room");
      if ($("bookingWidget")) $("bookingWidget").scrollIntoView({ behavior: "smooth", block: "center" });
      refreshLiveQuote();
    });
  }

  // ---------------- gallery ----------------
  function renderGallery(filter) {
    filter = filter || "all";
    const grid = $("galleryGrid");
    if (!grid) return;
    grid.innerHTML = "";
    const items = filter === "all" ? cachedGallery : cachedGallery.filter((p) => p.album === filter);
    if (!items.length) {
      grid.innerHTML = `<p class="col-span-full text-center text-slate-400 py-8 text-xs">No photographs added in this album yet in database.</p>`;
      return;
    }
    items.forEach((p) => {
      grid.insertAdjacentHTML("beforeend", `
        <div class="group relative h-64 rounded-2xl overflow-hidden bg-slate-900 border border-slate-200 shadow-sm hover:shadow-xl transition-all duration-300">
          <img loading="lazy" src="${esc(sanitizeImageUrl(p.url))}" alt="${esc(p.title)}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500">
          <div class="absolute inset-0 bg-gradient-to-t from-slate-950/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-4">
            <span class="text-white text-xs font-bold drop-shadow">${esc(p.title)}</span>
          </div>
        </div>`);
    });
  }
  if ($("albumFilterBar")) {
    $("albumFilterBar").addEventListener("click", (e) => {
      const b = e.target.closest("[data-album]"); if (!b) return;
      document.querySelectorAll(".album-btn").forEach((x) => (x.className = x === b ? ALBUM_ON : ALBUM_OFF));
      renderGallery(b.getAttribute("data-album"));
    });
  }

  // ---------------- live quote (display only; server recomputes on booking) ----------------
  function refreshLiveQuote() {
    if (!cachedRooms.length || !cachedConfig) return;
    const rtypeEl = $("rtype");
    const room = cachedRooms.find((r) => r.id === (rtypeEl ? rtypeEl.value : null)) || cachedRooms[0];
    if (stayMode === "night") {
      const cin = $("cin") ? $("cin").value : "", cout = $("cout") ? $("cout").value : "";
      const n = cout && cin && cout > cin ? nightsBetween(cin, cout) : 1;
      const base = n * room.price;
      let pct = 0;
      if (n === 2) pct = Number(cachedConfig.d2); else if (n === 3) pct = Number(cachedConfig.d3); else if (n >= 4) pct = Number(cachedConfig.d4plus);
      currentCalculatedPayable = Math.round(base * (1 - pct / 100));
      if ($("calcSummary")) $("calcSummary").textContent = `${n} Night(s) Stay (${room.name})`;
      if ($("calcDiscountTag")) {
        if (pct > 0) {
          $("calcDiscountTag").innerHTML = `<span class="bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded font-bold mr-1">-${pct}% OFF</span> Multi-night discount applied!`;
          if ($("calcOldPrice")) { $("calcOldPrice").textContent = money(base); $("calcOldPrice").classList.remove("hidden"); }
        } else {
          $("calcDiscountTag").textContent = `Standard rate (stay 2+ nights for up to ${Math.max(Number(cachedConfig.d2), Number(cachedConfig.d3), Number(cachedConfig.d4plus))}% OFF)`;
          if ($("calcOldPrice")) $("calcOldPrice").classList.add("hidden");
        }
      }
      if ($("calcFinalPrice")) $("calcFinalPrice").textContent = money(currentCalculatedPayable);
    } else {
      const hours = Number($("hDuration") ? $("hDuration").value : 1) || 1;
      let total = room.h1;
      if (hours === 2) total = room.h2; else if (hours === 3) total = room.h3; else if (hours >= 4) total = room.hday;
      currentCalculatedPayable = total;
      if ($("calcSummary")) $("calcSummary").textContent = `${hours} Hour(s) Transit Stay (${room.name})`;
      if ($("calcDiscountTag")) $("calcDiscountTag").textContent = hours >= 4 ? "Whole Day Pass Cap Applied" : "Hourly Transit Rate";
      if ($("calcOldPrice")) $("calcOldPrice").classList.add("hidden");
      if ($("calcFinalPrice")) $("calcFinalPrice").textContent = money(total);
    }
  }

  // ---------------- guest booking + QR ----------------
  const guestModal = $("guestModal");
  function clearPollingTimers() {
    if (pollCountdownTimer) clearInterval(pollCountdownTimer);
    pollCountdownTimer = null;
  }
  function closeGuestModal() { clearPollingTimers(); if (guestModal && guestModal.close) guestModal.close(); }
  if (guestModal) {
    guestModal.addEventListener("close", clearPollingTimers);
    guestModal.addEventListener("cancel", clearPollingTimers);
  }
  if ($("modalCloseBtn")) $("modalCloseBtn").onclick = closeGuestModal;
  if ($("btnModalCancel")) $("btnModalCancel").onclick = closeGuestModal;
  if ($("btnCancelWaiting")) $("btnCancelWaiting").onclick = closeGuestModal;

  if ($("bookForm")) {
    $("bookForm").addEventListener("submit", function (e) {
      e.preventDefault();
      const cin = $("cin").value, cout = $("cout").value, hDate = $("hDate").value;
      const todayStr = localISO(new Date());
      if (stayMode === "night") {
        if (!cin || !cout || cout <= cin) return alert("Please ensure Check-out date is strictly after Check-in date.");
        if (cin < todayStr) return alert("Check-in date cannot be in the past.");
      } else if (!hDate || hDate < todayStr) {
        return alert("Please select a valid date for transit stay.");
      }
      const rs = $("rtype");
      if ($("mSummaryRoom")) $("mSummaryRoom").textContent = rs.options[rs.selectedIndex].text;
      if ($("mSummaryDates")) $("mSummaryDates").textContent = stayMode === "night" ? `${cin} to ${cout}` : `${hDate} (${$("hDuration").value} hrs)`;
      if ($("mSummaryTotal")) $("mSummaryTotal").textContent = $("calcFinalPrice").textContent;
      if ($("modalErr")) $("modalErr").textContent = "";
      if ($("guestDetailsForm")) $("guestDetailsForm").classList.remove("hidden");
      if ($("upiPaymentScreen")) $("upiPaymentScreen").classList.add("hidden");
      clearPollingTimers();
      if (guestModal) {
        if (guestModal.showModal) guestModal.showModal(); else guestModal.setAttribute("open", "");
      }
    });
  }

  if ($("guestDetailsForm")) {
    $("guestDetailsForm").addEventListener("submit", async function (e) {
      e.preventDefault();
      if (isSubmitting) return;
      const name = $("custName").value.trim();
      const phone = $("custPhone").value.replace(/[^0-9]/g, "").slice(-10);
      const docType = $("custDocType").value;
      const docNum = $("custDocNum").value.trim();
      const payOpt = document.querySelector('input[name="payOption"]:checked') ? document.querySelector('input[name="payOption"]:checked').value : "upi";
      const errBox = $("modalErr"), confirmBtn = $("btnConfirmBooking");

      if (name.length < 2) { if (errBox) errBox.textContent = "Please enter guest full name."; return; }
      if (phone.length !== 10) { if (errBox) errBox.textContent = "Please enter a valid 10-digit mobile number."; return; }
      if (!/^[0-9A-Za-z]{4}$/.test(docNum)) { if (errBox) errBox.textContent = "Please enter the last 4 digits of your ID."; return; }
      if ($("custConsent") && !$("custConsent").checked) { if (errBox) errBox.textContent = "Please accept the privacy notice and terms to continue."; return; }

      const cin = stayMode === "night" ? $("cin").value : $("hDate").value;
      const cout = stayMode === "night" ? $("cout").value : $("hDate").value;
      const hours = stayMode === "hour" ? Number($("hDuration").value) : 0;
      const fullDoc = `${docType}: ${docNum}`;
      const fd = new FormData();
      fd.append("name", name); fd.append("phone", phone); fd.append("room_id", $("rtype").value);
      fd.append("booking_type", stayMode); fd.append("start_date", cin); fd.append("end_date", cout);
      fd.append("hours", String(hours)); fd.append("guests", $("guests") ? $("guests").value : "2");
      fd.append("id_proof", fullDoc); fd.append("payment_mode", payOpt === "desk" ? "Counter" : "UPI");

      try {
        isSubmitting = true;
        if (confirmBtn) {
          confirmBtn.disabled = true;
          confirmBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Registering Stay...';
        }
        if (errBox) errBox.textContent = "";

        const data = await api("/bookings", { method: "POST", body: fd });
        const record = { booking_id: data.booking_id, total: data.total, discount_applied: data.discount_applied };

        if (payOpt === "desk") {
          closeGuestModal();
          completeBookingNotification(record, name, phone, fullDoc, cin, cout, hours, "Pay at Counter");
          return;
        }

        if ($("guestDetailsForm")) $("guestDetailsForm").classList.add("hidden");
        if ($("upiPaymentScreen")) $("upiPaymentScreen").classList.remove("hidden");
        const upi = String(data.upi_id || "").trim();
        if ($("upiAmountDisplay")) $("upiAmountDisplay").textContent = money(data.total);
        if ($("upiTargetDisplay")) $("upiTargetDisplay").textContent = upi;
        if ($("upiBookingRef")) $("upiBookingRef").textContent = `#${data.booking_id}`;
        const upiUrl = `upi://pay?pa=${encodeURIComponent(upi)}&pn=${encodeURIComponent("Hotel Mahesh")}&am=${Number(data.total)}&tr=${encodeURIComponent(data.booking_id)}&tn=${encodeURIComponent("Stay " + data.booking_id)}&cu=INR`;
        if ($("btnUpiIntentLink")) $("btnUpiIntentLink").href = upiUrl;
        const qrBox = $("qrcodeContainer");
        if (qrBox && typeof qrcode !== "undefined") {
          qrBox.innerHTML = "";
          const qr = qrcode(0, "M"); qr.addData(upiUrl); qr.make();
          const qi = document.createElement("img"); qi.src = qr.createDataURL(5, 2); qi.alt = "UPI payment QR code"; qi.width = 190; qi.height = 190; qrBox.appendChild(qi);
        }

        if ($("waitingStatusLabel")) $("waitingStatusLabel").textContent = "Awaiting front-desk verification";
        clearPollingTimers();
        if ($("btnManualConfirmPaid")) $("btnManualConfirmPaid").onclick = () => { closeGuestModal(); completeBookingNotification(record, name, phone, fullDoc, cin, cout, hours, "UPI Sent (Pending Desk Verification)"); };
      } catch (err) {
        if (errBox) errBox.textContent = err.status ? err.message : "Server is waking up (about 45 seconds). Please try again shortly or call +91 82948 17088.";
      } finally {
        isSubmitting = false;
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.innerHTML = '<span>Proceed to Payment</span> <i class="fa-solid fa-arrow-right text-xs"></i>';
        }
      }
    });
  }

  function completeBookingNotification(data, name, phone, fullDoc, cin, cout, hours, payMethod) {
    const disc = data.discount_applied > 0 ? ` (${esc(data.discount_applied)}% multi-night discount applied)` : "";
    if ($("msg")) {
      $("msg").innerHTML = `<span class="text-emerald-700 font-bold"><i class="fa-solid fa-circle-check mr-1"></i> Booking Received! Ref: #${esc(data.booking_id)} · Total: ${money(data.total)}${disc} [${esc(payMethod)}]. Confirmed once the front desk verifies payment.</span>`;
      const roomText = $("rtype") ? $("rtype").options[$("rtype").selectedIndex].text : "Room";
      const stayText = stayMode === "night" ? `${cin} to ${cout}` : `${cin} (${hours} hrs)`;
      const waText = `Hello Hotel Mahesh, I reserved #${data.booking_id}: ${roomText} for ${stayText}. Total: ${money(data.total)}. Guest: ${name}, Mobile: ${phone}, ID Ref: ${maskSensitiveRef(fullDoc)}. Status: ${payMethod}. Please confirm availability!`;
      const a = document.createElement("a");
      a.href = `https://wa.me/${PHONE}?text=${encodeURIComponent(waText)}`;
      a.target = "_blank"; a.rel = "noopener noreferrer";
      a.className = "inline-flex items-center gap-1.5 ml-2 px-3 py-1 bg-emerald-600 text-white rounded-lg text-xs font-bold hover:bg-emerald-700 shadow-sm";
      a.innerHTML = '<i class="fa-brands fa-whatsapp"></i> Confirm on WhatsApp';
      $("msg").appendChild(a);
    }
    if ($("custName")) $("custName").value = "";
    if ($("custPhone")) $("custPhone").value = "";
    if ($("custDocNum")) $("custDocNum").value = "";
  }

  window.sendWhatsAppConfirmationById = function (bookingId) {
    const b = (window.currentBookingsList || []).find((x) => String(x.id) === String(bookingId));
    if (!b) return alert("Booking details not found.");
    const p = String(b.phone || "").replace(/[^0-9]/g, "").slice(-10);
    if (p.length !== 10) return alert("Invalid customer phone number.");
    const stayText = b.booking_type === "hour" ? `${b.start_date} (${b.hours} Hours Transit)` : `${b.start_date} to ${b.end_date}`;
    const roomAssigned = b.room_number ? `Allotted Room: No. ${b.room_number}` : `Room Category: ${b.room_name}`;
    const message =
`*Booking Confirmed - Hotel Mahesh, Sasaram* 🏨

Dear ${b.guest_name},

We are pleased to inform you that your reservation #${b.id} has been confirmed. ${roomAssigned}!

📅 *Reservation Summary:*
• Dates/Timing: ${stayText}
• Total Bill: ${money(b.total)}
• Guests: ${b.guests || 2}

📍 *Hotel Location:*
Near Gas Agency, Fazalganj, Sasaram, Rohtas, Bihar 821115
Google Maps: https://maps.google.com/?q=Hotel+Mahesh+Fazalganj+Sasaram

Front Desk Helpline: +91 82948 17088

We look forward to welcoming you!`;
    window.open(`https://wa.me/91${p}?text=${encodeURIComponent(message)}`, "_blank", "noopener");
  };

  // ---------------- staff login ----------------
  const adminAuthModal = $("adminAuthModal");
  const openAdminModal = () => {
    if ($("modalAdminErr")) $("modalAdminErr").textContent = "";
    if (adminAuthModal) {
      if (adminAuthModal.showModal) adminAuthModal.showModal(); else adminAuthModal.setAttribute("open", "");
    }
  };
  ["btnOpenAdminModal", "btnOpenAdminModal2"].forEach((id) => { 
    const el = $(id);
    if (el) el.onclick = openAdminModal; 
  });
  if ($("adminModalClose")) $("adminModalClose").onclick = () => adminAuthModal && adminAuthModal.close();

  if ($("adminLoginForm")) {
    $("adminLoginForm").onsubmit = async function (e) {
      e.preventDefault();
      const errBox = $("modalAdminErr"), btn = $("btnAdminSubmit");
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Authenticating...';
      }
      if (errBox) errBox.textContent = "";
      try {
        const d = await api("/auth/login", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: $("modalAu").value.trim(), password: $("modalAp").value }),
        });
        sessionStorage.setItem("hm_staff_token", d.token);
        if (adminAuthModal && adminAuthModal.close) adminAuthModal.close();
        if ($("modalAp")) $("modalAp").value = "";
        window.location.hash = "#admin";
        route();
      } catch (err) {
        if (errBox) errBox.textContent = err.status ? err.message : "Server waking up (~45s). Please try again shortly.";
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-arrow-right-to-bracket text-xs"></i> <span>Login to Management Portal</span>';
        }
      }
    };
  }

  function logoutLocal() { sessionStorage.removeItem("hm_staff_token"); window.location.hash = ""; route(); }
  function handleAdminError(e) {
    if (e && e.status === 401) { logoutLocal(); alert("Session expired. Please log in again."); }
    else alert((e && e.message) || "Request failed.");
  }

  // ---------------- admin panes ----------------
  function switchAdminPane(tab) {
    if ($("admTabOccupancy")) $("admTabOccupancy").className = tab === "occupancy" ? TAB_ON : TAB_OFF;
    if ($("admTabBookings")) $("admTabBookings").className = tab === "bookings" ? TAB_ON : TAB_OFF;
    if ($("admTabRooms")) $("admTabRooms").className = tab === "rooms" ? TAB_ON : TAB_OFF;
    if ($("paneOccupancy")) $("paneOccupancy").classList.toggle("hidden", tab !== "occupancy");
    if ($("paneBookings")) $("paneBookings").classList.toggle("hidden", tab !== "bookings");
    if ($("paneRooms")) $("paneRooms").classList.toggle("hidden", tab !== "rooms");
  }
  if ($("admTabOccupancy")) $("admTabOccupancy").onclick = () => switchAdminPane("occupancy");
  if ($("admTabBookings")) $("admTabBookings").onclick = () => switchAdminPane("bookings");
  if ($("admTabRooms")) $("admTabRooms").onclick = () => switchAdminPane("rooms");

  function calculateTimeRemaining(b) {
    const now = Date.now();
    if (b.booking_type === "hour") {
      const start = b.check_in_time ? new Date(b.check_in_time).getTime() : new Date(b.created_at || now).getTime();
      const diff = start + (Number(b.hours) || 1) * 3600000 - now;
      if (diff <= 0) return `<span class="px-2 py-0.5 rounded bg-rose-100 text-rose-800 font-bold text-[11px] animate-pulse">Time Expired (Overdue)</span>`;
      const h = Math.floor(diff / 3600000), m = Math.floor((diff % 3600000) / 60000), s = Math.floor((diff % 60000) / 1000);
      return `<span class="px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-bold text-xs font-mono">${h}h ${m}m ${s}s left</span>`;
    }
    const diff = new Date(`${b.end_date}T12:00:00+05:30`).getTime() - now;
    if (diff <= 0) return `<span class="px-2 py-0.5 rounded bg-rose-100 text-rose-800 font-bold text-[11px]">Due for Check-out</span>`;
    const d = Math.floor(diff / 86400000), h = Math.floor((diff % 86400000) / 3600000), m = Math.floor((diff % 3600000) / 60000);
    if (d > 0) return `<span class="px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 font-bold text-xs font-mono">${d}d ${h}h remaining</span>`;
    return `<span class="px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-bold text-xs font-mono">${h}h ${m}m left (Last 24h)</span>`;
  }
  function startLiveOccupancyTicker() {
    if (occupancyTimer) clearInterval(occupancyTimer);
    occupancyTimer = setInterval(() => {
      document.querySelectorAll("[data-live-countdown]").forEach((el) => {
        const b = (window.currentBookingsList || []).find((x) => String(x.id) === el.getAttribute("data-live-countdown"));
        if (b) el.innerHTML = calculateTimeRemaining(b);
      });
    }, 1000);
  }

  async function renderAdmin() {
    if (!adminOn()) { alert("Please log in using the Staff Authentication dialog."); window.location.hash = ""; return; }
    loadConfig();
    renderAdminRooms();
    const listC = $("adminList"), activeC = $("activeOccupancyList");
    if (listC) listC.innerHTML = "<p class='py-4 text-slate-500 text-xs'>Querying live database...</p>";
    if (activeC) activeC.innerHTML = "<p class='py-4 text-slate-500 text-xs'>Querying currently occupied rooms...</p>";

    const bookings = await loadBookings();
    const active = bookings.filter((b) => b.status === "Checked In");
    if ($("activeGuestsBadge")) $("activeGuestsBadge").textContent = active.length;

    if (!active.length) {
      if (activeC) activeC.innerHTML = `<div class="text-center py-10 bg-slate-50 rounded-xl border border-dashed border-slate-200"><i class="fa-solid fa-bed text-slate-300 text-3xl mb-2"></i><p class="text-slate-500 text-xs font-semibold">No guests currently checked into rooms.</p></div>`;
    } else if (activeC) {
      let oh = `<table class="w-full text-left text-xs border-collapse min-w-[750px]"><thead><tr class="border-b border-slate-200 uppercase font-bold text-slate-500 bg-slate-50">
        <th class="py-2.5 px-3">Room No.</th><th class="py-2.5 px-3">Guest Details</th><th class="py-2.5 px-3">Room Category</th><th class="py-2.5 px-3">Stay Basis</th><th class="py-2.5 px-3">Time Left</th><th class="py-2.5 px-3 text-right">Departure</th>
        </tr></thead><tbody class="divide-y divide-slate-100">`;
      active.forEach((b) => {
        oh += `<tr class="hover:bg-slate-50 transition">
          <td class="py-3 px-3 font-mono font-black text-xs text-emerald-950">${esc(b.room_number || "Unassigned")}</td>
          <td class="py-3 px-3"><strong class="text-slate-900">${esc(b.guest_name)}</strong><div class="text-[11px] text-slate-500">${esc(b.phone)}</div></td>
          <td class="py-3 px-3 font-medium text-slate-800">${esc(b.room_name)}</td>
          <td class="py-3 px-3"><span class="px-2 py-0.5 rounded font-bold text-[10px] ${b.booking_type === "hour" ? "bg-purple-100 text-purple-800" : "bg-blue-100 text-blue-800"}">${b.booking_type === "hour" ? `${Number(b.hours)}h Transit` : `${nightsBetween(b.start_date, b.end_date)} Night(s)`}</span></td>
          <td class="py-3 px-3" data-live-countdown="${esc(b.id)}">${calculateTimeRemaining(b)}</td>
          <td class="py-3 px-3 text-right"><button type="button" data-act="checkout" data-id="${esc(b.id)}" class="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded-lg text-xs font-bold transition shadow-sm cursor-pointer">Vacate</button></td>
        </tr>`;
      });
      activeC.innerHTML = oh + "</tbody></table>";
      startLiveOccupancyTicker();
    }

    if (!listC) return;
    if (!bookings.length) { listC.innerHTML = '<p class="text-slate-400 py-6 text-center text-xs">No reservations recorded yet.</p>'; return; }
    let h = `<table class="w-full text-left text-xs border-collapse min-w-[850px]"><thead><tr class="border-b border-slate-200 uppercase font-bold text-slate-500">
      <th class="py-2.5 px-3">ID / Room</th><th class="py-2.5 px-3">Guest Details</th><th class="py-2.5 px-3">Room Category</th><th class="py-2.5 px-3">Stay Period</th><th class="py-2.5 px-3">ID Document</th><th class="py-2.5 px-3">Billing</th><th class="py-2.5 px-3">Status</th><th class="py-2.5 px-3 text-right">Actions</th>
      </tr></thead><tbody class="divide-y divide-slate-100">`;
    const act = (cls, a, id, label) => `<button class="px-2 py-1 ${cls} text-white rounded text-[10px] font-bold cursor-pointer" data-act="${a}" data-id="${esc(id)}">${label}</button>`;
    bookings.forEach((b) => {
      const dates = b.booking_type === "hour" ? `${esc(b.start_date)} (${Number(b.hours)} hrs)` : `${esc(b.start_date)} to ${esc(b.end_date)}`;
      const stCls = b.status === "Checked In" ? "bg-blue-100 text-blue-800" : b.status === "Confirmed" ? "bg-emerald-100 text-emerald-800" : b.status === "Cancelled" ? "bg-rose-100 text-rose-800" : b.status === "Checked Out" ? "bg-slate-200 text-slate-700" : "bg-amber-100 text-amber-800";
      h += `<tr class="hover:bg-slate-50 transition">
        <td class="py-3 px-3 font-mono"><div class="font-bold text-slate-800">#${esc(b.id)}</div>${b.room_number ? `<div class="text-[10px] text-emerald-800 font-bold">Room: ${esc(b.room_number)}</div>` : ""}</td>
        <td class="py-3 px-3"><strong>${esc(b.guest_name)}</strong><br><small class="text-slate-500">${esc(b.phone)}</small></td>
        <td class="py-3 px-3 font-medium">${esc(b.room_name)}</td>
        <td class="py-3 px-3">${dates}</td>
        <td class="py-3 px-3 text-slate-600 font-mono text-[11px]">${esc(maskSensitiveRef(b.document_url))}</td>
        <td class="py-3 px-3 font-bold text-slate-900">${money(b.total)}${b.discount_pct > 0 ? `<div class="text-[10px] text-emerald-600 font-semibold">-${Number(b.discount_pct)}% off</div>` : ""}<div class="text-[10px] text-slate-500 font-normal">${esc(b.payment_mode || "")}${b.utr ? ` · UTR ${esc(b.utr)}` : ""}</div></td>
        <td class="py-3 px-3"><span class="inline-block px-2 py-0.5 rounded-full text-[11px] font-bold ${stCls}">${esc(b.status)}</span></td>
        <td class="py-3 px-3 text-right space-x-1.5 whitespace-nowrap">
          ${b.status === "Pending" ? act("bg-emerald-600 hover:bg-emerald-700", "verify", b.id, "Verify Payment") : ""}
          ${b.status === "Confirmed" || b.status === "Pending" ? act("bg-blue-600 hover:bg-blue-700", "checkin", b.id, "Check In") : ""}
          ${b.status === "Checked In" ? act("bg-rose-600 hover:bg-rose-700", "checkout", b.id, "Check Out") : ""}
          ${b.status === "Confirmed" || b.status === "Pending" ? act("bg-slate-600 hover:bg-slate-700", "cancel", b.id, "Cancel") : ""}
          <button class="px-2 py-1 bg-emerald-700 hover:bg-emerald-800 text-white rounded text-[10px] font-bold cursor-pointer inline-flex items-center gap-1" data-act="whatsapp" data-id="${esc(b.id)}"><i class="fa-brands fa-whatsapp"></i> WhatsApp</button>
        </td></tr>`;
    });
    listC.innerHTML = h + "</tbody></table>";
  }
  window.renderAdmin = renderAdmin;
  if ($("btnRefreshAdmin")) $("btnRefreshAdmin").onclick = () => renderAdmin();

  const findBooking = (id) => (window.currentBookingsList || []).find((x) => String(x.id) === String(id));
  async function patchStatus(id, body) {
    try {
      await api(`/bookings/${encodeURIComponent(id)}/status`, {
        method: "PATCH", headers: getAuthHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body),
      });
      return true;
    } catch (e) { handleAdminError(e); return false; }
  }
  function promptUtr() {
    const v = prompt("Enter the 12-digit UPI reference (UTR) from your bank SMS/app, after confirming the amount was received:");
    if (v === null) return null;
    const t = v.trim();
    if (!/^[0-9]{12}$/.test(t)) { alert("UTR must be exactly 12 digits."); return null; }
    return t;
  }
  function promptRoom() {
    const v = prompt("Enter Physical Room Number to allot (e.g. 101, 102, 204):");
    if (v === null) return null;
    const t = v.trim();
    if (!/^[A-Za-z0-9-]{1,10}$/.test(t)) { alert("Please enter a valid room number."); return null; }
    return t;
  }

  function askPayMethod() {
    const v = (prompt("How was the payment received? Type Cash, UPI or Card:") || "").trim().toLowerCase();
    const m = { cash: "Cash", upi: "UPI", card: "Card" }[v];
    if (!m) alert("Please type Cash, UPI or Card.");
    return m || null;
  }
  async function actVerify(id) {
    const b = findBooking(id); if (!b) return;
    const body = { new_status: "Confirmed" };
    if (b.payment_mode === "UPI") { const u = promptUtr(); if (!u) return; body.utr = u; }
    else { if (!confirm("Confirm that payment was received at the counter?")) return; const pm = askPayMethod(); if (!pm) return; body.pay_method = pm; }
    if (!(await patchStatus(id, body))) return;
    if (confirm("Booking approved! Send WhatsApp confirmation to guest now?")) window.sendWhatsAppConfirmationById(id);
    renderAdmin();
  }
  async function actCheckIn(id) {
    const b = findBooking(id); if (!b) return;
    const body = { new_status: "Checked In" };
    if (b.status === "Pending" && b.payment_mode === "UPI" && !b.utr) { const u = promptUtr(); if (!u) return; body.utr = u; }
    const room = promptRoom(); if (!room) return;
    body.room_number = room;
    if (b.status === "Pending" && b.payment_mode !== "UPI") { const pm = askPayMethod(); if (!pm) return; body.pay_method = pm; }
    if (!(await patchStatus(id, body))) return;
    if (confirm(`Guest checked into Room ${room}! Send WhatsApp confirmation?`)) window.sendWhatsAppConfirmationById(id);
    renderAdmin();
  }
  async function actCheckOut(id) {
    if (!confirm("Confirm guest departure and vacate room?")) return;
    if (await patchStatus(id, { new_status: "Checked Out" })) renderAdmin();
  }
  async function actCancel(id) {
    if (!confirm("Cancel this booking? This cannot be undone.")) return;
    if (await patchStatus(id, { new_status: "Cancelled" })) renderAdmin();
  }
  const ACTIONS = { verify: actVerify, checkin: actCheckIn, checkout: actCheckOut, cancel: actCancel,
    whatsapp: (id) => window.sendWhatsAppConfirmationById(id), editroom: (id) => window.editRoom(id) };
  function onAdminClick(e) {
    const el = e.target.closest("[data-act]");
    const fn = el && ACTIONS[el.getAttribute("data-act")];
    if (fn) fn(el.getAttribute("data-id"));
  }
  ["adminList", "activeOccupancyList", "adminRoomList"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("click", onAdminClick);
  });

  // ---------------- config + rooms editor ----------------
  if ($("btnSaveConfig")) {
    $("btnSaveConfig").onclick = async function () {
      const payload = {
        upi_id: $("cfgUpiId").value.trim(),
        d2: num($("cfgDisc2").value, 20), d3: num($("cfgDisc3").value, 25), d4plus: num($("cfgDisc4").value, 30),
        event_full: num($("cfgEvFull").value, 1000),
      };
      if (cachedConfig && cachedConfig.event_six != null) payload.event_six = Number(cachedConfig.event_six);
      if (cachedConfig && payload.upi_id !== cachedConfig.upi_id) {
        payload.current_password = $("cfgPass") ? $("cfgPass").value : "";
        if (!payload.current_password) return alert("Enter your admin password to change the UPI ID.");
      }
      if (!confirm(`Save these settings?\n\nCustomers will pay to: ${payload.upi_id}\n\nCheck this UPI ID carefully.`)) return;
      try {
        const d = await api("/config", { method: "POST", headers: getAuthHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(payload) });
        cachedConfig = d.config;
        if ($("cfgPass")) $("cfgPass").value = "";
        if ($("cfgSaveNotice")) $("cfgSaveNotice").textContent = "Rates & UPI Destination saved in database!";
        setTimeout(() => { if ($("cfgSaveNotice")) $("cfgSaveNotice").textContent = ""; }, 3000);
        loadConfig();
      } catch (e) { handleAdminError(e); }
    };
  }

  function renderAdminRooms() {
    const cont = $("adminRoomList");
    if (!cont) return;
    cont.innerHTML = "";
    cachedRooms.forEach((r) => {
      const card = document.createElement("div");
      card.className = "bg-slate-50 rounded-xl p-4 border border-slate-200 flex flex-col justify-between";
      card.innerHTML = `
        <div>
          <img src="${esc(sanitizeImageUrl(r.image_url))}" alt="" class="h-36 w-full object-cover rounded-lg mb-3">
          <div class="flex items-center justify-between mb-1"><h4 class="font-bold text-slate-900">${esc(r.name)}</h4><span class="text-xs font-black text-emerald-900">${money(r.price)}/nt</span></div>
          <p class="text-[11px] text-slate-500 mb-2">${esc(r.sleeps)}</p>
          <div class="text-[10px] bg-white p-2 rounded border border-slate-200 text-slate-700 space-y-0.5">
            <div>1h: ₹${Number(r.h1)} | 2h: ₹${Number(r.h2)}</div><div>3h: ₹${Number(r.h3)} | Whole Day: ₹${Number(r.hday)}</div>
          </div>
        </div>
        <div class="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-slate-200">
          <button class="px-2.5 py-1 bg-emerald-50 text-emerald-800 font-semibold text-xs rounded hover:bg-emerald-100 transition cursor-pointer" data-act="editroom" data-id="${esc(r.id)}"><i class="fa-solid fa-pen mr-1"></i> Edit Rates &amp; Details</button>
        </div>`;
      cont.appendChild(card);
    });
  }
  if ($("btnCloseRoomForm")) $("btnCloseRoomForm").onclick = () => $("roomEditDrawer").classList.add("hidden");
  if ($("btnCancelRoomForm")) $("btnCancelRoomForm").onclick = () => $("roomEditDrawer").classList.add("hidden");

  window.editRoom = function (id) {
    const r = cachedRooms.find((x) => x.id === id);
    if (!r) return;
    $("rfId").value = r.id; $("rfName").value = r.name; $("rfBasePrice").value = r.price;
    $("rfCapacity").value = r.sleeps || ""; $("rfDesc").value = r.description || "";
    $("rfH1").value = r.h1; $("rfH2").value = r.h2; $("rfH3").value = r.h3; $("rfHDay").value = r.hday;
    $("roomFormTitle").textContent = "Edit " + r.name;
    $("roomEditDrawer").classList.remove("hidden");
    $("roomEditDrawer").scrollIntoView({ behavior: "smooth" });
  };

  if ($("roomForm")) {
    $("roomForm").onsubmit = async function (e) {
      e.preventDefault();
      const payload = {
        name: $("rfName").value.trim(), price: num($("rfBasePrice").value, NaN),
        sleeps: $("rfCapacity").value.trim(), description: $("rfDesc").value.trim(),
        h1: num($("rfH1").value, NaN), h2: num($("rfH2").value, NaN), h3: num($("rfH3").value, NaN), hday: num($("rfHDay").value, NaN),
      };
      if ([payload.price, payload.h1, payload.h2, payload.h3, payload.hday].some((n) => !Number.isFinite(n))) return alert("Please enter valid prices.");
      try {
        await api(`/rooms/${encodeURIComponent($("rfId").value)}`, { method: "POST", headers: getAuthHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(payload) });
        await loadRooms();
        $("roomEditDrawer").classList.add("hidden");
        alert("Room specifications updated in database successfully!");
      } catch (err) { handleAdminError(err); }
    };
  }

  // ---------------- counter booking ----------------
  if ($("nGo")) {
    $("nGo").onclick = async function () {
      const err = $("nErr");
      const name = $("nName").value.trim();
      const phone = $("nPh").value.replace(/[^0-9]/g, "").slice(-10);
      const idNum = $("nId").value.trim();
      if (name.length < 2) { if (err) err.textContent = "Please enter guest name."; return; }
      if (phone.length !== 10) { if (err) err.textContent = "Please enter 10-digit mobile number."; return; }
      if (!/^[0-9A-Za-z]{4}$/.test(idNum)) { if (err) err.textContent = "ID proof is required: enter the last 4 characters."; return; }
      const isHour = $("nType").value === "hour";
      const cin = isHour ? $("nDate").value : $("nIn").value;
      const cout = isHour ? $("nDate").value : $("nOut").value;
      if (!cin || !cout) { if (err) err.textContent = "Please select dates."; return; }
      const room = $("nRoomNo").value.trim();
      if (!/^[A-Za-z0-9-]{1,10}$/.test(room)) { if (err) err.textContent = "Enter the room number."; return; }
      const fd = new FormData();
      fd.append("name", name); fd.append("phone", phone); fd.append("room_id", $("nRoom").value);
      fd.append("booking_type", $("nType").value); fd.append("start_date", cin); fd.append("end_date", cout);
      fd.append("hours", String(isHour ? Number($("nHrs").value) : 0)); fd.append("guests", "2");
      fd.append("id_proof", `${$("nDoc") ? $("nDoc").value : "Aadhaar"}: ${idNum}`); fd.append("room_number", room); fd.append("pay_method", $("nPay") ? $("nPay").value : "Cash");
      try {
        await api("/admin/bookings", { method: "POST", headers: getAuthHeaders(), body: fd });
        alert("Counter guest checked in successfully!");
        if ($("nName")) $("nName").value = "";
        if ($("nPh")) $("nPh").value = "";
        if ($("nId")) $("nId").value = "";
        if (err) err.textContent = "";
        renderAdmin();
      } catch (e) { if (err) err.textContent = e.message; if (e.status === 401) handleAdminError(e); }
    };
  }
  if ($("adminOut")) {
    $("adminOut").onclick = async function () { 
      try { await api("/auth/logout", { method: "POST", headers: getAuthHeaders() }); } catch (_) { /* token expires anyway */ } 
      sessionStorage.clear(); 
      window.location.hash = ""; 
      route(); 
    };
  }

  // ---------------- booking widget tabs + inputs ----------------
  if ($("tabNightly")) {
    $("tabNightly").onclick = function () {
      stayMode = "night";
      this.className = "px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-emerald-800 text-white shadow transition flex items-center gap-2 cursor-pointer";
      if ($("tabHourly")) $("tabHourly").className = "px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-700 hover:bg-slate-100 transition flex items-center gap-2 cursor-pointer";
      document.querySelectorAll(".b-night").forEach((el) => el.classList.remove("hidden"));
      document.querySelectorAll(".b-hour").forEach((el) => el.classList.add("hidden"));
      refreshLiveQuote();
    };
  }
  if ($("tabHourly")) {
    $("tabHourly").onclick = function () {
      stayMode = "hour";
      this.className = "px-4 py-2 rounded-xl text-xs sm:text-sm font-bold bg-emerald-800 text-white shadow transition flex items-center gap-2 cursor-pointer";
      if ($("tabNightly")) $("tabNightly").className = "px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-slate-700 hover:bg-slate-100 transition flex items-center gap-2 cursor-pointer";
      document.querySelectorAll(".b-night").forEach((el) => el.classList.add("hidden"));
      document.querySelectorAll(".b-hour").forEach((el) => el.classList.remove("hidden"));
      refreshLiveQuote();
    };
  }
  ["rtype", "cin", "cout", "hDuration"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("change", refreshLiveQuote);
  });
  if ($("nType")) {
    $("nType").onchange = function () {
      const isHour = this.value === "hour";
      document.querySelectorAll(".adm-gn").forEach((e) => e.classList.toggle("hidden", isHour));
      document.querySelectorAll(".adm-gh").forEach((e) => e.classList.toggle("hidden", !isHour));
    };
  }

  const todayD = new Date(), tomD = new Date(); tomD.setDate(tomD.getDate() + 1);
  const today = localISO(todayD), tomorrow = localISO(tomD);
  if ($("cin")) { $("cin").min = today; $("cin").value = today; }
  if ($("cout")) { $("cout").min = tomorrow; $("cout").value = tomorrow; }
  if ($("hDate")) { $("hDate").min = today; $("hDate").value = today; }
  if ($("nIn")) $("nIn").value = today;
  if ($("nOut")) $("nOut").value = tomorrow;
  if ($("nDate")) $("nDate").value = today;
  if ($("cin")) {
    $("cin").addEventListener("change", function () {
      if (!this.value) return;
      const d = new Date(this.value + "T00:00:00"); d.setDate(d.getDate() + 1);
      const next = localISO(d);
      if ($("cout")) {
        $("cout").min = next;
        if ($("cout").value <= this.value) $("cout").value = next;
      }
      refreshLiveQuote();
    });
  }

  // ---------------- router ----------------
  function route() {
    const site = $("site"), adminPage = $("adminPage");
    if (location.hash === "#admin") {
      if (!adminOn()) { alert("Please log in using the Staff Authentication dialog."); window.location.hash = ""; return; }
      if (site) site.style.display = "none";
      if (adminPage) {
        adminPage.style.display = "block";
        adminPage.classList.remove("hidden");
      }
      renderAdmin();
      window.scrollTo(0, 0);
    } else {
      if (site) site.style.display = "flex";
      if (adminPage) {
        adminPage.style.display = "none";
        adminPage.classList.add("hidden");
      }
      if (occupancyTimer) clearInterval(occupancyTimer);
    }
  }
  window.addEventListener("hashchange", route);

  loadConfig();
  loadRooms();
  loadGallery();
  route();
})();
