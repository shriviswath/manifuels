#!/usr/bin/env python3
"""
MF_REPORTS_V1 — Reports upgrade.

FIXES
  1 COMPARE     Compare mode had its own profit formula: it left out oil and
                pack margin and costed litres at today's average for both
                periods, so its "profit" never matched NET PROFIT on the same
                page. It now uses the P&L engine plus the same discounts /
                wages (_plExtras — also used by the P&L card itself).
                Realized fuel margin no longer counts the hydrometer rupees
                (its litres were already taken out of cost).
  2 TREND       The daily trend line subtracted stock BOUGHT that day, so a
                tanker day read as a big loss. It is each day's own P&L now:
                revenue, cost of goods sold, net profit.
  3 STATEMENT   40 ml pack lines on an oil bill were debited twice (bill +
                pack register). A bill is now a memo line; the money out is
                each payment on the day it was paid (oil). Fuel-load payments
                have no date, so they show on the bill date and say so.
  4 PDF         Menu → Export Report (PDF) was an all-time dump with the old
                "profit on purchases" figures, open to every role. It is now
                the report for the chosen period, from the P&L engine, owner
                only: P&L, petrol vs diesel, day/month table, oil & stock,
                expenses, dues, staff vs cash, and the leak checks.

NEW (REPORT VIEWS, under the P&L)
  6 TABLE       By shift / day / month: litres, revenue, net profit, profit/L,
                expenses, cash, digital %, credit, short/excess.
  7 FUEL        Petrol vs diesel: sale rate, landed cost, margin/L, margin %,
                profit share; pump-rate periods.
  8 YEAR        THIS FY / LAST FY range buttons; April–March month table.
  9 OIL         Sales by item with cost and margin; stock health — dead
                (no sale 60 d), slow, reorder soon, value tied up.
 10 EXPENSES    By head, per day, per litre, highest days; testing and
                handover shown apart (not a cost). Chit shown as recorded.
 11 DUES        Customers by age of unpaid bill (0–30/31–60/61–90/90+),
                advances held, supplier bills with due dates, net position.
 12 STAFF       Cash short / excess by who was on duty (from attendance).
 13 CSV         Every table downloads as CSV.

Usage:  python3 patch_reports.py [path/to/index.html]   (idempotent)
Requires MF_OIL_V1 (supplier due dates) and MF_PL_WORKINGS_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_REPORTS_V1"

MODULE = r"""// ══════════════════════════════════════════════════════════════════
// REPORT VIEWS — MF_REPORTS_V1
// Everything below reads records; nothing writes business data.
//   _plExtras()        what the P&L deducts below the engine's net profit
//                      (credit discounts, wages when ticked) — one routine
//                      for the NET PROFIT card, compare mode and every table
//   renderReportViews  tabs under the P&L: TABLE (shift / day / month),
//                      PETROL vs DIESEL, FINANCIAL YEAR, OIL & STOCK,
//                      EXPENSES, DUES, STAFF & CASH — each table with CSV
//   exportPeriodReport the printable report for the chosen period
// ══════════════════════════════════════════════════════════════════
function _plExtras(from,to,P,shift){
  var rates={}; try{ rates=JSON.parse(localStorage.getItem('fuelRates')||'{}')||{}; }catch(e){}
  var avg=((parseFloat(rates.hsd)||90)+(parseFloat(rates.msd)||100))/2;
  var msdRate=parseFloat(rates.msd)||avg, hsdRate=parseFloat(rates.hsd)||avg;
  var profs=(typeof customerProfiles!=='undefined'&&customerProfiles)||{};
  // Only fuel actually taken on credit, each row at its own fuel's rate —
  // advances and account adjustments are not sales.
  var names=Object.keys(profs).filter(function(n){ return ((profs[n]||{}).discountPerL||0)>0; });
  var disc=0;
  names.forEach(function(name){
    var d=profs[name].discountPerL||0; if(!d)return;
    var L=ledger.filter(function(e){
      return e.customer===name&&(e.amount||0)>0&&e.kind!=='adjust'&&e.fuel!=='ADJUST'&&
             (!from||e.date>=from)&&(!to||e.date<=to)&&(!shift||e.shift===shift);
    }).reduce(function(s,e){ var rt=e.fuel==='MSD'?msdRate:(e.fuel==='HSD'?hsdRate:avg); return s+(rt>0?e.amount/rt:0); },0);
    disc+=L*d;
  });
  var inR=function(x){ return x&&(!from||x.date>=from)&&(!to||x.date<=to); };
  var sp=[]; try{ sp=JSON.parse(localStorage.getItem('staffPayments')||'[]')||[]; }catch(e){}
  sp=sp.filter(inR);
  var sal=0,adv=0,rec=0,bon=0;
  sp.forEach(function(p){ var a=+p.amount||0;
    if(p.type==='salary')sal+=a; else if(p.type==='advance')adv+=a; else if(p.type==='bonus')bon+=a;
    rec+=(+p.advanceDeducted||0); });
  var inc=false; try{ inc=localStorage.getItem('plIncludeWages')==='1'; }catch(e){}
  var staffCost=0;
  if(inc){
    var w=(typeof _wagesEarned==='function')?_wagesEarned(from,to):{earned:0};
    staffCost=((w.earned>0)?w.earned:sal)+bon;
    if(shift)staffCost/=2;          // a shift is half of that day's wage
  }
  var dr=[]; try{ dr=JSON.parse(localStorage.getItem('ownerDrawings')||'[]')||[]; }catch(e){}
  var drawings=dr.filter(inR).reduce(function(s,d){return s+(+d.amount||0);},0);
  return {disc:disc, discNames:names, includeWages:inc, wageDed:inc?staffCost:0,
          staffCashOut:sal-rec+adv+bon, drawings:drawings,
          netFinal:(P?P.netProfit:0)-disc-(inc?staffCost:0)};
}

var RV_TABS=[['table','📋 TABLE'],['fuel','⛽ PETROL vs DIESEL'],['year','📅 FINANCIAL YEAR'],
             ['oil','🛢 OIL & STOCK'],['exp','💸 EXPENSES'],['dues','⚖ DUES'],['staff','👥 STAFF & CASH']];
var RV_BUILD={};
var _rvLast={}, _rvCtx=null, _rvFyShift=0;
function _rvGet(k,d){ try{ var v=localStorage.getItem('mf_rv_'+k); return v==null?d:v; }catch(e){ return d; } }
function _rvSet(k,v){ try{ localStorage.setItem('mf_rv_'+k,v); }catch(e){} }
function _rvAdd(s,n){ var p=String(s).split('-'); var d=new Date(+p[0],+p[1]-1,+p[2]); d.setDate(d.getDate()+n); return _isoLocal(d); }
function _rvDays(a,b){ return Math.round((Date.parse(b+'T00:00:00')-Date.parse(a+'T00:00:00'))/86400000); }
function _rvDm(d){ var p=String(d).split('-'); return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString('en-IN',{day:'2-digit',month:'short'}); }
function _rvDmy(d){ var p=String(d).split('-'); return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'2-digit'}); }
function _rvMon(ym){ var p=String(ym).split('-'); return new Date(+p[0],+p[1]-1,1).toLocaleDateString('en-IN',{month:'short',year:'numeric'}); }
function _rvSum(a,f){ return a.reduce(function(s,x){ return s+(+f(x)||0); },0); }
function _rvMoney(n){ n=Math.round(+n||0); return (n<0?'−':'')+'₹'+Math.abs(n).toLocaleString('en-IN'); }

