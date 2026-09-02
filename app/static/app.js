let SCHEMAS = {};
let CURRENT_TABLE = null;
let CURRENT_FILTERS = [];
let CURRENT_SORTS = [];
let VIEWS = [];
let ACTIVE_VIEW_ID = null; // null = 默认 Grid
let RECORDS = [];
let EDITING_ID = null;

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

async function init() {
  document.getElementById("user-name").textContent =
    window.CURRENT_USER.display_name + (window.CURRENT_USER.role === "admin" ? "（管理员）" : "");
  SCHEMAS = await api("/api/tables/schemas");
  const tableKeys = Object.keys(SCHEMAS).sort((a, b) => SCHEMAS[a].order - SCHEMAS[b].order);
  renderSidebar(tableKeys);
  selectTable(tableKeys[0]);
}

function renderSidebar(tableKeys) {
  const el = document.getElementById("table-list");
  el.innerHTML = "";
  const groups = [
    { key: "business", label: "业务表" },
    { key: "config", label: "配置表" },
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
}

async function selectTable(key) {
  CURRENT_TABLE = key;
  CURRENT_FILTERS = [];
  CURRENT_SORTS = [];
  ACTIVE_VIEW_ID = null;
  document.querySelectorAll(".table-item").forEach((d) => {
    d.classList.toggle("active", d.dataset.key === key);
  });
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
    tab.textContent = v.name;
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

function renderTable() {
  const schema = SCHEMAS[CURRENT_TABLE];
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
      html += `<td>${renderCell(f, rec.data[f.key])}</td>`;
    });
    html += `<td class="col-actions">
      <a href="#" onclick="openRecordModal(${rec.id}); return false;">编辑</a>
      <a href="#" onclick="removeRecord(${rec.id}); return false;">删除</a>
    </td>`;
    row.innerHTML = html;
    body.appendChild(row);
  });
}

function renderCell(field, value) {
  if (value === undefined || value === null || value === "") return "";
  switch (field.type) {
    case "url":
      return `<a href="${escapeHtml(value)}" target="_blank" class="cell-link">${escapeHtml(value)}</a>`;
    case "select":
      return `<span class="badge" style="background:${badgeColor(value)}">${escapeHtml(value)}</span>`;
    case "multiselect":
      return (Array.isArray(value) ? value : []).map(
        (v) => `<span class="badge" style="background:${badgeColor(v)}">${escapeHtml(v)}</span>`
      ).join(" ");
    case "rating": {
      const n = parseInt(value) || 0;
      return "★".repeat(n) + `<span class="star-empty">${"★".repeat(5 - n)}</span>`;
    }
    case "checkbox":
      return value === true || value === "true" ? "✅" : "";
    default:
      return escapeHtml(String(value));
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ---------------- 记录增改 ----------------

function openRecordModal(id) {
  EDITING_ID = id || null;
  const schema = SCHEMAS[CURRENT_TABLE];
  const rec = id ? RECORDS.find((r) => r.id === id) : null;
  document.getElementById("record-modal-title").textContent = id ? "编辑记录" : "添加记录";
  const form = document.getElementById("record-form");
  form.innerHTML = "";
  schema.fields.forEach((f) => {
    if (f.auto) return; // 创建时间/创建人/SKU开发阶段 完全由系统生成，不给编辑
    if (f.auto_on_create && !id) return; // 制作人/店铺负责人 新建时由自动化规则分配，编辑时才允许手动改
    const value = rec ? rec.data[f.key] : undefined;
    form.appendChild(buildFieldInput(f, value));
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
  if (EDITING_ID) {
    await api(`/api/tables/${CURRENT_TABLE}/records/${EDITING_ID}`, {
      method: "PUT", body: JSON.stringify({ data }),
    });
  } else {
    await api(`/api/tables/${CURRENT_TABLE}/records`, {
      method: "POST", body: JSON.stringify({ data }),
    });
  }
  closeModal("record-modal");
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

  function refreshOps() {
    const type = schema.fields.find((fl) => fl.key === fieldSelect.value)?.type || "text";
    const ops = TYPE_OPS[type] || ["eq"];
    opSelect.innerHTML = ops.map((o) => `<option value="${o}">${OP_LABELS[o]}</option>`).join("");
    if (f.op) opSelect.value = f.op;
  }
  fieldSelect.onchange = refreshOps;
  refreshOps();

  const del = document.createElement("a");
  del.href = "#"; del.textContent = "✕"; del.className = "row-del";
  del.onclick = (e) => { e.preventDefault(); CURRENT_FILTERS.splice(i, 1); renderFilterRows(); };

  row.append(fieldSelect, opSelect, valueInput, del);
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
  const name = prompt("视图名称：");
  if (!name) return;
  const { filters, sorts } = readFilterModalState();
  await api(`/api/tables/${CURRENT_TABLE}/views`, {
    method: "POST",
    body: JSON.stringify({ name, filters, sorts, is_shared: true }),
  });
  CURRENT_FILTERS = filters;
  CURRENT_SORTS = sorts;
  await loadViews();
  const created = VIEWS.find((v) => v.name === name);
  ACTIVE_VIEW_ID = created ? created.id : null;
  renderViewTabs();
  closeModal("filter-modal");
  await loadRecords();
}

init();
