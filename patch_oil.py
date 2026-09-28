#!/usr/bin/env python3
"""
MF_OIL_V1 — oil stock and oil register.

OIL STOCK
 1 Edits reach the server   One timer per item. With one shared timer, changing
                            item A then item B inside 0.8 s cancelled A's upload
                            and the next sync put A back.
 2 COUNT, not typing        Quantity is read-only. COUNT records what is on the
                            shelf, the difference and a reason (opening stock,
                            damaged, counting error, theft suspected, other),
                            logged and kept on the item (stock_items.adjustments).
 3 Stock card               Per item: received on invoices, sold in shifts,
                            opened for loose oil, counts — running balance.
 4 Value at cost            Weighted purchase cost from the invoices; cost and
                            margin under each selling rate. Selling price only
                            where no purchase is on record (marked ≈).
 5 Low + reorder            LOW by ~10 days of cover (same rule as the
                            dashboard); REORDER list sized for ~30 days with the
                            last supplier and price.
OIL REGISTER
 6 Supplier payments        Dated, with mode and reference; history on each
                            invoice with ↶ REVERSE (owner/manager). Payments
                            made before this keep their total as one line.
 7 Safe delete              Owner/manager; refused while payments exist;
                            logged; warns when the stock it reverses was sold.
 8 Duplicate bill           Same supplier + invoice number → asks first.
 9 Edit invoice             ✎ EDIT refills the form; SAVE applies only the
                            difference to stock, rewrites its pack-register
                            lines, keeps its payments (refused if they would
                            exceed the new total). Logged old → new.
10 Due dates                Credit days per supplier (⚙ on the invoice, synced);
                            "due dd/mm" / "OVERDUE n days"; dashboard alert.

Needs db/018_oil_stock_register.sql for payments and counts to reach other
phones; until then they stay on the phone that entered them (no error).

Usage:  python3 patch_oil.py [path/to/index.html]      Idempotent.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_OIL_V1"

HUNKS = [
# ═════════ STOCK: HTML ═════════
("S0 reorder container",
r"""  <div id="pack_stock_wrap" style="margin-bottom:12px"></div>""",
r"""  <div id="pack_stock_wrap" style="margin-bottom:12px"></div>
  <div id="stk_reorder" style="margin-bottom:12px"></div><!-- MF_OIL_V1 -->"""),

("S0b value header",
r"""<th>STATUS</th><th>VALUE</th><th></th></tr></thead>""",
r"""<th>STATUS</th><th title="Quantity × weighted purchase cost">VALUE (COST)</th><th></th></tr></thead>"""),

# ═════════ STOCK: rows ═════════
("S1 row: cost-based value and days-of-cover status",
r"""    const val=item.qty*item.rate;tv+=val;if(item.qty<=3)low++;cats.add(item.cat);
    const sc=item.qty<=0?'szero':item.qty<=3?'slow':'sok';
    const st=item.qty<=0?'OUT':item.qty<=3?'LOW':'OK';""",
r"""    // MF_OIL_V1: valued at what it cost; LOW by days of cover
    const _uc=_ucost[String(item.id)], _cv=_stockCover(item);
    const val=item.qty*(_uc||item.rate);tv+=val;cats.add(item.cat);
    const _isLow=item.qty>0&&_stockLow(item); if(item.qty<=0||_isLow)low++;
    const sc=item.qty<=0?'szero':_isLow?'slow':'sok';
    const st=item.qty<=0?'OUT':_isLow?('LOW'+(_cv.days!=null?' ≈'+Math.floor(_cv.days)+'d':'')):'OK';"""),

("S1b row: precompute costs",
r"""  let tv=0,low=0,cats=new Set();
  const _la=_looseOilCfg().allowed;""",
r"""  let tv=0,low=0,cats=new Set();
  const _la=_looseOilCfg().allowed;
  let _ucost={}; try{ _ucost=_stockUnitCost(); }catch(e){}   // MF_OIL_V1"""),

("S2 row: name escaped",
r"""    tr.innerHTML=`<td><input type="text" value="${item.name}" onchange="updStock(${item.id},'name',this.value)" style="width:140px"></td>
      <td><input type="text" value="${item.cat}" onchange="updStock(${item.id},'cat',this.value)" style="width:90px"></td>""",
r"""    tr.innerHTML=`<td><input type="text" value="${_esc(item.name)}" onchange="updStock(${item.id},'name',this.value)" style="width:140px"></td>
      <td><input type="text" value="${_esc(item.cat)}" onchange="updStock(${item.id},'cat',this.value)" style="width:90px"></td>"""),

("S3 row: quantity by COUNT, stock card",
r"""      <td><input type="number" value="${item.qty}" onchange="updStock(${item.id},'qty',this.value)" style="width:65px"></td>""",
r"""      <td style="white-space:nowrap"><b style="font-family:'JetBrains Mono',monospace;font-size:13px">${item.qty}</b>
        <button class="btn btn-g" style="padding:2px 7px;font-size:9px;margin-left:4px" onclick="countStockItem(${item.id})" title="Record a shelf count">COUNT</button>
        <button class="btn btn-g" style="padding:2px 6px;font-size:9px" onclick="openStockCard(${item.id})" title="Stock card — every movement">📋</button></td>"""),

("S4 row: cost and margin under the selling rate",
r"""      <td><input type="number" value="${item.rate}" onchange="updStock(${item.id},'rate',this.value)" style="width:70px"></td>
      <td><input type="text" value="${item.unit}" onchange="updStock(${item.id},'unit',this.value)" style="width:60px"></td>""",
r"""      <td><input type="number" value="${item.rate}" onchange="updStock(${item.id},'rate',this.value)" style="width:70px">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);margin-top:2px">${_uc?'cost ₹'+_uc.toFixed(2)+' · '+(item.rate>0?((item.rate-_uc)/item.rate*100).toFixed(0)+'%':'—'):'no purchase yet'}</div></td>
      <td><input type="text" value="${_esc(item.unit)}" onchange="updStock(${item.id},'unit',this.value)" style="width:60px"></td>"""),