function _rvFmt(v,t){
  if(v==null||v===''||(typeof v==='number'&&!isFinite(v)))return '—';
  if(t==='m')return _rvMoney(v);
  if(t==='m2')return (v<0?'−':'')+'₹'+Math.abs(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(t==='L')return (+v).toLocaleString('en-IN',{minimumFractionDigits:1,maximumFractionDigits:1})+' L';
  if(t==='p')return (+v).toFixed(1)+'%';
  if(t==='n')return (+v).toLocaleString('en-IN',{maximumFractionDigits:2});
  return String(v);
}
function _rvCell(x,t){
  if(x&&typeof x==='object')return {v:x.v, s:(x.s!=null?x.s:_rvFmt(x.v,t)), c:x.c};
  return {v:x, s:_rvFmt(x,t)};
}
function _rvIsNum(t){ return !!t&&t!=='t'; }
function _rvTblHtml(sp,print){
  var th=sp.cols.map(function(c){ return '<th'+(_rvIsNum(c.t)?' class="n" style="text-align:right"':'')+'>'+_esc(c.h)+'</th>'; }).join('');
  var tr=function(r,cls){
    return '<tr'+(cls?' class="'+cls+'"':'')+'>'+r.map(function(x,i){
      var t=(sp.cols[i]||{}).t, c=_rvCell(x,t);
      return '<td'+(_rvIsNum(t)?' class="n" style="text-align:right;white-space:nowrap'+(!print&&c.c?';color:'+c.c:'')+'"':(!print&&c.c?' style="color:'+c.c+'"':''))+'>'+_esc(c.s)+'</td>';
    }).join('')+'</tr>';
  };
  var body=sp.rows.length
    ? sp.rows.map(function(r){ return tr(r); }).join('')+(sp.foot?tr(sp.foot,print?'wk-tot':'rv-tot'):'')
    : '<tr><td colspan="'+sp.cols.length+'" style="text-align:center;color:var(--muted)">'+_esc(sp.empty||'Nothing in this period.')+'</td></tr>';
  return '<table class="'+(print?'wk-tbl':'data-tbl rv-tbl')+'"><thead><tr>'+th+'</tr></thead><tbody>'+body+'</tbody></table>';
}
function rvCsv(key){
  var sp=_rvLast[key]; if(!sp){ showToast('Nothing to download'); return; }
  var q=function(s){ s=String(s==null?'':s); return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s; };
  var raw=function(x){ var v=(x&&typeof x==='object')?x.v:x; if(v==null)return ''; if(typeof v==='number')return String(Math.round(v*100)/100); return v; };
  var lines=[sp.cols.map(function(c){ return q(c.h); }).join(',')];
  sp.rows.concat(sp.foot?[sp.foot]:[]).forEach(function(r){ lines.push(r.map(function(x){ return q(raw(x)); }).join(',')); });
  var ctx=_rvCtx||{};
  var blob=new Blob([String.fromCharCode(0xFEFF)+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='ManiFuels_'+key+'_'+(ctx.from||'all')+'_'+(ctx.to||'')+'.csv';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(function(){ try{ URL.revokeObjectURL(a.href); }catch(e){} },1500);
  if(typeof logActivity==='function')logActivity('export_csv','report',null,key+' '+(ctx.from||'')+' → '+(ctx.to||''));
}

// ── 6. TABLE: one row per shift, day or month ─────────────────────────────
RV_BUILD.table=function(from,to,recs,opt){
  var g=(opt&&opt.group)||_rvGet('group','day');
  var G={}, order=[];
  recs.forEach(function(r){
    var k=g==='shift'?String(r.id):(g==='month'?String(r.date).slice(0,7):String(r.date));
    if(!G[k]){ G[k]={k:k,recs:[],lo:r.date,hi:r.date,r:r}; order.push(k); }
    var x=G[k]; x.recs.push(r); if(r.date<x.lo)x.lo=r.date; if(r.date>x.hi)x.hi=r.date;
  });
  var rank=function(s){ return s==='night'?2:1; };
  var list=order.map(function(k){ return G[k]; }).sort(function(a,b){
    return String(b.hi).localeCompare(String(a.hi))||(g==='shift'?rank(b.r.shift)-rank(a.r.shift):0); });
  var calc=function(rs,lo,hi,shift){
    var P=_plCore(rs,lo,hi), X=_plExtras(lo,hi,P,shift);
    var L=(P.soldMSDL||0)+(P.soldHSDL||0), net=P.fuelUncosted?null:X.netFinal;
    var cash=_rvSum(rs,function(r){return r.cash;}), dig=_rvSum(rs,function(r){return (r.gpay||0)+(r.paytm||0);});
    var bal=_rvSum(rs,function(r){return r.bal;});
    return {P:P,L:L,net:net,cash:cash,dig:dig,bal:bal,cr:_rvSum(rs,function(r){return r.credit;})};
  };
  var row=function(label,c,n){
    return [label, n, c.P.soldMSDL, c.P.soldHSDL, c.P.revenue,
      c.net==null?null:{v:c.net,c:c.net<0?'var(--red)':'var(--green)'},
      (c.net!=null&&c.L>0)?c.net/c.L:null, c.P.opex, c.cash, c.dig,
      (c.cash+c.dig)>0?c.dig/(c.cash+c.dig)*100:null, c.cr,
      {v:c.bal,c:c.bal<-1?'var(--red)':(c.bal>1?'var(--diesel)':null)}];
  };
  var calcs=[];
  var rows=list.map(function(x){
    var c=calc(x.recs,x.lo,x.hi,g==='shift'?x.r.shift:null); calcs.push({x:x,c:c});
    var lbl=g==='shift'?{v:x.r.id,s:_rvDm(x.r.date)+' · '+(x.r.shift==='night'?'NIGHT':'MORNING')}
           :(g==='month'?{v:x.k,s:_rvMon(x.k)}
           :{v:x.k,s:new Date(x.k+'T00:00:00').toLocaleDateString('en-IN',{weekday:'short'})+' '+_rvDm(x.k)});
    return row(lbl,c,x.recs.length);
  });
  var T=calc(recs,from,to,null);
  var cards=[];
  if(calcs.length>1&&g!=='shift'){
    var known=calcs.filter(function(k){ return k.c.net!=null; });
    if(known.length){
      var best=known.slice().sort(function(a,b){return b.c.net-a.c.net;})[0], worst=known.slice().sort(function(a,b){return a.c.net-b.c.net;})[0];
      var nm=function(k){ return g==='month'?_rvMon(k.x.k):_rvDmy(k.x.k); };
      cards.push(['Average net per '+(g==='month'?'month':'day'),_rvMoney(_rvSum(known,function(k){return k.c.net;})/known.length),'var(--text)']);
      cards.push(['Best '+(g==='month'?'month':'day'),_rvMoney(best.c.net),'var(--green)',nm(best)]);
      cards.push(['Weakest '+(g==='month'?'month':'day'),_rvMoney(worst.c.net),worst.c.net<0?'var(--red)':'var(--diesel)',nm(worst)]);
      cards.push(['Litres per '+(g==='month'?'month':'day'),_rvFmt(_rvSum(calcs,function(k){return k.c.L;})/calcs.length,'L'),'var(--petrol)']);
    }
  }
  var X0=_plExtras(from,to,null);
  return {cards:cards, blocks:[{key:'table_'+g, h:(g==='shift'?'BY SHIFT':(g==='month'?'BY MONTH':'BY DAY')),
    note:'Net profit is on the same basis as the NET PROFIT card'+(X0.includeWages?' (wages deducted)':' (wages not deducted)')+
      '. Litres are sold litres — testing poured back into the tank is left out. Each row costs its fuel at the purchase cost on its own last day; the total is costed at the period end, so the rows can add up a few rupees differently.',
    tbl:{cols:[{h:g==='shift'?'Shift':(g==='month'?'Month':'Day'),t:'t'},{h:'Shifts',t:'n'},{h:'Petrol L',t:'L'},{h:'Diesel L',t:'L'},
      {h:'Revenue',t:'m'},{h:'Net profit',t:'m'},{h:'Profit / L',t:'m2'},{h:'Expenses',t:'m'},{h:'Cash',t:'m'},{h:'GPay + Paytm',t:'m'},
      {h:'Digital',t:'p'},{h:'Credit given',t:'m'},{h:'Short / excess',t:'m'}],
      rows:rows, foot:row('Total',T,recs.length), empty:'No shifts in this period.'}}]};
};

// ── 7. PETROL vs DIESEL ───────────────────────────────────────────────────
RV_BUILD.fuel=function(from,to,recs){
  var P=_plCore(recs,from,to);
  var hyd={MSD:0,HSD:0};
  recs.forEach(function(r){ var hv=_recHydro(r); if(hv<=0)return; var mv=r.msdV||0, dv=r.hsdV||0, t=mv+dv; if(t<=0)return;
    hyd.MSD+=hv*mv/t; hyd.HSD+=hv*dv/t; });
  var F=[{k:'MSD',n:'Petrol (MSD)',V:P.sumMSDV,tv:P.testValMSD,sold:P.soldMSDL,wac:P.wacMSD,met:P.totalMSDL,tl:(P.testMSDL||0)+(P.hydMSDL||0)},
         {k:'HSD',n:'Diesel (HSD)',V:P.sumHSDV,tv:P.testValHSD,sold:P.soldHSDL,wac:P.wacHSD,met:P.totalHSDL,tl:(P.testHSDL||0)+(P.hydHSDL||0)}];
  F.forEach(function(f){
    f.rev=Math.max(0,(f.V||0)-(f.tv||0)-hyd[f.k]);
    f.rate=f.sold>0?f.rev/f.sold:null;
    f.cost=(f.wac>0)?f.sold*f.wac:(f.sold>0?null:0);
    f.m=f.cost==null?null:f.rev-f.cost;
    f.mL=(f.m!=null&&f.sold>0)?f.m/f.sold:null;
    f.mP=(f.m!=null&&f.rev>0)?f.m/f.rev*100:null;
  });
  var soldT=F[0].sold+F[1].sold, revT=F[0].rev+F[1].rev;
  var costT=(F[0].cost==null||F[1].cost==null)?null:F[0].cost+F[1].cost, mT=costT==null?null:revT-costT;
  var rows=F.map(function(f){
    return [f.n, f.sold, soldT>0?f.sold/soldT*100:null, f.rev, f.rate, f.wac>0?f.wac:null, f.cost, f.m, f.mL, f.mP,
            (f.m!=null&&mT>0)?f.m/mT*100:null];
  });
  var foot=['Total fuel', soldT, soldT>0?100:null, revT, soldT>0?revT/soldT:null, (costT!=null&&soldT>0)?costT/soldT:null, costT, mT,
            (mT!=null&&soldT>0)?mT/soldT:null, (mT!=null&&revT>0)?mT/revT*100:null, mT!=null?100:null];
  var cards=[];
  F.forEach(function(f){ cards.push([f.n+' margin / L', f.mL==null?'—':_rvFmt(f.mL,'m2'), f.k==='MSD'?'var(--petrol)':'var(--diesel)',
    f.sold>0?_rvFmt(f.sold,'L')+' sold':'none sold']); });
  if(F[0].mL!=null&&F[1].mL!=null&&F[0].sold>0&&F[1].sold>0){
    var hi=F[0].mL>=F[1].mL?F[0]:F[1], lo=hi===F[0]?F[1]:F[0];
    cards.push(['Higher margin', hi.n.split(' ')[0], 'var(--green)', '+'+_rvFmt(hi.mL-lo.mL,'m2')+' per litre']);
    if(mT>0)cards.push(['Diesel share of fuel profit', _rvFmt(F[1].m/mT*100,'p'), 'var(--diesel)', _rvFmt(F[1].sold/soldT*100,'p')+' of litres']);
  }
  // Pump-rate periods: consecutive shifts at the same average rate.
  var segs=[];
  ['MSD','HSD'].forEach(function(k){
    var seg=null;
    recs.slice().sort(_wkSortAsc).forEach(function(r){
      var T=k==='MSD'?r.msdT:r.hsdT, V=k==='MSD'?r.msdV:r.hsdV; if(!((T||0)>0&&(V||0)>0))return;
      var rate=Math.round(V/T*100)/100;
      if(seg&&Math.abs(seg.rate-rate)<0.005){ seg.to=r.date; seg.L+=T; seg.n++; }
      else { seg={k:k,from:r.date,to:r.date,rate:rate,L:T,n:1}; segs.push(seg); }
    });
  });
  segs.sort(function(a,b){ return String(b.to).localeCompare(String(a.to))||(a.k<b.k?-1:1); });
  var wac={MSD:P.wacMSD,HSD:P.wacHSD};
  return {cards:cards, blocks:[
    {key:'fuel', h:'MARGIN BY FUEL',
     note:'Metered '+_rvFmt(F[0].met,'L')+' petrol and '+_rvFmt(F[1].met,'L')+' diesel, of which '+_rvFmt(F[0].tl+F[1].tl,'L')+
       ' was testing / hydrometer fuel returned to the tank — left out of sold litres and revenue. Landed cost is the weighted purchase cost as at '+(to?_rvDmy(to):'today')+'.'+
       (P.fuelUncosted?' ⚠ One fuel has no purchase cost on record, so its margin cannot be stated.':''),
     tbl:{cols:[{h:'Fuel',t:'t'},{h:'Sold',t:'L'},{h:'Litre share',t:'p'},{h:'Revenue',t:'m'},{h:'Avg sale / L',t:'m2'},{h:'Landed cost / L',t:'m2'},
       {h:'Cost of sales',t:'m'},{h:'Margin',t:'m'},{h:'Margin / L',t:'m2'},{h:'Margin %',t:'p'},{h:'Profit share',t:'p'}],
       rows:rows, foot:foot}},
    {key:'fuel_rates', h:'PUMP RATE PERIODS',
     note:'Shifts in a row at the same average rate. A shift with a price change in the middle shows its own blended rate. Margin / L uses the period’s landed cost.',
     tbl:{cols:[{h:'Fuel',t:'t'},{h:'From',t:'t'},{h:'To',t:'t'},{h:'Rate / L',t:'m2'},{h:'Margin / L',t:'m2'},{h:'Litres',t:'L'},{h:'Shifts',t:'n'}],
       rows:segs.slice(0,24).map(function(s){ return [s.k==='MSD'?'Petrol':'Diesel',{v:s.from,s:_rvDmy(s.from)},{v:s.to,s:_rvDmy(s.to)},s.rate,
         wac[s.k]>0?s.rate-wac[s.k]:null,s.L,s.n]; }), empty:'No fuel sold in this period.'}}]};
};

// ── 8. FINANCIAL YEAR (April → March) ─────────────────────────────────────
RV_BUILD.year=function(from,to){
  var today=_isoLocal(), base=to||today, p=base.split('-');
  var cy=(+today.slice(5,7)>=4)?+today.slice(0,4):+today.slice(0,4)-1;
  var y=((+p[1]>=4)?+p[0]:+p[0]-1)+_rvFyShift;
  if(y>cy){ _rvFyShift-=(y-cy); y=cy; }
  var fyFrom=y+'-04-01', fyTo=(y+1)+'-03-31', fyEnd=fyTo<today?fyTo:today;
  var rows=[], known=[];
  for(var i=0;i<12;i++){
    var m=(3+i)%12, yr=y+(i>=9?1:0);
    var ms=_isoLocal(new Date(yr,m,1)), me=_isoLocal(new Date(yr,m+1,0)), ym=ms.slice(0,7);
    if(ms>today){ rows.push([{v:ym,s:_rvMon(ym)},null,null,null,null,null,null,null,null,null,null,null]); continue; }
    var end=me<today?me:today;
    var mr=records.filter(function(r){ return r.date>=ms&&r.date<=end; });
    var P=_plCore(mr,ms,end), X=_plExtras(ms,end,P);
    var L=(P.soldMSDL||0)+(P.soldHSDL||0), net=(P.fuelUncosted||!mr.length)?null:X.netFinal;
    if(net!=null)known.push({ym:ym,net:net});
    rows.push([{v:ym,s:_rvMon(ym)+(me>today?' (to date)':'')}, mr.length, P.soldMSDL, P.soldHSDL, P.revenue,
      (P.fuelUncosted||!mr.length)?null:P.grossProfit, P.opex,
      net==null?null:{v:net,c:net<0?'var(--red)':'var(--green)'}, (net!=null&&L>0)?net/L:null,
      P.purchases, X.drawings, X.staffCashOut]);
  }
  var fr=records.filter(function(r){ return r.date>=fyFrom&&r.date<=fyEnd; });
  var FP=_plCore(fr,fyFrom,fyEnd), FX=_plExtras(fyFrom,fyEnd,FP), FL=(FP.soldMSDL||0)+(FP.soldHSDL||0);
  var fnet=(FP.fuelUncosted||!fr.length)?null:FX.netFinal;
  var lbl='FY '+y+'–'+String(y+1).slice(2);
  var cards=[['Net profit · '+lbl, fnet==null?'—':_rvMoney(fnet), fnet!=null&&fnet<0?'var(--red)':'var(--green)', fyEnd<fyTo?'to '+_rvDmy(fyEnd):''],
             ['Revenue', _rvMoney(FP.revenue), 'var(--petrol)'], ['Litres sold', _rvFmt(FL,'L'), 'var(--blue)'],
             ['Profit per litre', (fnet!=null&&FL>0)?_rvFmt(fnet/FL,'m2'):'—', 'var(--text)']];
  if(known.length>1){ var b=known.slice().sort(function(a,c){return c.net-a.net;})[0]; cards.push(['Best month',_rvMon(b.ym),'var(--green)',_rvMoney(b.net)]); }
  return {ctl:'<button class="btn btn-g" style="padding:4px 10px" onclick="rvFy(-1)">◀</button>'+
      '<b style="font-family:\'JetBrains Mono\',monospace;font-size:12px;margin:0 8px">'+lbl+'</b>'+
      '<button class="btn btn-g" style="padding:4px 10px"'+(y>=cy?' disabled':'')+' onclick="rvFy(1)">▶</button>',
    title:lbl, cards:cards, blocks:[{key:'year_'+y, h:'MONTH BY MONTH · '+lbl+' (APRIL – MARCH)',
    note:'Not tied to the date range above — use ◀ ▶ to change year. Stock bought, drawings and money paid to staff are cash out, not deductions from profit.',
    tbl:{cols:[{h:'Month',t:'t'},{h:'Shifts',t:'n'},{h:'Petrol L',t:'L'},{h:'Diesel L',t:'L'},{h:'Revenue',t:'m'},{h:'Gross profit',t:'m'},
      {h:'Running exp.',t:'m'},{h:'Net profit',t:'m'},{h:'Profit / L',t:'m2'},{h:'Stock bought',t:'m'},{h:'Drawings',t:'m'},{h:'Paid to staff',t:'m'}],
      rows:rows, foot:['Total '+lbl, fr.length, FP.soldMSDL, FP.soldHSDL, FP.revenue, (FP.fuelUncosted||!fr.length)?null:FP.grossProfit, FP.opex,
        fnet, (fnet!=null&&FL>0)?fnet/FL:null, FP.purchases, FX.drawings, FX.staffCashOut]}}]};
};
function rvFy(n){ _rvFyShift+=n; if(_rvCtx)renderReportViews(_rvCtx.from,_rvCtx.to,_rvCtx.recs); }

// ── 9. OIL & STOCK ────────────────────────────────────────────────────────
RV_BUILD.oil=function(from,to,recs){
  var nf=_plNonFuelDetail(recs), rows=[];
  Object.keys(nf.items).forEach(function(k){
    var it=nf.items[k], cost=it.unit>0?it.cost:null, m=cost==null?null:it.sales-cost;
    rows.push([it.name, {v:it.qty,s:_rvFmt(it.qty,'n')}, it.sales, it.unit>0?it.unit:null, cost, m, (m!=null&&it.sales>0)?m/it.sales*100:null]);
  });
  var pvT=_rvSum(recs,function(r){return r.pv;});
  var pk=Object.keys(nf.packs).sort(function(a,b){return (+a)-(+b);});
  if(pvT>0||pk.length){
    var pq=pk.map(function(s){ return _rvFmt(nf.packs[s].qty,'n')+' × '+s+' ml'+(nf.packs[s].est?' (some est.)':''); }).join(', ');
    var allP=pk.length&&pk.every(function(s){ return nf.packs[s].unit>0; });
    var pc=allP?pk.reduce(function(s,k){return s+nf.packs[k].cost;},0):null;
    rows.push(['Packs'+(pq?' — '+pq:''), {v:pk.reduce(function(s,k){return s+nf.packs[k].qty;},0),s:_rvFmt(pk.reduce(function(s,k){return s+nf.packs[k].qty;},0),'n')},
      pvT, null, pc, pc==null?null:pvT-pc, (pc!=null&&pvT>0)?(pvT-pc)/pvT*100:null]);
  }
  if(nf.loose.sales>0){
    var lc=(nf.loose.noQtySales>0||!(nf.loose.cost>0))?null:nf.loose.cost;
    rows.push(['Loose oil'+(nf.loose.litres>0?' — '+_rvFmt(nf.loose.litres,'L'):''), {v:nf.loose.litres,s:nf.loose.litres>0?_rvFmt(nf.loose.litres,'n')+' L':'—'},
      nf.loose.sales, (lc!=null&&nf.loose.litres>0)?lc/nf.loose.litres:null, lc, lc==null?null:nf.loose.sales-lc, (lc!=null&&nf.loose.sales>0)?(nf.loose.sales-lc)/nf.loose.sales*100:null]);
  }
  rows.sort(function(a,b){ var x=a[5], y=b[5]; if(x==null&&y==null)return b[2]-a[2]; if(x==null)return 1; if(y==null)return -1; return y-x; });
  var sT=_rvSum(rows,function(r){return r[2];}), cT=_rvSum(rows,function(r){return r[4];}), mT=_rvSum(rows,function(r){return r[5];});
  var unpriced=rows.filter(function(r){ return r[5]==null; }).length;

  // Stock health, as of today
  var today=_isoLocal(), d30=_rvAdd(today,-29), d60=_rvAdd(today,-59), last={}, s30={}, first={};
  records.forEach(function(r){
    var use=function(id,q){ var k=String(id); q=parseFloat(q)||0; if(q<=0)return;
      if(!last[k]||r.date>last[k])last[k]=r.date; if(r.date>=d30&&r.date<=today)s30[k]=(s30[k]||0)+q; };
    (r.stockSold||[]).forEach(function(it){ use(it.id,it.qty); });
    (Array.isArray(r.looseOpened)?r.looseOpened:[]).forEach(function(o){ use(o.id,o.qty); });
  });
  (typeof oilReg!=='undefined'?oilReg:[]).forEach(function(o){ (o.items||[]).forEach(function(it){ var k=String(it.stockId);
    if(!first[k]||o.date<first[k])first[k]=o.date; }); });
  var uc=_stockUnitCost(), H=[], dead=0, deadN=0, slow=0, soon=0;
  var ORD={'DEAD':0,'SLOW':1,'REORDER SOON':2,'OUT':3,'NEW — NO SALE YET':4,'OK':5};
  (typeof stock!=='undefined'?stock:[]).forEach(function(s){
    var k=String(s.id), qty=+s.qty||0, sold=s30[k]||0, per=sold/30, cover=per>0?qty/per:null;
    var unit=uc[k]||0, val=qty*(unit>0?unit:(+s.rate||0));
    var st=qty<=0?'OUT':(!last[k]||last[k]<d60)?((first[k]&&first[k]>=d60)?'NEW — NO SALE YET':'DEAD'):(cover!=null&&cover<10)?'REORDER SOON':(cover!=null&&cover>90)?'SLOW':'OK';
    if(st==='DEAD'){ dead+=val; deadN++; } else if(st==='SLOW')slow+=val; else if(st==='REORDER SOON')soon++;
    H.push({o:ORD[st],val:val,r:[s.name||('#'+k), {v:qty,s:_rvFmt(qty,'n')+' '+(s.unit||'')}, sold, cover==null?null:{v:Math.round(cover),s:Math.round(cover)+' d'},
      last[k]?{v:last[k],s:_rvDmy(last[k])}:{v:'',s:'never'}, {v:val,s:(unit>0?'':'≈ ')+_rvMoney(val)},
      {v:st,s:st,c:st==='DEAD'||st==='OUT'?'var(--red)':(st==='SLOW'||st==='REORDER SOON'?'var(--diesel)':null)}]});
  });
  H.sort(function(a,b){ return a.o-b.o||b.val-a.val; });
  return {cards:[['Oil & stock sales',_rvMoney(sT),'var(--petrol)'],['Margin',unpriced&&!mT?'—':_rvMoney(mT),'var(--green)',unpriced?unpriced+' line'+(unpriced>1?'s':'')+' without a purchase price':''],
                 ['Dead stock',_rvMoney(dead),dead>0?'var(--red)':'var(--muted)',deadN+' item'+(deadN!==1?'s':'')+' · no sale in 60 days'],
                 ['Slow stock',_rvMoney(slow),slow>0?'var(--diesel)':'var(--muted)','over 90 days of cover'],
                 ['Reorder soon',String(soon),soon?'var(--diesel)':'var(--muted)','under 10 days of cover']],
    blocks:[{key:'oil_sales', h:'SALES BY ITEM · THIS PERIOD',
      note:'Cost is the weighted purchase price from Oil Register. A line with no purchase price shows no margin — enter the price on its invoice to fill it in.',
      tbl:{cols:[{h:'Item',t:'t'},{h:'Qty sold',t:'n'},{h:'Sales',t:'m'},{h:'Unit cost',t:'m2'},{h:'Cost',t:'m'},{h:'Margin',t:'m'},{h:'Margin %',t:'p'}],
        rows:rows, foot:['Total',null,sT,null,cT||null,unpriced&&!mT?null:mT,(sT>0&&mT)?mT/sT*100:null], empty:'No oil or counter stock sold in this period.'}},
     {key:'oil_health', h:'STOCK HEALTH · AS OF TODAY',
      note:'Sold 30 d counts counter sales and bottles opened for loose oil. DEAD = in stock with no sale for 60 days (money sitting on the shelf). SLOW = more than 90 days of stock at the current pace. Value is at purchase cost; ≈ = no purchase price, valued at the selling rate.',
      tbl:{cols:[{h:'Item',t:'t'},{h:'In stock',t:'n'},{h:'Sold 30 d',t:'n'},{h:'Cover',t:'n'},{h:'Last sold',t:'t'},{h:'Value',t:'m'},{h:'Status',t:'t'}],
        rows:H.map(function(h){return h.r;}), foot:['Total',null,null,null,null,_rvSum(H,function(h){return h.val;}),null], empty:'No stock items.'}}]};
};

// ── 10. EXPENSES BY HEAD ──────────────────────────────────────────────────
RV_BUILD.exp=function(from,to,recs){
  var HEADS=[['tea','Tea / food'],['items','Items'],['other','Other'],['chit','Chit fund'],['_un','Not split (older shifts)']];
  var TEST=[['tmsd','Testing — petrol'],['thsd','Testing — diesel'],['toil','Hydrometer']];
  var tot={}, byDay={}, test={}, hand=0;
  recs.forEach(function(r){
    var h=_recExpHeads(r), hs=0, ts=0, d=r.date;
    if(!byDay[d])byDay[d]={};
    if(h){
      HEADS.forEach(function(k){ if(k[0]==='_un')return; var v=parseFloat(h[k[0]])||0; if(v>0){ tot[k[0]]=(tot[k[0]]||0)+v; byDay[d][k[0]]=(byDay[d][k[0]]||0)+v; hs+=v; } });
      TEST.forEach(function(k){ var v=parseFloat(h[k[0]])||0; if(v>0){ test[k[0]]=(test[k[0]]||0)+v; ts+=v; } });
    }
    var rest=(r.exp||0)-hs-ts;
    if(rest>0.5){ tot._un=(tot._un||0)+rest; byDay[d]._un=(byDay[d]._un||0)+rest; }
    hand+=(r.handover||0);
  });
  var days=Object.keys(byDay).sort(), nD=Math.max(1,days.length);
  var run=HEADS.reduce(function(s,k){return s+(tot[k[0]]||0);},0);
  var P=_plCore(recs,from,to), L=(P.soldMSDL||0)+(P.soldHSDL||0);
  var rows=HEADS.filter(function(k){ return (tot[k[0]]||0)>0; }).map(function(k){
    var top=null; days.forEach(function(d){ var v=byDay[d][k[0]]||0; if(v>0&&(!top||v>top.v))top={d:d,v:v}; });
    return [k[1], tot[k[0]], run>0?tot[k[0]]/run*100:null, tot[k[0]]/nD, top?{v:top.d,s:_rvDmy(top.d)}:null, top?top.v:null];
  }).sort(function(a,b){ return b[1]-a[1]; });
  var dayRows=days.map(function(d){
    var t=0, big=null; Object.keys(byDay[d]).forEach(function(k){ var v=byDay[d][k]; t+=v; if(!big||v>big.v)big={k:k,v:v}; });
    var nm=big?(HEADS.find(function(h){return h[0]===big.k;})||[0,big.k])[1]:'';
    return {d:d,t:t,r:[{v:d,s:_rvDmy(d)},t,big?nm+' '+_rvMoney(big.v):'']};
  }).sort(function(a,b){ return b.t-a.t; }).slice(0,7);
  var testT=TEST.reduce(function(s,k){return s+(test[k[0]]||0);},0);
  var big=rows[0];
  var diff=Math.abs(run-P.opex)>1;
  return {cards:[['Running expenses',_rvMoney(run),'var(--red)'],['Per day',_rvMoney(run/nD),'var(--text)',days.length+' day'+(days.length!==1?'s':'')],
                 ['Per litre sold',L>0?_rvFmt(run/L,'m2'):'—','var(--text)'],['Biggest head',big?big[0]:'—','var(--diesel)',big?_rvFmt(big[2],'p')+' of expenses':'']],
    blocks:[{key:'exp_heads', h:'BY HEAD',
      note:'As entered on the shifts. Chit fund is shown exactly as recorded — nothing here changes it.'+
        (diff?' The P&L’s running expenses ('+_rvMoney(P.opex)+') take testing out using the meter litres, so they differ slightly from the heads here.':''),
      tbl:{cols:[{h:'Head',t:'t'},{h:'Total',t:'m'},{h:'Share',t:'p'},{h:'Per day',t:'m'},{h:'Highest day',t:'t'},{h:'That day',t:'m'}],
        rows:rows, foot:['Total',run,run>0?100:null,run/nD,null,null], empty:'No expenses in this period.'}},
     {key:'exp_days', h:'HIGHEST-SPEND DAYS',
      tbl:{cols:[{h:'Day',t:'t'},{h:'Running expenses',t:'m'},{h:'Largest item',t:'t'}], rows:dayRows.map(function(x){return x.r;}), empty:'No expenses in this period.'}},
     {key:'exp_notcost', h:'NOT A COST',
      note:'Testing fuel goes back in the tank and handover is cash moved out of the drawer — both are in the shift tally but not in running expenses.',
      tbl:{cols:[{h:'Item',t:'t'},{h:'Total',t:'m'}],
        rows:TEST.filter(function(k){return (test[k[0]]||0)>0;}).map(function(k){return [k[1]+' (returned to tank)',test[k[0]]];})
             .concat(hand>0?[['Cash handed over',hand]]:[]),
        foot:(testT+hand)>0?['Total',testT+hand]:null, empty:'None in this period.'}}]};
};

// ── 11. DUES: owed to you / you owe (today) ───────────────────────────────
RV_BUILD.dues=function(){
  var today=_isoLocal(), names={}, R=[], A=[], B=[0,0,0,0];
  ledger.forEach(function(e){ if(e&&e.customer)names[e.customer]=1; });
  Object.keys(names).forEach(function(n){
    var pos=_custPosition(n), b=[0,0,0,0], oldest='';
    _custUnpaid(n).forEach(function(e){ var due=(e.amount||0)-(e.paidBack||0); if(due<=0.005)return;
      var age=_rvDays(e.date,today), i=age<=30?0:age<=60?1:age<=90?2:3; b[i]+=due; if(!oldest||e.date<oldest)oldest=e.date; });
    var owes=b[0]+b[1]+b[2]+b[3];
    if(owes>0.5){
      b.forEach(function(v,i){ B[i]+=v; });
      var oa=oldest?_rvDays(oldest,today):0;
      R.push([n, owes, b[0]||null, b[1]||null, b[2]||null, b[3]?{v:b[3],c:'var(--red)'}:null,
        oldest?{v:oldest,s:_rvDmy(oldest)+' · '+oa+' d',c:oa>60?'var(--red)':null}:null, pos.advLeft>0.5?pos.advLeft:null, pos.net]);
    } else if(pos.advLeft>0.5) A.push([n,pos.advLeft]);
  });
  R.sort(function(a,b){ return b[1]-a[1]; }); A.sort(function(a,b){ return b[1]-a[1]; });
  var recv=B[0]+B[1]+B[2]+B[3], advT=_rvSum(A,function(a){return a[1];});
  var P=[], fuelDue=0, oilDue=0, overdue=0;
  (typeof fuelLoads!=='undefined'?fuelLoads:[]).forEach(function(l){
    var tc=+(l.totalCost!=null?l.totalCost:l.total_cost)||0, paid=Math.min(tc,+l.amountPaid||0), due=tc-paid; if(due<=0.5)return;
    fuelDue+=due; var age=_rvDays(l.date,today);
    P.push({late:-1,age:age,r:['Fuel',{v:l.date,s:_rvDmy(l.date)},l.supplier||'—',(l.type||'')+' '+_rvFmt(+l.vol||0,'L')+(l.inv?' · '+l.inv:''),tc,paid,due,{v:'',s:'—'},age]});
  });
  (typeof oilReg!=='undefined'?oilReg:[]).forEach(function(o){
    var tc=+o.totalCost||0, paid=Math.min(tc,(typeof _invPaid==='function')?_invPaid(o):(+o.amountPaid||0)), due=tc-paid; if(due<=0.5)return;
    oilDue+=due; var age=_rvDays(o.date,today), dd=(typeof _invDueDate==='function')?_invDueDate(o):null, late=dd?_rvDays(dd,today):-1;
    if(late>0)overdue+=due;
    P.push({late:late,age:age,r:['Oil',{v:o.date,s:_rvDmy(o.date)},o.company||'—','Invoice '+(o.inv||'—'),tc,paid,due,
      dd?{v:dd,s:_rvDmy(dd)+(late>0?' · '+late+' d late':''),c:late>0?'var(--red)':null}:{v:'',s:'no credit days set'},age]});
  });
  P.sort(function(a,b){ return (b.late>0?b.late:0)-(a.late>0?a.late:0)||b.age-a.age; });
  var pay=fuelDue+oilDue, net=recv-pay-advT;
  return {cards:[['Customers owe you',_rvMoney(recv),'var(--diesel)',R.length+' customer'+(R.length!==1?'s':'')],
                 ['Of it, over 60 days',_rvMoney(B[2]+B[3]),(B[2]+B[3])>0?'var(--red)':'var(--muted)'],
                 ['You owe suppliers',_rvMoney(pay),'var(--red)','fuel '+_rvMoney(fuelDue)+' · oil '+_rvMoney(oilDue)],
                 ['Overdue to suppliers',_rvMoney(overdue),overdue>0?'var(--red)':'var(--muted)','oil bills past their credit days'],
                 ['Advances held',_rvMoney(advT),'var(--blue)','fuel you owe customers'],
                 ['Net position',_rvMoney(net),net>=0?'var(--green)':'var(--red)','owed to you − you owe − advances']],
    blocks:[{note:'As of today — the date range above does not change this section.'},
     {key:'dues_customers', h:'CUSTOMERS — BY AGE OF THE UNPAID BILL',
      tbl:{cols:[{h:'Customer',t:'t'},{h:'Owes',t:'m'},{h:'0–30 d',t:'m'},{h:'31–60 d',t:'m'},{h:'61–90 d',t:'m'},{h:'Over 90 d',t:'m'},
        {h:'Oldest unpaid',t:'t'},{h:'Advance held',t:'m'},{h:'Net',t:'m'}],
        rows:R, foot:['Total',recv,B[0]||null,B[1]||null,B[2]||null,B[3]||null,null,null,null], empty:'No customer owes anything.'}},
     {key:'dues_advances', h:'ADVANCES HELD (FUEL STILL TO BE GIVEN)',
      tbl:{cols:[{h:'Customer',t:'t'},{h:'Advance',t:'m'}], rows:A, foot:A.length?['Total',advT]:null, empty:'No advances held.'}},
     {key:'dues_suppliers', h:'SUPPLIERS — UNPAID BILLS',
      note:'Overdue first, then the oldest. Due dates come from each oil supplier’s credit days (⚙ on Oil Register). Fuel loads have no due date.',
      tbl:{cols:[{h:'Type',t:'t'},{h:'Bill date',t:'t'},{h:'Supplier',t:'t'},{h:'Bill',t:'t'},{h:'Amount',t:'m'},{h:'Paid',t:'m'},{h:'Due',t:'m'},{h:'Due date',t:'t'},{h:'Age (d)',t:'n'}],
        rows:P.map(function(x){return x.r;}), foot:P.length?['Total',null,null,null,null,null,pay,null,null]:null, empty:'Nothing owed to suppliers.'}}]};
};

// ── 12. STAFF ON DUTY vs CASH ─────────────────────────────────────────────
RV_BUILD.staff=function(from,to,recs){
  var on={};
  (typeof staffAttendance!=='undefined'?staffAttendance:[]).forEach(function(a){
    if(a.status!=='present'&&a.status!=='half')return; var k=a.date+'|'+a.shift; (on[k]=on[k]||[]).push(a);
  });
  var S={}, none={n:0,short:0}, shortN=0, shortT=0, TOL=50;   // within ₹50 is counting rounding
  recs.forEach(function(r){
    var b=r.bal||0, list=on[r.date+'|'+r.shift]||[];
    if(b<-TOL){ shortN++; shortT+=-b; }
    if(!list.length){ none.n++; if(b<-TOL)none.short+=-b; return; }
    list.forEach(function(a){
      var s=S[a.staffId]||(S[a.staffId]={id:a.staffId,n:0,sn:0,short:0,ex:0,net:0,worst:null});
      s.n++; s.net+=b; if(b<-TOL){ s.sn++; s.short+=-b; } if(b>TOL)s.ex+=b;
      if(b<-TOL&&(!s.worst||b<s.worst.b))s.worst={b:b,r:r};
    });
  });
  var rows=Object.keys(S).map(function(id){ var s=S[id];
    return [_sStaffName(s.id), s.n, s.sn, s.n?{v:s.sn/s.n*100,c:(s.sn/s.n)>0.3?'var(--red)':null}:null,
      s.short?{v:-s.short,c:'var(--red)'}:null, s.ex||null, {v:s.net,c:s.net<-1?'var(--red)':null},
      s.worst?_rvDmy(s.worst.r.date)+' '+(s.worst.r.shift==='night'?'N':'M')+' '+_rvMoney(s.worst.b):''];
  }).sort(function(a,b){ return ((a[4]&&a[4].v)||0)-((b[4]&&b[4].v)||0)||b[1]-a[1]; });
  return {cards:[['Shifts in period',String(recs.length),'var(--blue)'],['Short shifts',String(shortN),shortN?'var(--red)':'var(--muted)',_rvMoney(shortT)+' in all'],
                 ['No one marked on duty',String(none.n),none.n?'var(--diesel)':'var(--muted)',none.n?_rvMoney(none.short)+' short on those':'']],
    blocks:[{key:'staff_cash', h:'CASH DIFFERENCE BY WHO WAS ON DUTY',
      note:'Each shift’s whole short or excess is shown against everyone marked present on it (half-day included), so a name here means “was on duty”, not “took it”. Short or excess within ₹50 is treated as counting rounding. Use it to spot a pattern worth checking. It only works when attendance is marked on every shift'+(none.n?' — '+none.n+' shift'+(none.n!==1?'s have':' has')+' nobody marked':'')+'.',
      tbl:{cols:[{h:'Staff',t:'t'},{h:'Shifts on duty',t:'n'},{h:'Short shifts',t:'n'},{h:'Short rate',t:'p'},{h:'Total short',t:'m'},{h:'Total excess',t:'m'},{h:'Net',t:'m'},{h:'Worst shift',t:'t'}],
        rows:rows, empty:'No attendance marked for the shifts in this period.'}}]};
};

function _rvScreen(out){
  var h='';
  if(out.cards&&out.cards.length)h+='<div class="rv-cards">'+out.cards.map(function(c){
    return '<div class="sbox"><div class="sb-t">'+_esc(c[0])+'</div><div class="sb-v" style="font-size:15px;color:'+(c[2]||'var(--text)')+'">'+_esc(c[1])+'</div>'+
      (c[3]?'<div class="rv-note" style="margin:3px 0 0">'+_esc(c[3])+'</div>':'')+'</div>'; }).join('')+'</div>';
  (out.blocks||[]).forEach(function(b){
    if(b.tbl&&b.key)_rvLast[b.key]=b.tbl;
    if(b.h)h+='<div class="rv-h"><span>'+_esc(b.h)+'</span>'+(b.tbl&&b.key?'<button class="btn btn-g" style="padding:3px 9px;font-size:9px;margin-left:auto" onclick="rvCsv(\''+b.key+'\')">⬇ CSV</button>':'')+'</div>';
    if(b.note)h+='<div class="rv-note">'+_esc(b.note)+'</div>';
    if(b.tbl)h+='<div style="overflow-x:auto">'+_rvTblHtml(b.tbl,false)+'</div>';
  });
  return h;
}
function renderReportViews(from,to,recs){
  var w=document.getElementById('rv_wrap'); if(!w)return;
  _rvCtx={from:from,to:to,recs:recs||[]};
  var tab=_rvGet('tab','table'); if(!RV_TABS.some(function(t){ return t[0]===tab; }))tab='table';
  var out;
  try{ out=RV_BUILD[tab](from,to,recs||[]); }
  catch(e){ console.error('report view '+tab+':',e); out={blocks:[{note:'⚠ This view could not be built: '+e.message}]}; }
  var ctl=out.ctl||'';
  if(tab==='table'){ var g=_rvGet('group','day');
    ctl='<select onchange="_rvSet(\'group\',this.value);renderReportViews(_rvCtx.from,_rvCtx.to,_rvCtx.recs)" style="height:30px;padding:4px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:11px">'+
      [['shift','By shift'],['day','By day'],['month','By month']].map(function(o){ return '<option value="'+o[0]+'"'+(g===o[0]?' selected':'')+'>'+o[1]+'</option>'; }).join('')+'</select>'; }
  w.style.display='block';
  w.innerHTML='<div class="sec" style="margin:0 0 10px;border:none"><span class="dot dp"></span>REPORT VIEWS'+
      '<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--muted);letter-spacing:0;margin-left:10px;font-weight:400">'+
      (from&&to?_rvDmy(from)+' → '+_rvDmy(to):'')+' · '+(recs||[]).length+' shift'+((recs||[]).length!==1?'s':'')+'</span></div>'+
    '<div class="rv-tabs">'+RV_TABS.map(function(t){ return '<button class="range-btn'+(t[0]===tab?' active':'')+'" onclick="rvTab(\''+t[0]+'\')">'+t[1]+'</button>'; }).join('')+'</div>'+
    (ctl?'<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px">'+ctl+'</div>':'')+
    _rvScreen(out);
}
function rvTab(k){ _rvSet('tab',k); if(_rvCtx)renderReportViews(_rvCtx.from,_rvCtx.to,_rvCtx.recs); }

// ── 4. Printable report for the chosen period ─────────────────────────────
function exportPeriodReport(){
  if(typeof _isOwner!=='undefined'&&!_isOwner){ showToast('🔒 Owner access only'); return; }
  var f=(document.getElementById('rep_from')||{}).value, t=(document.getElementById('rep_to')||{}).value;
  if(!f||!t){ var n=new Date(); f=_isoLocal(new Date(n.getFullYear(),n.getMonth(),1)); t=_isoLocal(n); }
  if(f>t){ showToast('The From date is after the To date'); return; }
  var recs=records.filter(function(r){ return r.date>=f&&r.date<=t; });
  var P=_plCore(recs,f,t), X=_plExtras(f,t,P), L=(P.soldMSDL||0)+(P.soldHSDL||0);
  var bz=(typeof bizProfile!=='undefined'&&bizProfile)||{}, NA='not known';
  var line=function(a,b,cls){ return '<tr'+(cls?' class="'+cls+'"':'')+'><td>'+a+'</td><td style="text-align:right;white-space:nowrap">'+b+'</td></tr>'; };
  var m=function(v){ return P.fuelUncosted?NA:_rvMoney(v); };
  var pl='<table class="wk-tbl"><thead><tr><th>Particulars</th><th style="text-align:right">₹</th></tr></thead><tbody>'+
    line('Fuel sales ('+_rvFmt(L,'L')+' sold, testing excluded)',_rvMoney(P.revFuel))+
    line('Pack and loose oil sales',_rvMoney(P.revOilPack))+
    (P.revStock>0?line('Counter stock sales',_rvMoney(P.revStock)):'')+
    line('<b>Revenue</b>','<b>'+_rvMoney(P.revenue)+'</b>','wk-tot')+
    line('Less: cost of fuel sold',m(P.cogsFuel))+
    line('Less: cost of oil and stock sold'+(P.cogsEstimated>0?' ('+_rvMoney(P.cogsEstimated)+' estimated)':''),_rvMoney(P.cogsNonFuel))+
    line('<b>Gross profit</b>'+(P.fuelUncosted?'':' · margin '+_rvFmt(P.grossMarginPct,'p')),'<b>'+m(P.grossProfit)+'</b>','wk-tot')+
    line('Less: running expenses (from the shifts)',_rvMoney(P.opex))+
    (X.includeWages&&X.wageDed>0?line('Less: staff wages',_rvMoney(X.wageDed)):'')+
    (X.disc>0?line('Less: credit discounts (estimated)',_rvMoney(X.disc)):'')+
    line('<b>NET PROFIT</b>'+(P.fuelUncosted?'':' · '+(L>0?_rvFmt(X.netFinal/L,'m2')+' per litre · ':'')+'margin '+_rvFmt(P.revenue>0?X.netFinal/P.revenue*100:0,'p')),
         '<b>'+m(X.netFinal)+'</b>','wk-grand')+
    '</tbody></table>'+
    '<p class="wk-p"><b>Cash out, not deducted above:</b> stock bought '+_rvMoney(P.purchases)+' · cash handed over '+_rvMoney(P.handoverTotal)+
    ' · paid to staff '+_rvMoney(X.staffCashOut)+' · owner drawings '+_rvMoney(X.drawings)+
    (X.includeWages?'':' · wages are not deducted (Reports → “deduct staff wages” is off)')+'.</p>'+
    (P.fuelUncosted?'<p class="wk-p"><b>⚠ Fuel was sold with no purchase cost on record, so gross and net profit cannot be stated.</b></p>':'');
  var sec=function(no,title,out){
    var h='<div class="wk-sec">'+no+'. '+_esc(title)+'</div>';
    if(out.cards&&out.cards.length){
      var c=out.cards, rows=[];
      for(var i=0;i<c.length;i+=3)rows.push('<tr>'+c.slice(i,i+3).map(function(x){ return '<td><span class="wk-f">'+_esc(x[0])+'</span><br><b>'+_esc(x[1])+'</b>'+(x[3]?' <span class="wk-f">'+_esc(x[3])+'</span>':'')+'</td>'; }).join('')+'</tr>');
      h+='<table class="wk-tbl" style="margin-bottom:6px"><tbody>'+rows.join('')+'</tbody></table>';
    }
    (out.blocks||[]).forEach(function(b){
      if(b.h)h+='<p class="wk-p" style="margin-top:10px"><b>'+_esc(b.h)+'</b></p>';
      if(b.note)h+='<p class="wk-p wk-f">'+_esc(b.note)+'</p>';
      if(b.tbl)h+=_rvTblHtml(b.tbl,true);
    });
    return h;
  };
  var span=_rvDays(f,t)+1, safe=function(k,a){ try{ return RV_BUILD[k].apply(null,a); }catch(e){ return {blocks:[{note:'Could not be built: '+e.message}]}; } };
  var checks='';
  try{
    checks=_plAuditChecks(f,t,recs,P,{totalCreditDiscounts:X.disc}).map(function(c){
      var ico={ok:'✓',warn:'!',bad:'✗',info:'i'}[c.st]||'·';
      return '<div class="wk-chk '+c.st+'" style="margin-bottom:4px"><b class="wk-ico">'+ico+'</b> <b class="wk-chk-t">'+_esc(c.t)+'</b><div class="wk-chk-d">'+_esc(c.d)+'</div></div>';
    }).join('');
  }catch(e){ checks='<p class="wk-p">Checks could not be run: '+_esc(e.message)+'</p>'; }
  var doc='<div class="wk"><div class="wk-h"><div class="wk-title">'+_esc(bz.name||'Mani Fuels')+' — Business report</div>'+
    '<div class="wk-meta">'+_esc(_rvDmy(f)+' to '+_rvDmy(t))+' · '+recs.length+' shifts · generated '+
      _esc(new Date().toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}))+
      ' by '+_esc(_currentUser?(_currentUser.display||_currentUser.username):'—')+
      (bz.gstin?' · GSTIN '+_esc(bz.gstin):'')+'</div></div>'+
    '<div class="wk-sec">1. Profit &amp; loss</div>'+pl+
    sec(2,'Petrol vs diesel',safe('fuel',[f,t,recs]))+
    sec(3,span>62?'Month by month':'Day by day',safe('table',[f,t,recs,{group:span>62?'month':'day'}]))+
    sec(4,'Oil & stock',safe('oil',[f,t,recs]))+
    sec(5,'Expenses',safe('exp',[f,t,recs]))+
    sec(6,'Dues — as of today',safe('dues',[]))+
    sec(7,'Staff on duty vs cash',safe('staff',[f,t,recs]))+
    '<div class="wk-sec">8. Checks — where money can leak</div>'+checks+
    '</div>';
  var area=document.getElementById('pdf-print-area'); if(!area){ showToast('Print area missing'); return; }
  area.innerHTML=doc;
  if(typeof _mfAlignNums==='function')_mfAlignNums(area);
  _mfPrintArea((bz.name||'Mani Fuels')+' · Business report · '+_rvDmy(f)+' – '+_rvDmy(t));
  if(typeof logActivity==='function')logActivity('export_report','report',null,'Business report '+f+' → '+t);
  setTimeout(function(){ window.print(); },300);
}"""

HUNKS = [
("C1 css",
r"""#pdf-print-area{display:none}""",
r"""#pdf-print-area{display:none}
/* MF_REPORTS_V1 — report views */
.rv-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.rv-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:14px 0 6px;font-family:'Syne',sans-serif;font-weight:800;font-size:11px;letter-spacing:1.5px;color:var(--text)}
.rv-note{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);line-height:1.6;margin:2px 0 8px}
.rv-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:6px}
.rv-tbl td,.rv-tbl th{padding:6px 8px}
.rv-tbl tr.rv-tot td{font-weight:800;border-top:1px solid var(--border2);background:var(--s2)}
.pl-charts-row>.chart-wrap,.charts-grid>.chart-wrap{min-width:0}   /* charts shrink when the phone is turned */"""),

