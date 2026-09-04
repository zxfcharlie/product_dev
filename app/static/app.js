let SCHEMAS = {};
let CURRENT_TABLE = null;
let CURRENT_FILTERS = [];
let CURRENT_SORTS = [];
let VIEWS = [];
let ACTIVE_VIEW_ID = null; // null = 默认 Grid
let RECORDS = [];
let USER_ADMIN_MODE = false;
let DASHBOARD_MODE = false;
let DASHBOARD_TIMER = null;
let DASHBOARD_CHARTS = {};
const DASHBOARD_REFRESH_MS = 30000; // 每30秒自动刷新一次，做到“实时更新”
const STATUS_COLS = ["待制作", "制作中", "已完成"];

const OP_LABELS = {
  eq: "等于", neq: "不等于", contains: "包含", gt: ">", gte: ">=",
  lt: "<", lte: "<=", is_true: "为是", is_false: "为否", in_multiselect: "包含标签",
};

const TYPE_OPS = {
  text: ["contains", "eq", "neq"],
  long_text: ["contains"],
  number: ["eq", "neq", "gt", "gte", "lt", "lte"],
  url: ["contains"],
  select: ["eq", "neq"],
  multiselect: ["in_multiselect"],
  rating: ["eq", "gte", "lte"],
  date: ["eq", "gt", "gte", "lt", "lte"],
  checkbox: ["is_true", "is_false"],
  user: ["contains"],
};

