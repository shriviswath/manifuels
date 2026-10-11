#!/usr/bin/env python3
"""
MF_STATEMENT_EDIT_V1 — a statement can be cut down, never altered.

A statement asked for by sections (patch_custom_report.py) can now be shaped
before it is printed:

  exportPeriodReport({from, to, sections, title,
                      note,       a line printed under the heading
                      hideCost,   leave out cost, margin and profit: those
                                  columns and cards, the price-revision gain
                                  table, and the profit and checks sections
                      drop,       ids of whole tables to leave out
                      orient})    'landscape'

Each of these removes or labels. None changes a figure that stays on the
page: every table is still built from the entries by the same function as the
full report. A statement that leaves something out says so under its heading.

mfReportParts(from, to, sections) lists the tables a statement would hold, so
whoever is choosing — the assistant — can name the one to leave out.

With none of these options the output is exactly what it was.
Needs patch_custom_report.py. Run patch_ai_assistant.py after this one.
No database change. Nothing is written to any record.

Usage:  python3 patch_statement_edit.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_STATEMENT_EDIT_V1"
APPLIED = "function _rvTrim("
NEEDS = "var MF_REPORT_SECTIONS="

ENGINE_ANCHOR = "// ── 4. Printable report for the chosen period ─────────────────────────────\nfunction exportPeriodReport(opt){\n"

HUNKS = [
    ("exportPeriodReport: profit and checks are left out when cost is hidden",
     "  if(!use.length){ showToast('Nothing to print — no such section'); return; }\n",
     "  if(opt.hideCost)use=use.filter(function(s){ return !MF_RV_COST_SECTIONS[s[0]]; });      // MF_STATEMENT_EDIT_V1\n"
     "  if(!use.length){ showToast('Nothing to print — no such section'); return; }\n"
     "  // what was left out, said on the page: a reader must be able to tell an extract from the whole\n"
     "  var cutN=[], dropN=Array.isArray(opt.drop)?opt.drop:[];\n"
     "  if(opt.hideCost)cutN.push('cost, margin and profit figures are not shown');\n"
     "  if(dropN.length){ var lost=[]; mfReportParts(f,t,use.map(function(s){ return s[0]; })).forEach(function(p){ p.tables.forEach(function(x){ if(dropN.indexOf(x.id)>=0)lost.push(x.title); }); });\n"
     "    if(lost.length)cutN.push('left out: '+lost.join('; ')); }\n"
     "  var noteT=String(opt.note==null?'':opt.note).replace(/\\s+/g,' ').trim().slice(0,300);\n"),
    ("exportPeriodReport: the note and what was left out, under the heading",
     "      (bz.gstin?' · GSTIN '+_esc(bz.gstin):'')+'</div></div>'+\n    use.map(function(s,i){\n",
     "      (bz.gstin?' · GSTIN '+_esc(bz.gstin):'')+'</div></div>'+\n"
     "    (noteT?'<p class=\"wk-p wk-note\"><b>Note:</b> '+_esc(noteT)+'</p>':'')+\n"
     "    (cutN.length?'<p class=\"wk-p wk-f wk-cut\">This statement is an extract — '+_esc(cutN.join('; '))+'.</p>':'')+\n"
     "    use.map(function(s,i){\n"),
    ("exportPeriodReport: tables and columns left out as asked",
     "      var out=body[s[0]](), title=(s[0]==='daily'&&span>62)?'Month by month':s[1];\n",
     "      var out=_rvTrim(body[s[0]](),opt), title=(s[0]==='daily'&&span>62)?'Month by month':s[1];\n"),
    ("exportPeriodReport: paper sideways when asked",
     "  _mfPrintArea((bz.name||'Mani Fuels')+' · '+ttl+' · '+_rvDmy(f)+' – '+_rvDmy(t));\n",
     "  _mfPrintArea((bz.name||'Mani Fuels')+' · '+ttl+' · '+_rvDmy(f)+' – '+_rvDmy(t),opt.orient==='landscape'?'landscape':undefined);\n"),
    ("exportPeriodReport: the activity log says how it was shaped",
     "ttl+' '+f+' → '+t+(pick?' ('+use.map(function(s){ return s[0]; }).join(', ')+')':''));\n",
     "ttl+' '+f+' → '+t+(pick?' ('+use.map(function(s){ return s[0]; }).join(', ')+')':'')+\n"
     "    (opt.hideCost?' · cost hidden':'')+(dropN.length?' · without '+dropN.join(', '):'')+(noteT?' · note: '+noteT.slice(0,80):''));\n"),
]

SE_JS = r'''// ══════════════════════════════════════════════════════════════════
// MF_STATEMENT_EDIT_V1 — A STATEMENT CAN BE CUT DOWN, NEVER ALTERED
// A statement asked for by sections (MF_CUSTOM_REPORT_V1) can then be shaped:
// a whole table left out, the cost / margin / profit columns left out, a
// heading, a note, the paper turned sideways. Every one of those removes or
// labels; none of them touches a figure that stays on the page, because the
// page is still printed from the entries by the same functions. A statement
// that leaves something out says so under its heading.
// ══════════════════════════════════════════════════════════════════
var MF_REPORT_BUILD={fuel:'fuel',daily:'table',oil:'oil',credit:'credit',expenses:'exp',dues:'dues',staff:'staff'};
// With cost hidden: these columns and cards go, these tables go whole, and
// "Margin by fuel" is what is left of it — sales by fuel.
var MF_RV_COST_COL=/^(landed cost \/ l|cost of sales|unit cost|cost|net profit|value)$|margin|profit/i;      // "Value" is stock at purchase cost
var MF_RV_COST_CARD=/margin|profit|^average net per day$|^best day$|^weakest day$|^dead stock$|^slow stock$/i;
var MF_RV_COST_DROP={fuel_revisions:1};
var MF_RV_COST_NAME={fuel:'SALES BY FUEL'};
var MF_RV_COST_SECTIONS={profit:1,checks:1};      // nothing would be left of these
function _rvTrim(out,opt){
  if(!out||typeof out!=='object'||!opt)return out;
  var drop=Array.isArray(opt.drop)?opt.drop:[], hide=!!opt.hideCost;
  if(!drop.length&&!hide)return out;
  var res={cards:(out.cards||[]).filter(function(c){ return !(hide&&(MF_RV_COST_CARD.test(String(c[0]||''))||MF_RV_COST_CARD.test(String(c[3]||'')))); }),blocks:[]};
  (out.blocks||[]).forEach(function(b){
    if(b.key&&drop.indexOf(b.key)>=0)return;
    if(!hide){ res.blocks.push(b); return; }
    if(b.key&&MF_RV_COST_DROP[b.key])return;
    var nb={key:b.key,h:(b.key&&MF_RV_COST_NAME[b.key])||b.h,note:b.note}, cutAny=false;
    if(b.tbl){
      var keep=[]; b.tbl.cols.forEach(function(c,i){ if(MF_RV_COST_COL.test(String(c.h||'')))cutAny=true; else keep.push(i); });
      var cut=function(r){ return r?keep.map(function(i){ return r[i]; }):r; };
      nb.tbl={cols:keep.map(function(i){ return b.tbl.cols[i]; }),rows:(b.tbl.rows||[]).map(cut),foot:cut(b.tbl.foot),empty:b.tbl.empty};
    }
    // the note under a table explains its columns; with some gone it would talk about what is not there
    if(nb.note&&(cutAny||/margin|profit|landed cost|purchase price/i.test(nb.note)))nb.note=null;
    res.blocks.push(nb);
  });
  return res;
}
// What a statement of these sections would hold: each section with its tables
// (id and heading), for whoever is choosing what to leave out.
function mfReportParts(from,to,sections,opt){
  var recs=records.filter(function(r){ return r.date>=from&&r.date<=to; }), span=_rvDays(from,to)+1, hide=!!(opt&&opt.hideCost);
  return MF_REPORT_SECTIONS.filter(function(s){ return (sections||[]).indexOf(s[0])>=0&&!(hide&&MF_RV_COST_SECTIONS[s[0]]); }).map(function(s){
    var k=MF_REPORT_BUILD[s[0]], tables=[];
    if(k){
      try{
        var out=RV_BUILD[k].apply(null,k==='dues'?[]:(k==='table'?[from,to,recs,{group:span>62?'month':'day'}]:[from,to,recs]));
        ((hide?_rvTrim(out,{hideCost:true}):out).blocks||[]).forEach(function(b){ if(b.key&&b.tbl)tables.push({id:b.key,title:b.h||b.key}); });
      }catch(e){}
    }
    return {key:s[0],title:(s[0]==='daily'&&span>62)?'Month by month':s[1],tables:tables};
  });
}

'''

def main():
    src = open(PATH, encoding="utf-8").read()
    if APPLIED in src:
        print(f"Nothing to do — {SENTINEL} already applied."); return
    if NEEDS not in src:
        sys.exit("✗ statements by section are not installed — run patch_custom_report.py first. Nothing written.")
    out = src
    for name, old, new in [("engine: _rvTrim + mfReportParts", ENGINE_ANCHOR, SE_JS + ENGINE_ANCHOR)] + HUNKS:
        if out.count(old) != 1:
            sys.exit(f"✗ {name}: anchor found {out.count(old)}× (need exactly 1) — nothing written")
        out = out.replace(old, new)
        print("  ✓", name)

    for must in ("function exportPeriodReport(opt){", "function _rvTrim(", "function mfReportParts(", "RV_BUILD.credit=function(",
                 "function renderReportViews(", "function _creditByFuel(", "function renderStatement(", "initMultiDeviceSync", "function _plCore("):
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
    print("  Next: python3 patch_ai_assistant.py — so the assistant can make these changes when asked.")


if __name__ == "__main__":
    main()
