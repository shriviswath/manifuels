#!/usr/bin/env python3
"""
MF_DASH_V5 — dashboard figures that agree with the pages behind them.

FIXES
  F1 LAST 7 DAYS tile: complete days only — today counts once its Night shift
     has ended (6 PM), same rule as the Business Pulse card — compared with the
     7 days before. It no longer leans red all day.
  F2 CREDIT OUTSTANDING: after advances, per customer, exactly as the ledger
     page adds it up.
  F3 SUPPLIER DUES (was FUEL LOAD DUES): tanker bills AND oil invoices, from
     the synced lists in memory — the same figure as the evening report.
  F4 Oil stock: "low" means under ~10 days of cover at the last 30 days' sales
     (items sold in shifts and bottles opened for loose oil); items with no
     sales keep the old "2 or fewer". The value moves off the front page (F7)
     and is shown on the alert at cost, not selling price.

ADDITIONS
  A5 Alerts sorted: red, then amber, then info.
  A6 14-day chart: net profit line on its own right-hand scale.
  A7 TODAY'S PROFIT tile (replaces STOCK VALUE): net profit and fuel margin per
     litre; says so when a fuel cost is missing.
  A8 Overdue card: unpaid bills by age (0–30 / 31–60 / 61–90 / 90+) on top,
     each customer's own credit-day limit where one is set (14 days if not).
     Also fixes the customer link — the name was put inside a double-quoted
     attribute with double quotes, so tapping a row did nothing.

Usage:  python3 patch_dashboard.py [path/to/index.html]
Idempotent. Requires MF_LEDGER_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_DASH_V5"

HUNKS = [
("F1 7-day tile: complete days",
r"""  const weekAgo=_daysAgo(6);
  const todayRecs = records.filter(r=>r.date===today);
  const weekRecs  = records.filter(r=>r.date>=weekAgo);
  const prevWeekRecs = records.filter(r=>r.date>=_daysAgo(13)&&r.date<weekAgo);""",
r"""  const todayRecs = records.filter(r=>r.date===today);
  // MF_DASH_V5: complete days only. Today joins once its Night shift is over
  // (6 PM); before that the comparison ran a part-day against full days.
  const _now=new Date();
  const _endIso=(typeof mfSlotEnd==='function'&&mfSlotEnd({date:today,shift:'night'})>_now)?_daysAgo(1):today;
  const _addD=(iso,n)=>{const d=new Date(iso+'T00:00:00');d.setDate(d.getDate()+n);return _isoLocal(d);};
  const weekAgo=_addD(_endIso,-6), prevFrom=_addD(_endIso,-13), prevTo=_addD(_endIso,-7);
  const weekRecs  = records.filter(r=>r.date>=weekAgo&&r.date<=_endIso);
  const prevWeekRecs = records.filter(r=>r.date>=prevFrom&&r.date<=prevTo);"""),

("F1b 7-day tile: matching P&L windows",
r"""  const weekRev = _plCore(weekRecs, weekAgo, today).revenue;
  const prevWeekRev = _plCore(prevWeekRecs, _daysAgo(13), _daysAgo(7)).revenue;""",
r"""  const weekRev = _plCore(weekRecs, weekAgo, _endIso).revenue;
  const prevWeekRev = _plCore(prevWeekRecs, prevFrom, prevTo).revenue;
  const _endLbl = new Date(_endIso+'T00:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short'});"""),

("F2 credit outstanding: after advances",
r"""  const outstanding = ledger.reduce((s,e)=>s+Math.max(0,(e.amount||0)-(e.paidBack||0)),0);
  const outstandingCustomers = new Set(ledger.filter(e=>(e.amount||0)>(e.paidBack||0)).map(e=>e.customer)).size;""",
r"""  // MF_DASH_V5: net of advances, per customer — the ledger page's figure.
  let outstanding=0, outstandingCustomers=0;
  [...new Set(ledger.map(e=>e.customer))].forEach(function(n){
    const p=_custPosition(n); if(p.net>0.5){ outstanding+=p.net; outstandingCustomers++; } });"""),

("F3+F4 supplier dues and stock",
r"""  // Stock value
  const stockValue = stock.reduce((s,x)=>s+((x.qty||0)*(x.rate||0)),0);
  const lowStockCount = stock.filter(x=>(x.qty||0)>0 && (x.qty||0)<=2).length;
  const outOfStock = stock.filter(x=>(x.qty||0)<=0).length;

  // Fuel load dues (if fuelLoads exists)
  let fuelDues = 0;
  try{
    const loads = JSON.parse(localStorage.getItem('fuelLoads')||'[]');
    // amountDue is maintained as totalCost - amountPaid, so subtracting
    // amountPaid again halved every outstanding balance.
    fuelDues = loads.reduce((s,l)=>s+Math.max(0,(l.totalCost!=null?l.totalCost:(l.amountDue||0))-(l.amountPaid||0)),0);
  }catch(e){}""",
r"""  // MF_DASH_V5: tankers AND oil invoices, from the synced lists in memory.
  const _sd=_supplierDues();
  const fuelDues=_sd.total;
  // Today's profit
  const _Pt=_plCore(todayRecs, today, today);
  const _lt=(_Pt.soldMSDL||0)+(_Pt.soldHSDL||0);
  const _fuelMarginL=_lt>0?((_Pt.revFuel||0)-(_Pt.cogsFuel||0))/_lt:0;"""),

("F3b+A7 tiles",
r"""    {cls: fuelDues>0?'diesel':'green', icon:'⛽', lbl:'FUEL LOAD DUES', val:fmt(fuelDues),
     sub: fuelDues>0?'Pending supplier payments':'No pending dues'},
    {cls: lowStockCount+outOfStock>0?'red':'purple', icon:'📦', lbl:'STOCK VALUE', val:fmt(stockValue),
     sub: outOfStock>0 ? `${outOfStock} out of stock, ${lowStockCount} low` : (lowStockCount>0?`${lowStockCount} items low`:'Stock healthy')},""",
r"""    {cls: fuelDues>0?'diesel':'green', icon:'⛽', lbl:'SUPPLIER DUES', val:fmt(fuelDues),
     sub: fuelDues>0?('Tankers '+fmt(_sd.fuel)+' · oil '+fmt(_sd.oil)):'No pending dues'},
    // MF_DASH_V5: today's profit instead of stock value
    {cls: !todayRecs.length?'purple':(_Pt.netProfit>=0?'green':'red'), icon:'💹', lbl:"TODAY'S PROFIT",
     val: todayRecs.length?fmt(_Pt.netProfit):'—',
     sub: !todayRecs.length?'No shift saved yet':(_Pt.fuelUncosted?'⚠ fuel cost missing — enter the tanker loads':
          ('fuel margin ₹'+_fuelMarginL.toFixed(2)+'/L · '+(_Pt.netMarginPct||0).toFixed(1)+'% net'))},"""),

("F1c 7-day tile text",
r"""    {cls:'blue', icon:'📅', lbl:'LAST 7 DAYS', val:fmt(weekRev),
     sub: prevWeekRev>0 ? `${weekChange>=0?'▲':'▼'} ${Math.abs(weekChange).toFixed(1)}% vs prev week` : `${weekRecs.length} shifts`},""",
r"""    {cls:'blue', icon:'📅', lbl:'LAST 7 FULL DAYS', val:fmt(weekRev),
     sub: (prevWeekRev>0 ? `${weekChange>=0?'▲':'▼'} ${Math.abs(weekChange).toFixed(1)}% vs the 7 before` : `${weekRecs.length} shifts`)+` · to ${_endLbl}`},"""),

("F4b alerts: low stock by days of cover",
r"""  const outOfStock = stock.filter(x=>(x.qty||0)<=0);
  const lowStock = stock.filter(x=>(x.qty||0)>0 && (x.qty||0)<=2);""",
r"""  const outOfStock = stock.filter(x=>(x.qty||0)<=0);
  const lowStock = stock.filter(x=>(x.qty||0)>0 && _stockLow(x));   // MF_DASH_V5: days of cover"""),

