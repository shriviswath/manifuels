#!/usr/bin/env python3
"""
MF_CUSTOM_REPORT_V1 — a statement with only what was asked for.

"The statement of oil stock, MSD and HSD credit and oil sales for September"
is not a new document: it is three sections of the business report, for those
dates. This lets that be printed as one PDF.

1. exportPeriodReport(opt)
   • opt.sections — print only these, in the report's own order, renumbered:
     profit, fuel, daily, oil, credit, expenses, dues, staff, checks.
   • opt.from / opt.to — the dates, without touching the Reports page.
   • opt.title — the heading and the PDF's name.
   • With no opt (the menu's "Export Report (PDF)"), the report is exactly
     what it was.
   Every section is built by the same function as the full report and the
   Reports page, so a figure cannot differ between them.

2. CUSTOMER CREDIT BY FUEL as a report section, and a view on Reports
   (💳 CREDIT BY FUEL, with CSV): credit given, received and unpaid by petrol
   and diesel, and by customer. Uses _creditByFuel — apply
   patch_credit_by_fuel.py first.

3. ASSISTANT
   "Statement PDF of oil stock, MSD and HSD credit and oil sales for
   September" gives one card and one PDF. That part lives in
   patch_ai_assistant.py: run it after this one.

No database change. Nothing is written to any record.

Usage:  python3 patch_custom_report.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_CUSTOM_REPORT_V1"
APPLIED = "var MF_REPORT_SECTIONS="
NEEDS = "function _creditByFuel("

ENGINE_ANCHOR = "// ── 4. Printable report for the chosen period ─────────────────────────────\nfunction exportPeriodReport(){\n"

SIG_OLD = ("function exportPeriodReport(){\n"
           "  if(typeof _isOwner!=='undefined'&&!_isOwner){ showToast('🔒 Owner access only'); return; }\n"
           "  var f=(document.getElementById('rep_from')||{}).value, t=(document.getElementById('rep_to')||{}).value;\n")
SIG_NEW = ("function exportPeriodReport(opt){\n"
           "  // MF_CUSTOM_REPORT_V1 — opt {from, to, sections, title}: the same report for\n"
           "  // the dates given, with only the sections asked for. No opt: as before.\n"
           "  opt=(opt&&typeof opt==='object'&&!opt.target)?opt:{};\n"
           "  if(typeof _isOwner!=='undefined'&&!_isOwner){ showToast('🔒 Owner access only'); return; }\n"
           "  var f=opt.from||(document.getElementById('rep_from')||{}).value, t=opt.to||(document.getElementById('rep_to')||{}).value;\n")

DOC_OLD = (
    '  var doc=\'<div class="wk"><div class="wk-h"><div class="wk-title">\'+_esc(bz.name||\'Mani Fuels\')+\' — Business report</div>\'+\n'
    '    \'<div class="wk-meta">\'+_esc(_rvDmy(f)+\' to \'+_rvDmy(t))+\' · \'+recs.length+\' shifts · generated \'+\n'
    "      _esc(new Date().toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}))+\n"
    "      ' by '+_esc(_currentUser?(_currentUser.display||_currentUser.username):'—')+\n"
    "      (bz.gstin?' · GSTIN '+_esc(bz.gstin):'')+'</div></div>'+\n"
    '    \'<div class="wk-sec">1. Profit &amp; loss</div>\'+pl+\n'
    "    sec(2,'Petrol vs diesel',safe('fuel',[f,t,recs]))+\n"
    "    sec(3,span>62?'Month by month':'Day by day',safe('table',[f,t,recs,{group:span>62?'month':'day'}]))+\n"
    "    sec(4,'Oil & stock',safe('oil',[f,t,recs]))+\n"
    "    sec(5,'Expenses',safe('exp',[f,t,recs]))+\n"
    "    sec(6,'Dues — as of today',safe('dues',[]))+\n"
    "    sec(7,'Staff on duty vs cash',safe('staff',[f,t,recs]))+\n"
    '    \'<div class="wk-sec">8. Checks — where money can leak</div>\'+checks+\n'
    "    '</div>';\n"
    "  var area=document.getElementById('pdf-print-area'); if(!area){ showToast('Print area missing'); return; }\n"
    '  area.innerHTML=doc;\n'
    "  if(typeof _mfAlignNums==='function')_mfAlignNums(area);\n"
    "  _mfPrintArea((bz.name||'Mani Fuels')+' · Business report · '+_rvDmy(f)+' – '+_rvDmy(t));\n"
    "  if(typeof logActivity==='function')logActivity('export_report','report',null,'Business report '+f+' → '+t);\n"
)
DOC_NEW = (
    '  // MF_CUSTOM_REPORT_V1 — the sections, in print order. With opt.sections only\n'
    '  // those are printed, renumbered. Without, the report as it always was:\n'
    '  // customer credit by fuel is printed on request, not added to it.\n'
    "  var pick=(Array.isArray(opt.sections)&&opt.sections.length)?opt.sections:null, ttl=opt.title||'Business report';\n"
    "  var use=MF_REPORT_SECTIONS.filter(function(s){ return pick?pick.indexOf(s[0])>=0:s[0]!=='credit'; });\n"
    "  if(!use.length){ showToast('Nothing to print — no such section'); return; }\n"
    '  var body={\n'
    '    profit:function(){ return pl; }, checks:function(){ return checks; },\n'
    "    fuel:function(){ return safe('fuel',[f,t,recs]); },\n"
    "    daily:function(){ return safe('table',[f,t,recs,{group:span>62?'month':'day'}]); },\n"
    "    oil:function(){ return safe('oil',[f,t,recs]); },\n"
    "    credit:function(){ return safe('credit',[f,t,recs]); },\n"
    "    expenses:function(){ return safe('exp',[f,t,recs]); },\n"
    "    dues:function(){ return safe('dues',[]); },\n"
    "    staff:function(){ return safe('staff',[f,t,recs]); }};\n"
    '  var doc=\'<div class="wk"><div class="wk-h"><div class="wk-title">\'+_esc(bz.name||\'Mani Fuels\')+\' — \'+_esc(ttl)+\'</div>\'+\n'
    '    \'<div class="wk-meta">\'+_esc(_rvDmy(f)+\' to \'+_rvDmy(t))+\' · \'+recs.length+\' shifts · generated \'+\n'
    "      _esc(new Date().toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}))+\n"
    "      ' by '+_esc(_currentUser?(_currentUser.display||_currentUser.username):'—')+\n"
    "      (bz.gstin?' · GSTIN '+_esc(bz.gstin):'')+'</div></div>'+\n"
    '    use.map(function(s,i){\n'
    "      var out=body[s[0]](), title=(s[0]==='daily'&&span>62)?'Month by month':s[1];\n"
    '      return typeof out===\'string\'?\'<div class="wk-sec">\'+(i+1)+\'. \'+_esc(title)+\'</div>\'+out:sec(i+1,title,out);\n'
    "    }).join('')+\n"
    "    '</div>';\n"
    "  var area=document.getElementById('pdf-print-area'); if(!area){ showToast('Print area missing'); return; }\n"
    '  area.innerHTML=doc;\n'
    "  if(typeof _mfAlignNums==='function')_mfAlignNums(area);\n"
    "  _mfPrintArea((bz.name||'Mani Fuels')+' · '+ttl+' · '+_rvDmy(f)+' – '+_rvDmy(t));\n"
    "  if(typeof logActivity==='function')logActivity('export_report','report',null,ttl+' '+f+' → '+t+(pick?' ('+use.map(function(s){ return s[0]; }).join(', ')+')':''));\n"
)

CR_JS = r'''// ══════════════════════════════════════════════════════════════════
// MF_CUSTOM_REPORT_V1 — A STATEMENT WITH ONLY WHAT WAS ASKED FOR
// "The statement of oil stock, MSD and HSD credit and oil sales for
// September" is not a new document. It is three sections of the business
// report, for those dates. exportPeriodReport(opt) prints the sections named
// in opt.sections, in the report's own order, renumbered — each built by the
// same RV_BUILD function as the full report and the Reports page, so a figure
// cannot differ between the three.
// Customer credit by fuel becomes a section here and a view on Reports.
// ══════════════════════════════════════════════════════════════════
var MF_REPORT_SECTIONS=[['profit','Profit & loss'],['fuel','Petrol vs diesel'],['daily','Day by day'],['oil','Oil & stock'],
  ['credit','Customer credit — by fuel'],['expenses','Expenses'],['dues','Dues — as of today'],['staff','Staff on duty vs cash'],
  ['checks','Checks — where money can leak']];
RV_TABS.push(['credit','💳 CREDIT BY FUEL']);
RV_BUILD.credit=function(from,to){
  var B=_creditByFuel(from,to);
  var row=function(k){ return B.rows.filter(function(r){ return r.key===k; })[0]||{given:0,bills:0,recv:0,unpaid:0}; };
  var has=function(k){ return B.rows.some(function(r){ return r.key===k; }); }, M=row('MSD'), H=row('HSD');
  var bills=function(n){ return n+' bill'+(n!==1?'s':''); };
  var cols=MF_CREDIT_FUELS.filter(function(d){ return d[0]==='MSD'||d[0]==='HSD'||B.customers.some(function(c){ return Math.abs(c.by[d[0]]||0)>0.005; }); });
  var given={}; B.customers.forEach(function(c){ given[c.name]=c; });
  var names=Object.keys(given); Object.keys(B.received).forEach(function(n){ if(!given[n]&&Math.abs(B.received[n])>0.005)names.push(n); });
  var ct={}, rT=0, last=cols.length+1;
  var rows=names.map(function(n){
    var c=given[n]||{by:{},total:0}, rc=B.received[n]||0, net=_custPosition(n).net;
    cols.forEach(function(d){ ct[d[0]]=(ct[d[0]]||0)+(c.by[d[0]]||0); }); rT+=rc;
    return [n].concat(cols.map(function(d){ return c.by[d[0]]||null; }),
      [c.total||null, rc||null, net<-0.5?{v:net,s:_rvMoney(-net)+' adv'}:(Math.abs(net)<=0.5?{v:0,s:'settled'}:{v:net,s:_rvMoney(net),c:'var(--diesel)'})]);
  }).sort(function(a,b){ return (b[last]||0)-(a[last]||0)||String(a[0]).localeCompare(String(b[0])); });
  return {cards:[['Credit given',_rvMoney(B.tot.given),'var(--diesel)',bills(B.tot.bills)+' in the period'],
                 ['Petrol (MSD)',_rvMoney(M.given),'var(--petrol)',bills(M.bills)],
                 ['Diesel (HSD)',_rvMoney(H.given),'var(--diesel)',bills(H.bills)],
                 ['Received against bills',_rvMoney(B.tot.recv),'var(--green)','in the period'],
                 ['Unpaid today',_rvMoney(B.tot.unpaid),B.tot.unpaid>0.5?'var(--red)':'var(--muted)','all bills, whenever raised'],
                 ['Advances held',_rvMoney(B.held),'var(--blue)',B.net>=0?'net owed to you '+_rvMoney(B.net):'more held in advance than owed, by '+_rvMoney(-B.net)]],
    blocks:[{key:'credit_fuel', h:'CREDIT BY FUEL',
      note:'Read from the ledger, not estimated: each credit bill is saved with its fuel, and each payment with the bill it settled. Unpaid today is on every bill, whenever it was raised.'+
        (has('MIX')?' Bills saved as “MSD/HSD” were never split between petrol and diesel, and cannot be split now.':'')+
        (has('NONE')?' “Not recorded against a bill” is money received that was not saved against a particular bill.':''),
      tbl:{cols:[{h:'Fuel on the bill',t:'t'},{h:'Bills',t:'n'},{h:'Credit given',t:'m'},{h:'Received',t:'m'},{h:'Unpaid today',t:'m'}],
        rows:B.rows.map(function(r){ return [r.label,r.bills||null,r.given||null,r.recv||null,r.unpaid||null]; }),
        foot:['Total',B.tot.bills,B.tot.given,B.tot.recv,B.tot.unpaid]}},
     {key:'credit_customers', h:'BY CUSTOMER — CREDIT GIVEN AND RECEIVED IN THE PERIOD',
      note:'“Owes today” is net of any advance held, and is as of today — not as of the last day of the period.',
      tbl:{cols:[{h:'Customer',t:'t'}].concat(cols.map(function(d){ return {h:d[2],t:'m'}; }),[{h:'Total given',t:'m'},{h:'Received',t:'m'},{h:'Owes today',t:'m'}]),
        rows:rows, foot:rows.length?['Total'].concat(cols.map(function(d){ return ct[d[0]]||null; }),[B.tot.given||null,rT||null,null]):null,
        empty:'No credit was given or received in this period.'}}]};
};

'''

def main():
    src = open(PATH, encoding="utf-8").read()
    if APPLIED in src:
        print(f"Nothing to do — {SENTINEL} already applied."); return
    if NEEDS not in src:
        sys.exit("✗ credit by fuel is not installed — run patch_credit_by_fuel.py first. Nothing written.")
    out = src

    for name, old, new in (
        ("engine: report sections + credit by fuel as a section and a Reports view", ENGINE_ANCHOR, CR_JS + ENGINE_ANCHOR),
        ("exportPeriodReport: takes the dates and the sections", SIG_OLD, SIG_NEW),
        ("exportPeriodReport: prints the chosen sections, renumbered", DOC_OLD, DOC_NEW),
    ):
        if out.count(old) != 1:
            sys.exit(f"✗ {name}: anchor found {out.count(old)}× (need exactly 1) — nothing written")
        out = out.replace(old, new)
        print("  ✓", name)

    # post-state: nothing that must survive was lost
    for must in ("function exportPeriodReport(opt){", "RV_BUILD.credit=function(", "RV_BUILD.oil=function(", "RV_BUILD.dues=function(",
                 "function renderReportViews(", "function _rvTblHtml(", "function _creditByFuel(", "function renderStatement(",
                 "initMultiDeviceSync", "function _plCore("):
        if must not in out:
            sys.exit(f"✗ post-check: '{must}' missing after patch — nothing written")

    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js"); open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode:
                sys.exit(f"✗ node --check failed on script #{i}:\n{r.stderr}\nNothing written.")
    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ {SENTINEL} applied; node --check passed on {len(scripts)} script(s); backup {PATH}.bak")
    print("  Next: python3 patch_ai_assistant.py — so the assistant can hand out these statements.")


if __name__ == "__main__":
    main()