("M1 menu: period report, owner only",
r"""    <button class="nav-tab" onclick="exportPDF();closeMenu()"><span class="tab-icon">📄</span>Export Report (PDF)</button>""",
r"""    <button class="nav-tab owner-only" onclick="exportPeriodReport();closeMenu()" title="Business report for the period chosen on Reports (this month if none)"><span class="tab-icon">📄</span>Export Report (PDF)<span class="owner-badge" title="Owner only">🔒</span></button><!-- MF_REPORTS_V1 -->"""),

("R1 FY range buttons",
r"""    <button class="range-btn" onclick="setReportRange('lastmonth')">LAST MONTH</button>""",
r"""    <button class="range-btn" onclick="setReportRange('lastmonth')">LAST MONTH</button>
    <button class="range-btn" onclick="setReportRange('fy')" title="April 1 to today">THIS FY</button><!-- MF_REPORTS_V1 -->
    <button class="range-btn" onclick="setReportRange('lastfy')" title="April to March">LAST FY</button>"""),

("R2 FY ranges",
r"""    from=iso(s); to=iso(e);
  }
  document.getElementById('rep_from').value=from;""",
r"""    from=iso(s); to=iso(e);
  }
  else if(range==='fy'||range==='lastfy'){   // MF_REPORTS_V1: Indian financial year, April–March
    let y=now.getMonth()>=3?now.getFullYear():now.getFullYear()-1; if(range==='lastfy')y--;
    from=iso(new Date(y,3,1)); to=range==='fy'?iso(now):iso(new Date(y+1,2,31));
  }
  document.getElementById('rep_from').value=from;"""),

