const $ = (id) => document.getElementById(id);
const at = () => $("at").value.trim();
const qp = (p) => new URLSearchParams(p).toString();

async function api(path, params) {
  const url = "/api" + path + (params ? "?" + qpParams(params) : "");
  const res = await fetch(url);
  return res.json();
}
const qpParams = (o) => Object.entries(o)
  .filter(([, v]) => v !== undefined && v !== null && v !== "")
  .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");

function setTime(t) { $("at").value = t; refresh(currentEid); }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g,
  (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])); }

const V_TAG = {
  verified: ["t-ok", "已核对"], stale: ["t-warn", "待重新核对"],
  unchecked: ["t-unk", "未核对"], missing: ["t-bad", "缺翻译"]
};

async function loadOverview() {
  const ov = await api("/overview");
  $("floors").innerHTML = ov.floors.map(f => `
    <div class="floor"><div class="f">${f.floor}F
      <span class="muted">${f.exhibit_count} 件展品</span></div>
      ${f.zones.map(z => `<button class="zone-btn"
        onclick="loadZone('${z.zone}')">▸ ${esc(z.name)} (${z.zone})</button>`).join("")}
    </div>`).join("");
  const list = await api("/exhibits");
  $("exhibits").innerHTML = list.exhibits.map(e => `
    <button class="ex-btn" id="ex-${e.exhibit_id}"
      onclick="refresh('${e.exhibit_id}')">${e.exhibit_id} · ${esc(e.title)}
      <span class="muted">${e.floor}F</span></button>`).join("");
}
async function loadZone(zone) {
  const list = await api("/exhibits", { zone });
  list.exhibits.forEach(e => highlight(e.exhibit_id));
}

let currentEid = null;
function highlight(eid) {
  document.querySelectorAll(".ex-btn").forEach(b => b.classList.remove("active"));
  const el = $("ex-" + eid); if (el) el.classList.add("active");
}

async function refresh(eid) {
  if (!eid) return;
  currentEid = eid;
  highlight(eid);
  const params = { mode: $("mode").value, lang: $("lang").value, at: at() };
  const [page, mp, route] = await Promise.all([
    api(`/exhibit/${eid}`, params),
    api(`/map/${eid}`, { at: at() }),
    api(`/route/${eid}`, { origin: "N-LOBBY", at: at() })
  ]);
  renderPage(page); renderMap(mp); renderRoute(route);
}

function errBox(e) {
  return `<div class="err"><div class="code">${esc(e.code)}</div>
    <div>${esc(e.message)}</div>
    ${e.expires_at ? `<div class="muted">有效期至 ${esc(e.expires_at)}</div>` : ""}
    ${e.block_id ? `<div class="muted">缺失块: ${esc(e.block_id)}</div>` : ""}
    </div>`;
}

function renderPage(p) {
  if (p.error) { $("page").innerHTML = errBox(p.error); $("p-tag").textContent = ""; return; }
  const [cls, label] = V_TAG[p.content.verified] || ["t-unk", p.content.verified];
  const loc = p.location;
  $("p-tag").textContent = `布局 ${p.layout_token} · 时点 ${p.as_of}`;
  $("page").innerHTML = `
    <div><b>${esc(p.exhibit.title)}</b> <span class="muted">${p.exhibit.exhibit_id}</span></div>
    <div style="margin:6px 0"><span class="tag ${cls}">${label}</span>
      <span class="muted">基线版本 v${p.content.baseline_version ?? "—"}
      ${p.content.checked_against ? `（核对于 v${p.content.checked_against}）` : ""}</span></div>
    <div>${esc(p.content.body) || '<span class="muted">（该语言无讲稿，不回退其他语言）</span>'}</div>
    <hr style="border-color:#2a3550"/>
    <div class="muted">当前位置: ${loc ? esc(loc.reason) + " → " +
      loc.node_id + " / " + esc(loc.cabinet) : "不在展"}</div>
    <div class="muted">空间有效期至: ${p.freshness.spatial_expires_at ?? "—"}</div>`;
}