("S5 row: value cell",
r"""      <td><span class="spill ${sc}">${st}</span></td>
      <td style="color:var(--petrol)">${fmt(val)}</td>""",
r"""      <td><span class="spill ${sc}">${st}</span></td>
      <td style="color:var(--petrol)">${_uc?'':'≈'}${fmt(val)}</td>"""),

("S6 reorder list after the table",
r"""  document.getElementById('stk_val').textContent=fmt(tv);""",
r"""  try{ _renderReorder(); }catch(e){ console.warn('reorder:',e); }   // MF_OIL_V1
  document.getElementById('stk_val').textContent=fmt(tv);"""),

# ═════════ STOCK: sync ═════════
("S7 per-item push timers + adjustments",
r"""var _stockPushTimer=null;
function _pushStockItem(item){
  if(!_currentUser||!item)return;
  clearTimeout(_stockPushTimer);
  // Debounced: these fire on every keystroke.
  _stockPushTimer=setTimeout(function(){
    _sbUpsert('stock_items',{id:item.id,user_id:_currentUser.id,name:item.name,
      cat:item.cat,unit:item.unit,qty:item.qty,rate:item.rate,
      updated_at:_touch(item).updatedAt});
  },800);
}""",
r"""// MF_OIL_V1: one timer PER ITEM. A single shared timer meant editing item A
// then item B within 0.8 s cancelled A's upload, and the next sync reverted A.
var _stockPushTimers={};
var MF_STKADJ_COL=null;   // false once stock_items is proven to have no adjustments column
function _stockRow(s){
  var r={id:s.id,user_id:_currentUser.id,name:s.name,cat:s.cat,unit:s.unit,qty:s.qty,rate:s.rate,
         updated_at:_touch(s).updatedAt};
  if(MF_STKADJ_COL!==false&&Array.isArray(s.adjustments)&&s.adjustments.length)r.adjustments=s.adjustments;
  return r;
}
// What was last sent (or received) per item, kept on the phone so it also
// holds after an offline start.
var _stkSig=(function(){ try{ return JSON.parse(localStorage.getItem('mf_stk_sig')||'{}')||{}; }catch(e){ return {}; } })();
function _stkRowSig(s){ return JSON.stringify([s.name,s.cat,s.unit,s.qty,s.rate,(s.adjustments||[]).length]); }
function _stkSigSave(){ try{ localStorage.setItem('mf_stk_sig',JSON.stringify(_stkSig)); }catch(e){} }
async function _upsertStockRows(rows){
  if(!rows.length)return;
  if(rows.some(function(r){return r.adjustments;})&&_supa&&!(typeof navigator!=='undefined'&&navigator.onLine===false)){
    var res=await _supa.from('stock_items').upsert(rows,{onConflict:'id'});
    if(!res.error){ MF_STKADJ_COL=true; return; }
    if(_isMissingCol(res.error.message)||/adjustments/i.test(String(res.error.message))){
      MF_STKADJ_COL=false; rows.forEach(function(r){delete r.adjustments;});
      console.warn('stock_items has no adjustments column — apply db/018_oil_stock_register.sql. Counts stay on this device until then.');
    }
  }
  await _sbUpsert('stock_items', rows);
}
function _pushStockItem(item){
  if(!_currentUser||!item)return;
  var k=String(item.id);
  clearTimeout(_stockPushTimers[k]);
  _stockPushTimers[k]=setTimeout(function(){
    delete _stockPushTimers[k];
    _upsertStockRows([_stockRow(item)]).catch(console.error);
  },800);
}"""),

("S8 bulk stock save carries adjustments",
r"""  const rows = stock.map(s => ({
    id: s.id, user_id: _currentUser.id,
    name: s.name, cat: s.cat, unit: s.unit, qty: s.qty, rate: s.rate,
    updated_at: _touch(s).updatedAt
  }));
  if (rows.length) await _sbUpsert('stock_items', rows);""",
r"""  // MF_OIL_V1: only items that changed since they were last sent. Sending and
  // re-stamping EVERY item on every save let a phone holding an old copy
  // overwrite another phone's newer changes to items it never touched.
  const changed = stock.filter(s => _stkSig[String(s.id)] !== _stkRowSig(s));
  if (!changed.length) return;
  const rows = changed.map(s => _stockRow(s));
  await _upsertStockRows(rows);
  changed.forEach(s => { _stkSig[String(s.id)] = _stkRowSig(s); });
  _stkSigSave();"""),

("S9 load keeps counts",
r"""        id: s.id, name: s.name, cat: s.cat, unit: s.unit, qty: s.qty, rate: s.rate,
        updatedAt: s.updated_at
      }));""",
r"""        id: s.id, name: s.name, cat: s.cat, unit: s.unit, qty: s.qty, rate: s.rate,
        updatedAt: s.updated_at,
        // MF_OIL_V1: keep this device's counts when the server has no column yet
        adjustments: ('adjustments' in s) ? (s.adjustments||[])
                   : ((stock.find(function(x){return String(x.id)===String(s.id);})||{}).adjustments||[])
      }));"""),