("F4c alerts: low stock text",
r"""desc:lowStock.slice(0,3).map(x=>`${x.name} (${x.qty})`).join(', ')+(lowStock.length>3?'…':''),action:'STOCK',page:'stock'});""",
r"""desc:lowStock.slice(0,3).map(x=>{const c=_stockCover(x);return `${x.name} (${x.qty}${c.days!=null?' ≈'+Math.floor(c.days)+'d':''})`;}).join(', ')+(lowStock.length>3?'…':''),action:'STOCK',page:'stock'});"""),

("H helpers",
r"""function renderDashOverdue(){""",
r"""// MF_DASH_V5 ── helpers ─────────────────────────────────────────────────
function _supplierDues(){
  var fuel=(typeof fuelLoads!=='undefined'?fuelLoads:[]).reduce(function(s,l){
    return s+Math.max(0,(l.totalCost!=null?l.totalCost:(l.amountDue||0))-(l.amountPaid||0));},0);
  var oil=(typeof oilReg!=='undefined'?oilReg:[]).reduce(function(s,i){return s+Math.max(0,+i.amountDue||0);},0);
  return {fuel:_r2(fuel),oil:_r2(oil),total:_r2(fuel+oil)};
}
// Units of an oil item that left the shelf per day over the last 30 days:
// sold in shifts plus whole bottles opened for the loose-oil jar.
function _stockCover(item){
  var from=_daysAgo(30), used=0;
  (records||[]).forEach(function(r){
    if(String(r.date)<from)return;
    (r.stockSold||[]).forEach(function(s){ if(String(s.id)===String(item.id))used+=(+s.qty||0); });
    (Array.isArray(r.looseOpened)?r.looseOpened:[]).forEach(function(o){ if(String(o.id)===String(item.id))used+=(+o.qty||0); });
  });
  var perDay=used/30;
  return {perDay:perDay, days:perDay>0?(item.qty||0)/perDay:null};
}
function _stockLow(item){
  var c=_stockCover(item);
  return c.days!=null ? c.days<10 : (item.qty||0)<=2;
}
var _ALERT_RANK={danger:0,warn:1,info:2,ok:3};
function renderDashOverdue(){"""),

