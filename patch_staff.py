#!/usr/bin/env python3
"""
MF_STAFF_V1 — Staff register upgrade.

FIXES
  1 ACCESS      A staff login could open the whole register: everyone's
                salary, record pay, delete staff or payments. Staff logins now
                see ATTENDANCE only; pay is owner / manager in the app, and
                staff_payments is owners + managers only in the database (020).
  2 PAY MONTH   Salary was matched to the month it was PAID in, so September
                paid on 2 October showed September unpaid. A payment now
                carries the month it settles (FOR MONTH); older ones keep the
                month of their date.
  3 ADVANCE     The whole advance came off the month's pay, and old months
                used today's balance. Advance is taken as it stood for that
                month, recovered per the person's plan (in full, or ₹X/month).
  4 LEAVING     ✕ deleted a person (history orphaned); OFF dropped them from
                that month's payroll; the P&L kept charging their salary.
                LEFT records the last working day: wages stop there, the final
                month stays for settlement. Delete only for someone added by
                mistake (nothing recorded), owner only.
  5 DELETE PAY  Anyone, no reason, no log → owner / manager, reason, logged.
  6 REVISION    A raise inside a month billed the whole month at the new
                rate. Each day is now paid at the salary in force that day.

NEW
  7 GRID        Month grid: staff × days, morning/night, tap to change;
                unmarked shifts in amber.
  8 STATEMENT   Per person: earned, paid, advances by month; who owes whom.
  9 PAYMENTS    Mode (cash / UPI / bank / cheque), reference, FOR MONTH;
                payslip lists the payments made against the month.
 10 DAYS OFF    Payroll rule "paid days off per month" (default 0).
 11 ADVANCES    Recovery plan per person; warning when an advance would
                take the balance past one month's salary.
 12 MISSING     Shifts in the last 14 days with somebody unmarked, with
                OPEN and ALL PRESENT.

SQL: db/020_staff_register.sql (the app works without it until it is run).
Usage:  python3 patch_staff.py [path/to/index.html]   (idempotent)
Requires MF_FIVE_V1 and MF_REPORTS_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_STAFF_V1"

MODULE = r"""// ══════════════════════════════════════════════════════════════════
// STAFF REGISTER — MF_STAFF_V1
//   access        staff logins see attendance only; pay is owner / manager
//   leaving       a "left on" date instead of delete / OFF; final month kept
//   pay months    a salary payment belongs to the month it settles
//   advances      as at the month; recovery plan per person
//   rules         salary revisions split by date; paid days off
//   grid          whole month of attendance; missing marks with one tap
//   statement     earned, paid, advances and the balance, per person
// Optional columns (db/020): staff.left_date, staff.meta,
// staff_payments.for_month / mode / ref — the app works without them.
// ══════════════════════════════════════════════════════════════════
function _staffPayOk(){ return !_currentUser||(typeof _isOwner!=='undefined'&&_isOwner)||(_currentUser&&_currentUser.role==='manager'); }
function _payMonth(p){ return (p&&p.forMonth&&/^\d{4}-\d{2}$/.test(p.forMonth))?p.forMonth:String(p&&p.date||'').slice(0,7); }
function _ymOf(d){ return String(d||'').slice(0,7); }
function _dm2(d){ return d?String(d).slice(8,10)+'/'+String(d).slice(5,7):''; }
// Last day this person could have worked. An old "OFF" with no date ends at
// their last attendance mark, so wages stop accruing there.
function _staffEnd(s){
  if(!s)return null;
  if(s.leftDate)return s.leftDate;
  if(s.active===false){
    var last=''; (typeof staffAttendance!=='undefined'?staffAttendance:[]).forEach(function(a){ if(a.staffId===s.id&&a.date>last)last=a.date; });
    return last||s.joinedDate||'0000-01-01';
  }
  return null;
}
function _staffOn(s,d){ return (!s.joinedDate||s.joinedDate<=d)&&(!_staffEnd(s)||_staffEnd(s)>=d); }
function _advPlan(s){ var p=s&&s.meta&&s.meta.advPlan; return (p&&p.mode==='fixed'&&(+p.amount>0))?{mode:'fixed',amount:+p.amount}:{mode:'full'}; }

// ── optional columns: try, drop the one the server lacks, try again ─────
var _MF_OPTCOL={};
async function _sbUpsertOpt(table,row,opt){
  opt.forEach(function(c){ if(_MF_OPTCOL[table+'.'+c]===false||row[c]===undefined)delete row[c]; });
  var cols=opt.filter(function(c){ return row[c]!==undefined; });
  if(cols.length&&_supa&&!(typeof navigator!=='undefined'&&navigator.onLine===false)){
    for(var i=0;i<4&&cols.length;i++){
      var r=await _supa.from(table).upsert(row,{onConflict:'id'});
      if(!r.error){ cols.forEach(function(c){ _MF_OPTCOL[table+'.'+c]=true; }); return; }
      var m=String(r.error.message||''), hit=cols.find(function(c){ return m.indexOf(c)>=0; });
      if(!hit&&typeof _isMissingCol==='function'&&_isMissingCol(m))hit=cols[cols.length-1];
      if(!hit)break;
      _MF_OPTCOL[table+'.'+hit]=false; delete row[hit]; cols=cols.filter(function(c){ return c!==hit; });
      console.warn(table+' has no '+hit+' column — apply db/020_staff_register.sql. That detail stays on this device until then.');
    }
  }
  await _sbUpsert(table,row);
}

// ── 4. leaving ─────────────────────────────────────────────────────────
function staffLeft(id){
  var s=staffList.find(function(x){ return x.id===id; }); if(!s)return;
  if(!_staffPayOk()){ showToast('🔒 Owner or manager only'); return; }
  if(s.active===false||s.leftDate){
    if(!confirm(s.name+' left on '+(s.leftDate||'—')+'. Take them back on from today?'))return;
    s.active=true; s.leftDate=null;
    if(!s.meta)s.meta={}; (s.meta.rejoined=s.meta.rejoined||[]).push({date:_isoLocal(),by:_currentUser?_currentUser.username:''});
    saveStaffLS(); if(_currentUser&&typeof sbSaveStaff==='function')sbSaveStaff(s).catch(console.error);
    if(typeof logActivity==='function')logActivity('staff_rejoin','staff',s.id,s.name+' back on '+_isoLocal());
    renderStaff(); showToast(s.name+' is active again'); return;
  }
  var d=prompt('Last working day for '+s.name+' (YYYY-MM-DD):\n\nWages are counted up to this day; their final month stays on the payroll so it can be settled.',_isoLocal());
  if(d===null)return; d=String(d).trim();
  if(!/^\d{4}-\d{2}-\d{2}$/.test(d)){ showToast('Use the form YYYY-MM-DD'); return; }
  if(s.joinedDate&&d<s.joinedDate){ showToast('That is before they joined ('+s.joinedDate+')'); return; }
  s.leftDate=d; s.active=false;
  saveStaffLS(); if(_currentUser&&typeof sbSaveStaff==='function')sbSaveStaff(s).catch(console.error);
  if(typeof logActivity==='function')logActivity('staff_left','staff',s.id,s.name+' left • last day '+d);
  renderStaff(); showToast(s.name+' marked as left — settle '+_monthRange(_ymOf(d)).label+' on the Monthly Report');
}