("S9b load: server rows count as sent",
r"""      stock = mrg.merged;""",
r"""      stock = mrg.merged;
      { const _lo=new Set(mrg.localOnly.map(function(x){return String(x.id);}));   // MF_OIL_V1
        stock.forEach(function(s){ if(!_lo.has(String(s.id)))_stkSig[String(s.id)]=_stkRowSig(s); }); _stkSigSave(); }"""),

# ═════════ STOCK: functions ═════════
("S10 count / card / reorder functions",
r"""function addStockItem(){""",
r"""// MF_OIL_V1 ── shelf counts, stock card, reorder ─────────────────────────
var _COUNT_REASONS=['Opening stock','Counting error','Damaged / leaked','Theft suspected','Returned to supplier','Other'];
function countStockItem(id){
  var item=stock.find(function(x){return x.id===id;}); if(!item)return;
  var ov=document.getElementById('stk_count_ov'); if(ov)ov.remove();
  ov=document.createElement('div'); ov.id='stk_count_ov';
  ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:950;display:flex;align-items:center;justify-content:center;padding:16px';
  ov.onclick=function(e){ if(e.target===ov)ov.remove(); };
  ov.innerHTML='<div style="background:var(--s2);border:1px solid var(--border2);border-radius:12px;padding:16px;width:100%;max-width:380px;font-family:\'JetBrains Mono\',monospace;font-size:12px">'+
    '<div style="font-family:\'Syne\',sans-serif;font-weight:800;letter-spacing:1.5px;margin-bottom:10px">COUNT — '+_esc(item.name)+'</div>'+
    '<div style="color:var(--muted);margin-bottom:10px">The app says <b style="color:var(--text)">'+item.qty+' '+_esc(item.unit||'')+'</b>. Count the shelf and enter what is there.</div>'+
    '<label>ON THE SHELF</label><input type="number" id="stk_cnt_q" min="0" step="1" inputmode="numeric" value="'+item.qty+'" style="width:100%;margin-bottom:8px">'+
    '<label>REASON FOR A DIFFERENCE</label><select id="stk_cnt_r" style="width:100%;margin-bottom:8px;padding:6px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text)">'+
      _COUNT_REASONS.map(function(r){return '<option>'+r+'</option>';}).join('')+'</select>'+
    '<label>NOTE (optional)</label><input type="text" id="stk_cnt_n" style="width:100%;margin-bottom:12px">'+
    '<div style="display:flex;gap:8px"><button class="save-btn" style="flex:1" onclick="saveStockCount('+item.id+')">✓ SAVE COUNT</button>'+
    '<button class="btn btn-g" onclick="document.getElementById(\'stk_count_ov\').remove()">CANCEL</button></div></div>';
  document.body.appendChild(ov);
  if(!item.qty&&!(item.adjustments||[]).length)document.getElementById('stk_cnt_r').value='Opening stock';
  setTimeout(function(){ var q=document.getElementById('stk_cnt_q'); if(q){q.focus();q.select();} },50);
}
function saveStockCount(id){
  var item=stock.find(function(x){return x.id===id;}); if(!item)return;
  var to=Math.max(0,Math.round(parseFloat((document.getElementById('stk_cnt_q')||{}).value)));
  if(!isFinite(to)){showToast('Enter the count');return;}
  var reason=(document.getElementById('stk_cnt_r')||{}).value||'Other';
  var note=_clean(((document.getElementById('stk_cnt_n')||{}).value||'').trim());
  var from=Math.round(item.qty||0), diff=to-from;
  var adj={at:new Date().toISOString(),date:_isoLocal(),from:from,to:to,diff:diff,reason:diff?reason:'Checked — matches',
           note:note,by:(_currentUser&&_currentUser.username)||''};
  item.adjustments=(item.adjustments||[]).concat([adj]).slice(-200);
  item.qty=to;
  saveStockLS(); _pushStockItem(item);
  if(typeof logActivity==='function')logActivity('stock_count','stock',item.id,
    item.name+' • counted '+to+' (app said '+from+', '+(diff>=0?'+':'')+diff+')'+(diff?' • '+reason:'')+(note?' • '+note:''));
  var ov=document.getElementById('stk_count_ov'); if(ov)ov.remove();
  renderMasterStock(); renderStockSales();
  showToast(diff?('Count saved — '+(diff>0?'+':'')+diff+' '+(item.unit||'')+' ('+reason+')'):'✓ Count matches');
}
// Every movement of one item, newest first, with the balance after each.
function _stockMovements(item){
  var id=String(item.id), mv=[], rk={morning:1,night:2};
  (typeof oilReg!=='undefined'?oilReg:[]).forEach(function(inv){ (inv.items||[]).forEach(function(it){
    if(String(it.stockId)===id&&(+it.qty||0))mv.push({date:inv.date,k:0.5,d:+it.qty,what:'Received — invoice '+(inv.inv||'')+' ('+(inv.company||'')+')'});
  }); });
  (records||[]).forEach(function(r){
    (r.stockSold||[]).forEach(function(s){ if(String(s.id)===id&&(+s.qty||0))mv.push({date:r.date,k:rk[r.shift]||1,d:-(+s.qty),what:'Sold — '+r.id}); });
    (Array.isArray(r.looseOpened)?r.looseOpened:[]).forEach(function(o){ if(String(o.id)===id&&(+o.qty||0))mv.push({date:r.date,k:rk[r.shift]||1,d:-(+o.qty),what:'Opened for loose oil — '+r.id}); });
  });
  (item.adjustments||[]).forEach(function(a){
    mv.push({date:a.date||String(a.at||'').slice(0,10),k:3,d:+a.diff||0,count:a,what:'Count '+a.from+' → '+a.to+' · '+(a.reason||'')+(a.note?' · '+a.note:'')+(a.by?' ('+a.by+')':'')});
  });
  mv.sort(function(a,b){ return String(b.date).localeCompare(String(a.date))||(b.k-a.k); });
  var bal=Math.round(item.qty||0);
  mv.forEach(function(m){ m.after=bal; bal=bal-m.d; });
  return {rows:mv, before:bal};
}
function openStockCard(id){
  var item=stock.find(function(x){return x.id===id;}); if(!item)return;
  var M=_stockMovements(item);
  var ov=document.getElementById('stk_card_ov'); if(ov)ov.remove();
  ov=document.createElement('div'); ov.id='stk_card_ov';
  ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:950;display:flex;align-items:flex-start;justify-content:center;padding:40px 12px;overflow:auto';
  ov.onclick=function(e){ if(e.target===ov)ov.remove(); };
  var rows=M.rows.map(function(m){
    return '<tr><td>'+_esc(m.date)+'</td><td style="font-size:11px">'+_esc(m.what)+'</td>'+
      '<td style="text-align:right;color:'+(m.d>0?'var(--green)':(m.d<0?'var(--red)':'var(--muted)'))+'">'+(m.d>0?'+':'')+m.d+'</td>'+
      '<td style="text-align:right;font-weight:700">'+m.after+'</td></tr>';
  }).join('');
  ov.innerHTML='<div style="background:var(--s2);border:1px solid var(--border2);border-radius:12px;padding:16px;width:100%;max-width:640px;font-family:\'JetBrains Mono\',monospace;font-size:12px">'+
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><div style="font-family:\'Syne\',sans-serif;font-weight:800;letter-spacing:1.5px">📋 '+_esc(item.name)+'</div>'+
    '<button class="btn btn-g" style="padding:4px 10px" onclick="document.getElementById(\'stk_card_ov\').remove()">✕</button></div>'+
    '<div style="color:var(--muted);margin-bottom:8px">Now: <b style="color:var(--text)">'+item.qty+' '+_esc(item.unit||'')+'</b> · '+M.rows.length+' movement'+(M.rows.length!==1?'s':'')+'</div>'+
    (M.rows.length?'<div style="overflow-x:auto"><table class="data-tbl"><thead><tr><th>DATE</th><th>WHAT</th><th style="text-align:right">IN / OUT</th><th style="text-align:right">BALANCE</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'<div style="color:var(--muted)">No movements recorded yet.</div>')+
    '<div style="color:var(--muted);font-size:10px;margin-top:8px;line-height:1.6">Balance before the first movement shown: '+M.before+'. '+
    (M.before<0?'<span style="color:var(--diesel)">Below zero means stock was changed without a record before counts were kept — a COUNT now sets the baseline.</span>':'')+'</div></div>';
  document.body.appendChild(ov);
}
function _renderReorder(){
  var el=document.getElementById('stk_reorder'); if(!el)return;
  var uc={}; try{ uc=_stockUnitCost(); }catch(e){}
  var last=function(id){ var best=null; (oilReg||[]).forEach(function(inv){ (inv.items||[]).forEach(function(it){
      if(String(it.stockId)===String(id)&&(!best||String(inv.date)>String(best.date)))best={date:inv.date,company:inv.company,buy:+it.buy||0}; }); }); return best; };
  var rows=stock.map(function(item){
    var c=_stockCover(item), out=(item.qty||0)<=0;
    if(!(out||_stockLow(item)))return null;
    var need=c.perDay>0?Math.max(0,Math.ceil(c.perDay*30-(item.qty||0))):null;
    var l=last(item.id), cost=need!=null?need*((l&&l.buy)||uc[String(item.id)]||0):0;
    return {item:item,c:c,need:need,l:l,cost:cost,out:out};
  }).filter(Boolean).sort(function(a,b){ return (a.c.days==null?99:a.c.days)-(b.c.days==null?99:b.c.days); });
  if(!rows.length){ el.innerHTML=''; return; }
  var tot=rows.reduce(function(s,r){return s+r.cost;},0);
  el.innerHTML='<div class="card" style="border-color:var(--diesel)"><div class="card-head" style="color:var(--diesel)">🛒 REORDER — ENOUGH FOR ABOUT 30 DAYS'+
    (tot>0?' <span style="color:var(--muted);font-weight:400">· ≈ '+fmt(tot)+'</span>':'')+'</div>'+
    '<div style="overflow-x:auto"><table class="data-tbl"><thead><tr><th>ITEM</th><th>LEFT</th><th>SELLS / DAY</th><th>ORDER</th><th>LAST BOUGHT</th></tr></thead><tbody>'+
    rows.map(function(r){ return '<tr><td>'+_esc(r.item.name)+'</td>'+
      '<td style="color:'+(r.out?'var(--red)':'var(--diesel)')+'">'+(r.item.qty||0)+(r.c.days!=null&&!r.out?' <span style="font-size:10px;color:var(--muted)">≈'+Math.floor(r.c.days)+'d</span>':'')+'</td>'+
      '<td>'+(r.c.perDay>0?r.c.perDay.toFixed(2):'<span style="color:var(--muted)">no sales in 30 d</span>')+'</td>'+
      '<td style="font-weight:700">'+(r.need!=null?r.need+' '+_esc(r.item.unit||''):'—')+'</td>'+
      '<td style="font-size:11px;color:var(--muted)">'+(r.l?_esc(r.l.company||'')+' · ₹'+r.l.buy+' · '+_esc(r.l.date):'—')+'</td></tr>'; }).join('')+
    '</tbody></table></div></div>';
}
function addStockItem(){"""),