("R3 views container; old shift table hidden",
r"""  <div style="overflow-x:auto">
    <table class="data-tbl">
      <thead><tr><th>DATE</th><th>SHIFT</th><th>MSD (L)</th><th>HSD (L)</th><th>RIGHT (₹)</th><th>LEFT (₹)</th><th>EXPENSES (₹)</th><th>BALANCE</th></tr></thead>""",
r"""  <div id="rv_wrap" style="display:none;margin:6px 0 16px"></div><!-- MF_REPORTS_V1: report views -->
  <div id="rep_tbl_old" style="overflow-x:auto;display:none"><!-- MF_REPORTS_V1: replaced by TABLE → By shift -->
    <table class="data-tbl">
      <thead><tr><th>DATE</th><th>SHIFT</th><th>MSD (L)</th><th>HSD (L)</th><th>RIGHT (₹)</th><th>LEFT (₹)</th><th>EXPENSES (₹)</th><th>BALANCE</th></tr></thead>"""),

("G1 genReport: views when the period is empty",
r"""    const plSec=document.getElementById('pl_section');if(plSec)plSec.style.display='none';
    return;""",
r"""    const plSec=document.getElementById('pl_section');if(plSec)plSec.style.display='none';
    try{ if(typeof renderReportViews==='function')renderReportViews(from,to,[]); }catch(e){ console.error('report views:',e); }   // MF_REPORTS_V1
    return;"""),

