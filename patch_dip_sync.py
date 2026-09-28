#!/usr/bin/env python3
"""
MF_DIP_SYNC_V1 — dips stuck in "unsent"; dashboard ignores today's dips.

Problem 1 — "duplicate key value violates unique constraint dip_readings_unique_slot"
  The server allows one dip per (station, date, slot, tank). Deletes are soft
  (db/013): the deleted row stays and still holds that slot. A dip re-entered
  for the same slot — or entered on a second device — gets a NEW id, the
  upsert (conflict on id) collides with the old row, and it sits in the outbox
  retrying forever. Every sync re-sends it and fails again.
  S1 _sbDipUpsert(): on that conflict, look up the row holding the slot, take
     its id (reviving it if it was deleted), write the new reading, and re-key
     the local copy. Last reading for a slot wins — same as "Replace it?".
  S2 sbSaveDip()   : goes through it.
  S3 _outboxFlush(): parked dip jobs go through it too, so the two already
     stuck on your device clear themselves on the next sync.

Problem 2 — dashboard does not change after a dip
  The Dip page defaulted to "Day open" = 6 PM the evening BEFORE the date.
  A dip taken this afternoon and left on "Day open" sits before an opening
  measured "after Morning shift (9 AM)", and the opening (the later
  measurement) wins, so the dip is ignored.
  D1 Dip page slots relabelled to the station's shift times, preview re-runs
     when the slot changes.
  D2 Slot defaults to the time of day (before 3 PM → shift change 9 AM,
     after → after Night shift 6 PM).
  D3 Preview warns when the dip is timed before the opening point.
  D4 Dip table marks such dips "not used".
  D5 Dashboard says so under the tank instead of silently ignoring it.
  D6 Two dips at the same point: the one recorded last wins.

Usage:  python3 patch_dip_sync.py [path/to/index.html]
Idempotent. Requires MF_OPENING_SLOT_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_DIP_SYNC_V1"

HUNKS = [
# ───────── sync ─────────
("S1+S2 sbSaveDip via conflict-safe upsert",
"""async function sbSaveDip(d){
  if(!_currentUser) return;
  await _sbUpsert('dip_readings', {
    id:d.id, user_id:_currentUser.id, date:d.date, slot:d.slot, type:d.type,
    dip_cm:d.dipCm||null, observed_l:d.observed||0, book_l:d.book||0,
    variation_l:d.variation||0, notes:d.notes||'',
    created_by:_currentUser.username, saved_at:d.savedAt||new Date().toISOString()
  });
}""",
"""// MF_DIP_SYNC_V1: one dip per (station, date, slot, tank) on the server, and a
// soft-deleted row still holds its slot. A dip entered again for that slot has
// a new id and used to bounce off the unique index forever. Take over the row
// that holds the slot instead (reviving it if deleted) and re-key our copy.
async function _sbDipUpsert(row){
  const payload=Object.assign({},row);
  if(MF_SOFT_DEL['dip_readings']!==false)payload.deleted_at=null;
  let r=await _supa.from('dip_readings').upsert(payload,{onConflict:'id'});
  if(r.error&&payload.deleted_at===null&&_isMissingCol(r.error.message)){
    MF_SOFT_DEL['dip_readings']=false; delete payload.deleted_at;
    r=await _supa.from('dip_readings').upsert(payload,{onConflict:'id'});
  }
  if(!r.error||!/unique_slot|duplicate key/i.test(String(r.error.message||'')))return r;
  const q=await _supa.from('dip_readings').select('id')
    .eq('user_id',payload.user_id).eq('date',payload.date)
    .eq('slot',payload.slot).eq('type',payload.type).limit(1);
  if(q.error||!q.data||!q.data.length)return r;
  const sid=q.data[0].id;
  if(String(sid)===String(payload.id))return r;
  const oldId=payload.id; payload.id=sid;
  r=await _supa.from('dip_readings').upsert(payload,{onConflict:'id'});
  if(!r.error)_dipRekey(oldId,sid);
  return r;
}
function _dipRekey(oldId,newId){
  if(typeof dipReadings!=='undefined'){
    const mine=dipReadings.find(function(x){return String(x.id)===String(oldId);});
    if(mine){
      dipReadings=dipReadings.filter(function(x){return x===mine||String(x.id)!==String(newId);});
      mine.id=newId; saveDipsLS();
    }
  }
  if(typeof _tombDel==='function')_tombDel('dip_readings',newId);
  if(typeof renderDip==='function'&&document.getElementById('dip_body'))renderDip();
}
async function sbSaveDip(d){
  if(!_currentUser) return;
  const row={
    id:d.id, user_id:_currentUser.id, date:d.date, slot:d.slot, type:d.type,
    dip_cm:d.dipCm||null, observed_l:d.observed||0, book_l:d.book||0,
    variation_l:d.variation||0, notes:d.notes||'',
    created_by:_currentUser.username, saved_at:d.savedAt||new Date().toISOString()
  };
  if(!_supa||(typeof navigator!=='undefined'&&navigator.onLine===false)){
    _outboxQueue('dip_readings','upsert',[row],null,'offline'); return;
  }
  let r;
  try{ r=await _sbDipUpsert(row); }catch(e){ r={error:{message:String(e.message||e)}}; }
  if(r&&r.error){
    console.warn('Dip queued for retry:',r.error.message);
    _outboxQueue('dip_readings','upsert',[row],null,r.error.message);
  }
}"""),

("S3 outbox: parked dips use the same path",
"""      } else {
        const r=await _supa.from(job.table).upsert(job.rows,{onConflict:_conflictKey(job.table)});
        error=r.error;
      }""",
"""      } else if(job.table==='dip_readings'&&typeof _sbDipUpsert==='function'){
        // MF_DIP_SYNC_V1: a dip parked on the unique-slot conflict clears here.
        for(const row of (job.rows||[])){
          const r=await _sbDipUpsert(row);
          if(r&&r.error){ error=r.error; break; }
        }
      } else {
        const r=await _supa.from(job.table).upsert(job.rows,{onConflict:_conflictKey(job.table)});
        error=r.error;
      }"""),

# ───────── dip timing ─────────
("D1 dip slots: station shift times",
"""          <select id="dip_slot" style="width:100%;padding:5px 9px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px">
            <option value="open">Day open</option>
            <option value="mid">Shift change</option>
            <option value="close">Day close</option>""",
"""          <select id="dip_slot" onchange="dipPreview()" style="width:100%;padding:5px 9px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px">
            <!-- MF_DIP_SYNC_V1: named by the station's shift times -->
            <option value="open">Before Morning shift (6 PM, day before)</option>
            <option value="mid">Shift change (9 AM)</option>
            <option value="close">After Night shift (6 PM)</option>"""),

("D2a helpers + default slot",
"""function dipResetForm(){""",
"""// MF_DIP_SYNC_V1 ─────────────────────────────────────────────────────────
var _DIP_SLOT_LBL={open:'before Morning shift (6 PM, day before)',mid:'shift change (9 AM)',close:'after Night shift (6 PM)'};
// The old default, "Day open", is 6 PM the evening BEFORE the date — a dip
// taken in the afternoon and left on it landed a whole shift too early.
function _dipDefaultSlot(){ return new Date().getHours()<15?'mid':'close'; }
// Is this dip timed before the opening measurement (so the opening is used)?
function _dipBeforeOpening(d){
  var asOf=(typeof _openingAsOf==='function')?_openingAsOf():''; if(!asOf||!d)return false;
  var r=_slotRank((typeof _openingAsOfSlot==='function')?_openingAsOfSlot():'open');
  return _posCmp(d.date,_slotRank(d.slot),asOf,r)<0;
}
// Dips on or after the opening DATE that are timed before its point — the
// ones someone expects to count and that are silently not used.
function _dipsHiddenByOpening(type){
  var asOf=(typeof _openingAsOf==='function')?_openingAsOf():''; if(!asOf)return [];
  return (typeof dipReadings!=='undefined'?dipReadings:[]).filter(function(d){
    return (!type||d.type===type)&&String(d.date)>=asOf&&_dipBeforeOpening(d);
  });
}
function dipResetForm(){"""),

("D2b reset form: default slot",
"""  var d=document.getElementById('dip_date'); if(d)d.value=_isoLocal();
  dipPreview();
}""",
"""  var d=document.getElementById('dip_date'); if(d)d.value=_isoLocal();
  var s=document.getElementById('dip_slot'); if(s)s.value=_dipDefaultSlot();   // MF_DIP_SYNC_V1
  dipPreview();
}"""),

("D2c first render: default slot",
"""  var d=document.getElementById('dip_date'); if(d&&!d.value)d.value=_isoLocal();

  var rows=_dipSorted();""",
"""  var d=document.getElementById('dip_date');
  if(d&&!d.value){ d.value=_isoLocal();
    var _s=document.getElementById('dip_slot'); if(_s)_s.value=_dipDefaultSlot(); }   // MF_DIP_SYNC_V1

  var rows=_dipSorted();"""),

("D3 preview: warn when timed before the opening",
"""  if(he)he.textContent=type+' book: '+b.book.toFixed(0)+' L';
  if(be)be.textContent=b.book.toFixed(3)+' L';""",
"""  if(he)he.textContent=type+' book: '+b.book.toFixed(0)+' L';
  if(be)be.textContent=b.book.toFixed(3)+' L';
  // MF_DIP_SYNC_V1
  if(he&&_dipBeforeOpening({date:date,slot:slot})){
    he.textContent='⚠ Timed before the opening ('+_openingAsOf()+', '+_DIP_SLOT_LBL[_openingAsOfSlot()]+
      ') — it will not be used. Pick a later WHEN.';
  }"""),

("D4 dip table: mark dips not used",
"""      '<td style="color:var(--muted);font-size:11px">'+_esc(r.notes||'')+'</td>'+""",
"""      '<td style="color:var(--muted);font-size:11px">'+_esc(r.notes||'')+
        (_dipBeforeOpening(r)?' <span style="color:var(--diesel)">· before opening — not used</span>':'')+'</td>'+   // MF_DIP_SYNC_V1"""),