# ═════════ REGISTER: HTML ═════════
("R0 form title id",
r"""      <div class="card-head" style="color:var(--diesel)">NEW PURCHASE INVOICE</div>""",
r"""      <div class="card-head" style="color:var(--diesel)" id="or_form_title">NEW PURCHASE INVOICE</div>"""),

("R0b toggle leaves edit mode",
r"""function toggleOilRegForm(){
  const f=document.getElementById('oilreg_form');
  f.style.display=f.style.display==='none'?'block':'none';""",
r"""function toggleOilRegForm(){
  const f=document.getElementById('oilreg_form');
  f.style.display=f.style.display==='none'?'block':'none';
  _orEditId=null; { const _t=document.getElementById('or_form_title'); if(_t)_t.textContent='NEW PURCHASE INVOICE'; }   // MF_OIL_V1"""),

("R1 invoice card: edit / delete / days",
r"""        <button class="btn btn-d" style="padding:3px 10px;font-size:10px" onclick="delInvoice(${inv.id})">&#10005; DELETE</button>""",
r"""        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn btn-g" style="padding:3px 10px;font-size:10px" onclick="editOilInvoice(${inv.id})">✎ EDIT</button>
          <button class="btn btn-d" style="padding:3px 10px;font-size:10px" onclick="delInvoice(${inv.id})">&#10005; DELETE</button>
        </div>"""),