("G2 genReport: views after the P&L",
r"""  try{ renderPL(from,to,filt); }
  catch(e){ console.warn('P&L render failed:',e.message);
    const ps=document.getElementById('pl_section'); if(ps)ps.style.display='none'; }
}""",
r"""  try{ renderPL(from,to,filt); }
  catch(e){ console.warn('P&L render failed:',e.message);
    const ps=document.getElementById('pl_section'); if(ps)ps.style.display='none'; }
  try{ if(typeof renderReportViews==='function')renderReportViews(from,to,filt); }catch(e){ console.error('report views:',e); }   // MF_REPORTS_V1
}"""),

("F1 compare uses the P&L engine",
r"""function _summarizeRecs(recs){
  // Same basis as the P&L and the dashboard: recorded takings less the
  // weighted-average landed cost of the litres that actually left, testing
  // removed from both sides. Comparing two periods with today's rate applied
  // to both made a price rise look like flat trade.
  const tv=recs.reduce((s,r)=>s+
    ((r.msdT?(r.msdV/r.msdT)*(r.testMSDL||0):0)+
     (r.hsdT?(r.hsdV/r.hsdT)*(r.testHSDL||0):0)+
     _recHydro(r)),0);   // testing fuel and the hydrometer draw
  const msdAvg=_fuelWAC('MSD'), hsdAvg=_fuelWAC('HSD');
  const totalMSDL=Math.max(0,recs.reduce((s,r)=>s+(r.msdT||0)-(r.testMSDL||0),0));
  const totalHSDL=Math.max(0,recs.reduce((s,r)=>s+(r.hsdT||0)-(r.testHSDL||0),0));
  const fuelTake=recs.reduce((s,r)=>s+(r.msdV||0)+(r.hsdV||0),0)-tv;
  const realizedFuel=fuelTake-(totalMSDL*msdAvg+totalHSDL*hsdAvg);
  const exp=Math.max(0,recs.reduce((s,r)=>s+(r.exp||0),0)-tv);
  const revenue=Math.max(0,recs.reduce((s,r)=>s+_recRevenue(r),0)-tv);
  const credit=recs.reduce((s,r)=>s+(r.credit||0),0);
  const costKnown=!((totalMSDL>0&&msdAvg<=0)||(totalHSDL>0&&hsdAvg<=0));
  return {shifts:recs.length,msdL:totalMSDL,hsdL:totalHSDL,revenue,exp,
          profit:realizedFuel-exp,credit,realizedFuel,costKnown};
}""",
r"""function _summarizeRecs(recs,from,to){
  // MF_REPORTS_V1: the P&L engine, plus the same discounts / wages as the
  // NET PROFIT card. The old copy left out oil and pack margin and costed
  // litres at today's average for BOTH periods, so its profit never matched.
  const P=_plCore(recs,from,to), X=_plExtras(from,to,P);
  return {shifts:recs.length,msdL:P.soldMSDL,hsdL:P.soldHSDL,revenue:P.revenue,exp:P.opex,
          profit:X.netFinal,credit:recs.reduce((s,r)=>s+(r.credit||0),0),
          realizedFuel:P.realizedFuelProfit,costKnown:!P.fuelUncosted};
}"""),

