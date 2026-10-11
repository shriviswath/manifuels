#!/usr/bin/env python3
"""
MF_CREDIT_FUEL_V1 — credit by fuel, in the business statement.

The statement's "3. Customer credit" lists each customer. It could not answer
"how much petrol and how much diesel went out on credit this month". Every
credit bill is already saved with its fuel, and every payment with the bill it
settled, so the split is read from the ledger — nothing is estimated.

1. BUSINESS STATEMENT → 3. Customer credit gains two tables
   • Credit by fuel: bills in the period, credit given, received, unpaid today
     — a row each for Petrol (MSD) and Diesel (HSD), and for Oil / Other /
     "MSD/HSD" bills where there are any. Given and received are the totals of
     the customer table above, split; unpaid today less advances held is its
     "Balance today".
   • Credit given in the period, by customer and fuel.
   Bills saved as "MSD/HSD" were never split and are shown as exactly that.

2. ASSISTANT
   "How much diesel credit did we give in September?" is answered from the
   same engine. That part lives in patch_ai_assistant.py: run it after this
   one — it installs the assistant, or brings an installed one up to date.

No database change. Nothing is written to the ledger.

Usage:  python3 patch_credit_by_fuel.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_CREDIT_FUEL_V1"
APPLIED = "function _creditByFuel("          # the sentinel name alone also appears in notes

# the engine goes in just above the statement renderer
ENGINE_ANCHOR = "var _stmtLastRows=[];\nfunction renderStatement(){"

# …and is printed at the end of "3. Customer credit"
STMT_OLD = "Balance today is net of advances held.</p>');\n  }\n\n  // ── 4. Fuel stock register ──"
STMT_NEW = ("Balance today is net of advances held.</p>'+\n"
            "      _stmtCreditFuelHtml(from,to,names));      // MF_CREDIT_FUEL_V1\n  }\n\n  // ── 4. Fuel stock register ──")

CF_JS = r'''// ══════════════════════════════════════════════════════════════════
// MF_CREDIT_FUEL_V1 — CREDIT BY FUEL
// Every credit bill is saved with the fuel it was for, and every payment row
// with the bill it settled. So "how much diesel went out on credit this
// month, and how much of it came back" is read from the ledger — it is not
// estimated from litres or rates.
//   given   bills dated in the period. Balances moved between customers are
//           left out: the same test as "Credit given in period" above it.
//   recv    payments dated in the period, under the fuel of the bill each
//           one settled. Advances are left out, as they are above.
//   unpaid  what is still owed on every bill today, whenever it was raised.
// A bill saved as "MSD/HSD" was never split and is shown as exactly that.
// Returns rows (one per fuel), customers (credit given, by fuel), received
// (payments in the period, by customer), tot, held and net.
// `only` (a {name:1} map) limits it to those customers, so the statement's
// figures tie to the table it prints above; without it, everyone.
// ══════════════════════════════════════════════════════════════════
var MF_CREDIT_FUELS=[
  ['MSD','Petrol (MSD)','Petrol (MSD)'],['HSD','Diesel (HSD)','Diesel (HSD)'],
  ['MIX','Petrol or diesel — not recorded which','Petrol / diesel'],
  ['OIL','Oil','Oil'],['OTHER','Other','Other'],
  ['ADJ','Balance moved from another customer','Moved'],
  ['NONE','Not recorded against a bill','No bill']];
function _creditFuelKey(e){
  if(!e)return 'NONE';
  if(e.kind==='adjust'||e.fuel==='ADJUST')return 'ADJ';
  var f=String(e.fuel||'').trim().toUpperCase();
  if(f==='MSD'||f==='PETROL')return 'MSD';
  if(f==='HSD'||f==='DIESEL')return 'HSD';
  if(f==='MSD/HSD'||f==='HSD/MSD')return 'MIX';
  if(f==='OIL')return 'OIL';
  return 'OTHER';
}
function _creditByFuel(from,to,only){
  var F={}, cust={}, bill={}, held=0, got={};
  var b=function(k){ return F[k]||(F[k]={given:0,bills:0,recv:0,unpaid:0}); };
  var inSet=function(n){ return !only||only[n]===1; };
  (typeof ledger!=='undefined'?ledger:[]).forEach(function(e){
    if(!e)return;
    bill[String(e.id)]=e;
    if(!inSet(e.customer))return;
    var amt=+e.amount||0, pb=+e.paidBack||0;
    if(amt>0){
      var k=_creditFuelKey(e); b(k).unpaid+=amt-pb;
      if(k!=='ADJ'&&e.date>=from&&e.date<=to){
        b(k).given+=amt; b(k).bills++;
        var c=cust[e.customer]||(cust[e.customer]={}); c[k]=(c[k]||0)+amt;
      }
    } else held+=Math.abs(amt)-pb;                 // advances and credits still held
  });
  (typeof ledgerPayments!=='undefined'?ledgerPayments:[]).forEach(function(p){
    if(!p||p.kind==='advance'||!(p.date>=from&&p.date<=to)||!inSet(p.customer))return;
    var e=p.ledgerId==null?null:bill[String(p.ledgerId)];
    b(e?_creditFuelKey(e):'NONE').recv+=+p.amount||0;
    got[p.customer]=(got[p.customer]||0)+(+p.amount||0);
  });
  b('MSD'); b('HSD');                              // always shown, even at zero
  var tot={given:0,bills:0,recv:0,unpaid:0};
  var rows=MF_CREDIT_FUELS.map(function(d){
    var x=F[d[0]]; if(!x)return null;
    tot.given+=x.given; tot.bills+=x.bills; tot.recv+=x.recv; tot.unpaid+=x.unpaid;
    return {key:d[0],label:d[1],short:d[2],given:_r2(x.given),bills:x.bills,recv:_r2(x.recv),unpaid:_r2(x.unpaid)};
  }).filter(function(x){
    return x&&(x.key==='MSD'||x.key==='HSD'||x.bills||Math.abs(x.given)>0.005||Math.abs(x.recv)>0.005||Math.abs(x.unpaid)>0.005);
  });
  var customers=Object.keys(cust).map(function(n){
    var t=0; Object.keys(cust[n]).forEach(function(k){ t+=cust[n][k]; });
    return {name:n,by:cust[n],total:_r2(t)};
  }).sort(function(a,b){ return b.total-a.total||String(a.name).localeCompare(String(b.name)); });
  return {from:from,to:to,rows:rows,customers:customers,received:got,
    tot:{given:_r2(tot.given),bills:tot.bills,recv:_r2(tot.recv),unpaid:_r2(tot.unpaid)},
    held:_r2(held),net:_r2(tot.unpaid-held)};
}
// The two tables printed under "3. Customer credit" in the business statement.
function _stmtCreditFuelHtml(from,to,names){
  var only=null; if(names){ only={}; names.forEach(function(n){ only[n]=1; }); }
  var B=_creditByFuel(from,to,only);
  if(!B.rows.some(function(r){ return r.bills||Math.abs(r.recv)>0.005||Math.abs(r.unpaid)>0.005; }))return '';
  var hs=' style="page-break-after:avoid;break-after:avoid"';
  var has=function(k){ return B.rows.some(function(r){ return r.key===k; }); };
  var h='<h3'+hs+'>Credit by fuel</h3>'+
    '<table class="st-t st-cf"><thead><tr><th>Fuel on the bill</th><th class="n">Bills in period</th><th class="n">Credit given in period</th><th class="n">Received in period</th><th class="n">Unpaid today</th></tr></thead><tbody>'+
    B.rows.map(function(r){
      return '<tr data-fuel="'+r.key+'"><td>'+_esc(r.label)+'</td><td class="n">'+(r.bills||'')+'</td><td class="n">'+_sAmt(r.given)+'</td><td class="n">'+_sAmt(r.recv)+'</td><td class="n">'+_sAmt(r.unpaid)+'</td></tr>';
    }).join('')+
    '<tr class="st-tot"><td><b>Total</b></td><td class="n"><b>'+B.tot.bills+'</b></td><td class="n"><b>'+_sN(B.tot.given)+'</b></td><td class="n"><b>'+_sN(B.tot.recv)+'</b></td><td class="n"><b>'+_sN(B.tot.unpaid)+'</b></td></tr></tbody></table>'+
    '<p class="st-note st-cf-note">Read from the ledger, not estimated: each credit bill is saved with its fuel, and each payment with the bill it settled. Credit given and received are the totals of the table above, split. '+
      'Unpaid today ₹ '+_sN(B.tot.unpaid)+', less advances and credits held ₹ '+_sN(B.held)+', is the balance today of ₹ '+_sN(B.net)+'.'+
      (has('MIX')?' Bills saved as “MSD/HSD” were never split between petrol and diesel, and cannot be split now.':'')+
      (has('NONE')?' “Not recorded against a bill” is money received that was not saved against a particular bill.':'')+'</p>';
  if(B.customers.length){
    var cols=MF_CREDIT_FUELS.filter(function(d){ return d[0]==='MSD'||d[0]==='HSD'||B.customers.some(function(c){ return Math.abs(c.by[d[0]]||0)>0.005; }); });
    var ct={}; cols.forEach(function(d){ ct[d[0]]=0; });
    h+='<h3'+hs+'>Credit given in the period — by customer and fuel</h3>'+
      '<table class="st-t st-cfc"><thead><tr><th>Customer</th>'+cols.map(function(d){ return '<th class="n">'+_esc(d[2])+'</th>'; }).join('')+'<th class="n">Total</th></tr></thead><tbody>'+
      B.customers.map(function(c){
        return '<tr><td>'+_esc(c.name)+'</td>'+cols.map(function(d){ var v=c.by[d[0]]||0; ct[d[0]]+=v; return '<td class="n">'+_sAmt(v)+'</td>'; }).join('')+'<td class="n">'+_sN(c.total)+'</td></tr>';
      }).join('')+
      '<tr class="st-tot"><td><b>Total</b></td>'+cols.map(function(d){ return '<td class="n"><b>'+_sN(ct[d[0]])+'</b></td>'; }).join('')+'<td class="n"><b>'+_sN(B.tot.given)+'</b></td></tr></tbody></table>';
  }
  return h;
}

'''

def main():
    src = open(PATH, encoding="utf-8").read()
    if APPLIED in src:
        print(f"Nothing to do — {SENTINEL} already applied."); return
    out = src

    for name, old, new in (
        ("engine: _creditByFuel + the statement's two tables", ENGINE_ANCHOR, CF_JS + ENGINE_ANCHOR),
        ("statement: printed under 3. Customer credit", STMT_OLD, STMT_NEW),
    ):
        if out.count(old) != 1:
            sys.exit(f"✗ {name}: anchor found {out.count(old)}× (need exactly 1) — nothing written")
        out = out.replace(old, new)
        print("  ✓", name)

    # post-state: nothing that must survive was lost
    for must in ("function renderStatement(", "function _stmtTransactions(", "function _custPosition(",
                 "function _bulkPayPlan(", "function _creditByFuel(", "function _stmtCreditFuelHtml(",
                 "<h2>3. Customer credit</h2>", "initMultiDeviceSync", "function _plCore("):
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


if __name__ == "__main__":
    main()