("R2 invoice card: due date",
r"""          <div style="font-size:11px;color:var(--muted);margin-top:2px">${inv.company}</div>""",
r"""          <div style="font-size:11px;color:var(--muted);margin-top:2px">${_esc(inv.company)} ${_invDueHtml(inv)}</div>"""),

("R3 invoice card: payments",
r"""      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--s3);padding:10px;border-radius:6px">
        <div style="font-size:11px;color:var(--muted)">Amount Due to Supplier:</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;color:${dueCls}">&#8377;${due.toLocaleString('en-IN')}</div>
        <div style="font-size:11px;color:var(--muted);margin-left:8px">Paid: &#8377;${(inv.amountPaid||0).toLocaleString('en-IN')}</div>
        ${due>0?`<input type="number" id="or_pay_${inv.id}" placeholder="Pay amount" style="width:130px;padding:4px 8px;font-size:12px;margin-left:auto">
          <button class="btn btn-g" style="padding:4px 12px;font-size:11px" onclick="payInvoice(${inv.id})">RECORD PAYMENT</button>`:'<span class="badge bg_" style="margin-left:auto">&#10003; FULLY PAID</span>'}
      </div>`;""",
r"""      ${_oilPayHtml(inv)}`;   // MF_OIL_V1"""),

# ═════════ REGISTER: functions ═════════
("R4 register helpers, payments, edit, due dates",
r"""function payInvoice(id){""",
r"""// MF_OIL_V1 ── supplier payments, due dates, edit ───────────────────────
var _orEditId=null;
var MF_OILPAY_COL=null;   // false once oil_invoices is proven to have no payments column
function _invPaid(inv){
  if(Array.isArray(inv.payments)&&inv.payments.length)return _r2(inv.payments.reduce(function(s,p){return s+(+p.amount||0);},0));
  return +inv.amountPaid||0;
}
// A bill paid before payment history existed: keep its total as one line.
function _invPaymentsList(inv){
  if(!Array.isArray(inv.payments)||!inv.payments.length){
    if((+inv.amountPaid||0)>0)inv.payments=[{id:_newId(),date:inv.date,amount:+inv.amountPaid,mode:'—',ref:'',
      note:'recorded before payment history',legacy:true,by:'',at:''}];
    else inv.payments=[];
  }
  return inv.payments;
}
function _supplierCfg(){ try{ return JSON.parse(localStorage.getItem('supplierCfg')||'null')||{days:{}}; }catch(e){ return {days:{}}; } }
function _supplierDays(co){ var d=_supplierCfg().days||{}; return parseInt(d[String(co||'').trim().toLowerCase()],10)||0; }
function _invDueDate(inv){
  var n=_supplierDays(inv.company); if(!n||!inv.date)return null;
  var d=new Date(inv.date+'T00:00:00'); d.setDate(d.getDate()+n); return _isoLocal(d);
}
function _invDueHtml(inv){
  var dd=_invDueDate(inv), due=+inv.amountDue||0;
  var set='<button class="btn btn-g" style="padding:1px 6px;font-size:9px;margin-left:6px" data-co="'+_esc(inv.company||'')+'" onclick="setSupplierDays(this.dataset.co)" title="Credit days for this supplier">⚙ '+(_supplierDays(inv.company)||'set')+' d</button>';
  if(!dd||due<=0.5)return set;
  var late=Math.floor((Date.parse(_isoLocal())-Date.parse(dd))/86400000);
  return (late>0?'<span style="color:var(--red);font-weight:700">· OVERDUE '+late+' d</span>':'<span>· due '+dd.slice(8,10)+'/'+dd.slice(5,7)+'</span>')+set;
}
function setSupplierDays(co){
  co=String(co||'').trim(); if(!co)return;
  var cur=_supplierDays(co);
  var v=prompt('Credit days for "'+co+'" — how many days after the invoice date is it due?\n(0 = no due date)',cur||'');
  if(v===null)return;
  var n=Math.max(0,parseInt(v,10)||0), c=_supplierCfg(); c.days=c.days||{};
  if(n)c.days[co.toLowerCase()]=n; else delete c.days[co.toLowerCase()];
  c.updatedAt=new Date().toISOString();
  localStorage.setItem('supplierCfg',JSON.stringify(c));
  localStorage.setItem('mf_cfg_savedAt',new Date().toISOString());
  if(typeof queueSettingsSave==='function')queueSettingsSave();
  if(typeof logActivity==='function')logActivity('supplier_days','supplier',co,co+' • '+(n?n+' days credit':'no due date'));
  renderOilReg();
}
function _supplierDueAlerts(){
  var late=(typeof oilReg!=='undefined'?oilReg:[]).filter(function(inv){
    var dd=_invDueDate(inv); return dd&&(+inv.amountDue||0)>0.5&&dd<_isoLocal(); });
  if(!late.length)return [];
  var amt=late.reduce(function(s,i){return s+(+i.amountDue||0);},0);
  return [{type:'danger',icon:'🧾',title:late.length+' supplier invoice'+(late.length>1?'s':'')+' overdue — '+fmt(amt),
    desc:[...new Set(late.map(function(i){return i.company;}))].slice(0,3).join(', '),action:'REGISTER',page:'oilreg'}];
}
function _oilPayHtml(inv){
  var pays=_invPaymentsList(inv), due=+inv.amountDue||0, can=!_currentUser||_isOwner||_currentUser.role==='manager';
  var hist=pays.length?'<div style="margin-top:8px;font-family:\'JetBrains Mono\',monospace;font-size:11px">'+pays.map(function(p){
      return '<div style="display:flex;gap:8px;align-items:center;padding:3px 0;border-top:1px solid var(--border)">'+
        '<span style="color:var(--muted)">'+_esc(p.date||'')+'</span><b style="color:var(--green)">'+fmt(+p.amount||0)+'</b>'+
        '<span>'+_esc(p.mode||'')+'</span><span style="color:var(--muted);flex:1">'+_esc([p.ref,p.note].filter(Boolean).join(' · '))+'</span>'+
        (can&&!p.legacy?'<button class="btn btn-g" style="padding:1px 7px;font-size:9px" onclick="reverseOilPayment('+inv.id+','+p.id+')">↶ REVERSE</button>':'')+'</div>';
    }).join('')+'</div>':'';
  var form=due>0.005?
    '<input type="number" id="or_pay_'+inv.id+'" placeholder="Amount" inputmode="decimal" style="width:110px;padding:4px 8px;font-size:12px;margin-left:auto">'+
    '<select id="or_pmode_'+inv.id+'" style="padding:4px 6px;font-size:11px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text)">'+
      ['Cash','Bank Transfer','Cheque','GPay','Other'].map(function(m){return '<option>'+m+'</option>';}).join('')+'</select>'+
    '<input type="date" id="or_pdate_'+inv.id+'" value="'+_isoLocal()+'" style="width:130px;padding:4px 6px;font-size:11px">'+
    '<input type="text" id="or_pref_'+inv.id+'" placeholder="Ref / cheque no." style="width:120px;padding:4px 6px;font-size:11px">'+
    '<button class="btn btn-g" style="padding:4px 12px;font-size:11px" onclick="payInvoice('+inv.id+')">RECORD PAYMENT</button>'
    :'<span class="badge bg_" style="margin-left:auto">&#10003; FULLY PAID</span>';
  return '<div style="background:var(--s3);padding:10px;border-radius:6px">'+
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'+
    '<div style="font-size:11px;color:var(--muted)">Due to supplier:</div>'+
    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:700;color:'+(due<=0.005?'var(--green)':'var(--red)')+'">'+fmt(due)+'</div>'+
    '<div style="font-size:11px;color:var(--muted);margin-left:6px">Paid: '+fmt(_invPaid(inv))+'</div>'+form+'</div>'+hist+'</div>';
}
function _saveOilInv(inv){
  inv.amountPaid=_invPaid(inv); inv.amountDue=_r2((+inv.totalCost||0)-inv.amountPaid);
  localStorage.setItem('oilReg',JSON.stringify(oilReg));
  if(_currentUser)sbSaveOilInvoice(inv).catch(console.error);
}
function reverseOilPayment(invId,payId){
  var inv=oilReg.find(function(x){return x.id===invId;}); if(!inv)return;
  if(_currentUser&&!(_isOwner||_currentUser.role==='manager')){showToast('🔒 Only an owner or manager can reverse a payment');return;}
  var p=_invPaymentsList(inv).find(function(x){return String(x.id)===String(payId);}); if(!p)return;
  var reason=prompt('Reverse '+fmt(+p.amount||0)+' paid to '+inv.company+' on '+p.date+' ('+p.mode+')?\n\nOnly for a payment entered by mistake. Reason:','Entered by mistake');
  if(reason===null)return;
  inv.payments=inv.payments.filter(function(x){return x!==p;});
  _saveOilInv(inv);
  if(typeof logActivity==='function')logActivity('reverse_supplier_pay','oil_invoice',inv.id,
    inv.company+' '+inv.inv+' • reversed '+fmt(+p.amount||0)+' ('+p.mode+', '+p.date+') • '+_clean(String(reason)));
  renderOilReg(); showToast('↶ Payment reversed');
}
function editOilInvoice(id){
  var inv=oilReg.find(function(x){return x.id===id;}); if(!inv)return;
  if(_currentUser&&!(_isOwner||_currentUser.role==='manager')){showToast('🔒 Only an owner or manager can edit an invoice');return;}
  var f=document.getElementById('oilreg_form');
  f.style.display='block';
  document.getElementById('or_date').value=inv.date||_isoLocal();
  document.getElementById('or_inv').value=inv.inv||'';
  document.getElementById('or_company').value=inv.company||'';
  document.getElementById('or_items_list').innerHTML=''; orItemCount=0;
  (inv.items||[]).forEach(function(it){
    addOilRegItem(); var k=orItemCount;
    var s=document.getElementById('or_stock_'+k);
    if(s&&[].some.call(s.options,function(o){return o.value===String(it.stockId);}))s.value=String(it.stockId);
    document.getElementById('or_qty_'+k).value=it.qty; document.getElementById('or_buy_'+k).value=it.buy;
    document.getElementById('or_sell_'+k).value=it.sell; calcOrRow(k);
  });
  if(!(inv.items||[]).length)addOilRegItem();
  _orEditId=id;
  var t=document.getElementById('or_form_title'); if(t)t.textContent='EDIT INVOICE '+(inv.inv||'')+' — SAVE applies only the difference to stock';
  f.scrollIntoView({behavior:'smooth',block:'start'});
}
function payInvoice(id){
  // MF_OIL_V1: a dated payment with mode and reference, kept on the invoice.
  const inv=oilReg.find(x=>x.id===id);if(!inv)return;
  const amt=_r2(parseFloat((document.getElementById('or_pay_'+id)||{}).value)||0);
  if(!(amt>0)){showToast('Enter payment amount');return;}
  const due=_r2((+inv.totalCost||0)-_invPaid(inv));
  if(amt>due+0.005){showToast('More than the '+fmt(due)+' still due');return;}
  _invPaymentsList(inv).push({id:_newId(),date:(document.getElementById('or_pdate_'+id)||{}).value||_isoLocal(),amount:amt,
    mode:(document.getElementById('or_pmode_'+id)||{}).value||'Cash',
    ref:_clean(((document.getElementById('or_pref_'+id)||{}).value||'').trim()),note:'',
    by:(_currentUser&&_currentUser.username)||'',at:new Date().toISOString()});
  _saveOilInv(inv);
  if(typeof logActivity==='function')logActivity('supplier_pay','oil_invoice',inv.id,inv.company+' '+inv.inv+' • paid '+fmt(amt));
  renderOilReg();showToast('Payment recorded — '+fmt(inv.amountDue)+' still due');
}
function _payInvoiceOld(id){"""),