("F1b compare passes each period",
r"""  const sa=_summarizeRecs(a), sb=_summarizeRecs(b);""",
r"""  const sa=_summarizeRecs(a,f,t), sb=_summarizeRecs(b,cmpFrom,cmpTo);   // MF_REPORTS_V1"""),

("F1c realized fuel margin excludes the hydrometer rupees",
r"""  const realizedFuelProfit = (sumMSDV - testValMSD - soldMSDL*wacMSD) +
                             (sumHSDV - testValHSD - soldHSDL*wacHSD);""",
r"""  const realizedFuelProfit = (sumMSDV - testValMSD - soldMSDL*wacMSD) +
                             (sumHSDV - testValHSD - soldHSDL*wacHSD) -
                             testHydro;   // MF_REPORTS_V1: its litres are already out of cost, so its rupees come out of sales"""),

("F1d P&L card uses the shared discount routine",
r"""  const rates=JSON.parse(localStorage.getItem('fuelRates')||'{}');
  const avgFuelRate=((parseFloat(rates.hsd)||90)+(parseFloat(rates.msd)||100))/2;
  let totalCreditDiscounts=0;
  const creditCustNames=[...new Set(Object.keys(customerProfiles).filter(n=>customerProfiles[n].discountPerL>0))];
  creditCustNames.forEach(name=>{
    const discPerL=customerProfiles[name].discountPerL||0;
    if(!discPerL)return;
    // Only fuel actually taken on credit. An advance is a negative row and not
    // a sale; an account adjustment is money moving between two customers.
    // Summing the raw column counted both as litres and invented a discount
    // that was never given. Each row is also divided by ITS OWN fuel's rate —
    // the average of petrol and diesel overstated every diesel line.
    const msdRate=parseFloat(rates.msd)||avgFuelRate;
    const hsdRate=parseFloat(rates.hsd)||avgFuelRate;
    const estLitres=ledger.filter(e=>
        e.customer===name && (e.amount||0)>0 &&
        e.kind!=='adjust' && e.fuel!=='ADJUST' &&
        (!from||e.date>=from) && (!to||e.date<=to))
      .reduce(function(s,e){
        const rate = e.fuel==='MSD'?msdRate : (e.fuel==='HSD'?hsdRate : avgFuelRate);
        return s + (rate>0 ? e.amount/rate : 0);
      },0);
    totalCreditDiscounts+=estLitres*discPerL;
  });""",
r"""  // MF_REPORTS_V1: one routine for the card, compare mode and the tables —
  // same rule as before (credit fuel only, each row at its own fuel's rate).
  const _ext=_plExtras(from,to,_pl);
  const totalCreditDiscounts=_ext.disc;
  const creditCustNames=_ext.discNames;"""),

