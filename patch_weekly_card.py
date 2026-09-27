#!/usr/bin/env python3
"""
MF_WEEKLY_CARD_V2 — dashboard "Profit vs Loss — this week vs last week" card.

Problems in V1
  * A partial week (shifts not entered yet, or lost) was compared against a
    full last week, so the card showed red almost every time.
  * "-325% worse" — a percentage is meaningless once profit changes sign.
  * "expected ~14" counted shifts that had not even closed yet.

V2
  * Headline comparison is PROFIT PER LITRE (₹/L), which missing shifts
    cannot distort. Totals are still shown, underneath.
  * If any closed shift in the window is not saved, the card turns AMBER
    ("incomplete") instead of red, and names the missing shifts.
  * No profit percentage at all; ₹ figures only.
  * Red/green only when the week is complete and the per-litre margin moved.
  * The profit figure itself stays red when it really is a loss.

Usage:  python3 patch_weekly_card.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_WEEKLY_CARD_V2"
START = "function renderWeeklyPL(){"
END = "// ── DATE: always work in LOCAL time."

NEW = r"""function renderWeeklyPL(){
  // MF_WEEKLY_CARD_V2 — compare like with like. The old card set a partial
  // week (unsaved or lost shifts) against a full one and printed "-325% worse",
  // so it was red almost every time. The headline is now profit per litre,
  // which missing shifts cannot distort, and an incomplete week is amber.
  const el=document.getElementById('dashWeeklyPL');
  if(!el)return;
  const now=new Date();
  const today=new Date(now);
  const startThis=new Date(today);startThis.setDate(today.getDate()-6);
  const startLast=new Date(today);startLast.setDate(today.getDate()-13);
  const endLast=new Date(today);endLast.setDate(today.getDate()-7);
  const iso=d=>_isoLocal(d);
  const inRange=(d,from,to)=>d>=iso(from)&&d<=iso(to);

  const recsThis=records.filter(r=>inRange(r.date,startThis,today));
  const recsLast=records.filter(r=>inRange(r.date,startLast,endLast));

  // Each period costed at its OWN period end.
  const _tw=_plCore(recsThis, iso(startThis), iso(today));
  const _lw=_plCore(recsLast, iso(startLast), iso(endLast));
  const shape=c=>{
    const L=(c.soldMSDL||0)+(c.soldHSDL||0);
    return {revenue:c.revenue, profit:c.netProfit, costKnown:!c.fuelUncosted,
            margin:c.netMarginPct, msdL:c.soldMSDL, hsdL:c.soldHSDL,
            litres:L, perL:L>0?c.netProfit/L:0, shifts:c.shifts};
  };
  const tw=shape(_tw), lw=shape(_lw);

  // Shifts that have CLOSED in each window, and which of them are not saved.
  const _slots=(from,to)=>{
    const out=[]; const d=new Date(from);
    while(iso(d)<=iso(to)){
      ['morning','night'].forEach(function(sh){
        const s={date:iso(d),shift:sh};
        if(mfSlotEnd(s)<=now)out.push(s);
      });
      d.setDate(d.getDate()+1);
    }
    return out;
  };
  const closedThis=_slots(startThis,today);
  const missingThis=closedThis.filter(s=>!mfSlotSaved(s));
  const closedLast=_slots(startLast,endLast);
  const missingLast=closedLast.filter(s=>!mfSlotSaved(s));
  const incomplete=missingThis.length>0||missingLast.length>0;
  const _slotTxt=s=>{const p=s.date.split('-');return p[2]+'/'+p[1]+' '+(s.shift==='morning'?'MOR':'NIGHT');};

  const _known=tw.costKnown&&lw.costKnown&&tw.litres>0&&lw.litres>0;
  const dPerL=tw.perL-lw.perL;
  const dProfit=tw.profit-lw.profit;
  const dRev=tw.revenue-lw.revenue;
  const AMBER='var(--diesel)', GREEN='var(--green)', RED='var(--red)', MUTED='var(--muted)';
  // Colour of the comparison: amber whenever either week is incomplete.
  const cmpCol=!_known?MUTED:(incomplete?AMBER:(dPerL>=0?GREEN:RED));
  const cmpBg =!_known?'var(--s3)':(incomplete?'rgba(255,176,32,.06)':(dPerL>=0?'rgba(61,220,132,.05)':'rgba(255,77,106,.05)'));
  const arrow=dPerL>=0?'▲':'▼';
  const perL=n=>(n<0?'−':'')+'₹'+Math.abs(n).toFixed(2)+'/L';
  const profitCol=!_known?MUTED:(tw.profit>=0?GREEN:RED);

  const missNote=missingThis.length
    ? missingThis.length+' closed shift'+(missingThis.length>1?'s':'')+' not saved: '+
      missingThis.slice(0,3).map(_slotTxt).join(', ')+(missingThis.length>3?' …':'')
    : 'all '+closedThis.length+' closed shifts saved';

  el.innerHTML=`
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px">
      <div style="padding:14px;background:var(--s3);border:1px solid var(--border2);border-radius:8px">
        <div style="font-family:'Syne',sans-serif;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">PROFIT THIS WEEK</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:800;color:${profitCol}">${_known?fmt(tw.profit):'—'}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">${_known
          ?('Last week: '+fmt(lw.profit)+(tw.profit<0?' &nbsp;·&nbsp; <span style="color:var(--red)">loss — open Full Reports to see which line</span>':''))
          :'No fuel load costed yet — record a tanker to see profit'}</div>
      </div>
      <div style="padding:14px;background:${cmpBg};border:1px solid ${cmpCol};border-radius:8px">
        <div style="font-family:'Syne',sans-serif;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">PROFIT PER LITRE vs LAST WEEK</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:800;color:${cmpCol}">${_known?(arrow+' ₹'+Math.abs(dPerL).toFixed(2)+'/L'):'—'}</div>
        <div style="font-size:10px;color:${_known?cmpCol:MUTED};margin-top:4px">${_known
          ?(perL(tw.perL)+' this week vs '+perL(lw.perL)+' last week'+
            (incomplete?' &nbsp;·&nbsp; incomplete — totals not comparable':' &nbsp;·&nbsp; total '+(dProfit>=0?'+':'−')+fmt(Math.abs(dProfit))))
          :'profit needs a cost per litre'}</div>
      </div>
      <div style="padding:14px;background:var(--s3);border:1px solid var(--border2);border-radius:8px">
        <div style="font-family:'Syne',sans-serif;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">REVENUE THIS WEEK</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:800;color:var(--text)">${fmt(tw.revenue)}</div>
        <div style="font-size:10px;color:${incomplete?AMBER:(dRev>=0?GREEN:RED)};margin-top:4px">Last week ${fmt(lw.revenue)}${incomplete?' — this week is missing shifts':''}</div>
      </div>
      <div style="padding:14px;background:var(--s3);border:1px solid var(--border2);border-radius:8px">
        <div style="font-family:'Syne',sans-serif;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">VOLUMES THIS WEEK</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--petrol);font-weight:700">MSD: ${tw.msdL.toFixed(0)}L</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--diesel);font-weight:700">HSD: ${tw.hsdL.toFixed(0)}L</div>
        <div style="font-size:10px;color:${missingThis.length?AMBER:MUTED};margin-top:4px">${tw.shifts} of ${closedThis.length} closed shifts saved${missingThis.length?'<br>'+missNote:''}</div>
      </div>
    </div>
  `;
}

"""


def main():
    src = open(PATH, encoding="utf-8").read()
    if SENTINEL in src:
        print("Nothing to do — MF_WEEKLY_CARD_V2 already applied."); return
    a = src.find(START); b = src.find(END)
    if a < 0 or b < 0 or b <= a or src.count(START) != 1:
        sys.exit("✗ renderWeeklyPL boundaries not found exactly once — nothing written.")
    out = src[:a] + NEW + src[b:]
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
