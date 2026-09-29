#!/usr/bin/env python3
"""
MF_PACK_CARRY_V1 — carry the 40 ml (and every pack size) opening properly.

What was there: CARRY OPENING and the automatic fill already copied the 40 ml
closing into the opening — but quietly, and in two cases wrongly:

  1 WRONG SHIFT  For a MORNING shift, the NIGHT shift of the same date was
                 taken as "the shift before" (it is the shift AFTER: morning of
                 D is 6 PM D-1 → 9 AM D). Entering a missed morning after the
                 night was saved carried the wrong readings — meters, loose
                 oil and packs alike. Now morning of D follows night of D-1.
  2 STALE COUNT  If the last shift saved no 40 ml closing, the fill silently
                 took an older shift's count — days old — and the packs sold
                 in between vanished. It now fills automatically only from the
                 shift immediately before; an older count is offered, not used.

NEW
  • Under each pack card's OPENING: "Last shift (28/09 NIGHT) closed at 30
    packs" with a USE button, ✓ when the opening matches, or a clear note
    when the last shift has no count.
  • Labels read "OPENING (packs) — last shift's closing", like loose oil.

Usage:  python3 patch_pack_carry.py [path/to/index.html]   (idempotent)
Requires MF_TANK_PACK_V1 and MF_OPENING_SLOT_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_PACK_CARRY_V1"

HUNKS = [
("1 the shift before a morning is the night before",
r"""(r.date===d&&r.shift!==shift)""",
r"""(r.date===d&&_shiftRank(r.shift)<_shiftRank(shift))""",
4),

("2 40 ml label",
r"""            <div><label>OPENING (packs)</label><input type="number" id="pack_prev" placeholder="0" oninput="calc()"></div>""",
r"""            <div><label>OPENING (packs) — last shift's closing</label><input type="number" id="pack_prev" placeholder="0" oninput="calc()"></div>"""),

("3 other sizes label",
r"""        <div><label>OPENING (packs)</label><input type="number" id="pack${ps.size}_prev" placeholder="0" oninput="calc()"></div>""",
r"""        <div><label>OPENING (packs) — last shift's closing</label><input type="number" id="pack${ps.size}_prev" placeholder="0" oninput="calc()"></div>"""),

("4 automatic fill only from the shift just before",
r"""  // MF_TANK_PACK_V1: 40 ml counter starts where the last shift left it.
  const _pp=(typeof _lastPackClose==='function')?_lastPackClose():null;
  if(_pp){
    const _pv=parseFloat(_pp.meters.pack_cur);
    const _pe=document.getElementById('pack_prev');
    if(_pe&&isFinite(_pv)&&(silent?!_pe.value:true)){_pe.value=_pv;n++;}
  }
  // MF_OPENING_SLOT_V1: the other pack sizes too.
  (typeof packSizesConfig!=='undefined'?packSizesConfig:[]).filter(function(p){return p.enabled;}).forEach(function(p){
    const cv=_lastPackCloseFor(p.size), el=document.getElementById('pack'+p.size+'_prev');
    if(el&&cv!=null&&isFinite(cv)&&(silent?!el.value:true)){el.value=cv;n++;}
  });""",
r"""  // MF_TANK_PACK_V1 / MF_PACK_CARRY_V1: each pack counter starts where the
  // shift before left it. Filled by itself only from the shift immediately
  // before; an older count is offered under the card, never slipped in.
  [40].concat((typeof packSizesConfig!=='undefined'?packSizesConfig:[]).filter(function(p){return p.enabled;}).map(function(p){return +p.size;}))
    .forEach(function(sz){
      const ci=_packCloseInfo(sz), el=document.getElementById(sz===40?'pack_prev':'pack'+sz+'_prev');
      if(!el||!ci.rec||!isFinite(ci.val))return;
      if(silent&&(el.value||!ci.isPrev))return;
      el.value=ci.val; n++;
    });"""),

("5 hints drawn with the 40 ml line",
r"""function _pack40Hint(){
  var h=document.getElementById('pack_units_hint'); if(!h)return;""",
r"""function _pack40Hint(){
  try{ if(typeof _renderPackCarryHints==='function')_renderPackCarryHints(); }catch(e){ console.warn('pack carry hint:',e); }   // MF_PACK_CARRY_V1
  var h=document.getElementById('pack_units_hint'); if(!h)return;"""),