("T1 trend: each day's own P&L",
r"""  const dateMap={};
  shiftRecs.forEach(r=>{
    if(!dateMap[r.date])dateMap[r.date]={date:r.date,rev:0,cogs:0,opex:0};
    dateMap[r.date].rev += _recRevenue(r);
    dateMap[r.date].opex += (r.exp||0);
  });
  loadsInRange.forEach(l=>{
    if(!dateMap[l.date])dateMap[l.date]={date:l.date,rev:0,cogs:0,opex:0};
    dateMap[l.date].cogs += (l.totalCost||l.total_cost||0);
  });
  oilInRange.forEach(o=>{
    if(!dateMap[o.date])dateMap[o.date]={date:o.date,rev:0,cogs:0,opex:0};
    dateMap[o.date].cogs += (o.totalCost||o.total_cost||0);
  });
  const sortedDays = Object.values(dateMap).sort((a,b)=>a.date.localeCompare(b.date));
  const trendLabels = sortedDays.map(d=>new Date(d.date+'T00:00:00').toLocaleDateString('en-IN',{day:'2-digit',month:'short'}));
  const trendRev = sortedDays.map(d=>Math.round(d.rev));
  const trendCogs = sortedDays.map(d=>Math.round(d.cogs));
  const trendNet = sortedDays.map(d=>Math.round(d.rev - d.cogs - d.opex));""",
r"""  // MF_REPORTS_V1: each day's own P&L. The old line subtracted stock BOUGHT
  // that day, so a tanker day read as a big loss and the days after as windfalls.
  const _byDay={};
  shiftRecs.forEach(r=>{ (_byDay[r.date]=_byDay[r.date]||[]).push(r); });
  const sortedDays = Object.keys(_byDay).sort().map(d=>{
    const Q=_plCore(_byDay[d],d,d), X=_plExtras(d,d,Q);
    return {date:d, rev:Q.revenue, cogs:Q.fuelUncosted?null:Q.totalCOGS, net:Q.fuelUncosted?null:X.netFinal};
  });
  const trendLabels = sortedDays.map(d=>new Date(d.date+'T00:00:00').toLocaleDateString('en-IN',{day:'2-digit',month:'short'}));
  const trendRev = sortedDays.map(d=>Math.round(d.rev));
  const trendCogs = sortedDays.map(d=>d.cogs==null?null:Math.round(d.cogs));
  const trendNet = sortedDays.map(d=>d.net==null?null:Math.round(d.net));"""),

