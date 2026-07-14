"""Pumpfun Scanner — web dashboard.

A read-only browser view of what the monitor is collecting: the current
GO / NEUTRAL / WAIT call and heat gauge, live platform metrics, a 24h heat
trend, the best-times-by-hour table, and a disk-footprint panel so the project
can't silently balloon again.

Stdlib only (http.server) — no extra deps beyond what the monitor already uses.
It reads the same SQLite the monitor writes, opened read-only, so the two never
contend for a write lock.

Run:  python dashboard.py            # http://127.0.0.1:8787
      DASHBOARD_HOST=0.0.0.0 python dashboard.py   # reachable on the VPS IP
"""
from __future__ import annotations

import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import best_times
import config
import heat as heat_mod
import sizeguard
import storage


def _ro_conn() -> sqlite3.Connection | None:
    """Open the snapshot DB read-only. Returns None if it doesn't exist yet."""
    p = Path(config.DB_PATH)
    if not p.exists():
        return None
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def build_state() -> dict:
    """Assemble the full dashboard payload from the current DB contents."""
    size = sizeguard.stats()
    conn = _ro_conn()
    if conn is None:
        return {"status": "no_data", "size": size, "generated": time.time()}
    try:
        rows = storage.all_rows(conn)
        if not rows:
            return {"status": "no_data", "size": size, "generated": time.time()}

        baseline = storage.recent(conn, config.BASELINE_HOURS)
        latest = dict(rows[-1])
        # Recompute live so signal/reasons reflect the current baseline, not just
        # the heat frozen into the last logged row.
        heat, signal, reasons = heat_mod.compute(dict(latest), baseline)
        components = heat_mod.components(dict(latest), baseline)

        cutoff = time.time() - config.DASHBOARD_HISTORY_HOURS * 3600
        history = [{"t": r["ts"], "heat": r["heat"]} for r in rows if r["ts"] >= cutoff]

        # How long the platform has held the current signal: walk logged snapshots
        # backward while their heat maps to the same signal as right now.
        streak_start = latest["ts"]
        for r in reversed(rows):
            if heat_mod.signal_from_heat(r["heat"]) == signal:
                streak_start = r["ts"]
            else:
                break
        streak_min = round((latest["ts"] - streak_start) / 60, 1)

        span_h = (rows[-1]["ts"] - rows[0]["ts"]) / 3600
        baseline_n = len(baseline)
        return {
            "status": "ok",
            "generated": time.time(),
            "signal": signal,
            "heat": heat,
            "reasons": reasons,
            "components": components,
            "streak_min": streak_min,
            "snapshot": latest,
            "history": history,
            "best_hours": best_times.hour_stats(rows),
            "dow_grid": best_times.dow_hour_grid(rows),
            "size": size,
            "meta": {
                "snapshots": len(rows),
                "span_hours": round(span_h, 1),
                "baseline_n": baseline_n,
                "cold_start": baseline_n < config.MIN_BASELINE_SNAPSHOTS,
                "min_baseline": config.MIN_BASELINE_SNAPSHOTS,
                "go_threshold": config.GO_THRESHOLD,
                "wait_threshold": config.WAIT_THRESHOLD,
            },
        }
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path.startswith("/api/state"):
            try:
                body = json.dumps(build_state(), default=str).encode()
                self._send(200, body, "application/json")
            except Exception as e:  # keep the server up even if a read fails
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args) -> None:  # silence per-request logging
        pass