("6 carry helpers",
r"""// MF_OPENING_SLOT_V1: opening/closing for every enabled extra pack size.
function _packExtraReadings(){""",
r"""// ── MF_PACK_CARRY_V1 ────────────────────────────────────────────────────
// The saved shift immediately before the one on the form.
function _prevShiftRec(){
  const d=document.getElementById('shiftDate')?.value||'';
  const prior=records.filter(r=>r.date&&(r.date<d||(r.date===d&&_shiftRank(r.shift)<_shiftRank(shift))))
    .sort((a,b)=>String(b.date).localeCompare(String(a.date))||(_shiftRank(b.shift)-_shiftRank(a.shift)));
  return prior.length?prior[0]:null;
}
// Last saved closing count for a pack size: which shift, how many, and
// whether that shift is the one immediately before.
function _packCloseInfo(size){
  const d=document.getElementById('shiftDate')?.value||'', sz=+size;
  const val=function(r){ if(!r.meters)return NaN; const v=sz===40?r.meters.pack_cur:(r.meters.packs&&r.meters.packs[sz]?r.meters.packs[sz].cur:null);
    return (v==null||v==='')?NaN:parseFloat(v); };
  const has=function(r){ return isFinite(val(r)); };
  const prior=records.filter(r=>has(r)&&(r.date<d||(r.date===d&&_shiftRank(r.shift)<_shiftRank(shift))))
    .sort((a,b)=>String(b.date).localeCompare(String(a.date))||(_shiftRank(b.shift)-_shiftRank(a.shift)));
  const prev=_prevShiftRec(), rec=prior.length?prior[0]:null;
  return {rec:rec, val:rec?val(rec):NaN, prev:prev, isPrev:!!(rec&&prev&&rec.id===prev.id)};
}
function _slotTxt(r){ return r?String(r.date).slice(8,10)+'/'+String(r.date).slice(5,7)+' '+(r.shift==='night'?'NIGHT':'MORNING'):''; }
function usePackCarry(size){
  const ci=_packCloseInfo(size), el=document.getElementById(+size===40?'pack_prev':'pack'+size+'_prev');
  if(!el||!ci.rec)return;
  el.value=ci.val; calc();
  showToast('✓ '+size+' ml opening set to '+ci.val+' — the closing of '+_slotTxt(ci.rec));
}
function _renderPackCarryHints(){
  document.querySelectorAll('.pack-size-card').forEach(function(card){
    const sz=+(card.getAttribute('data-pack-size')||40);
    const el=document.getElementById(sz===40?'pack_prev':'pack'+sz+'_prev'); if(!el)return;
    let h=card.querySelector('.pack-carry-hint');
    if(!h){ h=document.createElement('div'); h.className='pack-carry-hint';
      h.style.cssText="font-family:'JetBrains Mono',monospace;font-size:10px;margin:2px 0 6px;line-height:1.5";
      const rg=card.querySelector('.rg'); if(rg&&rg.nextSibling)card.insertBefore(h,rg.nextSibling); else card.appendChild(h); }
    const ci=_packCloseInfo(sz), cur=el.value===''?null:parseFloat(el.value);
    const btn='<button class="btn btn-g" style="padding:1px 8px;font-size:9px;margin-left:6px" onclick="usePackCarry('+sz+')">USE '+ci.val+'</button>';
    if(!ci.rec){ h.style.color='var(--muted)'; h.innerHTML='No earlier closing count for '+sz+' ml — count the counter and type the opening.'; return; }
    if(ci.isPrev){
      if(cur!=null&&Math.abs(cur-ci.val)<0.5){ h.style.color='var(--green)'; h.innerHTML='✓ Carried from '+_slotTxt(ci.rec)+' closing ('+ci.val+' packs)'; return; }
      h.style.color=cur==null?'var(--muted)':'var(--diesel)';
      h.innerHTML=(cur==null?'↻ ':'⚠ ')+_slotTxt(ci.rec)+' closed at <b>'+ci.val+'</b> packs'+(cur!=null?' — opening differs by '+(cur-ci.val>0?'+':'')+(cur-ci.val)+' packs':'')+btn;
      return;
    }
    h.style.color='var(--diesel)';
    h.innerHTML='⚠ '+_slotTxt(ci.prev)+' saved no '+sz+' ml closing. Last count: <b>'+ci.val+'</b> packs on '+_slotTxt(ci.rec)+
      ' — packs sold since then are not in any shift.'+(cur==null||Math.abs(cur-ci.val)>=0.5?btn:'');
  });
}
// MF_OPENING_SLOT_V1: opening/closing for every enabled extra pack size.
function _packExtraReadings(){"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    for need in ("MF_TANK_PACK_V1", "MF_OPENING_SLOT_V1"):
        if need not in src:
            sys.exit(f"✗ {need} is not in {PATH} — apply that patch first. Nothing written.")
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