("T2 trend labels",
r"""      {type:'bar',label:'Stock bought',data:trendCogs,""",
r"""      {type:'bar',label:'Cost of goods sold',data:trendCogs,"""),

("T3 trend line: net profit on its own axis",
r"""      {type:'line',label:'Revenue − stock − expenses',data:trendNet,borderColor:'#3ddc84',backgroundColor:'rgba(61,220,132,.12)',borderWidth:2.5,tension:.3,fill:false,pointRadius:3,pointHoverRadius:6,pointBackgroundColor:'#3ddc84',order:1,yAxisID:'y'}""",
r"""      {type:'line',label:'Net profit (right scale)',data:trendNet,borderColor:'#3ddc84',backgroundColor:'rgba(61,220,132,.12)',borderWidth:2.5,tension:.3,fill:false,pointRadius:3,pointHoverRadius:6,pointBackgroundColor:'#3ddc84',order:1,yAxisID:'y1',spanGaps:false}"""),

("T3b right-hand scale for net profit",
r"""        y:{grid:{color:'rgba(47,47,47,.9)'},ticks:{color:'#AAAAAA',font:{family:'JetBrains Mono',size:9},callback:v=>'₹'+(Math.abs(v)>=1000?(v/1000).toFixed(0)+'k':v)}}""",
r"""        y:{grid:{color:'rgba(47,47,47,.9)'},ticks:{color:'#AAAAAA',font:{family:'JetBrains Mono',size:9},callback:v=>'₹'+(Math.abs(v)>=1000?(v/1000).toFixed(0)+'k':v)}},
        // MF_REPORTS_V1: net profit is a few % of revenue — on the same axis it was a flat line
        y1:{position:'right',beginAtZero:true,grid:{drawOnChartArea:false},ticks:{color:'#3ddc84',font:{family:'JetBrains Mono',size:9},callback:v=>'₹'+(Math.abs(v)>=1000?(v/1000).toFixed(1)+'k':v)}}"""),

("T4 trend tooltip null-safe",
r"""          callbacks:{label:c=>' '+c.dataset.label+': ₹'+c.raw.toLocaleString('en-IN')}}""",
r"""          callbacks:{label:c=>' '+c.dataset.label+': '+(c.raw==null?'not known':'₹'+c.raw.toLocaleString('en-IN'))}}"""),

("S1 statement: bills as memo, payments on their dates, no double pack",
r"""  // Purchases — bills on their bill date (supplier payments carry no date of their own)
  (typeof fuelLoads!=='undefined'?fuelLoads:[]).filter(function(l){return inR(l.date);}).forEach(function(l){
    var tc=+(l.totalCost!=null?l.totalCost:l.total_cost)||0, due=Math.max(0,tc-(+l.amountPaid||0));
    rows.push({date:l.date,ord:0,ref:l.inv||'LOAD',dr:tc,desc:'Fuel purchase — '+(l.type||'')+' '+_sL(l.vol,0)+' L'+(l.supplier?' · '+l.supplier:''),
      sub:'landed ₹'+_sN((+l.vol||0)>0?tc/l.vol:0)+'/L'+(l.billTotal?' · bill ₹'+_sN(l.billTotal):'')+(l.lorryRent?' + lorry ₹'+_sN(l.lorryRent):'')+
          (l.lorry?' · '+l.lorry:'')+' · paid ₹'+_sN(l.amountPaid||0)+(due>0.5?' · DUE ₹'+_sN(due):''),warn:due>0.5});
  });
  (typeof oilReg!=='undefined'?oilReg:[]).filter(function(o){return inR(o.date);}).forEach(function(o){
    var due=Math.max(0,(+o.totalCost||0)-(+o.amountPaid||0));
    rows.push({date:o.date,ord:0,ref:o.inv||'OIL',dr:o.totalCost||0,desc:'Oil purchase — '+(o.company||''),
      sub:(o.items||[]).map(function(i){return (i.name||'item')+' ×'+i.qty+' @ ₹'+_sN(i.buy);}).join(' · ')+' · paid ₹'+_sN(o.amountPaid||0)+(due>0.5?' · DUE ₹'+_sN(due):''),warn:due>0.5});
  });
  (typeof packReg!=='undefined'?packReg:[]).filter(function(p){return inR(p.date)&&(+p.totalCost||0)>0;}).forEach(function(p){""",
r"""  // MF_REPORTS_V1 — a bill is not money out until it is paid. Each bill is a
  // memo line (shown, not in the balance); the money out is each payment on
  // the day it was paid. Fuel-load payments carry no date of their own, so
  // what has been paid on a load is shown on its bill date, and says so.
  (typeof fuelLoads!=='undefined'?fuelLoads:[]).filter(function(l){return inR(l.date);}).forEach(function(l){
    var tc=+(l.totalCost!=null?l.totalCost:l.total_cost)||0, paid=Math.min(tc,+l.amountPaid||0), due=Math.max(0,tc-paid);
    rows.push({date:l.date,ord:0,ref:l.inv||'LOAD',memo:true,desc:'Fuel bill — '+(l.type||'')+' '+_sL(l.vol,0)+' L'+(l.supplier?' · '+l.supplier:'')+' · ₹'+_sN(tc),
      sub:'landed ₹'+_sN((+l.vol||0)>0?tc/l.vol:0)+'/L'+(l.billTotal?' · bill ₹'+_sN(l.billTotal):'')+(l.lorryRent?' + lorry ₹'+_sN(l.lorryRent):'')+
          (l.lorry?' · '+l.lorry:'')+' · paid ₹'+_sN(paid)+(due>0.5?' · DUE ₹'+_sN(due):'')+' · bill shown for information',warn:due>0.5});
    if(paid>0.005)rows.push({date:l.date,ord:0,ref:l.inv||'LOAD',dr:paid,desc:'Paid for fuel — '+(l.type||'')+(l.supplier?' · '+l.supplier:''),
      sub:'payment date not recorded — shown on the bill date'});
  });
  (typeof oilReg!=='undefined'?oilReg:[]).forEach(function(o){
    var tc=+o.totalCost||0, pays=(Array.isArray(o.payments)&&o.payments.length)?o.payments
          :((+o.amountPaid||0)>0?[{date:o.date,amount:+o.amountPaid,mode:'',legacy:true}]:[]);
    var paid=Math.min(tc,pays.reduce(function(s,p){return s+(+p.amount||0);},0)), due=Math.max(0,tc-paid);
    if(inR(o.date))rows.push({date:o.date,ord:0,ref:o.inv||'OIL',memo:true,desc:'Oil bill — '+(o.company||'')+' · ₹'+_sN(tc),
      sub:(o.items||[]).map(function(i){return (i.name||'item')+' ×'+i.qty+' @ ₹'+_sN(i.buy);}).join(' · ')+' · paid ₹'+_sN(paid)+(due>0.5?' · DUE ₹'+_sN(due):'')+' · bill shown for information',warn:due>0.5});
    pays.forEach(function(p){
      if(!inR(p.date)||!((+p.amount||0)>0))return;
      rows.push({date:p.date,ord:0,ref:o.inv||'OIL',dr:+p.amount,desc:'Paid to '+(o.company||'supplier')+' — invoice '+(o.inv||''),
        sub:[p.mode&&p.mode!=='—'?p.mode:'',p.ref||'',p.legacy?'paid before payment dates were kept — shown on the bill date':'',
             p.date!==o.date?'bill of '+_sD(o.date):''].filter(Boolean).join(' · ')});
    });
  });
  // Pack lines on an oil bill are part of that bill, not a second purchase.
  var _onOilBill=function(p){
    var reg=(typeof oilReg!=='undefined'?oilReg:[]);
    if(p.invId!=null&&reg.some(function(o){return String(o.id)===String(p.invId);}))return true;
    return reg.some(function(o){return o.date===p.date&&String(p.notes||'')==='Invoice '+(o.inv||'')&&String(o.company||'')===String(p.supplier||'');});
  };
  (typeof packReg!=='undefined'?packReg:[]).filter(function(p){return inR(p.date)&&(+p.totalCost||0)>0&&!_onOilBill(p);}).forEach(function(p){"""),

("S2 statement note",
r"""purchase bills are taken on their bill date.""",
r"""purchase bills are shown for information and the money out is each payment, on the day it was paid (a fuel load’s payment has no date of its own, so it shows on the bill date)."""),

("V1 report views module",
r"""// ── CREDIT LEDGER ──
var currentLedgerCustomer=null;""",
MODULE + r"""
// ── CREDIT LEDGER ──
var currentLedgerCustomer=null;"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    for need in ("MF_OIL_V1", "MF_PL_WORKINGS_V1"):
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