// ── payroll for one person, one month ──────────────────────────────────
function payrollFor(staff,ym){
  var cfg=payrollCfg(), R=_monthRange(ym), today=_isoLocal(), key=R.first.slice(0,7);
  var joined=staff.joinedDate||'', end=_staffEnd(staff);
  var from=(joined&&joined>R.first)?joined:R.first;
  var to=(R.last>today)?today:R.last; if(end&&end<to)to=end;
  var dates=[];
  if(to>=from){ for(var d=new Date(from+'T00:00:00');_isoLocal(d)<=to;d.setDate(d.getDate()+1))dates.push(_isoLocal(d)); }
  var eligible=dates.length, byDate={};
  staffAttendance.forEach(function(a){ if(a.staffId===staff.id&&a.date>=from&&a.date<=to)(byDate[a.date]=byDate[a.date]||[]).push(a.status); });
  var present=0, half=0, v={}, s={};
  dates.forEach(function(dd){
    var st=byDate[dd];
    if(!st){ v[dd]=cfg.unmarked==='present'?1:0; s[dd]=cfg.unmarked==='absent'?1:0; return; }
    var vals=st.map(function(x){ return x==='present'?1:(x==='half'?cfg.half:0); });
    present+=st.filter(function(x){ return x==='present'; }).length;
    half+=st.filter(function(x){ return x==='half'; }).length;
    v[dd]=cfg.both==='sum'?vals.reduce(function(a,b){ return a+b; },0):Math.min(1,Math.max.apply(null,vals.concat([0])));
    s[dd]=Math.max(0,1-v[dd]);
  });
  var markedDates=Object.keys(byDate).length, unmarked=Math.max(0,eligible-markedDates);
  // Paid days off: the first N days missed in the month are paid (prorated
  // for a part month). Weekly offs are not docked.
  var allow=(cfg.offDays>0&&R.days>0)?Math.floor(cfg.offDays*eligible/R.days*2)/2:0, left=allow, o={}, offPaid=0;
  dates.forEach(function(dd){ if(left<=0||!(s[dd]>0))return; var t=Math.min(left,s[dd]); o[dd]=t; left-=t; offPaid+=t; });
  // Each day at the salary in force that day — a raise on the 16th pays the
  // first fifteen days at the old rate.
  var rate=function(dd){ var sal=_salaryOn(staff,dd); return cfg.basis==='fixed30'?sal/30:sal/R.days; };
  var earned=0, worked=0, absent=0;
  dates.forEach(function(dd){
    var od=o[dd]||0; worked+=v[dd]+od; absent+=Math.max(0,s[dd]-od);
    if(cfg.basis==='deduct')earned+=(_salaryOn(staff,dd)/R.days)*(1-Math.max(0,s[dd]-od));
    else earned+=rate(dd)*(v[dd]+od);
  });
  earned=Math.max(0,_r2(earned));
  var salary=_salaryOn(staff,dates.length?dates[dates.length-1]:R.last);
  var perDay=cfg.basis==='fixed30'?salary/30:salary/R.days;
  // Payments that settle THIS month, whatever day they were made on.
  var pays=staffPayments.filter(function(p){ return p.staffId===staff.id&&p.type==='salary'&&_payMonth(p)===key; })
    .sort(function(a,b){ return String(a.date).localeCompare(String(b.date)); });
  var paid=_r2(pays.reduce(function(a,p){ return a+(+p.amount||0); },0));
  var dedThis=_r2(pays.reduce(function(a,p){ return a+(+p.advanceDeducted||0); },0));
  // Advance as it stood for this month: given up to its last day, less what
  // earlier months recovered.
  var advGiven=staffPayments.filter(function(p){ return p.staffId===staff.id&&p.type==='advance'&&String(p.date)<=R.last; })
    .reduce(function(a,p){ return a+(+p.amount||0); },0);
  var advRec=staffPayments.filter(function(p){ return p.staffId===staff.id&&(+p.advanceDeducted||0)>0&&_payMonth(p)<key; })
    .reduce(function(a,p){ return a+(+p.advanceDeducted||0); },0);
  var advOut=_r2(Math.max(0,advGiven-advRec-dedThis));
  var plan=_advPlan(staff), remaining=_r2(Math.max(0,earned-paid));
  var cap=plan.mode==='fixed'?Math.max(0,plan.amount-dedThis):Infinity;
  var advApplied=_r2(Math.min(advOut,cap,remaining));
  var net=_r2(remaining-advApplied);
  var revised=(staff.salaryHistory||[]).filter(function(h){ return h.date>=R.first&&h.date<=R.last; });
  return {staff:staff, month:R, key:key, salary:salary, perDay:_r2(perDay),
          eligible:eligible, present:present, half:half, absent:_r2(absent),
          unmarked:unmarked, worked:Math.round(worked*100)/100, offPaid:_r2(offPaid),
          earned:earned, paid:paid, payments:pays, dedThis:dedThis, advance:advOut,
          advApplied:advApplied, net:net, revised:revised, plan:plan,
          basis:cfg.basis, from:from, to:to, left:end&&end<=R.last&&end>=R.first?end:null};
}
function _payrollRows(){
  var el=document.getElementById('pay_month'), ym=el&&el.value?el.value:'', R=_monthRange(ym), key=R.first.slice(0,7);
  return staffList.filter(function(s){
    if(s.joinedDate&&s.joinedDate>R.last)return false;
    var e=_staffEnd(s); if(e&&e<R.first)return s.active!==false&&!s.leftDate;
    return true;
  }).sort(function(a,b){ return (typeof _nameCmp==='function')?_nameCmp(a.name,b.name):a.name.localeCompare(b.name); })
    .map(function(s){ return payrollFor(s,ym); })
    .filter(function(r){ return r.staff.active!==false||r.eligible>0||r.paid>0; });
}