function renderMap(m) {
  if (m.error) { $("map").innerHTML = errBox(m.error); return; }
  $("map").innerHTML = `
    <div class="muted">布局版 ${esc(m.layout_token)} · 时点 ${m.as_of}</div>
    <div class="map-cabinet">🧭 ${esc(m.node.floor)}F<br/>
      <span style="font-size:15px">${esc(m.node.name)} · ${esc(m.cabinet)}</span></div>
    <div class="muted">位置时段: ${m.assignment.valid_from} →
      ${m.assignment.valid_to ?? "（持续中）"}<br/>性质: ${esc(m.assignment.reason)}</div>`;
}

function renderRoute(r) {
  if (r.error) { $("route").innerHTML = errBox(r.error); return; }
  const res = r.result;
  if (!res.reachable) {
    $("route").innerHTML = `<div class="err"><div class="code">${esc(res.code)}</div>
      <div>${esc(res.message)}</div></div>
      ${(res.barriers || []).map(b => `<div class="muted">屏障: ${b.kind === "edge"
        ? "通道" : "展区"} ${esc(b.name)} — ${b.status === "closed" ? "关闭" : "状态未知"}
        ${b.cross_floor ? "（跨层）" : ""}</div>`).join("")}`;
    return;
  }
  $("route").innerHTML = `<div class="muted">时点 ${r.as_of} · 步行 ${res.minutes} 分钟
    ${res.crosses_floor ? " · 含跨层" : ""}</div>` +
    res.steps.map(s => `<div class="route-step ${s.cross_floor ? "cross" : ""}">
      ${s.cross_floor ? "🛗" : "🚶"} ${esc(s.from_name)} → ${esc(s.to_name)}
      <span class="muted">(${s.kind})</span></div>`).join("");
}

async function plan() {
  const p = await api("/plan", { origin: "N-LOBBY",
    minutes: $("minutes").value, lang: $("lang").value,
    mode: $("mode").value, at: at() });
  if (p.error) { $("plan").innerHTML = errBox(p.error); return; }
  $("plan").innerHTML = `
    <div class="muted">时点 ${p.as_of} · 预算 ${p.budget_minutes} 分钟 ·
      已排 ${p.used_minutes} 分钟</div>
    <ul class="tight">${p.stops.map(s => `<li>${esc(s.title)}
      ${s.missing_translation ? '<span class="tag t-bad">缺翻译</span>' : ""}
      ${s.content_state === "stale" ? '<span class="tag t-warn">待重新核对</span>' : ""}
      <span class="muted">步行${s.walk_minutes}′+观看${s.view_minutes}′ ·
      ${esc(s.location_reason)}</span></li>`).join("")}</ul>
    ${p.skipped_unreachable.length ? `<div class="muted">不可达:</div>
      <ul class="tight">${p.skipped_unreachable.map(s =>
        `<li>${esc(s.title)} — <span class="tag t-bad">${s.reason_code}</span>
        ${esc(s.reason)}</li>`).join("")}</ul>` : ""}
    ${p.off_display.length ? `<div class="muted">不在展:</div>
      <ul class="tight">${p.off_display.map(s =>
        `<li>${esc(s.title)}</li>`).join("")}</ul>` : ""}`;
}

async function loadPacks() {
  const c = await api("/packs");
  const row = (t, p) => `<div><b>${t}</b> <span class="muted">${p.pack_kind} ·
    gen ${p.generation}</span><br/>块数 ${p.block_count} ·
    ${(p.size_bytes / 1024).toFixed(1)} KB</div>`;
  $("packs").innerHTML = row("整馆包", c.full) + "<br/>" + row("路线包", c.route) +
    `<div class="muted" style="margin-top:6px">路线包节省 ${(c.saved_bytes / 1024).toFixed(1)} KB
    （${(c.saved_ratio * 100).toFixed(0)}%）</div>`;
}

$("mode").onchange = $("lang").onchange = () => refresh(currentEid);
loadOverview().then(() => refresh("E001"));
plan(); loadPacks();