("R5 delete: role, payments, log",
r"""function delInvoice(id){
  // Find the invoice before deleting so we can reverse its stock
  const inv=oilReg.find(x=>x.id===id);""",
r"""function delInvoice(id){
  // Find the invoice before deleting so we can reverse its stock
  const inv=oilReg.find(x=>x.id===id);
  // MF_OIL_V1: owner/manager, no payments against it, confirmed and logged
  if(!inv)return;
  if(_currentUser&&!(_isOwner||_currentUser.role==='manager')){showToast('🔒 Only an owner or manager can delete an invoice');return;}
  if(_invPaid(inv)>0.005){showToast(fmt(_invPaid(inv))+' has been paid on this invoice — reverse the payments first');return;}
  { const _short=(inv.items||[]).filter(function(it){ if(String(it.stockId).indexOf('pack:')===0)return false;
        const s=stock.find(x=>x.id==it.stockId); return s&&Math.round(s.qty)<Math.round(it.qty); })
      .map(function(it){ const s=stock.find(x=>x.id==it.stockId); return it.name+' (bill '+it.qty+', shelf '+s.qty+')'; });
    if(!confirm('Delete invoice '+inv.inv+' from '+inv.company+' ('+fmt(+inv.totalCost||0)+')?\n\nIts quantities come off stock again.'+
      (_short.length?'\n\n⚠ Some of it has already been sold, so stock stops at 0: '+_short.join(', '):'')))return;
    if(typeof logActivity==='function')logActivity('del_oil_inv','oil_invoice',inv.id,
      inv.inv+' • '+inv.company+' • '+fmt(+inv.totalCost||0)+' • '+(inv.items||[]).length+' line(s)'); }"""),