// ── 7 / 12. month grid + missing marks ─────────────────────────────────
function _attModeGet(){ try{ return localStorage.getItem('mf_att_mode')||'day'; }catch(e){ return 'day'; } }
function attSetMode(m){ try{ localStorage.setItem('mf_att_mode',m); }catch(e){} renderAttendance(); }
function _attStaffFor(d){ return staffList.filter(function(s){ return _staffOn(s,d)&&(s.active!==false||s.leftDate); }); }
// A day counts as missing for a person when neither shift has a mark for
// them — the same test payroll uses for an unmarked day. Checked once the
// day's night shift has ended.
function _attMissing(days){
  var out=[], now=new Date(), d=new Date(); d.setDate(d.getDate()-(days||14));
  for(var i=0;i<=(days||14)+1;i++){
    var ds=_isoLocal(d);
    if(!(typeof mfSlotEnd==='function'&&mfSlotEnd({date:ds,shift:'night'})>now)){
      var miss=_attStaffFor(ds).filter(function(s){ return !staffAttendance.some(function(a){ return a.staffId===s.id&&a.date===ds; }); });
      if(miss.length)out.push({date:ds,staff:miss});
    }
    d.setDate(d.getDate()+1);
  }
  return out.reverse();
}
function attOpenSlot(date,sh){
  try{ localStorage.setItem('mf_att_mode','day'); }catch(e){}
  var a=document.getElementById('att_date'), b=document.getElementById('att_shift'); if(a)a.value=date; if(b)b.value=sh;
  renderAttendance();
}
function attFillPresent(date,sh){
  var miss=_attStaffFor(date).filter(function(s){ return !staffAttendance.some(function(a){ return a.staffId===s.id&&a.date===date; }); });
  if(!miss.length)return;
  if(!confirm('Mark '+miss.map(function(s){ return s.name; }).join(', ')+' PRESENT on the '+sh+' shift of '+date+'?'))return;
  miss.forEach(function(s){ setAttendance(s.id,date,sh,'present'); });
  showToast('✓ '+miss.length+' marked present');
}
function _renderAttMissing(){
  var box=document.getElementById('att_missing'); if(!box)return;
  var m=_attMissing(14);
  if(!m.length){ box.innerHTML='<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--green);margin-bottom:10px">✓ Everyone on the staff list has a mark for every day of the last 14.</div>'; return; }
  box.innerHTML='<div class="card" style="border-color:var(--diesel);margin-bottom:12px"><div class="card-head" style="color:var(--diesel)">⚠ NO MARK AT ALL — LAST 14 DAYS ('+m.length+' day'+(m.length!==1?'s':'')+')</div>'+
    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--muted);margin-bottom:4px">Payroll counts these as unmarked. OPEN a shift to mark it, or mark them present on one.</div>'+
    m.slice(0,12).map(function(x){
      var b=function(t,f){ return '<button class="btn btn-g" style="padding:2px 8px;font-size:10px" onclick="'+f+'">'+t+'</button>'; };
      return '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:5px 0;border-top:1px solid var(--border);font-family:\'JetBrains Mono\',monospace;font-size:11px">'+
        '<b style="min-width:52px">'+_esc(_dm2(x.date))+'</b>'+
        '<span style="color:var(--muted);flex:1">'+_esc(x.staff.map(function(s){ return s.name; }).join(', '))+'</span>'+
        b('OPEN M','attOpenSlot(\''+x.date+'\',\'morning\')')+b('OPEN N','attOpenSlot(\''+x.date+'\',\'night\')')+
        b('ALL P · M','attFillPresent(\''+x.date+'\',\'morning\')')+b('ALL P · N','attFillPresent(\''+x.date+'\',\'night\')')+'</div>';
    }).join('')+(m.length>12?'<div style="font-size:10px;color:var(--muted);margin-top:4px">… and '+(m.length-12)+' more — use the month grid</div>':'')+'</div>';
}
function attCycle(staffId,date,sh){
  var cur=(staffAttendance.find(function(a){ return a.staffId===staffId&&a.date===date&&a.shift===sh; })||{}).status||'';
  var next={'':'present',present:'half',half:'absent',absent:''}[cur];
  setAttendance(staffId,date,sh,next);
}
function _renderAttGrid(){
  var box=document.getElementById('att_grid'); if(!box)return;
  var mEl=document.getElementById('att_month');
  if(mEl&&!mEl.value)mEl.value=_isoLocal().slice(0,7);
  var R=_monthRange(mEl?mEl.value:''), today=_isoLocal();
  var staff=staffList.filter(function(s){ return (!s.joinedDate||s.joinedDate<=R.last)&&(!_staffEnd(s)||_staffEnd(s)>=R.first); })
    .sort(function(a,b){ return a.name.localeCompare(b.name); });
  if(!staff.length){ box.innerHTML='<div style="color:var(--muted);font-size:11px">No staff in this month.</div>'; return; }
  var map={}; staffAttendance.forEach(function(a){ if(a.date>=R.first&&a.date<=R.last)map[a.staffId+'|'+a.date+'|'+a.shift]=a.status; });
  var L={present:'P',half:'½',absent:'A'}, C={present:'var(--green)',half:'var(--blue)',absent:'var(--red)'};
  var days=[]; for(var i=1;i<=R.days;i++)days.push(R.first.slice(0,8)+String(i).padStart(2,'0'));
  var gaps=0;
  var cell=function(s,d,sh){
    if(d>today||!_staffOn(s,d))return '<span style="display:inline-block;width:16px;color:var(--border2)">·</span>';
    var st=map[s.id+'|'+d+'|'+sh]; if(!st)gaps++;
    return '<button title="'+_esc(s.name)+' · '+d+' '+sh+'" onclick="attCycle('+s.id+',\''+d+'\',\''+sh+'\')" style="width:18px;height:18px;padding:0;margin:0 1px;border-radius:3px;cursor:pointer;font-size:10px;font-weight:700;font-family:\'JetBrains Mono\',monospace;'+
      (st?'background:transparent;border:1px solid '+C[st]+';color:'+C[st]:'background:rgba(255,176,32,.18);border:1px solid var(--diesel);color:var(--diesel)')+'">'+(st?L[st]:'?')+'</button>';
  };
  var h='<div style="overflow-x:auto"><table class="data-tbl" style="font-size:10px;width:auto"><thead><tr><th style="position:sticky;left:0;background:var(--s1);z-index:1">STAFF</th>'+
    days.map(function(d){ var dw=new Date(d+'T00:00:00').getDay(); return '<th style="text-align:center;padding:4px 2px;'+(dw===0?'color:var(--diesel)':'')+'">'+(+d.slice(8,10))+'<br><span style="font-weight:400">'+'SMTWTFS'[dw]+'</span></th>'; }).join('')+
    '<th>PAID DAYS</th></tr></thead><tbody>';
  staff.forEach(function(s){
    var pr=_staffPayOk()?payrollFor(s,R.first.slice(0,7)):null;
    h+='<tr><td style="position:sticky;left:0;background:var(--s2);z-index:1;white-space:nowrap"><b>'+_esc(s.name)+'</b><div style="font-size:9px;color:var(--muted)">M<br>N</div></td>'+
      days.map(function(d){ return '<td style="padding:2px;text-align:center;white-space:nowrap">'+cell(s,d,'morning')+'<br>'+cell(s,d,'night')+'</td>'; }).join('')+
      '<td style="text-align:right;font-weight:700">'+(pr?pr.worked:'—')+'</td></tr>';
  });
  h+='</tbody></table></div><div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--muted);margin-top:6px;line-height:1.6">Tap a box to cycle: ? → P → ½ → A → ?. Top row morning, bottom row night. '+
    (gaps?'<span style="color:var(--diesel)">'+gaps+' shift'+(gaps!==1?'s':'')+' not marked (amber).</span>':'<span style="color:var(--green)">Every shift marked.</span>')+'</div>';
  box.innerHTML=h;
}