("D5 dashboard: say when a dip is ignored",
"""    const bad = lvl<0 || (cap>0 && lvl>cap*1.02);
    let warn='';""",
"""    const bad = lvl<0 || (cap>0 && lvl>cap*1.02);
    let warn='';
    // MF_DIP_SYNC_V1: a dip that is timed before the opening is not used.
    const _hid=(typeof _dipsHiddenByOpening==='function')?_dipsHiddenByOpening(cls==='msd'?'MSD':'HSD'):[];
    if(_hid.length&&!bad){
      const _h=_hid[_hid.length-1];
      warn='<div style="font-size:10px;color:var(--diesel);margin-top:4px;line-height:1.5">⚠ Dip of '+_esc(_h.date)+
        ' ('+_esc(_DIP_SLOT_LBL[_h.slot]||_h.slot)+') is timed before the opening, so it is not used. '+
        'Re-enter it on the Dip page as “Shift change (9 AM)” or later.</div>';
    }"""),

("D6 same point: last recorded dip wins",
"""    if(!best||_posCmp(d.date,_slotRank(d.slot),best.date,_slotRank(best.slot))>0)best=d;""",
"""    var _c=best?_posCmp(d.date,_slotRank(d.slot),best.date,_slotRank(best.slot)):1;
    // MF_DIP_SYNC_V1: two dips at the same point — the one recorded last wins.
    if(_c>0||(_c===0&&String(d.savedAt||'')>String(best.savedAt||'')))best=d;"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_OPENING_SLOT_V1" not in src:
        sys.exit("✗ Apply patch_opening_slot_packs.py (MF_OPENING_SLOT_V1) first. Nothing written.")
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
