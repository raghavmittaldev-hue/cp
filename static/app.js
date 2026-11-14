// Set window.API_BASE to the API's URL if the frontend is hosted separately.
const API_BASE = window.API_BASE || "";
const $ = (id) => document.getElementById(id);

let meta = null;        // subjects + grading scheme, loaded from GET /api/subjects
let editingId = null;   // id of the student being edited, or null when adding

/* ---------- API client ---------- */
async function api(method, path, body) {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Cannot reach the server. Is the API running?");
  }
  const data = res.status === 204 ? null : await res.json();
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
const num = (n) => String(Math.round(Number(n) * 100) / 100);
const band = (gp) => (gp >= 9 ? "a" : gp >= 7 ? "b" : gp >= 5 ? "c" : "f");

function showError(msg) {
  $("form-error").textContent = msg;
  $("form-error").hidden = !msg;
}

/* ---------- form ---------- */
function buildForm() {
  for (const s of meta.subjects) {
    const wrap = el("div");
    const label = el("label", "", `${s.label} (out of ${meta.max_score})`);
    label.htmlFor = `m-${s.key}`;
    const input = Object.assign(el("input"), {
      id: `m-${s.key}`, type: "number", min: 0, max: meta.max_score, step: "any", required: true,
    });
    input.setAttribute("inputmode", "decimal");
    input.dataset.key = s.key;
    wrap.append(label, input);
    $("mark-fields").append(wrap);
  }
}

const markInputs = () => document.querySelectorAll("#mark-fields input");

function startEdit(s) {
  editingId = s.id;
  $("name").value = s.name;
  $("roll").value = s.roll_no;
  markInputs().forEach((i) => (i.value = s.marks[i.dataset.key]));
  $("form-h").textContent = `Edit ${s.name}`;
  $("submit").textContent = "Save changes";
  $("cancel").hidden = false;
  showError("");
  $("student-form").scrollIntoView({ behavior: "smooth", block: "center" });
  $("name").focus();
}

function stopEditing() {
  editingId = null;
  $("student-form").reset();
  $("form-h").textContent = "Add student";
  $("submit").textContent = "Add student";
  $("cancel").hidden = true;
}

$("cancel").addEventListener("click", () => { stopEditing(); showError(""); });

$("student-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const marks = {};
  markInputs().forEach((i) => (marks[i.dataset.key] = Number(i.value)));
  const payload = { name: $("name").value, roll_no: $("roll").value, marks };
  try {
    if (editingId) await api("PUT", `/api/students/${editingId}`, payload);
    else await api("POST", "/api/students", payload);
    stopEditing();
    showError("");
    await load();
    $("name").focus();
  } catch (err) {
    showError(err.message);
  }
});

/* ---------- results table (textContent only, so input can't inject HTML) ---------- */
function renderResults(students) {
  $("empty").hidden = students.length > 0;
  const table = $("results");
  table.hidden = students.length === 0;
  if (!students.length) return;

  const head = el("thead"), hr = el("tr");
  ["Rank", "Student", ...meta.subjects.map((s) => s.label), "CGPA", ""].forEach((h) => hr.append(el("th", "", h)));
  head.append(hr);

  const body = el("tbody");
  for (const s of students) {
    const tr = el("tr");
    tr.append(el("td", "rank", `#${s.rank}`));

    const who = el("td", "who");
    who.append(el("strong", "", s.name), el("small", "", s.roll_no));
    tr.append(who);

    for (const sub of meta.subjects) {
      const td = el("td");
      const gp = s.grade_points[sub.key];
      td.append(el("span", `chip ${band(gp)}`, String(gp)), el("small", "", `${num(s.marks[sub.key])}/${meta.max_score}`));
      tr.append(td);
    }

    tr.append(el("td", "cgpa", s.cgpa.toFixed(2)));

    const actions = el("td", "actions-cell");
    const edit = el("button", "secondary", "Edit");
    edit.addEventListener("click", () => startEdit(s));
    const del = el("button", "secondary danger", "Delete");
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${s.name}?`)) return;
      try {
        await api("DELETE", `/api/students/${s.id}`);
        if (editingId === s.id) stopEditing();
        await load();
      } catch (err) {
        showError(err.message);
      }
    });
    actions.append(edit, del);
    tr.append(actions);
    body.append(tr);
  }
  table.replaceChildren(head, body);
}

async function load() {
  renderResults(await api("GET", "/api/students"));   // already sorted by CGPA, highest first
}

/* ---------- grading scheme (built from the API so the rules live in one place) ---------- */
function renderScheme() {
  const head = el("thead"), hr = el("tr");
  ["Grade point", ...meta.subjects.map((s) => s.label)].forEach((h) => hr.append(el("th", "", h)));
  head.append(hr);
  const body = el("tbody");
  for (const gp of [10, 9, 8, 7, 6, 5, 0]) {
    const tr = el("tr");
    tr.append(el("td", "", String(gp)));
    for (const s of meta.subjects) {
      const row = s.scale.find((r) => r.grade_point === gp);
      const lowest = s.scale[s.scale.length - 1].min_marks;
      tr.append(el("td", "", row ? `${row.min_marks}+` : `below ${lowest}`));
    }
    body.append(tr);
  }
  $("scheme").replaceChildren(head, body);
}

/* ---------- start ---------- */
(async function init() {
  try {
    meta = await api("GET", "/api/subjects");
    buildForm();
    renderScheme();
    await load();
  } catch (err) {
    showError(err.message);
  }
})();