("A5 alerts sorted by severity",
r"""function renderDashAlerts(){
  const alerts=computeAlerts();""",
r"""function renderDashAlerts(){
  const alerts=computeAlerts();
  // MF_DASH_V5: red first, then amber, then info — order within a level kept.
  alerts.forEach(function(a,i){a._i=i;});
  alerts.sort(function(a,b){return ((_ALERT_RANK[a.type]!=null?_ALERT_RANK[a.type]:2)-(_ALERT_RANK[b.type]!=null?_ALERT_RANK[b.type]:2))||(a._i-b._i);});"""),

("A6a chart: profit series",
r"""    const dayRecs = records.filter(r=>r.date===iso);
    msdData.push(dayRecs.reduce((s,r)=>s+(r.msdV||0),0));
    hsdData.push(dayRecs.reduce((s,r)=>s+(r.hsdV||0),0));
  }""",
r"""    const dayRecs = records.filter(r=>r.date===iso);
    msdData.push(dayRecs.reduce((s,r)=>s+(r.msdV||0),0));
    hsdData.push(dayRecs.reduce((s,r)=>s+(r.hsdV||0),0));
    // MF_DASH_V5: net profit for the day; a gap where nothing was saved
    let _p=null; try{ if(dayRecs.length)_p=Math.round(_plCore(dayRecs,iso,iso).netProfit); }catch(e){}
    profitData.push(_p);
  }"""),

("A6b chart: profit array",
r"""  const msdData=[];
  const hsdData=[];""",
r"""  const msdData=[];
  const hsdData=[];
  const profitData=[];   // MF_DASH_V5"""),

