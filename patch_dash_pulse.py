#!/usr/bin/env python3
"""
MF_DASH_PULSE_V3 — replaces the "Profit vs Loss — this week vs last week" card
on the dashboard with three rows:

  B  THIS MONTH      month-to-date profit, same dates last month, projection,
                     profit per litre.
  A  LAST 7 DAYS     one bar per closed day, profit per litre; red day = loss,
                     amber = shifts missing; tap a day to open it in Reports.
  D  MONEY           cash short/over (last 7 days, with the shifts responsible),
                     credit outstanding, supplier dues.

Everything is computed by the same engine as Reports (_plCore) and the same
dues helper as the Order Advisor (_cashPosition), so no figure disagrees
with another screen.

Usage:  python3 patch_dash_pulse.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_DASH_PULSE_V3"
START = "function renderWeeklyPL(){"
END = "// ── DATE: always work in LOCAL time."

TITLE_OLD = '<span class="dot dpu"></span>PROFIT vs LOSS — THIS WEEK vs LAST WEEK</div>'
TITLE_NEW = '<span class="dot dpu"></span>BUSINESS PULSE — THIS MONTH · LAST 7 DAYS · MONEY</div>'

NEW = r"""function renderWeeklyPL(){
  // MF_DASH_PULSE_V3 — month-to-date, a 7-day strip and money health.
  // Replaces the week-vs-week card, which compared a partial week with a full
  // one and was red almost every time. Same engine as Reports (_plCore).
  const el=document.getElementById('dashWeeklyPL');
  if(!el)return;
  const now=new Date();
  const iso=d=>_isoLocal(d);
  const GREEN='var(--green)', RED='var(--red)', AMBER='var(--diesel)', MUTED='var(--muted)';
  const dm=s=>{const p=s.split('-');return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString('en-IN',{day:'numeric',month:'short'});};
  const k=n=>{const a=Math.abs(n),sg=n<0?'−':'';
    return a>=100000?sg+'₹'+(a/100000).toFixed(2)+'L':(a>=1000?sg+'₹'+(a/1000).toFixed(1)+'k':sg+'₹'+Math.round(a));};
  const perLtxt=n=>(n<0?'−':'')+'₹'+Math.abs(n).toFixed(2)+'/L';
  const litres=P=>(P.soldMSDL||0)+(P.soldHSDL||0);
  const slotTxt=s=>{const p=s.date.split('-');return p[2]+'/'+p[1]+' '+(s.shift==='morning'?'MOR':'NIGHT');};
  // Closed shift slots in a date range, and which of them are not saved.
  const slots=(fromIso,toIso)=>{
    const out=[]; const p=fromIso.split('-'); const d=new Date(+p[0],+p[1]-1,+p[2]);
    while(iso(d)<=toIso){
      ['morning','night'].forEach(function(sh){const s={date:iso(d),shift:sh}; if(mfSlotEnd(s)<=now)out.push(s);});
      d.setDate(d.getDate()+1);
    }
    return out;
  };
  const recsIn=(a,b)=>records.filter(r=>r.date>=a&&r.date<=b);
  const tile=(label,val,valCol,sub,subCol,extra)=>
    '<div style="padding:12px 14px;background:var(--s3);border:1px solid '+(extra&&extra.border||'var(--border2)')+';border-radius:8px'+(extra&&extra.click?';cursor:pointer':'')+'"'+
    (extra&&extra.click?' onclick="'+extra.click+'"':'')+'>'+
    '<div style="font-family:\'Syne\',sans-serif;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">'+label+'</div>'+
    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:20px;font-weight:800;color:'+valCol+'">'+val+'</div>'+
    '<div style="font-size:10px;color:'+(subCol||MUTED)+';margin-top:4px;line-height:1.5">'+sub+'</div></div>';
  const band=t=>'<div style="font-family:\'Syne\',sans-serif;font-size:10px;font-weight:700;letter-spacing:1.5px;color:var(--muted);margin:14px 0 8px">'+t+'</div>';
  const grid='display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px';

  // ── B. THIS MONTH ──────────────────────────────────────────────────────
  const todayIso=iso(now);
  const mStart=todayIso.slice(0,8)+'01';
  const lmFirst=new Date(now.getFullYear(),now.getMonth()-1,1);
  const lmLastDay=new Date(now.getFullYear(),now.getMonth(),0).getDate();
  const lmStart=iso(lmFirst);
  const lmEnd=iso(new Date(lmFirst.getFullYear(),lmFirst.getMonth(),Math.min(now.getDate(),lmLastDay)));
  const Pm=_plCore(recsIn(mStart,todayIso),mStart,todayIso);
  const Pl=_plCore(recsIn(lmStart,lmEnd),lmStart,lmEnd);
  const mKnown=!Pm.fuelUncosted&&Pm.shifts>0;
  const lKnown=!Pl.fuelUncosted&&Pl.shifts>0;
  const mMiss=slots(mStart,todayIso).filter(s=>!mfSlotSaved(s));
  const lMiss=slots(lmStart,lmEnd).filter(s=>!mfSlotSaved(s));
  const mL=litres(Pm), lL=litres(Pl);
  const mPerL=mL>0?Pm.netProfit/mL:0, lPerL=lL>0?Pl.netProfit/lL:0;
  const dim=new Date(now.getFullYear(),now.getMonth()+1,0).getDate();
  // Projection per SAVED shift, so a missing shift does not drag it down.
  const perShift=Pm.shifts>0?Pm.netProfit/Pm.shifts:0;
  const proj=perShift*dim*2;
  const early=Pm.shifts<8;
  const mRange=dm(mStart)+' – '+dm(todayIso), lRange=dm(lmStart)+' – '+dm(lmEnd);
  const cmpOk=mKnown&&lKnown;
  const cmpIncomplete=mMiss.length>0||lMiss.length>0;
  const diff=Pm.netProfit-Pl.netProfit;
  const cmpCol=!cmpOk?MUTED:(cmpIncomplete?AMBER:(diff>=0?GREEN:RED));

  let html=band('THIS MONTH — '+mRange.toUpperCase());
  html+='<div style="'+grid+'">'+
    tile('PROFIT SO FAR', mKnown?fmt(Pm.netProfit):'—', mKnown?(Pm.netProfit>=0?GREEN:RED):MUTED,
      mKnown?('Revenue '+k(Pm.revenue)+' · margin '+Pm.netMarginPct.toFixed(2)+'%'+
              (Pm.netProfit<0?'<br><span style="color:var(--red)">loss — open Full Reports to see which line</span>':''))
            :(Pm.shifts?'No fuel load costed yet — record a tanker':'No shift saved this month yet'),
      null)+
    tile('vs SAME DATES LAST MONTH', cmpOk?((diff>=0?'▲ ':'▼ ')+fmt(Math.abs(diff))):'—', cmpCol,
      lKnown?(lRange+': '+fmt(Pl.netProfit)+(cmpIncomplete?'<br>shifts missing — not a fair comparison yet':'')):'No costed data for '+lRange,
      cmpOk&&cmpIncomplete?AMBER:null, {border:cmpOk?cmpCol:null})+
    tile('PROJECTED FULL MONTH', (mKnown&&!early)?fmt(proj):'—', (mKnown&&!early)?(proj>=0?'var(--text)':RED):MUTED,
      !mKnown?'needs costed shifts':(early?'Too early — needs about 4 days of shifts':
        (k(perShift)+' per shift × '+(dim*2)+' shifts in the month')),
      null)+
    tile('PROFIT PER LITRE', mKnown&&mL>0?perLtxt(mPerL):'—', mKnown&&mL>0?(mPerL>=0?GREEN:RED):MUTED,
      mKnown&&mL>0?(Math.round(mL).toLocaleString('en-IN')+' L sold'+(lKnown&&lL>0?' · last month '+perLtxt(lPerL):'')):'—',
      null)+
  '</div>';
  if(mMiss.length){
    html+='<div style="font-size:10px;color:'+AMBER+';margin-top:6px">⚠ '+mMiss.length+' closed shift'+(mMiss.length>1?'s':'')+
      ' this month not saved: '+mMiss.slice(0,4).map(slotTxt).join(', ')+(mMiss.length>4?' …':'')+'</div>';
  }

  // ── A. LAST 7 CLOSED DAYS ──────────────────────────────────────────────
  // A day counts once its night shift has closed (6 PM).
  const lastClosed=new Date(now); if(mfSlotEnd({date:iso(now),shift:'night'})>now)lastClosed.setDate(lastClosed.getDate()-1);
  const days=[];
  for(let i=6;i>=0;i--){
    const d=new Date(lastClosed); d.setDate(lastClosed.getDate()-i);
    const di=iso(d), R=recsIn(di,di), P=_plCore(R,di,di), L=litres(P);
    const saved=['morning','night'].filter(sh=>mfSlotSaved({date:di,shift:sh})).length;
    days.push({date:di, wd:d.toLocaleDateString('en-IN',{weekday:'short'}), dn:d.getDate(),
      saved:saved, known:!P.fuelUncosted&&R.length>0, profit:P.netProfit, perL:L>0?P.netProfit/L:0});
  }
  const maxAbs=Math.max(0.5,...days.filter(d=>d.known).map(d=>Math.abs(d.perL)));
  const H=54;   // px for the tallest bar on either side of zero
  const anyNeg=days.some(d=>d.known&&d.perL<0);
  const bars=days.map(function(d){
    const h=d.known?Math.max(3,Math.round(Math.abs(d.perL)/maxAbs*H)):0;
    const col=!d.known?MUTED:(d.saved<2?AMBER:(d.perL>=0?GREEN:RED));
    const up=d.known&&d.perL>=0;
    const tip=d.date+' — '+(d.known?(perLtxt(d.perL)+', profit '+fmt(d.profit)):'no costed shifts')+(d.saved<2?' ('+d.saved+'/2 shifts saved)':'');
    return '<div title="'+_esc(tip)+'" onclick="_dashOpenDay(\''+d.date+'\')" style="flex:1;min-width:0;cursor:pointer;text-align:center">'+
      '<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;color:'+col+';height:14px">'+(d.known?perLtxt(d.perL).replace('/L',''):'—')+'</div>'+
      '<div style="height:'+H+'px;display:flex;align-items:flex-end;justify-content:center">'+(up?'<div style="width:62%;height:'+h+'px;background:'+col+';border-radius:3px 3px 0 0;opacity:.85"></div>':'')+'</div>'+
      '<div style="height:1px;background:var(--border2)"></div>'+
      (anyNeg?'<div style="height:'+H+'px;display:flex;align-items:flex-start;justify-content:center">'+((!up&&d.known)?'<div style="width:62%;height:'+h+'px;background:'+col+';border-radius:0 0 3px 3px;opacity:.85"></div>':'')+'</div>':'')+
      '<div style="font-size:10px;color:var(--text);margin-top:4px">'+d.wd+' '+d.dn+'</div>'+
      '<div style="font-size:9px;color:'+(d.saved<2?AMBER:MUTED)+'">'+(d.saved<2?d.saved+'/2 shifts':(d.known?k(d.profit):'—'))+'</div>'+
    '</div>';
  }).join('');
  html+=band('LAST 7 DAYS — PROFIT PER LITRE (TAP A DAY TO OPEN IT)');
  html+='<div style="display:flex;gap:6px;padding:10px 8px;background:var(--s3);border:1px solid var(--border2);border-radius:8px">'+bars+'</div>';
  html+='<div style="font-size:9px;color:var(--muted);margin-top:4px">Green = profit · Red = loss · Amber = a shift not saved (the day is not complete)</div>';

  // ── D. MONEY ───────────────────────────────────────────────────────────
  const w0=iso(new Date(lastClosed.getFullYear(),lastClosed.getMonth(),lastClosed.getDate()-6));
  const wRecs=recsIn(w0,iso(lastClosed));
  const shorts=wRecs.filter(r=>(r.bal||0)<-50).sort((a,b)=>(a.bal||0)-(b.bal||0));
  const shortSum=wRecs.reduce((s,r)=>s+Math.min(0,r.bal||0),0);
  const overSum=wRecs.reduce((s,r)=>s+Math.max(0,r.bal||0),0);
  const cp=(typeof _cashPosition==='function')?_cashPosition():{supplierDue:0,creditOut:0};
  const custOwing=new Set(ledger.filter(e=>(e.amount||0)>0&&(e.amount||0)>(e.paidBack||0)).map(e=>e.customer)).size;
  html+=band('MONEY');
  html+='<div style="'+grid+'">'+
    tile('CASH SHORT — LAST 7 DAYS', shortSum<-0.5?fmt(Math.abs(shortSum)):'₹0', shortSum<-500?RED:(shortSum<-0.5?AMBER:GREEN),
      (shorts.length?shorts.slice(0,3).map(r=>slotTxt({date:r.date,shift:r.shift})+' −'+k(Math.abs(r.bal))).join(' · ')+(shorts.length>3?' …':'')
                    :'No shift short by more than ₹50')+
      (overSum>0.5?'<br>Cash over: '+fmt(overSum):'')+
      '<br><span style="color:var(--muted)">Not included in profit</span>',
      null,{border:shortSum<-500?RED:null})+
    tile('CREDIT OUTSTANDING', fmt(cp.creditOut), cp.creditOut>0?AMBER:GREEN,
      custOwing+' customer'+(custOwing!==1?'s':'')+' owe you · tap to open the ledger', null, {click:"showPage('ledger')"})+
    tile('YOU OWE SUPPLIERS', fmt(cp.supplierDue), cp.supplierDue>0?AMBER:GREEN,
      'Fuel loads + oil invoices not yet paid · tap to open', null, {click:"showPage('fuelload')"})+
  '</div>';

  el.innerHTML=html;
}
// Open one day in Reports (profit & loss with workings).
function _dashOpenDay(d){
  const f=document.getElementById('rep_from'), t=document.getElementById('rep_to');
  if(f)f.value=d; if(t)t.value=d;
  showPage('report');
  if(typeof genReport==='function'&&document.getElementById('page-report')&&
     document.getElementById('page-report').classList.contains('active'))genReport();
}

"""


def main():
    src = open(PATH, encoding="utf-8").read()
    if SENTINEL in src:
        print("Nothing to do — MF_DASH_PULSE_V3 already applied."); return
    a = src.find(START); b = src.find(END)
    if a < 0 or b < 0 or b <= a or src.count(START) != 1:
        sys.exit("✗ renderWeeklyPL boundaries not found exactly once — nothing written.")
    out = src[:a] + NEW + src[b:]
    if out.count(TITLE_OLD) == 1:
        out = out.replace(TITLE_OLD, TITLE_NEW)
        print("  ✓ card title updated")
    elif TITLE_NEW not in out:
        sys.exit("✗ card title anchor not found — nothing written.")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js"); open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode:
                sys.exit(f"✗ node --check failed on script #{i}:\n{r.stderr}\nNothing written.")
    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ renderWeeklyPL replaced ({SENTINEL}); node --check passed on {len(scripts)} script(s); backup {PATH}.bak")


if __name__ == "__main__":
    main()
