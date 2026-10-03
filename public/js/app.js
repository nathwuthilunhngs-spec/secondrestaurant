const App = (() => {
  const state = { user: null, token: localStorage.getItem("itailaew_token"), authMode: "login", menuPage: 1, polling: null, qrTable: new URLSearchParams(location.search).get("table") };
  const $ = id => document.getElementById(id);

  async function api(path, options = {}) {
    const headers = {"Content-Type":"application/json", ...(options.headers || {})};
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await fetch(path, {...options, headers});
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || data.ok === false) throw new Error(data.message || "เกิดข้อผิดพลาด");
    return data;
  }

  function toast(message) {
    const el = $("toast"); el.textContent = message; el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2800);
  }

  function go(id) {
    const protectedPages = ["home","menu","reservation","customer","admin","staff","tables","pos"];
    if (protectedPages.includes(id) && !state.user) {
      document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
      $("login")?.classList.add("active");
      refreshNav();
      toast("กรุณา Login ก่อนจึงจะเข้าเว็บไซต์ได้");
      return;
    }
    if (id === "login" && state.user) {
      id = state.user.role === "admin" ? "admin" : state.user.role === "staff" ? "staff" : "home";
    }
    if (id === "admin" && state.user?.role !== "admin") { id = "home"; toast("ไม่มีสิทธิ์เข้าถึง"); }
    if ((id === "staff" || id === "tables" || id === "pos") && !["admin","staff"].includes(state.user?.role)) { id = "home"; toast("ไม่มีสิทธิ์เข้าถึง"); }
    // Admin only sees the admin area (no customer-facing Home / Menu / Reservation)
    if (state.user?.role === "admin" && ["home","menu","reservation","customer"].includes(id)) id = "admin";
    // Staff only sees the staff area (customer pages are not for staff)
    if (state.user?.role === "staff" && ["home","menu","reservation","customer"].includes(id)) id = "staff";
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
    $(id)?.classList.add("active");
    if (id === "menu") loadMenus();
    if (id === "reservation") loadReservations();
    if (id === "customer") loadCustomer();
    if (id === "admin") loadDashboard();
    if (state.polling) { clearInterval(state.polling); state.polling = null; }
    if (id === "staff") { loadStaff(); state.polling = setInterval(loadStaff, 3000); }
    if (id === "tables") { loadTables(); state.polling = setInterval(loadTables, 3000); }
    if (id === "pos") loadPos();
    window.scrollTo({top:0,behavior:"smooth"});
  }

  function authMode(mode) {
    state.authMode = mode;
    $("name-label").classList.toggle("hidden", mode === "login");
    $("auth-title").textContent = mode === "login" ? "Welcome back" : "Create your account";
    document.querySelectorAll(".tab").forEach((x,i) => x.classList.toggle("active", (mode==="login"&&i===0)||(mode==="register"&&i===1)));
  }

  async function submitAuth(event) {
    event.preventDefault();
    try {
      const mode = state.authMode;
      const body = {email:$("auth-email").value, password:$("auth-password").value};
      if (mode === "register") body.name = $("auth-name").value;
      const data = await api(`/api/auth/${mode === "login" ? "login" : "register"}`, {method:"POST",body:JSON.stringify(body)});
      state.token = data.token; state.user = data.user; localStorage.setItem("itailaew_token", state.token);
      refreshNav(); toast(data.message);
      if (state.user.role === "admin") go("admin"); else if (state.user.role === "staff") go("staff"); else go("customer");
    } catch(e) { toast(e.message); }
  }

  function refreshNav() {
    const loggedIn = !!state.user;
    $("main-nav").classList.toggle("hidden", !loggedIn);
    $("login-nav").classList.toggle("hidden", loggedIn);
    $("logout-nav").classList.toggle("hidden", !loggedIn);
    document.querySelectorAll("#main-nav button[data-roles]").forEach(b => {
      const roles = b.dataset.roles.split(",");
      b.classList.toggle("hidden", !(loggedIn && roles.includes(state.user.role)));
    });
  }

  function logout() {
    if (state.polling) { clearInterval(state.polling); state.polling = null; }
    state.user = null; state.token = null; localStorage.removeItem("itailaew_token");
    refreshNav();
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
    $("login")?.classList.add("active");
    authMode("login");
    toast("ออกจากระบบแล้ว");
  }

  async function restore() {
    refreshNav();
    if (state.qrTable && $("qr-banner")) {
      $("qr-banner").classList.remove("hidden");
      $("qr-banner").innerHTML = `<b>🍽️ itailaew — TABLE ${escapeHtml(state.qrTable)}</b><div class="small">กำลังสั่งจากโต๊ะนี้ ออเดอร์จะส่งเข้าครัวทันที</div>`;
    }
    if (!state.token) {
      document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
      $("login")?.classList.add("active");
      authMode("login");
      return;
    }
    try {
      const data = await api("/api/me");
      state.user = data.user;
      refreshNav();
      const target = state.user.role === "admin" ? "admin" : state.user.role === "staff" ? "staff" : "home";
      document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
      $(target)?.classList.add("active");
      if (target === "admin") loadDashboard();
      if (target === "staff") { loadStaff(); if (!state.polling) state.polling = setInterval(loadStaff, 3000); }
    } catch (_) {
      logout();
    }
  }

  async function loadMenus(page = state.menuPage) {
    try {
      state.menuPage = page;
      const q = encodeURIComponent($("menu-search")?.value || "");
      const sort = $("menu-sort")?.value || "name";
      const data = await api(`/api/menus?q=${q}&sort=${sort}&page=${page}&page_size=8`);
      const grid = $("menu-grid");
      grid.innerHTML = data.items.map(m => `<article class="menu-card"><div class="menu-image">${m.image_url ? `<img src="${escapeHtml(m.image_url)}" style="width:100%;height:100%;object-fit:cover">` : (m.category==="Pizza"?"🍕":m.category==="Dessert"?"🍰":"🍝")}</div><div class="menu-body"><h3>${escapeHtml(m.name)}</h3><p>${escapeHtml(m.category)}${m.is_out_of_stock ? ' <span class="sold">หมด</span>':''}</p><span class="price">฿${Number(m.price).toFixed(2)}</span>${state.user?.role !== "admin" ? `<button class="secondary" style="float:right;padding:7px 12px" ${m.is_out_of_stock?"disabled":""} onclick="App.quickOrder('${m.id}')">+</button>`:""}</div></article>`).join("") || `<div class="list-card">ยังไม่มีเมนู</div>`;
      $("menu-pages").innerHTML = Array.from({length:data.total_pages},(_,i)=>`<button onclick="App.loadMenus(${i+1})">${i+1}</button>`).join("");
    } catch(e) { $("menu-grid").innerHTML = `<div class="list-card">${escapeHtml(e.message)}</div>`; }
  }

  async function quickOrder(menuId) {
    if (!state.user) return go("login");
    if (state.user.role !== "customer") return toast("ฟังก์ชันนี้สำหรับ Customer");
    if (!state.qrTable) return toast("กรุณาเข้าหน้าเมนูผ่าน QR ของโต๊ะ");
    try {
      const data = await api("/api/customer/orders", {method:"POST", body:JSON.stringify({
        table_id: `table_${String(state.qrTable).padStart(2,"0")}`,
        items: [{menu_id: menuId, quantity: 1, options: {}}]
      })});
      toast(`ส่งออเดอร์โต๊ะ ${state.qrTable} เข้าครัวแล้ว`);
      go("customer");
    } catch(e) { toast(e.message); }
  }

  async function reserve(event) {
    event.preventDefault();
    if (!state.user) return go("login");
    try {
      const data = await api("/api/reservations",{method:"POST",body:JSON.stringify({
        customer_name:$("res-name").value, phone:$("res-phone").value,
        table_number:$("res-table").value, datetime:$("res-date").value
      })});
      toast("จองโต๊ะสำเร็จ"); event.target.reset(); loadReservations();
    } catch(e) { toast(e.message); }
  }

  const RES_LABEL = {waiting: "รอยืนยัน", confirmed: "ยืนยันแล้ว", seated: "นั่งแล้ว", cancelled: "ยกเลิก"};
  function resLabel(k) { return RES_LABEL[k] || k; }
  function resBadge(status) { return `<span class="badge res-${escapeHtml(status)}">${escapeHtml(resLabel(status))}</span>`; }

  async function loadReservations() {
    if (!state.user || state.user.role !== "customer") return;
    try {
      const data = await api("/api/reservations");
      const list = data.reservations.slice().sort((a, b) => String(b.datetime).localeCompare(String(a.datetime)));
      $("my-reservations").innerHTML = list.map(r=>`<div class="table-row"><div><b>โต๊ะ ${escapeHtml(r.table_number)}</b><div class="small">${escapeHtml(String(r.datetime).replace("T"," "))} · ${escapeHtml(r.customer_name)}</div></div>${resBadge(r.status)}</div>`).join("") || `<p class="small">ยังไม่มีรายการ</p>`;
    } catch(e) { toast(e.message); }
  }

  async function loadCustomer() {
    if (!state.user) return;
    $("customer-name").textContent = state.user.name;
    $("customer-points").textContent = state.user.member_points || 0;
    try {
      const data = await api("/api/orders");
      $("customer-orders").innerHTML = `<h3>My Orders</h3>` + (data.orders.map(o=>`<div class="table-row"><div><b>โต๊ะ ${escapeHtml(o.table_number||"-")}</b><div class="small">${escapeHtml(o.created_at||"")}</div></div><span class="badge">${escapeHtml(o.status)}</span></div>`).join("") || `<p class="small">ยังไม่มีออเดอร์</p>`);
    } catch(e) {}
  }

  function summaryRows(rows, total) {
    return rows.map(([label, n]) => `<div style="margin:12px 0"><div class="table-row" style="border:0;padding:0"><span>${escapeHtml(label)}</span><b>${n}</b></div><div class="meter"><i style="width:${total ? Math.round(n / total * 100) : 0}%"></i></div></div>`).join("") || `<p class="small">ยังไม่มีข้อมูล</p>`;
  }

  async function loadDashboard() {
    try {
      const d = await api("/api/dashboard");
      const baht = n => `฿${Number(n || 0).toLocaleString("th-TH", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
      $("stat-today").textContent = baht(d.today_sales);
      $("stat-total").textContent = baht(d.total_sales);
      $("stat-orders").textContent = d.closed_orders;
      $("stat-avg").textContent = baht(d.avg_bill);
      $("stat-open").textContent = d.open_orders;
      $("stat-res-today").textContent = d.reservations.today;
      $("stat-res-total").textContent = d.reservations.total;
      $("stat-users").textContent = d.users.total;
      $("best-sellers").innerHTML = d.best_sellers.map((x,i)=>`<div class="table-row"><span>${i+1}. ${escapeHtml(x.name)}</span><b>${x.quantity}</b></div>`).join("") || `<p class="small">ยังไม่มีข้อมูลยอดขาย</p>`;
      const max = Math.max(...d.sales_7d.map(x => x.total), 1);
      $("sales-chart").innerHTML = d.sales_7d.map(x => `<div class="bar-col"><span class="bar-val">${x.total ? Math.round(x.total) : ""}</span><div class="bar" style="height:${Math.round(x.total / max * 100)}%"></div><span class="bar-label">${escapeHtml(x.date.slice(5))}</span></div>`).join("");
      const t = d.tables;
      $("table-summary").innerHTML = summaryRows([["ว่าง", t.available], ["มีลูกค้า", t.occupied], ["รอเช็คบิล", t.waiting_bill], ["จองแล้ว", t.reserved]], t.total);
      const rs = d.reservations.by_status;
      $("res-summary").innerHTML = summaryRows(Object.entries(rs).map(([k, v]) => [resLabel(k), v]), d.reservations.total);
      const u = d.users;
      $("user-summary").innerHTML = summaryRows([["Admin", u.admin], ["Staff", u.staff], ["Customer", u.customer]], u.total) + (u.inactive ? `<p class="small">ถูกปิดการใช้งาน ${u.inactive} บัญชี</p>` : "");
    } catch(e) { toast(e.message); }
  }

  // ---------- Staff: reservations (shared with the customer reservation system) ----------
  const staffState = { tables: [] };

  function renderStaffReservations(list) {
    const rows = list.slice().sort((a, b) => String(a.datetime).localeCompare(String(b.datetime)));
    $("staff-reservations").innerHTML = rows.map(x => {
      const acts = [];
      if (x.status === "waiting") acts.push(`<button class="secondary" onclick="App.resAction('${x.id}','confirmed')">ยืนยัน</button>`);
      if (x.status === "confirmed") acts.push(`<button class="primary" onclick="App.resAction('${x.id}','seated')">จัดเข้านั่ง</button>`);
      if (x.status === "waiting" || x.status === "confirmed") acts.push(`<button class="secondary" onclick="App.resAction('${x.id}','cancelled')">ยกเลิก</button>`);
      return `<div class="table-row" style="align-items:flex-start"><div><b>โต๊ะ ${escapeHtml(x.table_number)}</b><div class="small">${escapeHtml(String(x.datetime).replace("T", " "))} · ${escapeHtml(x.customer_name)} · ${escapeHtml(x.phone || "-")}${x.source === "staff" ? " · จองโดยพนักงาน" : ""}</div><div class="row-actions">${acts.join("")}</div></div>${resBadge(x.status)}</div>`;
    }).join("") || `<p class="small">ไม่มีคิว</p>`;
  }

  async function resAction(id, status) {
    if (status === "cancelled" && !confirm("ยกเลิกการจองนี้หรือไม่?")) return;
    try { await api(`/api/reservations/${id}`, {method: "PATCH", body: JSON.stringify({status})}); toast("อัปเดตการจองแล้ว"); loadStaff(); }
    catch(e) { toast(e.message); }
  }

  async function showStaffReserve() {
    try {
      if (!staffState.tables.length) staffState.tables = (await api("/api/tables")).tables;
    } catch(e) { return toast(e.message); }
    const tables = staffState.tables.slice().sort((a, b) => String(a.table_number).localeCompare(String(b.table_number), undefined, {numeric: true}));
    openModal(`<h2>จองโต๊ะให้ลูกค้า</h2><form onsubmit="App.saveStaffReserve(event)"><label>ชื่อลูกค้า<input id="sr-name" required></label><label>เบอร์โทร<input id="sr-phone" required></label><label>โต๊ะ<select id="sr-table">${tables.map(t => `<option value="${escapeAttr(t.table_number)}">โต๊ะ ${escapeHtml(t.table_number)}</option>`).join("")}</select></label><label>วันและเวลา<input id="sr-date" type="datetime-local" required></label><div class="actions"><button class="primary">บันทึกการจอง</button><button type="button" class="secondary" onclick="App.closeModal()">Cancel</button></div></form>`);
  }

  async function saveStaffReserve(e) {
    e.preventDefault();
    try {
      await api("/api/reservations", {method: "POST", body: JSON.stringify({customer_name: $("sr-name").value, phone: $("sr-phone").value, table_number: $("sr-table").value, datetime: $("sr-date").value})});
      closeModal(); toast("บันทึกการจองสำเร็จ"); loadStaff();
    } catch(x) { toast(x.message); }
  }

  // ---------- Staff: Counter order (order on behalf of the customer) ----------
  const pos = { menus: [], cart: {}, tables: [] };

  async function loadPos() {
    try {
      const [m, t] = await Promise.all([api("/api/menus?page=1&page_size=100"), api("/api/tables")]);
      pos.menus = m.items;
      pos.tables = t.tables.slice().sort((a, b) => String(a.table_number).localeCompare(String(b.table_number), undefined, {numeric: true}));
      const sel = $("pos-table"), keep = sel.value;
      sel.innerHTML = pos.tables.map(x => `<option value="${escapeAttr(x.id)}" ${x.status === "reserved" ? "disabled" : ""}>โต๊ะ ${escapeHtml(x.table_number)} (${escapeHtml(x.status)})</option>`).join("");
      if (keep && pos.tables.some(x => x.id === keep && x.status !== "reserved")) sel.value = keep;
      renderPos();
    } catch(e) { toast(e.message); }
  }

  function renderPos() {
    const q = ($("pos-search").value || "").trim().toLowerCase();
    $("pos-menu").innerHTML = pos.menus.filter(m => !q || String(m.name).toLowerCase().includes(q) || String(m.category).toLowerCase().includes(q))
      .map(m => `<div class="pos-item"><div><b>${escapeHtml(m.name)}</b><span class="small">${escapeHtml(m.category)} · ฿${Number(m.price).toFixed(2)}${m.is_out_of_stock ? " · หมด" : ""}</span></div><button class="secondary" ${m.is_out_of_stock ? "disabled" : ""} onclick="App.posAdd('${m.id}',1)">+</button></div>`).join("") || `<p class="small">ไม่พบเมนู</p>`;
    const ids = Object.keys(pos.cart);
    let total = 0;
    $("pos-cart").innerHTML = ids.map(id => {
      const m = pos.menus.find(x => x.id === id); if (!m) return "";
      const qty = pos.cart[id]; total += Number(m.price) * qty;
      return `<div class="table-row"><div><b>${escapeHtml(m.name)}</b><div class="small">฿${(Number(m.price) * qty).toFixed(2)}</div></div><div class="qty"><button onclick="App.posAdd('${id}',-1)">−</button><b>${qty}</b><button onclick="App.posAdd('${id}',1)">+</button></div></div>`;
    }).join("") || `<p class="small">ยังไม่ได้เลือกเมนู</p>`;
    $("pos-total").textContent = `฿${total.toFixed(2)}`;
  }

  function posAdd(id, delta) {
    const next = (pos.cart[id] || 0) + delta;
    if (next <= 0) delete pos.cart[id]; else pos.cart[id] = next;
    renderPos();
  }
  function posClear() { pos.cart = {}; renderPos(); }

  async function posSubmit() {
    const items = Object.entries(pos.cart).map(([menu_id, quantity]) => ({menu_id, quantity, options: {}}));
    if (!items.length) return toast("กรุณาเลือกเมนูก่อน");
    const table_id = $("pos-table").value;
    if (!table_id) return toast("กรุณาเลือกโต๊ะ");
    try {
      await api("/api/orders", {method: "POST", body: JSON.stringify({table_id, items})});
      toast("ส่งออเดอร์เข้าครัวแล้ว"); pos.cart = {}; loadPos();
    } catch(e) { toast(e.message); }
  }

  // ---------- Staff: checkout & receipt ----------
  let billTimer = null;

  function billRows(b) {
    const r = (l, v, bold) => `<div class="table-row" style="padding:7px 0;${bold ? "font-size:17px" : ""}"><span>${l}</span><${bold ? "b" : "span"}>฿${Number(v).toFixed(2)}</${bold ? "b" : "span"}></div>`;
    return r("ยอดรวม", b.subtotal) + (b.discount ? r("ส่วนลด", -b.discount) : "") + r("Service charge", b.service_charge) + r("VAT", b.tax) + r("ยอดสุทธิ", b.total, true);
  }

  async function showCheckout(orderId) {
    try {
      const d = await api(`/api/orders/${orderId}/bill?discount=0`);
      const o = d.order;
      const rows = (o.items || []).map(it => `<div class="table-row" style="padding:7px 0"><span>${escapeHtml(it.name)} × ${it.quantity}</span><span>฿${(Number(it.unit_price) * Number(it.quantity)).toFixed(2)}</span></div>`).join("");
      openModal(`<h2>เช็คบิล โต๊ะ ${escapeHtml(o.table_number || "-")}</h2>${rows}<label>ส่วนลด (บาท)<input id="co-discount" type="number" min="0" step="0.01" value="0" oninput="App.previewBill('${orderId}')"></label><div id="co-summary">${billRows(d.bill)}</div><div class="actions"><button class="primary" onclick="App.doCheckout('${orderId}')">ยืนยันเช็คบิล</button><button type="button" class="secondary" onclick="App.closeModal()">Cancel</button></div>`);
    } catch(e) { toast(e.message); }
  }

  function previewBill(orderId) {
    clearTimeout(billTimer);
    billTimer = setTimeout(async () => {
      try {
        const d = await api(`/api/orders/${orderId}/bill?discount=${encodeURIComponent($("co-discount").value || 0)}`);
        $("co-summary").innerHTML = billRows(d.bill);
      } catch(e) { $("co-summary").innerHTML = `<p class="small">${escapeHtml(e.message)}</p>`; }
    }, 250);
  }

  async function doCheckout(orderId) {
    try {
      const d = await api(`/api/orders/${orderId}/checkout`, {method: "PATCH", body: JSON.stringify({discount: $("co-discount").value || 0})});
      toast("เช็คบิลสำเร็จ");
      showReceipt(d.order);
      if ($("tables").classList.contains("active")) loadTables(); else loadStaff();
    } catch(e) { toast(e.message); }
  }

  function showReceipt(o) {
    const rows = (o.items || []).map(it => `<div class="table-row" style="padding:5px 0;border:0"><span>${escapeHtml(it.name)} × ${it.quantity}</span><span>฿${(Number(it.unit_price) * Number(it.quantity)).toFixed(2)}</span></div>`).join("");
    const when = o.closed_at ? new Date(o.closed_at).toLocaleString("th-TH") : "";
    openModal(`<div class="receipt"><h2 style="text-align:center;margin-bottom:0">itailaew</h2><div class="small" style="text-align:center">Italian Restaurant & Café</div><div class="small" style="text-align:center;margin:8px 0 14px">ใบเสร็จรับเงิน · โต๊ะ ${escapeHtml(o.table_number || "-")} · ${escapeHtml(when)}</div>${rows}<hr style="border:0;border-top:1px dashed var(--line)">${billRows(o)}<div class="small" style="text-align:center;margin-top:12px">ขอบคุณที่ใช้บริการ</div></div><div class="actions no-print"><button class="primary" onclick="window.print()">พิมพ์ใบเสร็จ</button><button class="secondary" onclick="App.closeModal()">ปิด</button></div>`);
  }

  // ---------- Staff: Tables page ----------
  const tableState = { tables: [], orders: [], reservations: [] };

  async function loadTables() {
    try {
      const [t, o, r] = await Promise.all([api("/api/tables"), api("/api/orders"), api("/api/reservations")]);
      tableState.tables = t.tables.slice().sort((a, b) => String(a.table_number).localeCompare(String(b.table_number), undefined, {numeric: true}));
      tableState.orders = o.orders; tableState.reservations = r.reservations;
      renderTables();
    } catch(e) { toast(e.message); }
  }

  function renderTables() {
    const { tables, orders, reservations } = tableState;
    const count = s => tables.filter(x => x.status === s).length;
    $("tables-summary").innerHTML = [["ทั้งหมด", tables.length], ["ว่าง", count("available")], ["มีลูกค้า", count("occupied")], ["รอเช็คบิล", count("waiting_bill")]]
      .map(([l, n]) => `<div><span>${l}</span><b>${n}</b></div>`).join("");
    $("tables-grid").innerHTML = tables.map(tb => {
      const order = tb.current_order_id ? orders.find(o => o.id === tb.current_order_id) : null;
      const resv = reservations.filter(r => String(r.table_number) === String(tb.table_number) && ["waiting","confirmed"].includes(r.status));
      const opts = order ? ["occupied", "waiting_bill"] : ["available", "occupied", "reserved"];
      const select = `<select onchange="App.setTableStatus('${tb.id}',this.value)">${opts.map(v => `<option value="${v}" ${tb.status === v ? "selected" : ""}>${v}</option>`).join("")}</select>`;
      const info = order
        ? `${(order.items || []).length} รายการ · รวม <b>฿${Number(order.total || 0).toFixed(2)}</b><br>เปิดเมื่อ ${escapeHtml((order.created_at || "").slice(0, 16).replace("T", " "))}`
        : `ไม่มีออเดอร์`;
      const resInfo = resv.length ? `<br>📅 จอง ${resv.length} คิว (${escapeHtml(resv.map(r => r.customer_name + " " + String(r.datetime).slice(11, 16)).join(", "))})` : "";
      const buttons = order ? `<button class="secondary" onclick="App.showMove('${tb.id}')">ย้ายโต๊ะ</button><button class="secondary" onclick="App.showMerge('${tb.id}')">รวมโต๊ะ</button><button class="secondary" onclick="App.showSplit('${tb.id}')">แยกบิล</button><button class="primary" onclick="App.showCheckout('${order.id}')">เช็คบิล</button>` : "";
      return `<div class="table-card"><div class="top"><h3>โต๊ะ ${escapeHtml(tb.table_number)}</h3><span class="badge ${escapeHtml(tb.status)}">${escapeHtml(tb.status)}</span></div><div class="info">${info}${resInfo}</div>${select}<div class="actions">${buttons}</div></div>`;
    }).join("") || `<div class="list-card">ยังไม่มีโต๊ะ</div>`;
  }

  async function setTableStatus(id, status) {
    try { await api(`/api/tables/${id}`, {method: "PATCH", body: JSON.stringify({status})}); toast("อัปเดตสถานะโต๊ะแล้ว"); loadTables(); }
    catch(e) { toast(e.message); loadTables(); }
  }

  function openModal(html) { $("modal").classList.remove("hidden"); $("modal").innerHTML = `<div>${html}</div>`; }
  function tableOptions(list) { return list.map(t => `<option value="${escapeAttr(t.id)}">โต๊ะ ${escapeHtml(t.table_number)}</option>`).join(""); }
  function tableById(id) { return tableState.tables.find(t => t.id === id); }

  function showMove(id) {
    const free = tableState.tables.filter(t => t.status === "available");
    if (!free.length) return toast("ไม่มีโต๊ะว่างให้ย้าย");
    openModal(`<h2>ย้ายโต๊ะ ${escapeHtml(tableById(id).table_number)}</h2><form onsubmit="App.doMove(event,'${id}')"><label>ย้ายไปโต๊ะ<select id="mv-to">${tableOptions(free)}</select></label><div class="actions"><button class="primary">ย้ายโต๊ะ</button><button type="button" class="secondary" onclick="App.closeModal()">Cancel</button></div></form>`);
  }
  async function doMove(e, id) {
    e.preventDefault();
    try { await api("/api/tables/move", {method: "POST", body: JSON.stringify({old_table_id: id, new_table_id: $("mv-to").value})}); closeModal(); toast("ย้ายโต๊ะสำเร็จ"); loadTables(); }
    catch(x) { toast(x.message); }
  }

  function showMerge(id) {
    const others = tableState.tables.filter(t => t.id !== id && t.current_order_id);
    if (!others.length) return toast("ไม่มีโต๊ะอื่นที่มีออเดอร์ให้รวม");
    openModal(`<h2>รวมโต๊ะ ${escapeHtml(tableById(id).table_number)} เข้ากับ</h2><form onsubmit="App.doMerge(event,'${id}')"><label>โต๊ะปลายทาง (บิลจะไปรวมที่โต๊ะนี้)<select id="mg-to">${tableOptions(others)}</select></label><div class="actions"><button class="primary">รวมโต๊ะ</button><button type="button" class="secondary" onclick="App.closeModal()">Cancel</button></div></form>`);
  }
  async function doMerge(e, id) {
    e.preventDefault();
    try { await api("/api/tables/merge", {method: "POST", body: JSON.stringify({source_table_id: id, target_table_id: $("mg-to").value})}); closeModal(); toast("รวมโต๊ะสำเร็จ"); loadTables(); }
    catch(x) { toast(x.message); }
  }

  function showSplit(id) {
    const tb = tableById(id);
    const order = tableState.orders.find(o => o.id === tb.current_order_id);
    const free = tableState.tables.filter(t => t.status === "available");
    if (!order || !(order.items || []).length) return toast("ไม่พบรายการในออเดอร์");
    if (!free.length) return toast("ไม่มีโต๊ะว่างสำหรับบิลที่แยก");
    const rows = order.items.map((it, i) => `<label style="display:flex;gap:10px;align-items:center;margin:8px 0"><input type="checkbox" class="sp-item" value="${i}" style="width:auto;margin:0"> ${escapeHtml(it.name)} × ${it.quantity} <span class="small">฿${(Number(it.unit_price) * Number(it.quantity)).toFixed(2)}</span></label>`).join("");
    openModal(`<h2>แยกบิล โต๊ะ ${escapeHtml(tb.table_number)}</h2><form onsubmit="App.doSplit(event,'${order.id}')">${rows}<label>ย้ายรายการที่เลือกไปโต๊ะ<select id="sp-to">${tableOptions(free)}</select></label><div class="actions"><button class="primary">แยกบิล</button><button type="button" class="secondary" onclick="App.closeModal()">Cancel</button></div></form>`);
  }
  async function doSplit(e, orderId) {
    e.preventDefault();
    const picked = [...document.querySelectorAll(".sp-item:checked")].map(x => Number(x.value));
    if (!picked.length) return toast("กรุณาเลือกรายการที่ต้องการแยก");
    const order = tableState.orders.find(o => o.id === orderId);
    if (order && picked.length >= (order.items || []).length) return toast("เลือกได้ไม่เกินจำนวนรายการ เพื่อให้เหลือรายการอย่างน้อย 1 อย่างในบิลเดิม");
    try { await api("/api/orders/split", {method: "POST", body: JSON.stringify({order_id: orderId, item_indexes: picked, new_table_id: $("sp-to").value})}); closeModal(); toast("แยกบิลสำเร็จ"); loadTables(); }
    catch(x) { toast(x.message); }
  }

  async function loadStaff() {
    try {
      const [t,k,r,o] = await Promise.all([api("/api/tables"),api("/api/kitchen"),api("/api/reservations"),api("/api/orders")]);
      $("tables-list").innerHTML = t.tables.map(x=>`<div class="table-row"><div><b>โต๊ะ ${escapeHtml(x.table_number)}</b></div><span class="badge ${x.status}">${escapeHtml(x.status)}</span></div>`).join("");
      $("kitchen-list").innerHTML = k.items.map(x=>`<div class="table-row"><div><b>${escapeHtml(x.menu_name)}</b><div class="small">โต๊ะ ${escapeHtml(x.table_number)} × ${x.quantity}</div></div><select onchange="App.updateKitchen('${x.id}',this.value)"><option ${x.status==="pending"?"selected":""}>pending</option><option ${x.status==="cooking"?"selected":""}>cooking</option><option ${x.status==="done"?"selected":""}>done</option></select></div>`).join("") || `<p class="small">ยังไม่มีออเดอร์เข้าครัว</p>`;
      staffState.tables = t.tables; renderStaffReservations(r.reservations);
      $("staff-orders").innerHTML = o.orders.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).map(x => {
        const open = !["closed", "merged"].includes(x.status);
        return `<div class="table-row"><div><b>โต๊ะ ${escapeHtml(x.table_number||"-")}</b><div class="small">Total ฿${Number(x.total||0).toFixed(2)}</div>${open ? `<div class="row-actions"><button class="primary" onclick="App.showCheckout('${x.id}')">เช็คบิล</button></div>` : ""}</div><span class="badge">${escapeHtml(x.status)}</span></div>`;
      }).join("") || `<p class="small">ไม่มีออเดอร์</p>`;
    } catch(e) { toast(e.message); }
  }

  async function updateKitchen(id,status) {
    try { await api(`/api/kitchen/${id}`,{method:"PATCH",body:JSON.stringify({status})}); toast("อัปเดตครัวแล้ว"); }
    catch(e){toast(e.message)}
  }

  async function adminPage(type) {
    const c=$("admin-content");
    if(type==="menus") {
      try {
        const data=await api("/api/menus?page=1&page_size=100");
        c.innerHTML=`<div class="list-card"><div class="section-head" style="margin:0 0 15px"><h3>Menu Management</h3><button class="primary" onclick="App.showMenuForm()">+ Add Menu</button></div><table><tr><th>Menu</th><th>Category</th><th>Price</th><th>Status</th><th></th></tr>${data.items.map(m=>`<tr><td>${escapeHtml(m.name)}</td><td>${escapeHtml(m.category)}</td><td>฿${Number(m.price).toFixed(2)}</td><td>${m.is_out_of_stock?"หมด":"พร้อมขาย"}</td><td><button class="secondary" onclick='App.showMenuForm(${JSON.stringify(m)})'>Edit</button><button class="secondary" onclick="App.deleteMenu('${m.id}')">Delete</button></td></tr>`).join("")}</table></div>`;
      }catch(e){toast(e.message)}
    }
    if(type==="users") {
      try {
        const d=await api("/api/users");
        c.innerHTML=`<div class="list-card"><div class="section-head" style="margin:0 0 15px"><h3>User Management</h3><button class="primary" onclick="App.showStaffForm()">+ Add Staff</button></div><table><tr><th>Name</th><th>Email</th><th>Role</th><th>Active</th><th></th></tr>${d.users.map(u=>`<tr><td>${escapeHtml(u.name)}</td><td>${escapeHtml(u.email)}</td><td>${escapeHtml(u.role)}</td><td>${u.active?"Yes":"No"}</td><td>${u.role!=="admin"?`<button class="secondary" onclick="App.toggleUser('${u.id}',${!u.active})">${u.active?"Disable":"Enable"}</button>`:""}</td></tr>`).join("")}</table></div>`;
      }catch(e){toast(e.message)}
    }
    if(type==="logs") {
      try {
        const d=await api("/api/audit-logs");
        c.innerHTML=`<div class="list-card"><h3>Audit Logs</h3><table><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>Detail</th></tr>${d.logs.map(l=>`<tr><td>${escapeHtml(l.timestamp)}</td><td>${escapeHtml(l.user_name)}</td><td>${escapeHtml(l.action)}</td><td>${escapeHtml(l.target_type)} / ${escapeHtml(l.target_id)}</td><td>${escapeHtml(l.detail)}</td></tr>`).join("")}</table></div>`;
      }catch(e){toast(e.message)}
    }
  }

  function showMenuForm(menu={}) {
    $("modal").classList.remove("hidden");
    $("modal").innerHTML=`<div><h2>${menu.id?"Edit":"Add"} Menu</h2><form onsubmit="App.saveMenu(event,'${menu.id||""}')"><label>ชื่อเมนู<input id="mf-name" value="${escapeAttr(menu.name||"")}" required></label><label>หมวดหมู่<input id="mf-category" value="${escapeAttr(menu.category||"Pasta")}" required></label><label>ราคา<input id="mf-price" type="number" min="0" step="0.01" value="${menu.price||""}" required></label><label>Image URL<input id="mf-image" value="${escapeAttr(menu.image_url||"")}" placeholder="https://..."></label><label><input id="mf-stock" type="checkbox" ${menu.is_out_of_stock?"checked":""}> สินค้าหมด</label><div class="actions"><button class="primary">Save</button><button type="button" class="secondary" onclick="App.closeModal()">Cancel</button></div></form></div>`;
  }

  async function saveMenu(e,id){e.preventDefault();try{const body={name:$("mf-name").value,category:$("mf-category").value,price:$("mf-price").value,image_url:$("mf-image").value,is_out_of_stock:$("mf-stock").checked};await api(id?`/api/menus/${id}`:"/api/menus",{method:id?"PATCH":"POST",body:JSON.stringify(body)});closeModal();toast("บันทึกเมนูสำเร็จ");adminPage("menus")}catch(x){toast(x.message)}}
  async function deleteMenu(id){if(!confirm("ลบเมนูนี้หรือไม่?"))return;try{await api(`/api/menus/${id}`,{method:"DELETE"});toast("ลบเมนูสำเร็จ");adminPage("menus")}catch(e){toast(e.message)}}
  function showStaffForm(){$("modal").classList.remove("hidden");$("modal").innerHTML=`<div><h2>Add Staff</h2><form onsubmit="App.saveStaff(event)"><label>ชื่อ<input id="sf-name" required></label><label>Email<input id="sf-email" type="email" required></label><label>Password<input id="sf-pass" type="password" minlength="6" required></label><div class="actions"><button class="primary">Create Staff</button><button type="button" class="secondary" onclick="App.closeModal()">Cancel</button></div></form></div>`}
  async function saveStaff(e){e.preventDefault();try{await api("/api/users/staff",{method:"POST",body:JSON.stringify({name:$("sf-name").value,email:$("sf-email").value,password:$("sf-pass").value})});closeModal();toast("เพิ่ม Staff สำเร็จ");adminPage("users")}catch(x){toast(x.message)}}
  async function toggleUser(id,active){try{await api(`/api/users/${id}`,{method:"PATCH",body:JSON.stringify({active})});toast("อัปเดตผู้ใช้แล้ว");adminPage("users")}catch(e){toast(e.message)}}
  function closeModal(){$("modal").classList.add("hidden");$("modal").innerHTML=""}
  function escapeHtml(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
  function escapeAttr(v){return escapeHtml(v)}

  restore();
  return {go,authMode,submitAuth,logout,loadMenus,reserve,loadReservations,loadCustomer,loadDashboard,loadStaff,loadTables,showCheckout,previewBill,doCheckout,resAction,showStaffReserve,saveStaffReserve,loadPos,renderPos,posAdd,posClear,posSubmit,setTableStatus,showMove,doMove,showMerge,doMerge,showSplit,doSplit,updateKitchen,adminPage,showMenuForm,saveMenu,deleteMenu,showStaffForm,saveStaff,toggleUser,closeModal,quickOrder};
})();