// ── 8. staff statement ─────────────────────────────────────────────────
function staffStatement(id){
  var s=staffList.find(function(x){ return x.id===id; }); if(!s)return;
  if(!_staffPayOk()){ showToast('🔒 Owner or manager only'); return; }
  // From the first thing recorded for them — months before the register was
  // kept would all read zero.
  var first='';
  staffAttendance.forEach(function(a){ if(a.staffId===id&&(!first||a.date<first))first=a.date; });
  staffPayments.forEach(function(p){ if(p.staffId===id&&(!first||p.date<first))first=p.date; });
  if(!first)first=s.joinedDate||'';
  if(s.joinedDate&&first<s.joinedDate)first=s.joinedDate;
  if(!first){ showToast('Nothing recorded for '+s.name+' yet'); return; }
  var end=_staffEnd(s)||_isoLocal(), months=[], d=new Date(first.slice(0,7)+'-01T00:00:00'), stop=end.slice(0,7);
  while(_isoLocal(d).slice(0,7)<=stop&&months.length<36){ months.push(_isoLocal(d).slice(0,7)); d.setMonth(d.getMonth()+1); }
  months=months.slice(-24);
  var owed=0, rows=[];
  months.forEach(function(ym){
    var R=_monthRange(ym), pr=payrollFor(s,ym);
    var adv=staffPayments.filter(function(p){ return p.staffId===id&&p.type==='advance'&&_ymOf(p.date)===ym; }).reduce(function(a,p){ return a+(+p.amount||0); },0);
    var bon=staffPayments.filter(function(p){ return p.staffId===id&&p.type==='bonus'&&_ymOf(p.date)===ym; }).reduce(function(a,p){ return a+(+p.amount||0); },0);
    var chit=staffPayments.filter(function(p){ return p.staffId===id&&p.type==='chit'&&_ymOf(p.date)===ym; }).reduce(function(a,p){ return a+(+p.amount||0); },0);
    owed=_r2(owed+pr.earned-pr.paid);
    rows.push({R:R,pr:pr,adv:adv,bon:bon,chit:chit,owed:owed});
  });
  var advNow=getStaffAdvanceBalance(id), netNow=_r2(owed-advNow);
  var money=function(n){ return '₹'+(+n||0).toLocaleString('en-IN',{maximumFractionDigits:2}); };
  var html='<div class="wk"><div class="wk-h"><div class="wk-title">'+_esc(s.name)+' — staff statement</div>'+
    '<div class="wk-meta">'+_esc(s.role||'')+(s.joinedDate?' · joined '+_esc(s.joinedDate):'')+(_staffEnd(s)?' · left '+_esc(_staffEnd(s)):'')+
    ' · salary now '+money(s.monthlySalary)+'/mo · advance plan: '+(_advPlan(s).mode==='fixed'?money(_advPlan(s).amount)+' a month':'recover in full')+'</div></div>'+
    '<table class="wk-tbl"><thead><tr><th>Month</th><th style="text-align:right">Days paid</th><th style="text-align:right">Earned</th><th style="text-align:right">Salary paid</th>'+
    '<th style="text-align:right">Advance given</th><th style="text-align:right">Advance recovered</th><th style="text-align:right">Bonus</th><th style="text-align:right">Chit</th><th style="text-align:right">Wages owed (running)</th></tr></thead><tbody>'+
    rows.map(function(x){ return '<tr><td>'+x.R.label+'</td><td style="text-align:right">'+x.pr.worked+'</td><td style="text-align:right">'+money(x.pr.earned)+'</td>'+
      '<td style="text-align:right">'+money(x.pr.paid)+'</td><td style="text-align:right">'+(x.adv?money(x.adv):'—')+'</td><td style="text-align:right">'+(x.pr.dedThis?money(x.pr.dedThis):'—')+'</td>'+
      '<td style="text-align:right">'+(x.bon?money(x.bon):'—')+'</td><td style="text-align:right">'+(x.chit?money(x.chit):'—')+'</td>'+
      '<td style="text-align:right;font-weight:700">'+money(x.owed)+'</td></tr>'; }).join('')+
    '</tbody></table>'+
    '<table class="wk-tbl" style="margin-top:10px;max-width:420px"><tbody>'+
      '<tr><td>Wages earned but not yet paid</td><td style="text-align:right">'+money(owed)+'</td></tr>'+
      '<tr><td>Less: advance still outstanding</td><td style="text-align:right">− '+money(advNow)+'</td></tr>'+
      '<tr class="wk-grand"><td><b>'+(netNow>=0?'Station owes '+_esc(s.name):_esc(s.name)+' owes the station')+'</b></td><td style="text-align:right"><b>'+money(Math.abs(netNow))+'</b></td></tr>'+
    '</tbody></table>'+
    '<p class="wk-p wk-f">Earned is worked out from the attendance register on the payroll rules. Salary paid is matched to the month it settles. Bonus and chit are shown but are not part of the wages balance.</p></div>';
  var ov=document.getElementById('staffHistOverlay');
  if(!ov){
    ov=document.createElement('div'); ov.id='staffHistOverlay';
    ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:850;display:flex;align-items:center;justify-content:center;padding:20px';
    ov.innerHTML='<div id="staffHistContent" style="background:var(--s2);border:1px solid var(--border2);border-radius:12px;padding:22px;max-width:880px;width:100%;max-height:85vh;overflow-y:auto"></div>';
    document.body.appendChild(ov);
  }
  document.getElementById('staffHistContent').innerHTML=
    '<div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:10px"><button class="btn btn-g" onclick="staffStatementPrint()">🖨 PRINT</button>'+
    '<button class="btn btn-g" onclick="document.getElementById(\'staffHistOverlay\').style.display=\'none\'">✕</button></div>'+
    '<div id="staff_stmt_doc" style="background:#fff;color:#111;padding:14px;border-radius:6px">'+html+'</div>';
  ov.style.display='flex';
}
function staffStatementPrint(){
  var doc=document.getElementById('staff_stmt_doc'); if(!doc)return;
  document.getElementById('pdf-print-area').innerHTML=doc.innerHTML;
  document.getElementById('staffHistOverlay').style.display='none';
  _mfPrintArea('Mani Fuels · Staff statement');
  if(typeof logActivity==='function')logActivity('staff_statement','staff',null,'Statement printed');
  setTimeout(function(){ window.print(); },300);
}"""

HUNKS = [
("C1 statement on screen",
r"""/* MF_REPORTS_V1 — report views */""",
r"""/* MF_STAFF_V1 — staff statement on screen (white paper) */
#staff_stmt_doc .wk-title{font-size:16px;font-weight:800}
#staff_stmt_doc .wk-meta,#staff_stmt_doc .wk-f{font-size:10px;color:#555}
#staff_stmt_doc .wk-h{border-bottom:2px solid #111;padding-bottom:6px;margin-bottom:8px}
#staff_stmt_doc .wk-tbl{width:100%;border-collapse:collapse;font-size:11px;color:#111}
#staff_stmt_doc .wk-tbl th{background:#ececec;color:#333;font-size:9px;text-transform:uppercase;padding:4px 6px;border-bottom:1px solid #999;white-space:nowrap}
#staff_stmt_doc .wk-tbl td{padding:4px 6px;border-bottom:1px solid #e2e2e2}
#staff_stmt_doc .wk-grand td{border-top:1px solid #111;border-bottom:3px double #111;font-weight:800}
/* MF_REPORTS_V1 — report views */"""),

# ── HTML ────────────────────────────────────────────────────────────────
("H1 staff form: advance recovery",
r"""        <div style="margin-bottom:10px">
          <div class="flabel" style="margin-bottom:4px">NOTES</div>
          <input type="text" id="sf_notes" placeholder="Optional"></div>""",
r"""        <div style="margin-bottom:10px">
          <div class="flabel" style="margin-bottom:4px">NOTES</div>
          <input type="text" id="sf_notes" placeholder="Optional"></div>
        <div class="fgrid" style="margin-bottom:10px"><!-- MF_STAFF_V1 -->
          <div><div class="flabel" style="margin-bottom:4px">ADVANCE RECOVERY</div>
            <select id="sf_advmode" style="width:100%;padding:5px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px;height:32px">
              <option value="full">All of it from the next salary</option><option value="fixed">A fixed amount each month</option></select></div>
          <div><div class="flabel" style="margin-bottom:4px">₹ PER MONTH (IF FIXED)</div>
            <input type="number" id="sf_advamt" placeholder="e.g. 1000" min="0"></div>
        </div>"""),

("H2 attendance: day / month grid, missing marks",
r"""  <div id="staff_view_attendance" style="display:none">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
      <div class="flabel">DATE</div>""",
r"""  <div id="staff_view_attendance" style="display:none">
    <div style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;align-items:center"><!-- MF_STAFF_V1 -->
      <button class="range-btn" id="att_mode_day" onclick="attSetMode('day')">DAY</button>
      <button class="range-btn" id="att_mode_grid" onclick="attSetMode('grid')">MONTH GRID</button>
      <span id="att_grid_ctl" style="display:none;align-items:center;gap:8px"><input type="month" id="att_month" class="date-inp" onchange="renderAttendance()"></span>
    </div>
    <div id="att_missing"></div>
    <div id="att_grid" style="display:none;margin-bottom:12px"></div>
    <div id="att_day_ctl" style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
      <div class="flabel">DATE</div>"""),

("H3 day table id",
r"""    <div class="card" style="overflow-x:auto">
      <table class="data-tbl" style="width:100%;min-width:540px">""",
r"""    <div class="card" id="att_day_card" style="overflow-x:auto">
      <table class="data-tbl" style="width:100%;min-width:540px">"""),

("H4 payroll rule: paid days off",
r"""          <div>
            <div class="flabel" style="margin-bottom:4px">HALF DAY IS WORTH</div>
            <input type="number" id="pc_half" step="0.05" min="0" max="1" oninput="savePayrollCfg()" style="width:100%;height:34px">
          </div>""",
r"""          <div>
            <div class="flabel" style="margin-bottom:4px">HALF DAY IS WORTH</div>
            <input type="number" id="pc_half" step="0.05" min="0" max="1" oninput="savePayrollCfg()" style="width:100%;height:34px">
          </div>
          <div><!-- MF_STAFF_V1 -->
            <div class="flabel" style="margin-bottom:4px" title="Weekly offs: this many days missed in a month are paid, not docked">PAID DAYS OFF / MONTH</div>
            <input type="number" id="pc_off" step="0.5" min="0" max="10" oninput="savePayrollCfg()" style="width:100%;height:34px">
          </div>"""),

("H5 payroll header",
r"""<th>PER DAY</th><th>EARNED</th><th>ADVANCE DUE</th><th>PAID THIS MONTH</th>""",
r"""<th>PER DAY</th><th>EARNED</th><th>ADVANCE DUE</th><th title="Salary payments recorded FOR this month, whenever they were paid">PAID FOR MONTH</th>"""),

("H6 payment form: mode, ref, for month",
r"""        <div id="pf_preview" style="margin-bottom:10px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);min-height:14px"></div>""",
r"""        <div class="fgrid" style="margin-bottom:10px"><!-- MF_STAFF_V1 -->
          <div><div class="flabel" style="margin-bottom:4px">MODE</div>
            <select id="pf_mode" style="width:100%;padding:5px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px;height:32px">
              <option>Cash</option><option>UPI</option><option>Bank Transfer</option><option>Cheque</option></select></div>
          <div><div class="flabel" style="margin-bottom:4px">REF / UTR</div>
            <input type="text" id="pf_ref" placeholder="optional"></div>
          <div id="pf_for_wrap"><div class="flabel" style="margin-bottom:4px" title="Which month's salary this settles">FOR MONTH</div>
            <input type="month" id="pf_for" class="date-inp" style="width:100%"></div>
        </div>
        <div id="pf_preview" style="margin-bottom:10px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);min-height:14px"></div>"""),

("H7 payments table header",
r"""<thead><tr><th>DATE</th><th>STAFF</th><th>TYPE</th><th>AMOUNT</th><th>NOTES</th><th></th></tr></thead>""",
r"""<thead><tr><th>DATE</th><th>STAFF</th><th>TYPE</th><th>AMOUNT</th><th>MODE</th><th>FOR</th><th>NOTES</th><th></th></tr></thead>"""),

# ── access, tabs ────────────────────────────────────────────────────────
("J1 staff logins: attendance only",
r"""function staffShowTab(tab){
  _currentStaffTab=tab;""",
r"""function staffShowTab(tab){
  // MF_STAFF_V1: salaries and pay are owner / manager only
  var _payOk=(typeof _staffPayOk==='function')?_staffPayOk():true;
  ['list','pay','report'].forEach(function(k){ var b=document.getElementById('staff_tab_'+k); if(b)b.style.display=_payOk?'':'none'; });
  if(!_payOk)tab='attendance';
  _currentStaffTab=tab;"""),

("J2 edit: owner/manager; load the advance plan",
r"""function editStaff(id){
  const st=staffList.find(x=>x.id===id);""",
r"""function editStaff(id){
  if(typeof _staffPayOk==='function'&&!_staffPayOk()){showToast('🔒 Owner or manager only');return;}   // MF_STAFF_V1
  const st=staffList.find(x=>x.id===id);"""),

("J3 edit: plan fields",
r"""  set('sf_salary',st.monthlySalary); set('sf_joined',st.joinedDate); set('sf_notes',st.notes);""",
r"""  set('sf_salary',st.monthlySalary); set('sf_joined',st.joinedDate); set('sf_notes',st.notes);
  const _ap=(typeof _advPlan==='function')?_advPlan(st):{mode:'full'}; set('sf_advmode',_ap.mode); set('sf_advamt',_ap.mode==='fixed'?_ap.amount:'');   // MF_STAFF_V1"""),

("J4 new form resets the plan",
r"""    document.getElementById('sf_role').value='Operator';""",
r"""    document.getElementById('sf_role').value='Operator';
    { const _m=document.getElementById('sf_advmode'); if(_m)_m.value='full'; const _a=document.getElementById('sf_advamt'); if(_a)_a.value=''; }   // MF_STAFF_V1"""),

("J5 save: owner/manager",
r"""function submitStaff(){
  const name=_clean(document.getElementById('sf_name').value.trim());""",
r"""function submitStaff(){
  if(typeof _staffPayOk==='function'&&!_staffPayOk()){showToast('🔒 Owner or manager only');return;}   // MF_STAFF_V1
  const name=_clean(document.getElementById('sf_name').value.trim());"""),

("J6 save: read the plan",
r"""  const notes=_clean(document.getElementById('sf_notes').value.trim());

  if(_editingStaffId!=null){""",
r"""  const notes=_clean(document.getElementById('sf_notes').value.trim());
  // MF_STAFF_V1: how an advance is recovered from this person's salary
  const _am=(document.getElementById('sf_advmode')||{}).value||'full', _aa=parseFloat((document.getElementById('sf_advamt')||{}).value)||0;
  if(_am==='fixed'&&!(_aa>0)){showToast('Enter how much advance to recover each month');return;}
  const advPlan=_am==='fixed'?{mode:'fixed',amount:_aa}:{mode:'full'};

  if(_editingStaffId!=null){"""),

("J7 save: plan change is a change",
r"""    if(!changes.length){showToast('Nothing changed');_resetStaffForm();""",
r"""    const _op=(typeof _advPlan==='function')?_advPlan(st):{mode:'full'};
    if(_op.mode!==advPlan.mode||(_op.amount||0)!==(advPlan.amount||0)){
      st.meta=Object.assign({},st.meta||{},{advPlan:advPlan});
      changes.push('advance recovery → '+(advPlan.mode==='fixed'?'₹'+advPlan.amount+'/month':'in full'));
    }
    if(!changes.length){showToast('Nothing changed');_resetStaffForm();"""),

("J8 new staff carries the plan",
r"""    active:true, salaryHistory:[]
  };""",
r"""    active:true, salaryHistory:[], meta:{advPlan:advPlan}   // MF_STAFF_V1
  };"""),

("J9 delete only someone added by mistake",
r"""function deleteStaff(id){
  const s=staffList.find(x=>x.id===id);if(!s)return;
  if(!confirm('Remove '+s.name+' from staff register?'))return;""",
r"""function deleteStaff(id){
  const s=staffList.find(x=>x.id===id);if(!s)return;
  // MF_STAFF_V1: a person with history is marked LEFT, never deleted
  if(typeof _isOwner!=='undefined'&&!_isOwner){showToast('🔒 Owner access only');return;}
  if(staffAttendance.some(a=>a.staffId===id)||staffPayments.some(p=>p.staffId===id)){
    showToast(s.name+' has attendance or payments on record — use LEFT instead, so the history and the final settlement stay');return;}
  if(!confirm('Remove '+s.name+' from the staff register?\n\nOnly for someone added by mistake — nothing is recorded against them.'))return;"""),

("J10 OFF/ON becomes LEFT/REJOIN",
r"""function toggleStaffActive(id){
  const s=staffList.find(x=>x.id===id);if(!s)return;
  s.active=!s.active;
  saveStaffLS();
  if(_currentUser&&typeof sbSaveStaff==='function')sbSaveStaff(s).catch(console.error);
  renderStaff();
}""",
r"""function toggleStaffActive(id){ return staffLeft(id); }   // MF_STAFF_V1: leaving is dated"""),

# ── payroll ─────────────────────────────────────────────────────────────
("P1 payroll rules: paid days off",
r"""function payrollCfg(){
  var d={basis:'fixed30', both:'cap', unmarked:'ignore', half:0.5};
  try{
    var c=JSON.parse(localStorage.getItem('payrollCfg')||'null');
    if(c)return {
      basis:    c.basis    || d.basis,
      both:     c.both     || d.both,
      unmarked: c.unmarked || d.unmarked,
      half:     (c.half!=null && isFinite(parseFloat(c.half))) ? parseFloat(c.half) : d.half
    };""",
r"""function payrollCfg(){
  var d={basis:'fixed30', both:'cap', unmarked:'ignore', half:0.5, offDays:0};
  try{
    var c=JSON.parse(localStorage.getItem('payrollCfg')||'null');
    if(c)return {
      basis:    c.basis    || d.basis,
      both:     c.both     || d.both,
      unmarked: c.unmarked || d.unmarked,
      half:     (c.half!=null && isFinite(parseFloat(c.half))) ? parseFloat(c.half) : d.half,
      offDays:  (c.offDays!=null && isFinite(parseFloat(c.offDays))) ? Math.max(0,parseFloat(c.offDays)) : d.offDays   // MF_STAFF_V1
    };"""),

("P2 save paid days off",
r"""    half:     (isFinite(h)&&h>=0&&h<=1)?h:0.5
  }));""",
r"""    half:     (isFinite(h)&&h>=0&&h<=1)?h:0.5,
    offDays:  Math.max(0,parseFloat(g('pc_off'))||0)   // MF_STAFF_V1
  }));"""),

("P3 P&L wages stop on the last working day",
r"""  staffList.forEach(function(s){
    var start=(s.joinedDate&&s.joinedDate>lo)?s.joinedDate:lo;""",
r"""  var _hiAll=hi;   // MF_STAFF_V1
  staffList.forEach(function(s){
    var hi=_hiAll, _end=(typeof _staffEnd==='function')?_staffEnd(s):null; if(_end&&_end<hi)hi=_end;   // left: no wages after the last day
    var start=(s.joinedDate&&s.joinedDate>lo)?s.joinedDate:lo;"""),

("P4 old payrollFor retired",
r"""function payrollFor(staff,ym){
  var cfg=payrollCfg(), R=_monthRange(ym);
  var joined=staff.joinedDate||'';""",
r"""// MF_STAFF_V1: replaced by payrollFor() in the STAFF REGISTER block below.
function _payrollForOld(staff,ym){
  var cfg=payrollCfg(), R=_monthRange(ym);
  var joined=staff.joinedDate||'';"""),

("P5 old _payrollRows retired",
r"""function _payrollRows(){
  var el=document.getElementById('pay_month');
  var ym=el&&el.value?el.value:'';""",
r"""function _payrollRowsOld(){   // MF_STAFF_V1: replaced below
  var el=document.getElementById('pay_month');
  var ym=el&&el.value?el.value:'';"""),

("P6 report: rule field",
r"""  setv('pc_unmarked',cfg.unmarked); setv('pc_half',cfg.half);""",
r"""  setv('pc_unmarked',cfg.unmarked); setv('pc_half',cfg.half); setv('pc_off',cfg.offDays||0);   // MF_STAFF_V1"""),

("P7 report row: left, days off, plan",
r"""        (r.revised.length?'<br><span style="font-size:9px;color:var(--diesel)">&#9888; salary revised '+_esc(r.revised[0].date)+'</span>':'')+""",
r"""        (r.revised.length?'<br><span style="font-size:9px;color:var(--diesel)">&#9888; salary revised '+_esc(r.revised[0].date)+'</span>':'')+
        (r.left?'<br><span style="font-size:9px;color:var(--red)">LEFT '+_esc(r.left)+' — final month</span>':'')+
        (r.offPaid>0?'<br><span style="font-size:9px;color:var(--blue)">'+r.offPaid+' paid day'+(r.offPaid!==1?'s':'')+' off</span>':'')+
        (r.plan&&r.plan.mode==='fixed'&&r.advance>0?'<br><span style="font-size:9px;color:var(--diesel)">advance ₹'+r.plan.amount.toLocaleString('en-IN')+'/month</span>':'')+"""),

("P8 revision note: split by date",
r"""  var rev=rows.filter(function(r){return r.revised.length;});""",
r"""  // MF_STAFF_V1: a revision inside the month is split by date now
  rows.filter(function(r){return r.revised.length;}).forEach(function(r){
    notes.push({level:'info', text:r.staff.name+'’s salary changed on '+r.revised[0].date+
      ' — days before it are paid at the old rate, days from it at the new one.'}); });
  var rev=[];"""),

("P9 PAY pre-fills the month it settles",
r"""  set('pf_staff',staffId); set('pf_type','salary');""",
r"""  set('pf_staff',staffId); set('pf_type','salary'); set('pf_for',r.key);   // MF_STAFF_V1"""),

("P10 payslip: paid days off",
r"""['Shifts absent',r.absent],['Days not marked',r.unmarked],['<b>Days paid</b>','<b>'+r.worked+'</b>']]""",
r"""['Shifts absent',r.absent],['Days not marked',r.unmarked],['Paid days off',r.offPaid||0],['<b>Days paid</b>','<b>'+r.worked+'</b>']]"""),

("P11 payslip: payments against the month",
r"""      (r.advance>r.advApplied?'<div style="margin-top:10px;padding:8px 12px;background:#fff8e1;border:1px solid #ffe082;border-radius:4px;font-size:10px">Advance still outstanding after this month: <b>'+money(r.advance-r.advApplied)+'</b></div>':'')+""",
r"""      ((r.payments&&r.payments.length)?'<div style="margin-top:10px;font-size:10px"><b>Paid against this month</b><table style="width:100%;border-collapse:collapse;margin-top:4px">'+
        r.payments.map(function(p){ return '<tr><td style="padding:3px 8px;border:1px solid #ddd">'+_esc(p.date)+'</td><td style="padding:3px 8px;border:1px solid #ddd">'+_esc(p.mode||'—')+(p.ref?' · '+_esc(p.ref):'')+'</td>'+
          '<td style="padding:3px 8px;border:1px solid #ddd;text-align:right">'+money(p.amount)+'</td><td style="padding:3px 8px;border:1px solid #ddd;text-align:right">'+((+p.advanceDeducted||0)>0?'adv. '+money(p.advanceDeducted):'')+'</td></tr>'; }).join('')+
        '</table></div>':'')+   // MF_STAFF_V1
      (r.advance>r.advApplied?'<div style="margin-top:10px;padding:8px 12px;background:#fff8e1;border:1px solid #ffe082;border-radius:4px;font-size:10px">Advance still outstanding after this month: <b>'+money(r.advance-r.advApplied)+'</b></div>':'')+"""),

("P12 CSV columns",
r"""'advance_applied','paid_this_month','net_payable'];""",
r"""'advance_applied','paid_for_month','net_payable','paid_days_off','left_on'];"""),

("P13 CSV row",
r"""r.earned,r.advance,r.advApplied,r.paid,r.net].join(','));""",
r"""r.earned,r.advance,r.advApplied,r.paid,r.net,r.offPaid||0,r.left||''].join(','));"""),

# ── staff cards ─────────────────────────────────────────────────────────
("K1 card: name escaped",
r"""          <div style="font-family:'Syne',sans-serif;font-weight:800;font-size:14px">${s.name}</div>""",
r"""          <div style="font-family:'Syne',sans-serif;font-weight:800;font-size:14px">${_esc(s.name)}</div>"""),

("K2 card: salary paid FOR this month",
r"""    const salaryThisMonth=staffPayments.filter(p=>p.staffId===s.id&&p.type==='salary'&&p.date>=ms).reduce((sum,p)=>sum+(p.amount||0),0);""",
r"""    const salaryThisMonth=staffPayments.filter(p=>p.staffId===s.id&&p.type==='salary'&&(typeof _payMonth==='function'?_payMonth(p)===ms.slice(0,7):p.date>=ms)).reduce((sum,p)=>sum+(p.amount||0),0);   // MF_STAFF_V1"""),

("K3 card: LEFT badge",
r"""        ${s.active?'<span class="badge bg_">ACTIVE</span>':'<span class="badge" style="background:rgba(180,180,180,.15);color:var(--muted)">INACTIVE</span>'}""",
r"""        ${s.active?'<span class="badge bg_">ACTIVE</span>':'<span class="badge" style="background:rgba(180,180,180,.15);color:var(--muted)">'+(s.leftDate?'LEFT '+_esc(s.leftDate.slice(8,10)+'/'+s.leftDate.slice(5,7)+'/'+s.leftDate.slice(2,4)):'INACTIVE')+'</span>'}"""),

("K4 card: statement, LEFT/REJOIN",
r"""        <button class="btn btn-g" style="padding:4px 10px;font-size:10px" onclick="viewStaffHistory(${s.id})">📜</button>
        <button class="btn btn-g" style="padding:4px 10px;font-size:10px" onclick="toggleStaffActive(${s.id})">${s.active?'OFF':'ON'}</button>""",
r"""        <button class="btn btn-g" style="padding:4px 10px;font-size:10px" onclick="viewStaffHistory(${s.id})" title="Payments and salary changes">📜</button>
        <button class="btn btn-g" style="padding:4px 10px;font-size:10px" onclick="staffStatement(${s.id})" title="Statement: earned, paid, advances, balance">📒</button>
        <button class="btn btn-g" style="padding:4px 10px;font-size:10px" onclick="staffLeft(${s.id})" title="${s.active?'Record the last working day':'Take back on'}">${s.active?'LEFT':'REJOIN'}</button>"""),

# ── attendance ──────────────────────────────────────────────────────────
("A1 attendance: grid mode and missing marks",
r"""function renderAttendance(){
  const date=document.getElementById('att_date').value||_isoLocal();""",
r"""function renderAttendance(){
  // MF_STAFF_V1: missing marks + month grid
  try{ if(typeof _renderAttMissing==='function')_renderAttMissing(); }catch(e){ console.warn('attendance gaps:',e); }
  const _mode=(typeof _attModeGet==='function')?_attModeGet():'day';
  const _g=document.getElementById('att_grid'), _dc=document.getElementById('att_day_card'), _dctl=document.getElementById('att_day_ctl'), _gctl=document.getElementById('att_grid_ctl');
  if(_g)_g.style.display=_mode==='grid'?'':'none'; if(_dc)_dc.style.display=_mode==='grid'?'none':'';
  if(_dctl)_dctl.style.display=_mode==='grid'?'none':'flex'; if(_gctl)_gctl.style.display=_mode==='grid'?'flex':'none';
  ['day','grid'].forEach(function(k){ var b=document.getElementById('att_mode_'+k); if(b)b.classList.toggle('active',_mode===k); });
  if(_mode==='grid'){ try{ _renderAttGrid(); }catch(e){ console.error('attendance grid:',e); } return; }
  const date=document.getElementById('att_date').value||_isoLocal();"""),

("A2 day view: everyone employed that day",
r"""  const active=staffList.filter(s=>s.active);
  if(!active.length){""",
r"""  const active=staffList.filter(s=>(typeof _staffOn==='function')?(_staffOn(s,date)&&(s.active!==false||!!s.leftDate)):s.active);   // MF_STAFF_V1
  if(!active.length){"""),

("A3 day view: escaped",
r"""    tr.innerHTML=`<td><b>${s.name}</b></td>
      <td style="color:var(--muted);font-size:11px">${s.role}</td>""",
r"""    tr.innerHTML=`<td><b>${_esc(s.name)}</b>${s.leftDate?' <span style="font-size:9px;color:var(--muted)">left '+_esc(s.leftDate)+'</span>':''}</td>
      <td style="color:var(--muted);font-size:11px">${_esc(s.role||'')}</td>"""),

("A4 day view: notes escaped",
r"""        <input type="text" placeholder="—" value="${notes||''}" onchange="setAttNotes(""",
r"""        <input type="text" placeholder="—" value="${_esc(notes||'')}" onchange="setAttNotes("""),

# ── payments ────────────────────────────────────────────────────────────
("Y1 payment form: owner/manager",
r"""function togglePaymentForm(){
  const f=document.getElementById('pay_form');""",
r"""function togglePaymentForm(){
  if(typeof _staffPayOk==='function'&&!_staffPayOk()){showToast('🔒 Owner or manager only');return;}   // MF_STAFF_V1
  const f=document.getElementById('pay_form');"""),

("Y2 payment form: people who left can still be settled",
r"""    sel.innerHTML=staffList.filter(s=>s.active).map(s=>`<option value="${s.id}">${s.name}</option>`).join('');""",
r"""    sel.innerHTML=staffList.filter(s=>s.active||s.leftDate).map(s=>`<option value="${s.id}">${_esc(s.name)}${s.leftDate?' (left)':''}</option>`).join('');   // MF_STAFF_V1"""),

("Y3 payment form: reset mode/ref/month",
r"""    document.getElementById('pf_notes').value='';
    document.getElementById('pf_type').value='salary';""",
r"""    document.getElementById('pf_notes').value='';
    { const _m=document.getElementById('pf_mode'); if(_m)_m.value='Cash'; const _r=document.getElementById('pf_ref'); if(_r)_r.value=''; const _f=document.getElementById('pf_for'); if(_f)_f.value=''; }   // MF_STAFF_V1
    document.getElementById('pf_type').value='salary';"""),

("Y4 for-month only on salary; sensible default",
r"""  // Show advance deduction row only on salary if pending balance exists""",
r"""  // MF_STAFF_V1: which month a salary payment settles — up to the 7th, last month
  { const _fw=document.getElementById('pf_for_wrap'); if(_fw)_fw.style.display=type==='salary'?'':'none';
    const _pf=document.getElementById('pf_for');
    if(_pf&&!_pf.value){ const _n=new Date(); const _d=_n.getDate()<=7?new Date(_n.getFullYear(),_n.getMonth()-1,1):new Date(_n.getFullYear(),_n.getMonth(),1); _pf.value=_isoLocal(_d).slice(0,7); } }
  // Show advance deduction row only on salary if pending balance exists"""),

("Y5 save payment: owner/manager, advance warning",
r"""  if(!staffId||!amt){showToast('Select staff and enter amount');return;}""",
r"""  if(!staffId||!amt){showToast('Select staff and enter amount');return;}
  if(typeof _staffPayOk==='function'&&!_staffPayOk()){showToast('🔒 Owner or manager only');return;}   // MF_STAFF_V1
  if(type==='advance'){
    const _st=staffList.find(x=>x.id===staffId), _sal=_st?(parseFloat(_st.monthlySalary)||0):0, _out=getStaffAdvanceBalance(staffId);
    if(_sal>0&&_out+amt>_sal&&!confirm((_st?_st.name:'This person')+' would owe ₹'+(_out+amt).toLocaleString('en-IN')+' in advances — more than one month’s salary (₹'+_sal.toLocaleString('en-IN')+').\n\nGive it anyway?'))return;
  }"""),

("Y6 save payment: mode, ref, month",
r"""    advanceDeducted:deduct,
    createdBy:_currentUser?_currentUser.username:''
  };""",
r"""    advanceDeducted:deduct,
    createdBy:_currentUser?_currentUser.username:'',
    // MF_STAFF_V1
    mode:(document.getElementById('pf_mode')||{}).value||'Cash',
    ref:_clean(((document.getElementById('pf_ref')||{}).value||'').trim()),
    forMonth:type==='salary'?(((document.getElementById('pf_for')||{}).value)||date.slice(0,7)):null
  };"""),

("Y7 delete payment: owner/manager, reason, log",
r"""function delPayment(id){
  if(!confirm('Delete this payment?'))return;
  staffPayments=staffPayments.filter(p=>p.id!==id);
  savePayLS();
  if(_currentUser&&typeof sbDelete==='function')sbDelete('staff_payments',id).catch(console.error);
  renderPayments();
}""",
r"""function delPayment(id){
  // MF_STAFF_V1
  if(typeof _staffPayOk==='function'&&!_staffPayOk()){showToast('🔒 Owner or manager only');return;}
  const p=staffPayments.find(x=>x.id===id); if(!p)return;
  const s=staffList.find(x=>x.id===p.staffId);
  const why=prompt('Delete the '+p.type+' of ₹'+(+p.amount||0).toLocaleString('en-IN')+' to '+(s?s.name:'—')+' on '+p.date+'?\n\nReason:','Entered by mistake');
  if(why===null)return;
  staffPayments=staffPayments.filter(x=>x.id!==id);
  savePayLS();
  if(_currentUser&&typeof sbDelete==='function')sbDelete('staff_payments',id).catch(console.error);
  if(typeof logActivity==='function')logActivity('del_staff_pay','staff',p.staffId,
    (s?s.name:'')+' • '+p.type+' ₹'+p.amount+' of '+p.date+((+p.advanceDeducted||0)>0?' (adv ₹'+p.advanceDeducted+')':'')+' • '+_clean(String(why)));
  renderPayments(); if(typeof renderStaff==='function')renderStaff();
  showToast('Payment deleted');
}"""),

("Y8 payments list: mode and month",
r"""      <td style="font-size:11px;color:var(--muted)">${p.notes||'—'}</td>
      <td><button class="btn btn-d" style="padding:3px 8px;font-size:10px" onclick="delPayment(${p.id})">&#10005;</button></td>`;""",
r"""      <td style="font-size:11px">${_esc(p.mode||'—')}${p.ref?'<br><span style="color:var(--muted)">'+_esc(p.ref)+'</span>':''}</td>
      <td style="font-size:11px">${p.type==='salary'&&typeof _payMonth==='function'?_esc(_payMonth(p)):'—'}</td>
      <td style="font-size:11px;color:var(--muted)">${_esc(p.notes||'—')}</td>
      <td><button class="btn btn-d" style="padding:3px 8px;font-size:10px" onclick="delPayment(${p.id})">&#10005;</button></td>`;"""),

# ── sync ────────────────────────────────────────────────────────────────
("Z1 save staff: left date, meta",
r"""    await _sbUpsert('staff', {
      id:Math.round(s.id),user_id:_currentUser.id,name:s.name,role:s.role,
      monthly_salary:s.monthlySalary,phone:s.phone,active:s.active,
      joined_date:s.joinedDate,notes:s.notes,
      salary_history:s.salaryHistory||[]
    });""",
r"""    await _sbUpsertOpt('staff', {   // MF_STAFF_V1: left_date, meta are db/020
      id:Math.round(s.id),user_id:_currentUser.id,name:s.name,role:s.role,
      monthly_salary:s.monthlySalary,phone:s.phone,active:s.active,
      joined_date:s.joinedDate,notes:s.notes,
      salary_history:s.salaryHistory||[],
      left_date:s.leftDate||null, meta:s.meta||null
    }, ['left_date','meta']);"""),

("Z2 save payment: owner/manager; month, mode, ref",
r"""async function sbSavePayment(p){
  if(!_currentUser)return;   // no _supa: _sbUpsert queues it
  try{
    await _sbUpsert('staff_payments', {
      id:Math.round(p.id),user_id:_currentUser.id,staff_id:p.staffId,
      date:p.date,type:p.type,amount:p.amount,notes:p.notes||'',
      advance_deducted:p.advanceDeducted||0,
      created_by:p.createdBy||_currentUser.username
    });""",
r"""async function sbSavePayment(p){
  if(!_currentUser)return;   // no _supa: _sbUpsert queues it
  if(typeof _staffPayOk==='function'&&!_staffPayOk())return;   // MF_STAFF_V1: the database refuses staff logins
  try{
    await _sbUpsertOpt('staff_payments', {
      id:Math.round(p.id),user_id:_currentUser.id,staff_id:p.staffId,
      date:p.date,type:p.type,amount:p.amount,notes:p.notes||'',
      advance_deducted:p.advanceDeducted||0,
      created_by:p.createdBy||_currentUser.username,
      for_month:p.forMonth||null, mode:p.mode||null, ref:p.ref||null
    }, ['for_month','mode','ref']);"""),

("Z3 load staff: left date, meta",
r"""        notes:r.notes,active:r.active,
        salaryHistory:r.salary_history||[]
      }));
      const mS=_mergeById(staffList,remoteStaff,null,'staff');""",
r"""        notes:r.notes,active:r.active,
        salaryHistory:r.salary_history||[],
        // MF_STAFF_V1: keep this device's copy while the server has no column
        leftDate:('left_date' in r)?(r.left_date||null):((staffList.find(x=>String(x.id)===String(r.id))||{}).leftDate||null),
        meta:('meta' in r)?(r.meta||null):((staffList.find(x=>String(x.id)===String(r.id))||{}).meta||null)
      }));
      const mS=_mergeById(staffList,remoteStaff,null,'staff');"""),

("Z4 staff logins do not hold pay records",
r"""    const pR=await _sbSelectAll('staff_payments',q=>q.eq('user_id',_currentUser.id)""",
r"""    if(typeof _staffPayOk==='function'&&!_staffPayOk()){ staffPayments=[]; savePayLS(); return; }   // MF_STAFF_V1
    const pR=await _sbSelectAll('staff_payments',q=>q.eq('user_id',_currentUser.id)"""),

("Z5 load payments: month, mode, ref",
r"""        advanceDeducted:r.advance_deducted||0,
        createdBy:r.created_by
      }));
      const mP=_mergeById(staffPayments,remotePay,null,'staff_payments');""",
r"""        advanceDeducted:r.advance_deducted||0,
        createdBy:r.created_by,
        // MF_STAFF_V1
        forMonth:('for_month' in r)?(r.for_month||null):((staffPayments.find(x=>String(x.id)===String(r.id))||{}).forMonth||null),
        mode:('mode' in r)?(r.mode||null):((staffPayments.find(x=>String(x.id)===String(r.id))||{}).mode||null),
        ref:('ref' in r)?(r.ref||null):((staffPayments.find(x=>String(x.id)===String(r.id))||{}).ref||null)
      }));
      const mP=_mergeById(staffPayments,remotePay,null,'staff_payments');"""),

# ── module ──────────────────────────────────────────────────────────────
("V1 staff module",
r"""// ═══════════════════════════════════════════════════
// OWNER DRAWINGS""",
MODULE + r"""

// ═══════════════════════════════════════════════════
// OWNER DRAWINGS"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    for need in ("MF_FIVE_V1", "MF_REPORTS_V1"):
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