("A6c chart: profit dataset",
r"""        {label:'HSD Revenue',data:hsdData,borderColor:'#ffb020',backgroundColor:dieselGrad,borderWidth:2,tension:.35,fill:true,pointRadius:2,pointHoverRadius:5,pointBackgroundColor:'#ffb020'}
      ]""",
r"""        {label:'HSD Revenue',data:hsdData,borderColor:'#ffb020',backgroundColor:dieselGrad,borderWidth:2,tension:.35,fill:true,pointRadius:2,pointHoverRadius:5,pointBackgroundColor:'#ffb020'},
        // MF_DASH_V5: profit on its own scale — it is a tenth of revenue and
        // would be a flat line on the revenue axis.
        {label:'Net profit',data:profitData,yAxisID:'y1',borderColor:'#8ab4ff',backgroundColor:'transparent',borderWidth:2,borderDash:[5,4],tension:.3,fill:false,spanGaps:false,pointRadius:3,pointHoverRadius:6,pointBackgroundColor:'#8ab4ff'}
      ]"""),

("A6d chart: right-hand axis",
r"""        y:{grid:{color:'rgba(47,47,47,.9)'},ticks:{color:'#AAAAAA',font:{family:'JetBrains Mono',size:9},callback:v=>'₹'+(v>=1000?(v/1000).toFixed(0)+'k':v)}}
      }""",
r"""        y:{grid:{color:'rgba(47,47,47,.9)'},ticks:{color:'#AAAAAA',font:{family:'JetBrains Mono',size:9},callback:v=>'₹'+(v>=1000?(v/1000).toFixed(0)+'k':v)}},
        y1:{position:'right',grid:{drawOnChartArea:false},ticks:{color:'#8ab4ff',font:{family:'JetBrains Mono',size:9},
            callback:v=>'₹'+(Math.abs(v)>=1000?(v/1000).toFixed(1)+'k':v)}}   // MF_DASH_V5
      }"""),

("A8a overdue: per-customer days, ageing header, safe link",
r"""function renderDashOverdue(){
  const el=document.getElementById('dashOverdue');
  const today=new Date();today.setHours(0,0,0,0);
  const THRESHOLD_DAYS=14;""",
r"""function renderDashOverdue(){
  const el=document.getElementById('dashOverdue');
  const today=new Date();today.setHours(0,0,0,0);
  const THRESHOLD_DAYS=14;
  // MF_DASH_V5: a customer's own credit-day limit, where one is set
  const _lim=n=>{ try{ const L=_custLimit(n); return L.days>0?L.days:THRESHOLD_DAYS; }catch(e){ return THRESHOLD_DAYS; } };
  const _netOwed={}; [...new Set(ledger.map(e=>e.customer))].forEach(n=>{ _netOwed[n]=_custPosition(n).net; });
  const _T=[0,0,0,0];
  [...new Set(ledger.map(e=>e.customer))].forEach(n=>{ try{ _custAgeing(n).forEach((v,i)=>_T[i]+=v); }catch(e){} });
  const _tot=_T[0]+_T[1]+_T[2]+_T[3];
  const _ageHead=_tot>0.5?'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px">'+
    _T.map((v,i)=>'<div style="background:var(--s3);border-radius:4px;padding:4px;text-align:center;font-family:\'JetBrains Mono\',monospace">'+
      '<div style="font-size:8px;color:var(--muted)">'+_AGE_LBL[i]+'d</div><div style="font-size:11px;font-weight:700;color:'+(v>0.5?_AGE_COL[i]:'var(--muted)')+'">'+
      (v>0.5?'₹'+Math.round(v/1000*10)/10+'k':'—')+'</div></div>').join('')+'</div>':'';"""),

("A8b overdue: use each customer's limit",
r"""    if(ageDays<THRESHOLD_DAYS)return;""",
r"""    if(ageDays<_lim(e.customer))return;   // MF_DASH_V5"""),