("R6 submit: duplicate check, edit undo",
r"""  if(!inv||!company){showToast('Fill Invoice No. and Supplier');return;}""",
r"""  if(!inv||!company){showToast('Fill Invoice No. and Supplier');return;}
  // MF_OIL_V1 ── duplicate bill / edit ──
  const _norm=s=>String(s||'').toLowerCase().replace(/\s+/g,'');
  const _dup=oilReg.find(x=>x.id!==_orEditId&&_norm(x.inv)===_norm(inv)&&_norm(x.company)===_norm(company));
  if(_dup&&!confirm('Invoice '+inv+' from '+company+' is already entered ('+_dup.date+', '+fmt(+_dup.totalCost||0)+').\n\nSave it again anyway? That adds its stock a second time.'))return;
  const _rowsNow=[...document.querySelectorAll('[id^="or_item_"]')].map(function(row){
    const k=row.id.split('_')[2]; return {q:parseFloat(document.getElementById('or_qty_'+k)?.value)||0, b:parseFloat(document.getElementById('or_buy_'+k)?.value)||0};});
  if(!_rowsNow.some(r=>r.q>0)){showToast('Add at least one item with qty');return;}
  const _orEdit=_orEditId?oilReg.find(x=>x.id===_orEditId):null;
  let _editWas='';
  if(_orEdit){
    const _newTotal=_rowsNow.reduce((s,r)=>s+r.q*r.b,0);
    if(_invPaid(_orEdit)>_newTotal+0.005){showToast(fmt(_invPaid(_orEdit))+' is already paid — more than the new total '+fmt(_newTotal)+'. Reverse a payment first.');return;}
    _editWas=_orEdit.inv+' '+_orEdit.date+' '+fmt(+_orEdit.totalCost||0)+' ('+(_orEdit.items||[]).length+' lines)';
    // Undo what the old bill did to stock (no floor yet: the new lines are added
    // next, and only the net result is floored at 0).
    (_orEdit.items||[]).forEach(function(it){
      if(String(it.stockId).indexOf('pack:')===0)return;
      const s=stock.find(x=>x.id==it.stockId); if(s)s.qty=Math.round(s.qty)-Math.round(+it.qty||0);
    });
    const _oldPacks=packReg.filter(p=>p.invId===_orEdit.id);
    if(_oldPacks.length){ packReg=packReg.filter(p=>p.invId!==_orEdit.id);
      _oldPacks.forEach(function(p){ if(_currentUser&&typeof _sbRemove==='function')_sbRemove('pack_register',p.id,'id'); }); }
  }"""),

