#!/usr/bin/env python3
"""
MF_TARGET_SPLIT_V1 — monthly target set separately for MSD and HSD litres
(plus the profit target). An older combined litres target is still shown
until MSD/HSD are set, with a prompt to split it.

Usage:  python3 patch_target_split.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_TARGET_SPLIT_V1"

A_START = "  const lastMonthL=(function(){"
A_END = "    html+='<div style=\"font-size:9px;color:var(--muted)\">White line = where you should be today.</div>';\n  }\n"
A_NEW = r"""  // MF_TARGET_SPLIT_V1 — MSD and HSD targets are separate.
  const LM=(function(){const f=new Date(now.getFullYear(),now.getMonth()-1,1);const e=new Date(now.getFullYear(),now.getMonth(),0);
    const x=P(iso(f),iso(e)); return {msd:x.soldMSDL||0, hsd:x.soldHSDL||0};})();
  const sugg=n=>n>0?Math.round(n*1.05/100)*100:'';
  const daysDone=Math.max(1,dayNo-(mfSlotEnd({date:todayIso,shift:'night'})>now?1:0));
  const mMSD=Pm.soldMSDL||0, mHSD=Pm.soldHSDL||0;
  const anyT=T.msd||T.hsd||T.litres||T.profit;
  html+=band('MONTHLY TARGET — '+now.toLocaleDateString('en-IN',{month:'long',year:'numeric'}).toUpperCase()+
    ' &nbsp;<span onclick="_mfEditTarget()" style="cursor:pointer;color:var(--petrol);letter-spacing:1px">✎ '+(anyT?'CHANGE':'SET')+' TARGET</span>');
  html+='<div style="'+box+'">';
  const inp=(id,val,ph,w)=>'<input id="'+id+'" type="number" min="0" step="100" style="width:'+(w||110)+'px" value="'+(val||'')+'" placeholder="'+ph+'">';
  html+='<div id="mfTargetEdit" style="display:none;margin-bottom:10px;font-size:11px;line-height:2.2">'+
    '<span style="color:var(--petrol);font-weight:700">MSD</span> litres / month '+inp('mfTgtM',T.msd,sugg(LM.msd))+' &nbsp; '+
    '<span style="color:var(--diesel);font-weight:700">HSD</span> litres / month '+inp('mfTgtH',T.hsd,sugg(LM.hsd))+' &nbsp; '+
    'Profit / month ₹ '+inp('mfTgtP',T.profit,'',120)+' &nbsp; '+
    '<button class="btn btn-g" style="padding:3px 10px;font-size:10px" onclick="_mfSaveTarget()">SAVE</button>'+
    '<div style="color:var(--muted);font-size:10px;line-height:1.5">'+
      ((LM.msd||LM.hsd)?'Last month: MSD '+Lfmt(LM.msd)+' · HSD '+Lfmt(LM.hsd)+' (grey figures = last month + 5%). ':'')+
      'Leave a box empty to not track it. Same target every month until you change it; syncs to every phone.</div>'+
    '</div>';
  if(!anyT){
    html+='<div style="font-size:11px;color:var(--muted)">No target set yet. Tap <b style="color:var(--petrol)">✎ SET TARGET</b> above'+
      ((LM.msd||LM.hsd)?' — last month you sold MSD '+Lfmt(LM.msd)+' and HSD '+Lfmt(LM.hsd)+'.':'.')+
      ' So far this month: MSD '+Lfmt(mMSD)+' · HSD '+Lfmt(mHSD)+(mKnown?' · profit '+R0(Pm.netProfit):'')+'</div>';
  } else {
    if(T.msd)html+=tgtRow('<span style="color:var(--petrol)">MSD</span> (petrol) litres',mMSD,T.msd,Lfmt,Pm.shifts?mMSD/daysDone:null);
    if(T.hsd)html+=tgtRow('<span style="color:var(--diesel)">HSD</span> (diesel) litres',mHSD,T.hsd,Lfmt,Pm.shifts?mHSD/daysDone:null);
    if(T.litres&&!T.msd&&!T.hsd){
      html+=tgtRow('Litres sold (MSD + HSD)',mL,T.litres,Lfmt,Pm.shifts?mL/daysDone:null);
      html+='<div style="font-size:10px;color:var(--diesel);margin:-4px 0 8px">Tap ✎ CHANGE TARGET to set MSD and HSD separately.</div>';
    }
    if(T.profit)html+=mKnown?tgtRow('Profit',Pm.netProfit,T.profit,k,null)
                            :'<div style="font-size:10px;color:var(--muted)">Profit target: needs fuel cost on record.</div>';
    html+='<div style="font-size:9px;color:var(--muted)">White line = where you should be today.</div>';
  }