function badgeColor(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 60%, 88%)`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("未登录"); }
  if (!res.ok) {
    const j = await res.json().catch(() => ({ detail: "请求失败" }));
    alert(j.detail || "请求失败");
    throw new Error(j.detail);
  }
  return res.json();
}

async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
}

async function refreshSchemas() {
  SCHEMAS = await api("/api/tables/schemas");
}

async function init() {
  document.getElementById("user-name").textContent =
    window.CURRENT_USER.display_name + (window.CURRENT_USER.role === "admin" ? "（管理员）" : "");
  await refreshSchemas();
  const tableKeys = Object.keys(SCHEMAS).sort((a, b) => SCHEMAS[a].order - SCHEMAS[b].order);
  renderSidebar(tableKeys);
  if (tableKeys.length) selectTable(tableKeys[0]);
}

function renderSidebar(tableKeys) {
  const el = document.getElementById("table-list");
  el.innerHTML = "";
  const groups = [
    { key: "business", label: "业务表" },
    { key: "config", label: "配置表（管理员）" },
    { key: "archive", label: "历史归档（只读）" },
  ];
  groups.forEach((g) => {
    const keysInGroup = tableKeys.filter((k) => (SCHEMAS[k].group || "business") === g.key);
    if (!keysInGroup.length) return;
    const header = document.createElement("div");
    header.className = "sidebar-group-label";
    header.textContent = g.label;
    el.appendChild(header);
    keysInGroup.forEach((key) => {
      const div = document.createElement("div");
      div.className = "table-item" + (key === CURRENT_TABLE ? " active" : "");
      div.textContent = SCHEMAS[key].label;
      div.onclick = () => selectTable(key);
      div.dataset.key = key;
      el.appendChild(div);
    });
  });

  if (window.CURRENT_USER.role === "admin") {
    const header = document.createElement("div");
    header.className = "sidebar-group-label";
    header.textContent = "系统管理";
    el.appendChild(header);
    const item = document.createElement("div");
    item.className = "table-item" + (USER_ADMIN_MODE ? " active" : "");
    item.textContent = "👤 用户管理";
    item.onclick = () => selectUserAdmin();
    item.dataset.key = "__user_admin__";
    el.appendChild(item);
  }

  const dashHeader = document.createElement("div");
  dashHeader.className = "sidebar-group-label";
  dashHeader.textContent = "仪表盘";
  el.appendChild(dashHeader);
  const dashItem = document.createElement("div");
  dashItem.className = "table-item" + (DASHBOARD_MODE ? " active" : "");
  dashItem.textContent = "📊 每日任务进度仪表盘";
  dashItem.onclick = () => selectDashboard();
  dashItem.dataset.key = "__dashboard__";
  el.appendChild(dashItem);
}

function resetViewMode() {
  if (DASHBOARD_TIMER) { clearInterval(DASHBOARD_TIMER); DASHBOARD_TIMER = null; }
  USER_ADMIN_MODE = false;
  DASHBOARD_MODE = false;
  document.getElementById("grid-wrap").classList.remove("hidden");
  document.getElementById("dashboard-view").classList.add("hidden");
  document.querySelector(".toolbar").style.display = "flex";
}

async function selectTable(key) {
  resetViewMode();
  CURRENT_TABLE = key;
  CURRENT_FILTERS = [];
  CURRENT_SORTS = [];
  ACTIVE_VIEW_ID = null;
  document.querySelectorAll(".table-item").forEach((d) => {
    d.classList.toggle("active", d.dataset.key === key);
  });
  const isArchive = SCHEMAS[key].group === "archive";
  const addBtn = document.getElementById("add-record-btn");
  if (addBtn) addBtn.style.display = isArchive ? "none" : "";
  await loadViews();
  renderViewTabs();
  await loadRecords();
}

async function loadViews() {
  VIEWS = await api(`/api/tables/${CURRENT_TABLE}/views`);
}

function renderViewTabs() {
  const el = document.getElementById("view-tabs");
  el.innerHTML = "";
  const gridTab = document.createElement("div");
  gridTab.className = "view-tab" + (ACTIVE_VIEW_ID === null ? " active" : "");
  gridTab.textContent = "Grid（全部）";
  gridTab.onclick = () => switchView(null);
  el.appendChild(gridTab);
  VIEWS.forEach((v) => {
    const tab = document.createElement("div");
    tab.className = "view-tab" + (ACTIVE_VIEW_ID === v.id ? " active" : "");
    tab.textContent = (v.is_shared ? "" : "🔒 ") + v.name;
    tab.title = v.is_shared ? "团队共享视图" : "仅自己可见的私有视图";
    tab.onclick = () => switchView(v.id);
    tab.oncontextmenu = (e) => {
      e.preventDefault();
      if (confirm(`删除视图「${v.name}」？`)) deleteView(v.id);
    };
    el.appendChild(tab);
  });
}

async function switchView(viewId) {
  ACTIVE_VIEW_ID = viewId;
  if (viewId === null) {
    CURRENT_FILTERS = [];
    CURRENT_SORTS = [];
  } else {
    const v = VIEWS.find((x) => x.id === viewId);
    CURRENT_FILTERS = v.filters || [];
    CURRENT_SORTS = v.sorts || [];
  }
  renderViewTabs();
  await loadRecords();
}

async function deleteView(viewId) {
  await api(`/api/tables/${CURRENT_TABLE}/views/${viewId}`, { method: "DELETE" });
  await loadViews();
  if (ACTIVE_VIEW_ID === viewId) await switchView(null);
  else renderViewTabs();
}

async function loadRecords() {
  RECORDS = await api(`/api/tables/${CURRENT_TABLE}/query`, {
    method: "POST",
    body: JSON.stringify({ filters: CURRENT_FILTERS, sorts: CURRENT_SORTS }),
  });
  updateFilterSummary();
  renderTable();
}

function updateFilterSummary() {
  const parts = [];
  if (CURRENT_FILTERS.length) parts.push(`${CURRENT_FILTERS.length} 个筛选条件`);
  if (CURRENT_SORTS.length) parts.push(`${CURRENT_SORTS.length} 个排序条件`);
  document.getElementById("filter-summary").textContent =
    parts.length ? `(${parts.join("，")}) 共 ${RECORDS.length} 条` : `共 ${RECORDS.length} 条`;
}

// ---------------- 表格渲染 + 点击单元格内联编辑 ----------------

function renderTable() {
  const schema = SCHEMAS[CURRENT_TABLE];
  const isArchive = schema.group === "archive";
  const head = document.getElementById("grid-head");
  const body = document.getElementById("grid-body");
  head.innerHTML = "";
  body.innerHTML = "";

  const tr = document.createElement("tr");
  tr.innerHTML = "<th class='col-idx'>#</th>";
  schema.fields.forEach((f) => {
    tr.innerHTML += `<th>${f.label}</th>`;
  });
  tr.innerHTML += "<th class='col-actions'>操作</th>";
  head.appendChild(tr);

  RECORDS.forEach((rec, idx) => {
    const row = document.createElement("tr");
    let html = `<td class="col-idx">${idx + 1}</td>`;
    schema.fields.forEach((f) => {
      html += renderCellTd(f, rec, isArchive);
    });
    html += isArchive
      ? `<td class="col-actions dash-empty">只读</td>`
      : `<td class="col-actions"><a href="#" onclick="removeRecord(${rec.id}); return false;">删除</a></td>`;
    row.innerHTML = html;
    body.appendChild(row);
  });
}

function renderCellTd(field, rec, isArchive) {
  const value = rec.data[field.key];
  if (isArchive) {
    return `<td>${renderStaticCell(field, value)}</td>`;
  }
  if (field.type === "checkbox") {
    const checked = value === true || value === "true";
    if (field.auto) return `<td>${checked ? "✅" : ""}</td>`;
    return `<td><input type="checkbox" ${checked ? "checked" : ""}
      onchange="saveCellValue(${rec.id}, '${field.key}', this.checked)"></td>`;
  }
  if (field.type === "rating") {
    const n = parseInt(value) || 0;
    let stars = "";
    for (let i = 1; i <= 5; i++) {
      const filled = i <= n;
      stars += field.auto
        ? `<span class="${filled ? "" : "star-empty"}">${filled ? "★" : "☆"}</span>`
        : `<span class="star-cell" onclick="saveCellValue(${rec.id}, '${field.key}', ${i})">${filled ? "★" : "☆"}</span>`;
    }
    return `<td>${stars}</td>`;
  }
  if (field.auto) {
    return `<td>${renderStaticCell(field, value)}</td>`;
  }
  return `<td class="editable-cell" onclick="activateCell(${rec.id}, '${field.key}', this)">${renderStaticCell(field, value)}</td>`;
}

function renderStaticCell(field, value) {
  if (value === undefined || value === null || value === "") return "";
  switch (field.type) {
    case "url":
      return `<a href="${escapeHtml(value)}" target="_blank" class="cell-link cell-clip"
        title="${escapeHtml(value)}" onclick="event.stopPropagation()">${escapeHtml(value)}</a>`;
    case "select":
      return `<span class="badge" style="background:${badgeColor(value)}">${escapeHtml(value)}</span>`;
    case "multiselect":
      return (Array.isArray(value) ? value : []).map(
        (v) => `<span class="badge" style="background:${badgeColor(v)}">${escapeHtml(v)}</span>`
      ).join(" ");
    default: {
      const text = escapeHtml(String(value));
      return `<span class="cell-clip" title="${text}">${text}</span>`;
    }
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function activateCell(recordId, fieldKey, tdEl) {
  if (tdEl.classList.contains("editing")) return;
  const schema = SCHEMAS[CURRENT_TABLE];
  const field = schema.fields.find((f) => f.key === fieldKey);
  if (!field || field.auto) return;

  // 关键：必须在任何 await 之前就标记“正在编辑”，否则用户连续点击/双击同一个格子时，
  // 会在 refreshSchemas() 这个异步等待期间并发触发第二次编辑会话，产生两个互相不知道
  // 对方存在的 <select>——用户实际操作的那个正确保存了，另一个没人碰过的“幽灵”下拉框
  // 之后自己失焦，会把它自己那份没被改过的旧值又保存一次，把刚保存对的值覆盖回去。
  tdEl.classList.add("editing");

  // select / multiselect 的可选项可能来自配置表，进编辑前刷新一次，保证选项是最新的
  if (field.type === "select" || field.type === "multiselect") {
    try {
      await refreshSchemas();
    } catch (e) {
      // 刷新选项失败也不阻塞这次编辑，用现有的 SCHEMAS 兜底
    }
  }
  const freshField = SCHEMAS[CURRENT_TABLE].fields.find((f) => f.key === fieldKey) || field;
  const rec = RECORDS.find((r) => r.id === recordId);
  if (!rec) { tdEl.classList.remove("editing"); return; }
  const value = rec.data[fieldKey];

  tdEl.innerHTML = "";
  let input;

  if (freshField.type === "select") {
    input = document.createElement("select");
    input.innerHTML = `<option value="">-- 未设置 --</option>` +
      (freshField.options || []).map((o) => `<option value="${o}" ${o === value ? "selected" : ""}>${o}</option>`).join("");
    input.onchange = () => input.blur();
    input.onblur = () => finishCellEdit(recordId, fieldKey, tdEl, input.value);
  } else if (freshField.type === "multiselect") {
    input = document.createElement("select");
    input.multiple = true;
    input.size = Math.min(6, Math.max(3, (freshField.options || []).length));
    const selected = Array.isArray(value) ? value : [];
    input.innerHTML = (freshField.options || []).map(
      (o) => `<option value="${o}" ${selected.includes(o) ? "selected" : ""}>${o}</option>`
    ).join("");
    input.onblur = () => {
      const vals = [...input.selectedOptions].map((o) => o.value);
      finishCellEdit(recordId, fieldKey, tdEl, vals);
    };
  } else if (freshField.type === "long_text") {
    input = document.createElement("textarea");
    input.value = value || "";
    input.onblur = () => finishCellEdit(recordId, fieldKey, tdEl, input.value);
    input.onkeydown = (e) => { if (e.key === "Escape") { tdEl.classList.remove("editing"); renderTable(); } };
  } else if (freshField.type === "number") {
    input = document.createElement("input");
    input.type = "number";
    input.value = value ?? "";
    input.onblur = () => finishCellEdit(recordId, fieldKey, tdEl, input.value);
    input.onkeydown = (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") { tdEl.classList.remove("editing"); renderTable(); }
    };
  } else if (freshField.type === "date") {
    input = document.createElement("input");
    input.type = "date";
    input.value = value || "";
    input.onblur = () => finishCellEdit(recordId, fieldKey, tdEl, input.value);
    input.onchange = () => input.blur();
  } else {
    input = document.createElement("input");
    input.type = "text";
    input.value = value || "";
    input.onblur = () => finishCellEdit(recordId, fieldKey, tdEl, input.value);
    input.onkeydown = (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") { tdEl.classList.remove("editing"); renderTable(); }
    };
  }
  input.className = "cell-input";
  tdEl.appendChild(input);
  input.focus();
  if (input.select) input.select();
}

async function finishCellEdit(recordId, fieldKey, tdEl, newValue) {
  tdEl.classList.remove("editing");
  await saveCellValue(recordId, fieldKey, newValue);
}

async function saveCellValue(recordId, fieldKey, value) {
  await api(`/api/tables/${CURRENT_TABLE}/records/${recordId}`, {
    method: "PUT", body: JSON.stringify({ data: { [fieldKey]: value } }),
  });
  await loadRecords();
}

async function removeRecord(id) {
  if (!confirm("确定删除这条记录吗？")) return;
  await api(`/api/tables/${CURRENT_TABLE}/records/${id}`, { method: "DELETE" });
  await loadRecords();
}

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

// ---------------- 添加记录（新建走弹窗，编辑走点单元格） ----------------

async function openRecordModal() {
  await refreshSchemas();
  const schema = SCHEMAS[CURRENT_TABLE];
  const form = document.getElementById("record-form");
  form.innerHTML = "";
  schema.fields.forEach((f) => {
    if (f.auto) return;          // 完全自动生成的字段，新建时不出现
    if (f.auto_on_create) return; // 由自动化规则分配的字段，新建时不出现，建完后可点单元格改
    form.appendChild(buildFieldInput(f, undefined));
  });
  document.getElementById("record-modal").classList.remove("hidden");
}

function buildFieldInput(f, value) {
  const wrap = document.createElement("div");
  wrap.className = "form-row";
  const label = document.createElement("label");
  label.textContent = f.label;
  wrap.appendChild(label);

  let input;
  if (f.type === "long_text") {
    input = document.createElement("textarea");
    input.value = value || "";
  } else if (f.type === "select") {
    input = document.createElement("select");
    input.innerHTML = `<option value="">-- 未设置 --</option>` +
      (f.options || []).map((o) => `<option value="${o}" ${o === value ? "selected" : ""}>${o}</option>`).join("");
  } else if (f.type === "multiselect") {
    input = document.createElement("div");
    input.className = "checkbox-group";
    const selected = Array.isArray(value) ? value : [];
    (f.options || []).forEach((o) => {
      input.innerHTML += `<label class="checkbox-item">
        <input type="checkbox" value="${o}" ${selected.includes(o) ? "checked" : ""}> ${o}
      </label>`;
    });
  } else if (f.type === "rating") {
    input = document.createElement("div");
    input.className = "star-picker";
    input.dataset.value = value || 0;
    renderStarPicker(input);
  } else if (f.type === "checkbox") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = value === true || value === "true";
  } else if (f.type === "number") {
    input = document.createElement("input");
    input.type = "number";
    input.value = value ?? "";
  } else if (f.type === "date") {
    input = document.createElement("input");
    input.type = "date";
    input.value = value || "";
  } else {
    input = document.createElement("input");
    input.type = "text";
    input.value = value || "";
  }
  input.dataset.fieldKey = f.key;
  input.dataset.fieldType = f.type;
  wrap.appendChild(input);
  return wrap;
}

function renderStarPicker(container) {
  const val = parseInt(container.dataset.value) || 0;
  container.innerHTML = "";
  for (let i = 1; i <= 5; i++) {
    const s = document.createElement("span");
    s.textContent = i <= val ? "★" : "☆";
    s.className = "star-pick";
    s.onclick = () => { container.dataset.value = i; renderStarPicker(container); };
    container.appendChild(s);
  }
}

function collectFormData() {
  const form = document.getElementById("record-form");
  const data = {};
  form.querySelectorAll(".form-row").forEach((row) => {
    const checkboxGroup = row.querySelector(".checkbox-group");
    const starPicker = row.querySelector(".star-picker");
    if (checkboxGroup) {
      const values = [...checkboxGroup.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.value);
      data[checkboxGroup.dataset.fieldKey] = values;
    } else if (starPicker) {
      data[starPicker.dataset.fieldKey] = parseInt(starPicker.dataset.value) || 0;
    } else {
      const input = row.querySelector("[data-field-key]");
      if (!input) return;
      if (input.type === "checkbox") data[input.dataset.fieldKey] = input.checked;
      else data[input.dataset.fieldKey] = input.value;
    }
  });
  return data;
}

async function submitRecord() {
  const data = collectFormData();
  await api(`/api/tables/${CURRENT_TABLE}/records`, {
    method: "POST", body: JSON.stringify({ data }),
  });
  closeModal("record-modal");
  await loadRecords();
}

// ---------------- 筛选 / 排序 ----------------

function openFilterModal() {
  renderFilterRows();
  renderSortRows();
  document.getElementById("filter-modal").classList.remove("hidden");
}

function renderFilterRows() {
  const el = document.getElementById("filter-rows");
  el.innerHTML = "";
  CURRENT_FILTERS.forEach((f, i) => el.appendChild(buildFilterRow(f, i)));
}

function buildFilterRow(f, i) {
  const schema = SCHEMAS[CURRENT_TABLE];
  const row = document.createElement("div");
  row.className = "filter-row";
  const fieldSelect = document.createElement("select");
  fieldSelect.innerHTML = schema.fields.map(
    (fl) => `<option value="${fl.key}" ${fl.key === f.field ? "selected" : ""}>${fl.label}</option>`
  ).join("");
  const opSelect = document.createElement("select");
  const valueInput = document.createElement("input");
  valueInput.value = f.value || "";
  valueInput.placeholder = "值";

  const quickToday = document.createElement("button");
  quickToday.type = "button";
  quickToday.className = "btn btn-sm";
  quickToday.textContent = "今天";
  quickToday.onclick = () => { valueInput.value = "今天"; };

  const quickYesterday = document.createElement("button");
  quickYesterday.type = "button";
  quickYesterday.className = "btn btn-sm";
  quickYesterday.textContent = "昨天";
  quickYesterday.onclick = () => { valueInput.value = "昨天"; };

  function refreshOps() {
    const type = schema.fields.find((fl) => fl.key === fieldSelect.value)?.type || "text";
    const ops = TYPE_OPS[type] || ["eq"];
    opSelect.innerHTML = ops.map((o) => `<option value="${o}">${OP_LABELS[o]}</option>`).join("");
    if (f.op) opSelect.value = f.op;
    const showQuickDate = type === "date";
    quickToday.style.display = showQuickDate ? "" : "none";
    quickYesterday.style.display = showQuickDate ? "" : "none";
  }
  fieldSelect.onchange = refreshOps;
  refreshOps();

  const del = document.createElement("a");
  del.href = "#"; del.textContent = "✕"; del.className = "row-del";
  del.onclick = (e) => { e.preventDefault(); CURRENT_FILTERS.splice(i, 1); renderFilterRows(); };

  row.append(fieldSelect, opSelect, valueInput, quickToday, quickYesterday, del);
  row.dataset.index = i;
  fieldSelect.dataset.role = "field"; opSelect.dataset.role = "op"; valueInput.dataset.role = "value";
  return row;
}

function addFilterRow() {
  const schema = SCHEMAS[CURRENT_TABLE];
  const firstField = schema.fields[0];
  CURRENT_FILTERS.push({ field: firstField.key, op: TYPE_OPS[firstField.type][0], value: "" });
  renderFilterRows();
}

function renderSortRows() {
  const el = document.getElementById("sort-rows");
  el.innerHTML = "";
  CURRENT_SORTS.forEach((s, i) => el.appendChild(buildSortRow(s, i)));
}

function buildSortRow(s, i) {
  const schema = SCHEMAS[CURRENT_TABLE];
  const row = document.createElement("div");
  row.className = "filter-row";
  const fieldSelect = document.createElement("select");
  fieldSelect.innerHTML = schema.fields.map(
    (fl) => `<option value="${fl.key}" ${fl.key === s.field ? "selected" : ""}>${fl.label}</option>`
  ).join("");
  const dirSelect = document.createElement("select");
  dirSelect.innerHTML = `<option value="asc" ${s.dir === "asc" ? "selected" : ""}>升序</option>
    <option value="desc" ${s.dir === "desc" ? "selected" : ""}>降序</option>`;
  const del = document.createElement("a");
  del.href = "#"; del.textContent = "✕"; del.className = "row-del";
  del.onclick = (e) => { e.preventDefault(); CURRENT_SORTS.splice(i, 1); renderSortRows(); };
  fieldSelect.dataset.role = "field"; dirSelect.dataset.role = "dir";
  row.append(fieldSelect, dirSelect, del);
  return row;
}

function addSortRow() {
  const schema = SCHEMAS[CURRENT_TABLE];
  CURRENT_SORTS.push({ field: schema.fields[0].key, dir: "asc" });
  renderSortRows();
}

function readFilterModalState() {
  const filters = [...document.getElementById("filter-rows").children].map((row) => ({
    field: row.querySelector('[data-role=field]').value,
    op: row.querySelector('[data-role=op]').value,
    value: row.querySelector('[data-role=value]').value,
  }));
  const sorts = [...document.getElementById("sort-rows").children].map((row) => ({
    field: row.querySelector('[data-role=field]').value,
    dir: row.querySelector('[data-role=dir]').value,
  }));
  return { filters, sorts };
}

async function applyFilterModal() {
  const { filters, sorts } = readFilterModalState();
  CURRENT_FILTERS = filters;
  CURRENT_SORTS = sorts;
  ACTIVE_VIEW_ID = null;
  renderViewTabs();
  closeModal("filter-modal");
  await loadRecords();
}

async function saveAsView() {
  const nameInput = document.getElementById("view-name-input");
  const shareCheckbox = document.getElementById("view-share-checkbox");
  const name = nameInput.value.trim();
  if (!name) { alert("请输入视图名称"); nameInput.focus(); return; }
  const { filters, sorts } = readFilterModalState();
  await api(`/api/tables/${CURRENT_TABLE}/views`, {
    method: "POST",
    body: JSON.stringify({ name, filters, sorts, is_shared: shareCheckbox.checked }),
  });
  CURRENT_FILTERS = filters;
  CURRENT_SORTS = sorts;
  await loadViews();
  const created = VIEWS.find((v) => v.name === name);
  ACTIVE_VIEW_ID = created ? created.id : null;
  nameInput.value = "";
  shareCheckbox.checked = true;
  renderViewTabs();
  closeModal("filter-modal");
  await loadRecords();
}

// ---------------- 用户管理（仅管理员） ----------------

async function selectUserAdmin() {
  resetViewMode();
  USER_ADMIN_MODE = true;
  CURRENT_TABLE = null;
  document.querySelectorAll(".table-item").forEach((d) => d.classList.toggle("active", d.dataset.key === "__user_admin__"));
  document.getElementById("view-tabs").innerHTML = '<div class="view-tab active">用户管理</div>';
  document.getElementById("filter-summary").textContent = "";
  document.querySelector(".toolbar").style.display = "none";
  const users = await api("/api/admin/users");
  renderUserAdminTable(users);
}

function renderUserAdminTable(users) {
  const head = document.getElementById("grid-head");
  const body = document.getElementById("grid-body");
  head.innerHTML = `<tr>
    <th class="col-idx">#</th><th>用户名</th><th>姓名</th><th>角色</th>
    <th>备注</th><th>创建时间</th><th class="col-actions">操作</th>
  </tr>`;
  body.innerHTML = "";
  users.forEach((u, idx) => {
    const row = document.createElement("tr");
    const roleBadge = u.role === "admin"
      ? `<span class="badge" style="background:#ffe8cc">管理员</span>`
      : `<span class="badge" style="background:#e5f3ff">成员</span>`;
    row.innerHTML = `
      <td class="col-idx">${idx + 1}</td>
      <td>${escapeHtml(u.username)}</td>
      <td>${escapeHtml(u.display_name)}</td>
      <td>${roleBadge}</td>
      <td class="editable-cell" onclick="activateUserNoteCell(${u.id}, this)">${escapeHtml(u.note || "")}</td>
      <td>${u.created_at ? u.created_at.split("T")[0] : ""}</td>
      <td class="col-actions"><a href="#" onclick="removeUser(${u.id}); return false;">删除</a></td>
    `;
    body.appendChild(row);
  });
}

function activateUserNoteCell(userId, td) {
  if (td.classList.contains("editing")) return;
  const current = td.textContent;
  td.classList.add("editing");
  td.innerHTML = "";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "cell-input";
  input.value = current;
  input.onblur = async () => {
    td.classList.remove("editing");
    await api(`/api/admin/users/${userId}/note`, {
      method: "PUT", body: JSON.stringify({ note: input.value }),
    });
    const users = await api("/api/admin/users");
    renderUserAdminTable(users);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") input.blur(); };
  td.appendChild(input);
  input.focus();
  input.select();
}

async function removeUser(userId) {
  if (!confirm("确定删除这个用户吗？此操作不可恢复。")) return;
  await api(`/api/admin/users/${userId}`, { method: "DELETE" });
  const users = await api("/api/admin/users");
  renderUserAdminTable(users);
}

// ---------------- 仪表盘 ----------------

async function selectDashboard() {
  resetViewMode();
  DASHBOARD_MODE = true;
  CURRENT_TABLE = null;
  document.querySelectorAll(".table-item").forEach((d) => d.classList.toggle("active", d.dataset.key === "__dashboard__"));
  document.getElementById("view-tabs").innerHTML = '<div class="view-tab active">📊 每日任务进度仪表盘</div>';
  document.getElementById("filter-summary").textContent = "";
  document.querySelector(".toolbar").style.display = "none";
  document.getElementById("grid-wrap").classList.add("hidden");
  document.getElementById("dashboard-view").classList.remove("hidden");
  await loadDashboard();
  DASHBOARD_TIMER = setInterval(loadDashboard, DASHBOARD_REFRESH_MS);
}

async function loadDashboard() {
  const data = await api("/api/dashboard/summary");
  renderDashboard(data);
}

function renderDashboard(d) {
  const el = document.getElementById("dashboard-view");
  const t = d.totals;
  el.innerHTML = `
    <div class="dash-kpi-row">
      ${kpiCard("AI主图二创任务总数", t.ai_creative.total)}
      ${kpiCard("AI主图二创已完成任务数", t.ai_creative.done)}
      ${kpiCard("套图任务总数", t.set_task.total)}
      ${kpiCard("套图任务已完成数", t.set_task.done)}
      ${kpiCard("待上架任务总数", t.pending_listing.total)}
      ${kpiCard("已上架任务数", t.pending_listing.listed)}
    </div>

    <div class="dash-row">
      ${statusPivotTable("AI主图二创人员任务完成情况统计", "制作人", d.by_maker.ai_creative)}
      ${statusPivotTable("套图任务人员任务完成情况统计", "制作人", d.by_maker.set_task)}
      ${boolPivotTable("待上架任务人员任务完成情况统计", "店铺负责人", d.by_owner.pending_listing)}
    </div>

    <div class="dash-row">
      ${todayCardGroup("AI主图二创", d.today.ai_creative)}
      ${todayCardGroup("套图任务", d.today.set_task)}
      ${todayCardGroup("待上架任务", d.today.pending_listing)}
    </div>

    <div class="dash-row">
      <div class="dash-chart-card"><h4>AI主图二创任务状态分布</h4><canvas id="chart-ai"></canvas></div>
      <div class="dash-chart-card"><h4>套图任务状态分布</h4><canvas id="chart-set"></canvas></div>
      <div class="dash-chart-card"><h4>待上架任务状态分布</h4><canvas id="chart-pending"></canvas></div>
    </div>

    <div class="dash-updated">最近更新：${new Date(d.generated_at + "Z").toLocaleString("zh-CN")}（每 30 秒自动刷新）</div>
  `;
  renderPie("chart-ai", d.status_distribution.ai_creative);
  renderPie("chart-set", d.status_distribution.set_task);
  renderPie("chart-pending", d.status_distribution.pending_listing);
}

function kpiCard(label, value) {
  return `<div class="dash-kpi"><div class="dash-kpi-label">${label}</div><div class="dash-kpi-value">${value}</div></div>`;
}

function statusPivotTable(title, groupLabel, rows) {
  const head = `<th>${groupLabel}</th>` + STATUS_COLS.map((c) => `<th>${c}</th>`).join("") + `<th>总计</th>`;
  let body = rows.map((r) =>
    `<tr><td>${escapeHtml(r.name)}</td>${STATUS_COLS.map((c) => `<td>${r[c] || 0}</td>`).join("")}<td>${r.total}</td></tr>`
  ).join("");
  if (!rows.length) {
    body = `<tr><td colspan="${STATUS_COLS.length + 2}" class="dash-empty">暂无数据</td></tr>`;
  } else {
    const totals = STATUS_COLS.map((c) => rows.reduce((s, r) => s + (r[c] || 0), 0));
    const grand = rows.reduce((s, r) => s + r.total, 0);
    body += `<tr class="dash-total-row"><td>总计</td>${totals.map((v) => `<td>${v}</td>`).join("")}<td>${grand}</td></tr>`;
  }
  return `<div class="dash-pivot-card"><h4>${title}</h4>
    <table class="dash-pivot-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function boolPivotTable(title, groupLabel, rows) {
  const head = `<th>${groupLabel}</th><th>未上架</th><th>已上架</th><th>总计</th>`;
  let body = rows.map((r) =>
    `<tr><td>${escapeHtml(r.name)}</td><td>${r.false}</td><td>${r.true}</td><td>${r.total}</td></tr>`
  ).join("");
  if (!rows.length) {
    body = `<tr><td colspan="4" class="dash-empty">暂无数据</td></tr>`;
  } else {
    const totalFalse = rows.reduce((s, r) => s + r.false, 0);
    const totalTrue = rows.reduce((s, r) => s + r.true, 0);
    body += `<tr class="dash-total-row"><td>总计</td><td>${totalFalse}</td><td>${totalTrue}</td><td>${totalFalse + totalTrue}</td></tr>`;
  }
  return `<div class="dash-pivot-card"><h4>${title}</h4>
    <table class="dash-pivot-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function todayCardGroup(title, stats) {
  return `<div class="dash-today-card">
    <h4>${title}</h4>
    <div class="dash-today-grid">
      <div><div class="dash-today-value">${stats.current}</div><div class="dash-today-label">当前未完成</div></div>
      <div><div class="dash-today-value">${stats.completed_today}</div><div class="dash-today-label">今日完成</div></div>
      <div><div class="dash-today-value">${stats.created_yesterday}</div><div class="dash-today-label">昨日新增</div></div>
      <div><div class="dash-today-value">${stats.completed_yesterday}</div><div class="dash-today-label">昨日完成</div></div>
    </div>
  </div>`;
}

function badgeColorSolid(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 65%, 55%)`;
}

function renderPie(canvasId, distMap) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || typeof Chart === "undefined") return;
  if (DASHBOARD_CHARTS[canvasId]) DASHBOARD_CHARTS[canvasId].destroy();
  const labels = Object.keys(distMap).filter((k) => distMap[k] > 0);
  const values = labels.map((l) => distMap[l]);
  if (!labels.length) return;
  DASHBOARD_CHARTS[canvasId] = new Chart(ctx, {
    type: "pie",
    data: { labels, datasets: [{ data: values, backgroundColor: labels.map(badgeColorSolid) }] },
    options: { plugins: { legend: { position: "bottom" } }, responsive: true, maintainAspectRatio: true },
  });
}

init();