("R7 submit: reuse the invoice when editing",
r"""  const invoice={id:_newId(),date,inv,company,items,totalCost,totalSell,profit:totalSell-totalCost,
    amountDue:totalCost,amountPaid:0};
  oilReg.unshift(invoice);""",
r"""  let invoice;
  if(_orEdit){   // MF_OIL_V1: same invoice, same payments
    invoice=_orEdit;
    Object.assign(invoice,{date,inv,company,items,totalCost,totalSell,profit:totalSell-totalCost});
    invoice.amountPaid=_invPaid(invoice); invoice.amountDue=_r2(totalCost-invoice.amountPaid);
    stock.forEach(function(s){ if(s.qty<0)s.qty=0; });
  } else {
    invoice={id:_newId(),date,inv,company,items,totalCost,totalSell,profit:totalSell-totalCost,
      amountDue:totalCost,amountPaid:0,payments:[]};
    oilReg.unshift(invoice);
  }"""),

("R8 submit: log an edit as an edit",
r"""  if(typeof logActivity==='function')
    logActivity('add_oil_inv','oil_invoice',invoice.id,""",
r"""  if(_orEdit&&typeof logActivity==='function')   // MF_OIL_V1
    logActivity('edit_oil_inv','oil_invoice',invoice.id,'Was: '+_editWas+' • now: '+inv+' '+date+' '+fmt(totalCost)+' ('+items.length+' lines)');
  else if(typeof logActivity==='function')
    logActivity('add_oil_inv','oil_invoice',invoice.id,"""),

("R9 sync: payments column with fallback",
r"""  await _sbUpsert('oil_invoices', {
    id: inv.id, user_id: _currentUser.id,
    date: inv.date, inv: inv.inv, company: inv.company,
    items: inv.items, total_cost: inv.totalCost, total_sell: inv.totalSell,
    profit: inv.profit, amount_due: inv.amountDue, amount_paid: inv.amountPaid,
    updated_at: _touch(inv).updatedAt
  });""",
r"""  const _row = {
    id: inv.id, user_id: _currentUser.id,
    date: inv.date, inv: inv.inv, company: inv.company,
    items: inv.items, total_cost: inv.totalCost, total_sell: inv.totalSell,
    profit: inv.profit, amount_due: inv.amountDue, amount_paid: inv.amountPaid,
    updated_at: _touch(inv).updatedAt
  };
  // MF_OIL_V1: payment history rides in oil_invoices.payments (db/018)
  if (Array.isArray(inv.payments) && MF_OILPAY_COL !== false) {
    _row.payments = inv.payments;
    if (_supa && !(typeof navigator !== 'undefined' && navigator.onLine === false)) {
      const r = await _supa.from('oil_invoices').upsert(_row, { onConflict: 'id' });
      if (!r.error) { MF_OILPAY_COL = true; return; }
      if (_isMissingCol(r.error.message) || /payments/i.test(String(r.error.message))) {
        MF_OILPAY_COL = false; delete _row.payments;
        console.warn('oil_invoices has no payments column — apply db/018_oil_stock_register.sql. Payment history stays on this device until then.');
      }
    }
  }
  await _sbUpsert('oil_invoices', _row);"""),

("R10 load keeps payments",
r"""        profit: inv.profit, amountDue: inv.amount_due, amountPaid: inv.amount_paid,
        updatedAt: inv.updated_at
      }));""",
r"""        profit: inv.profit, amountDue: inv.amount_due, amountPaid: inv.amount_paid,
        updatedAt: inv.updated_at,
        // MF_OIL_V1: keep this device's history when the server has no column yet
        payments: ('payments' in inv) ? (inv.payments||[])
                : ((oilReg.find(function(x){return String(x.id)===String(inv.id);})||{}).payments||[])
      }));"""),

("R11 supplier days sync out",
r"""    monthTarget: g('monthTarget'),   // MF_DASH_PULSE_V4""",
r"""    monthTarget: g('monthTarget'),   // MF_DASH_PULSE_V4
    supplierCfg: g('supplierCfg'),   // MF_OIL_V1: credit days per supplier"""),

("R12 supplier days sync in",
r"""  _cfgApplyIfNewer('monthTarget', cfg.monthTarget);   // MF_DASH_PULSE_V4""",
r"""  _cfgApplyIfNewer('monthTarget', cfg.monthTarget);   // MF_DASH_PULSE_V4
  _cfgApplyIfNewer('supplierCfg', cfg.supplierCfg);   // MF_OIL_V1"""),

("R13 dashboard alert: overdue suppliers",
r"""  try{ if(typeof _receiptAlerts==='function')Array.prototype.push.apply(alerts,_receiptAlerts()); }catch(e){}""",
r"""  try{ if(typeof _receiptAlerts==='function')Array.prototype.push.apply(alerts,_receiptAlerts()); }catch(e){}
  try{ if(typeof _supplierDueAlerts==='function')Array.prototype.push.apply(alerts,_supplierDueAlerts()); }catch(e){}   // MF_OIL_V1"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_ROLE_LABEL_V1" not in src or "MF_DASH_V5" not in src:
        sys.exit("✗ Needs MF_ROLE_LABEL_V1 and MF_DASH_V5 applied first. Nothing written.")
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
