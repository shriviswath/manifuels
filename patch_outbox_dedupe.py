#!/usr/bin/env python3
"""
MF_OUTBOX_DEDUPE_V1 — the outbox piles up copies of the same row.

Cause: every sync re-sends local-only rows. When the server rejects one, a NEW
outbox job is appended each time, so two stuck dips became 24 jobs, each
retried separately (and each counted toward the 20-try give-up on its own).

Fix
  Q1 _outboxQueue : an upsert for a row already waiting replaces the older
                    job instead of adding another (newest payload wins —
                    upsert is idempotent, so nothing is lost).
  Q2 _outboxFlush : compacts an existing queue first, so the copies already
                    on a phone collapse to one job per row.

Usage:  python3 patch_outbox_dedupe.py [path/to/index.html]   (idempotent)
"""
import shutil, subprocess, sys, re, os, tempfile
PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_OUTBOX_DEDUPE_V1"
HUNKS = [
("Q1 _outboxQueue: replace, don't append",
"""function _outboxQueue(table, op, rows, key, why){
  const q=_outboxRead();
  q.push({""",
"""// MF_OUTBOX_DEDUPE_V1: one waiting job per row. Key = table + row key.
function _outboxRowKey(job){
  if(!job||job.op!=='upsert'||!Array.isArray(job.rows)||job.rows.length!==1)return null;
  const r=job.rows[0]||{}, k=_conflictKey(job.table).split(',');
  const v=k.map(function(c){return r[c];});
  if(v.some(function(x){return x==null;}))return null;
  return job.table+'|'+v.join('|');
}
function _outboxCompact(q){
  const seen={}, out=[];
  for(let i=q.length-1;i>=0;i--){            // newest last in the queue: keep it
    const k=_outboxRowKey(q[i]);
    if(k){ if(seen[k])continue; seen[k]=1; }
    out.push(q[i]);
  }
  return out.reverse();
}
function _outboxQueue(table, op, rows, key, why){
  const q=_outboxRead();
  q.push({"""),
("Q1b _outboxQueue: compact on write",
"""          lastError:why||''});
  _outboxWrite(q);
}""",
"""          lastError:why||''});
  _outboxWrite(_outboxCompact(q));   // MF_OUTBOX_DEDUPE_V1
}"""),
("Q2 _outboxFlush: compact existing queue",
"""  let q=_outboxRead();
  if(!q.length)return 0;
  const kept=[];""",
"""  let q=_outboxRead();
  if(!q.length)return 0;
  const _qc=_outboxCompact(q);          // MF_OUTBOX_DEDUPE_V1: collapse copies
  if(_qc.length!==q.length){ console.warn('Outbox: merged '+(q.length-_qc.length)+' duplicate job(s)'); q=_qc; }
  const kept=[];"""),
]
def main():
    src=open(PATH,encoding="utf-8").read(); out=src; applied=0
    for name,old,new in HUNKS:
        if new in out and old not in out.replace(new,""):
            print(f"  = {name}: already applied"); continue
        n=out.count(old)
        if n!=1: sys.exit(f"✗ {name}: anchor found {n} times (expected 1). Nothing written.")
        out=out.replace(old,new); applied+=1; print(f"  ✓ {name}")
    if not applied: print("Nothing to do — patch already applied."); return
    scripts=re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",out,flags=re.S|re.I)
    with tempfile.TemporaryDirectory() as td:
        for i,js in enumerate(scripts):
            p=os.path.join(td,f"s{i}.js"); open(p,"w",encoding="utf-8").write(js)
            r=subprocess.run(["node","--check",p],capture_output=True,text=True)
            if r.returncode: sys.exit(f"✗ node --check failed on inline script #{i}:\n{r.stderr}\nNothing written.")
    print(f"  ✓ node --check passed on {len(scripts)} inline script(s)")
    shutil.copyfile(PATH,PATH+".bak"); open(PATH,"w",encoding="utf-8").write(out)
    print(f"✓ {applied} hunk(s) applied to {PATH} (backup: {PATH}.bak) — sentinel {SENTINEL}")
if __name__=="__main__": main()