"""

B_OLD_FN = """  return {litres:parseFloat(t.litres)||0, profit:parseFloat(t.profit)||0, updatedAt:t.updatedAt||''};"""
B_NEW_FN = """  return {msd:parseFloat(t.msd)||0, hsd:parseFloat(t.hsd)||0,   // MF_TARGET_SPLIT_V1
          litres:parseFloat(t.litres)||0, profit:parseFloat(t.profit)||0, updatedAt:t.updatedAt||''};"""

C_OLD = """  var L=parseFloat((document.getElementById('mfTgtL')||{}).value)||0;
  var Pr=parseFloat((document.getElementById('mfTgtP')||{}).value)||0;
  localStorage.setItem('monthTarget',JSON.stringify({litres:L,profit:Pr,updatedAt:new Date().toISOString()}));
  if(typeof queueSettingsSave==='function')queueSettingsSave();
  if(typeof logActivity==='function')logActivity('set_target','settings',null,'Monthly target: '+(L?L+' L':'—')+' / '+(Pr?'₹'+Pr:'—'));"""
C_NEW = """  var num=function(id){return parseFloat((document.getElementById(id)||{}).value)||0;};
  var M=num('mfTgtM'), H=num('mfTgtH'), Pr=num('mfTgtP');   // MF_TARGET_SPLIT_V1
  localStorage.setItem('monthTarget',JSON.stringify({msd:M,hsd:H,profit:Pr,updatedAt:new Date().toISOString()}));
  if(typeof queueSettingsSave==='function')queueSettingsSave();
  if(typeof logActivity==='function')logActivity('set_target','settings',null,
    'Monthly target: MSD '+(M?M+' L':'—')+' · HSD '+(H?H+' L':'—')+' · profit '+(Pr?'₹'+Pr:'—'));"""


def main():
    src = open(PATH, encoding="utf-8").read()
    if SENTINEL in src:
        print("Nothing to do — MF_TARGET_SPLIT_V1 already applied."); return
    a = src.find(A_START); b = src.find(A_END)
    if a < 0 or b < 0 or b < a or src.count(A_START) != 1:
        sys.exit("✗ target block anchors not found — nothing written")
    out = src[:a] + A_NEW + src[b + len(A_END):]
    D_OLD = "    const d=a-b, c=!fair?AMBER:((d>=0)===(higherGood!==false)?GREEN:RED);\n"
    D_NEW = D_OLD + "    if(Math.abs(d)<0.005)return '<td style=\"text-align:right;padding:2px 0 2px 8px;color:var(--muted)\">no change</td>';   // MF_TARGET_SPLIT_V1\n"
    for name, old, new in [("_mfTarget returns msd/hsd", B_OLD_FN, B_NEW_FN), ("_mfSaveTarget saves msd/hsd", C_OLD, C_NEW), ("week table: zero change is neutral", D_OLD, D_NEW)]:
        if out.count(old) != 1: sys.exit(f"✗ {name}: anchor not found once — nothing written")
        out = out.replace(old, new); print("  ✓", name)
    print("  ✓ target block: MSD and HSD rows")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js"); open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode: sys.exit(f"✗ node --check failed on script #{i}:\n{r.stderr}\nNothing written.")
    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ {SENTINEL} applied; node --check passed on {len(scripts)} script(s); backup {PATH}.bak")


if __name__ == "__main__":
    main()