("A8c overdue: empty state keeps the ageing",
r"""    el.innerHTML=`<div class="empty-state"><div class="big">✓</div>No customers overdue<br><span style="color:var(--muted)">All credit within 14 days</span></div>`;""",
r"""    el.innerHTML=_ageHead+`<div class="empty-state"><div class="big">✓</div>No customers overdue<br><span style="color:var(--muted)">All credit within each customer's allowed days (14 if not set)</span></div>`;"""),

("A8d overdue: safe link and escaped name",
r"""    return `<div class="overdue-item ${urgent?'urgent':''}" onclick="showPage('ledger');setTimeout(()=>{if(typeof openLedgerDetail==='function')openLedgerDetail(${JSON.stringify(c.name)})},150)">
      <div class="overdue-body">
        <div class="overdue-name">${c.name}</div>""",
r"""    return `<div class="overdue-item ${urgent?'urgent':''}" data-name="${_esc(c.name)}" onclick="var n=this.getAttribute('data-name');showPage('ledger');setTimeout(function(){if(typeof openLedgerDetail==='function')openLedgerDetail(n)},150)">
      <div class="overdue-body">
        <div class="overdue-name">${_esc(c.name)}${_lim(c.name)!==THRESHOLD_DAYS?' <span style="font-size:9px;color:var(--muted)">(limit '+_lim(c.name)+'d)</span>':''}</div>"""),
("A8e overdue: ageing above the list",
r"""  el.innerHTML=overdue.map(c=>{""",
r"""  el.innerHTML=_ageHead+overdue.map(c=>{   // MF_DASH_V5"""),
("A8f overdue: skip customers whose advance covers them",
r"""    const due=(e.amount||0)-(e.paidBack||0);
    if(due<=0)return;
    const entryDate=new Date(e.date+'T00:00:00');""",
r"""    const due=(e.amount||0)-(e.paidBack||0);
    if(due<=0)return;
    if(!(_netOwed[e.customer]>0.5))return;   // MF_DASH_V5: advance covers it
    const entryDate=new Date(e.date+'T00:00:00');"""),

("L1 credit limit: not 'late' when the advance covers it",
r"""  return {L:L, exposure:exp, over:L.limit>0&&exp>L.limit+0.5, late:L.days>0&&age>L.days, age:age, oldest:oldest};""",
r"""  return {L:L, exposure:exp, over:L.limit>0&&exp>L.limit+0.5,
          late:L.days>0&&age>L.days&&exp>0.5, age:age, oldest:oldest};   // MF_DASH_V5: advance covers it"""),
("C1 KPI grid: 3 × 2, no orphan tile",
r""".kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-bottom:14px}""",
r""".kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-bottom:14px}
/* MF_DASH_V5: six dashboard tiles as 3 × 2 (2 × 3 on phones) — auto-fit left one alone on a row */
#kpiGrid{grid-template-columns:repeat(3,minmax(0,1fr))}
@media(max-width:700px){#kpiGrid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:380px){#kpiGrid{grid-template-columns:1fr}}
/* a chart drawn wider (rotation, resize) must not push the page sideways */
.dash-grid>*{min-width:0}"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_LEDGER_V1" not in src:
        sys.exit("✗ Apply patch_ledger_hardening.py (MF_LEDGER_V1) first. Nothing written.")
    out = src
    applied = 0
    for h in HUNKS:
        name, old, new = h[0], h[1], h[2]
        want = h[3] if len(h) > 3 else 1
        if new in out and old not in out.replace(new, ""):
            print(f"  = {name}: already applied")
            continue
        n = out.count(old)
        if n != want:
            sys.exit(f"✗ {name}: anchor found {n} times (expected {want}) — file differs from the traced version. Nothing written.")
        out = out.replace(old, new)
        applied += 1
        print(f"  ✓ {name}")

    if applied == 0:
        print("Nothing to do — patch already applied.")
        return

    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js")
            open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"✗ node --check failed on inline script #{i}:\n{r.stderr}\nNothing written.")
    print(f"  ✓ node --check passed on {len(scripts)} inline script(s)")

    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ {applied} hunk(s) applied to {PATH} (backup: {PATH}.bak) — sentinel {SENTINEL}")


if __name__ == "__main__":
    main()