PAGE = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pumpfun Platform Heat</title>
<style>
  :root{--bg:#0b1220;--card:#151f33;--edge:#243149;--txt:#e5edf7;--dim:#8296b3;
        --go:#16a34a;--neutral:#d97706;--wait:#dc2626;--accent:#38bdf8;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font:15px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:1040px;margin:0 auto;padding:22px 18px 60px}
  h1{font-size:18px;margin:0;font-weight:650;letter-spacing:.2px}
  .sub{color:var(--dim);font-size:12.5px;margin-top:3px}
  .banner{background:#3b1113;border:1px solid #7f1d1d;color:#fecaca;padding:10px 14px;
          border-radius:10px;margin:14px 0;font-size:13.5px}
  .card{background:var(--card);border:1px solid var(--edge);border-radius:14px;
        padding:16px 18px;margin-top:14px}
  .hd{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  .badge{font-weight:750;font-size:22px;padding:8px 18px;border-radius:10px;color:#fff}
  .heat{font-size:34px;font-weight:750}
  .heat small{font-size:15px;color:var(--dim);font-weight:500}
  .gauge{height:9px;border-radius:6px;background:#0b1424;overflow:hidden;margin-top:10px;
         border:1px solid var(--edge)}
  .gauge > i{display:block;height:100%}
  .reasons{color:var(--dim);font-size:13px;margin-top:10px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:6px}
  .tile{background:#0f1a2e;border:1px solid var(--edge);border-radius:10px;padding:11px 13px}
  .tile b{display:block;font-size:19px;font-weight:650;margin-top:2px}
  .tile span{color:var(--dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.4px}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
  th,td{text-align:right;padding:6px 9px;border-bottom:1px solid var(--edge)}
  th:first-child,td:first-child{text-align:left}
  th{color:var(--dim);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.4px}
  tr.top td{background:rgba(22,163,74,.12)}
  .sect{font-size:12.5px;color:var(--dim);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px}
  .foot{color:var(--dim);font-size:12px;margin-top:8px}
  svg{width:100%;height:120px;display:block}
  .dimtxt{color:var(--dim)}
  .pill{font-size:12px;color:var(--dim);background:#0f1a2e;border:1px solid var(--edge);
        padding:4px 10px;border-radius:999px;white-space:nowrap}
  /* heat component breakdown */
  .bk{display:grid;grid-template-columns:78px 1fr 96px;gap:8px 10px;align-items:center}
  .bk .lab{font-size:12.5px;color:var(--dim);text-transform:capitalize}
  .bk .track{height:14px;border-radius:5px;background:#0b1424;border:1px solid var(--edge);overflow:hidden}
  .bk .track > i{display:block;height:100%;border-radius:4px}
  .bk .val{font-size:12.5px;text-align:right}
  .bk .val .r{color:var(--dim);font-size:11px}
  /* day x hour heatmap */
  .hmwrap{overflow-x:auto}
  .hm{border-collapse:separate;border-spacing:2px;font-size:11px;margin-top:2px}
  .hm td,.hm th{padding:0;text-align:center;font-weight:500}
  .hm th{color:var(--dim);font-size:10px;font-weight:600;height:16px}
  .hm td.d{color:var(--dim);text-align:right;padding-right:6px;font-size:11px}
  .hm td.c{width:26px;height:22px;border-radius:4px;color:#04121f;font-size:10px;
           font-weight:650;background:#0f1a2e}
  .hm td.c.empty{color:var(--edge);background:#0d1626;font-weight:400}
  .scale{display:flex;align-items:center;gap:8px;margin-top:10px;color:var(--dim);font-size:11.5px}
  .scale .bar{flex:1;max-width:220px;height:8px;border-radius:5px;
    background:linear-gradient(90deg,hsl(0,60%,42%),hsl(60,62%,45%),hsl(120,60%,40%))}
</style></head><body><div class="wrap">
  <h1>Pumpfun Platform Heat</h1>
  <div class="sub" id="sub">loading…</div>
  <div id="banner"></div>
  <div id="body"></div>
  <div class="foot" id="foot"></div>
</div>
<script>
const SIG = {GO:"var(--go)", NEUTRAL:"var(--neutral)", WAIT:"var(--wait)"};
const fmt = (v,d=1,suf="")=> (v===null||v===undefined) ? "—" : (+v).toFixed(d)+suf;
const ago = t => { const s=Math.max(0,Date.now()/1000-t); return s<90?`${s|0}s`:`${(s/60)|0}m`; };
const dur = m => { if(m==null) return "—"; if(m<60) return `${Math.round(m)}m`;
  const h=m/60; return h<24?`${h.toFixed(1)}h`:`${(h/24).toFixed(1)}d`; };
// map a 0-100 heat to a cold→hot colour (red → amber → green), intensity by value
const heatColor = v => `hsl(${(v/100)*120},62%,${38+(v/100)*10}%)`;

function tile(label,val){ return `<div class="tile"><span>${label}</span><b>${val}</b></div>`; }

function breakdown(comps){
  if(!comps || !comps.length) return "";
  const total = comps.reduce((a,c)=>a+c.points,0) || 1;
  const rows = comps.map(c=>{
    const pct = Math.round(c.sub*100);                 // how "full" this component is
    const col = c.sub>=0.6 ? "var(--go)" : c.sub>=0.4 ? "var(--neutral)" : "var(--wait)";
    const share = ((c.points/total)*100).toFixed(0);   // % of the heat it accounts for
    const rtxt = c.ratio==null ? "" : `<span class="r"> ${(+c.ratio).toFixed(1)}×</span>`;
    return `<div class="lab" title="${share}% of heat">${c.name.replace('_',' ')}</div>
      <div class="track"><i style="width:${pct}%;background:${col}"></i></div>
      <div class="val">+${c.points.toFixed(1)}${rtxt}</div>`;
  }).join("");
  return `<div class="bk">${rows}</div>
    <div class="foot">Bar = how hot each input is vs its baseline (½ = at baseline).
    +points = its share of the 0–100 heat; they sum to the score above.</div>`;
}

function heatmap(g){
  if(!g || !g.grid) return '<div class="dimtxt">not enough history yet.</div>';
  const hrs = Array.from({length:24},(_,h)=>`<th>${String(h).padStart(2,'0')}</th>`).join("");
  const body = g.grid.map((row,d)=>{
    const cells = row.map((v,h)=> v==null
      ? `<td class="c empty" title="${g.dow[d]} ${String(h).padStart(2,'0')}:00 — no data">·</td>`
      : `<td class="c" style="background:${heatColor(v)}" title="${g.dow[d]} ${String(h).padStart(2,'0')}:00 — heat ${v}">${Math.round(v)}</td>`
    ).join("");
    return `<tr><td class="d">${g.dow[d]}</td>${cells}</tr>`;
  }).join("");
  return `<div class="hmwrap"><table class="hm">
      <thead><tr><th></th>${hrs}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="scale">cold<span class="bar"></span>hot
      <span style="margin-left:auto">confidence-adjusted · avg ${g.global}</span></div>`;
}

function spark(hist, meta){
  if(!hist || hist.length<2) return '<div class="dimtxt">collecting history…</div>';
  const W=1000,H=120,pad=4;
  const t0=hist[0].t, t1=hist[hist.length-1].t, span=Math.max(1,t1-t0);
  const x=t=>pad+(t-t0)/span*(W-2*pad);
  const y=h=>pad+(1-h/100)*(H-2*pad);
  const pts=hist.map(p=>`${x(p.t).toFixed(1)},${y(p.heat).toFixed(1)}`).join(" ");
  const line=(h,c)=>`<line x1="${pad}" y1="${y(h)}" x2="${W-pad}" y2="${y(h)}" stroke="${c}" stroke-width="1" stroke-dasharray="4 4" opacity="0.5"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    ${line(meta.go_threshold,"var(--go)")}${line(meta.wait_threshold,"var(--wait)")}
    <polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${pts}"/>
  </svg>`;
}

function bestTable(hours){
  if(!hours || !hours.length) return '<div class="dimtxt">not enough history yet.</div>';
  const solid = hours.filter(h=>h.solid);
  const pool = solid.length?solid:hours;
  const topSet = new Set([...pool].sort((a,b)=>b.adj-a.adj).slice(0,3).map(h=>h.hour));
  let rows = hours.map(h=>`<tr class="${topSet.has(h.hour)?'top':''}">
    <td>${String(h.hour).padStart(2,'0')}:00</td><td>${h.n}</td>
    <td><b>${h.adj.toFixed(0)}</b></td><td class="dimtxt">${h.raw.toFixed(0)}</td>
    <td>${h.vol_5m.toFixed(0)}</td><td>${h.migrations_1h.toFixed(1)}</td>
    <td>${h.mig_speed_min!=null?h.mig_speed_min.toFixed(0)+'m':'—'}</td>
    <td>${h.buyers_5m.toFixed(0)}</td>
    <td>${h.pf_froth!=null?h.pf_froth.toFixed(0):'—'}</td></tr>`).join("");
  return `<table><thead><tr>
    <th>Hour</th><th>Samples</th><th>Heat*</th><th>Raw</th><th>Vol 5m</th>
    <th>Migr/hr</th><th>Speed</th><th>Buyers</th><th>PF froth</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="foot">Heat* = confidence-adjusted (shrunk toward the mean so thin hours can't rank falsely hot). Top 3 highlighted.</div>`;
}

async function refresh(){
  let d; try{ d = await (await fetch("/api/state")).json(); }
  catch(e){ document.getElementById("sub").textContent="dashboard unreachable"; return; }
  const sub=document.getElementById("sub"), banner=document.getElementById("banner"),
        body=document.getElementById("body"), foot=document.getElementById("foot");

  const sz=d.size||{};
  banner.innerHTML = (sz.warnings&&sz.warnings.length)
    ? `<div class="banner">⚠ ${sz.warnings.join(" · ")}</div>` : "";

  if(d.status!=="ok"){
    sub.textContent="waiting for the monitor to log its first snapshots…";
    body.innerHTML = `<div class="card"><div class="sect">Disk footprint</div>${sizePanel(sz)}</div>`;
    return;
  }
  const s=d.snapshot, m=d.meta;
  sub.innerHTML = `${m.snapshots} snapshots over ${m.span_hours}h`
    + (m.cold_start?` · <span class="dimtxt">cold start — reference levels until ${m.min_baseline} snapshots (${m.baseline_n}/${m.min_baseline})</span>`:"");

  const solLine = s.sol_price!=null ? `$${(+s.sol_price).toFixed(2)} (${fmt(s.sol_chg_24h,1)}% 24h)` : "—";
  body.innerHTML = `
    <div class="card">
      <div class="hd">
        <span class="badge" style="background:${SIG[d.signal]}">${d.signal}</span>
        <span class="heat">${d.heat}<small>/100 heat</small></span>
        <span class="pill" style="margin-left:auto">${d.signal} for ${dur(d.streak_min)}</span>
      </div>
      <div class="gauge"><i style="width:${d.heat}%;background:${SIG[d.signal]}"></i></div>
      <div class="reasons">${d.reasons.length?d.reasons.join("  ·  "):"conditions near baseline"}</div>
    </div>
    <div class="card"><div class="sect">What's driving the heat</div>${breakdown(d.components)}</div>
    <div class="card"><div class="sect">Live platform metrics</div><div class="grid">
      ${tile("Launches /min", fmt(s.launches_5m,1))}
      ${tile("Migrations /hr", fmt(s.migrations_1h,0))}
      ${tile("Mig speed", s.mig_speed_min!=null?fmt(s.mig_speed_min,0,'m'):'—')}
      ${tile("Volume 5m", fmt(s.vol_5m,0,' SOL'))}
      ${tile("Buyers 5m", s.buyers_5m)}
      ${tile("Buy/sell", fmt(s.buy_sell,2))}
      ${tile("PF froth", fmt(s.pf_froth,1))}
      ${tile("SOL", solLine)}
      ${tile("SOL froth", fmt(s.sol_froth,2))}
    </div></div>
    <div class="card"><div class="sect">Heat — last ${Math.round(m.span_hours>24?24:m.span_hours)||24}h</div>${spark(d.history,m)}</div>
    <div class="card"><div class="sect">Best times to trade — by hour (local)</div>${bestTable(d.best_hours)}</div>
    <div class="card"><div class="sect">Heat by day &amp; hour (local)</div>${heatmap(d.dow_grid)}</div>
    <div class="card"><div class="sect">Disk footprint</div>${sizePanel(sz)}</div>`;
  foot.textContent = `updated ${ago(d.generated)} ago · auto-refresh 15s`;
}

function sizePanel(sz){
  if(!sz.project_human) return '<div class="dimtxt">unavailable</div>';
  return `<div class="grid">
    ${tile("Project dir", sz.project_human)}
    ${tile("Database", sz.db_human)}
    ${tile("Disk free", sz.disk_free_human)}
    ${tile("Disk used", (sz.disk_used_pct||0)+"%")}
  </div>`;
}

refresh(); setInterval(refresh, 15000);
</script></body></html>"""


def main() -> None:
    server = ThreadingHTTPServer((config.DASHBOARD_HOST, config.DASHBOARD_PORT), Handler)
    host = config.DASHBOARD_HOST
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"Pumpfun dashboard on http://{shown}:{config.DASHBOARD_PORT}  (reading {config.DB_PATH})")
    if host == "127.0.0.1":
        print(f"  localhost-only — tunnel with:  ssh -L {config.DASHBOARD_PORT}:localhost:{config.DASHBOARD_PORT} <this-vps>")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
