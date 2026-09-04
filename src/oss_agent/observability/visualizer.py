"""Pixel-world workflow visualizer — the "GitHub war room".

Renders a :class:`~oss_agent.domain.models.WorkflowSnapshot` as a self-contained,
interactive HTML page: a pixel-art control room where nine agents sit at glowing
laptops working a pull request together. A big wall screen shows the open-source
task and the current stage; the active agent's laptop glows and a spotlight falls
on their desk; completed agents show a check, pending agents sit dark. Clicking an
agent inspects its captured evidence.

The output is a single standalone HTML string with inline CSS/JS and no external
dependencies, so it opens straight in a browser (``oss-agent visualize``).
"""

from __future__ import annotations

import json
from typing import Optional

from oss_agent.domain.enums import WorkflowState as S
from oss_agent.domain.models import WorkflowSnapshot

# Each stage: key, label, agent name, role tagline, and hue.
STAGE_DEFS: list[dict] = [
    {"key": "discovery", "label": "Discovery", "agent": "github-discovery",
     "role": "Scouts GitHub for a match", "color": "#8f86ff"},
    {"key": "repo", "label": "Repo scan", "agent": "repository-analyzer",
     "role": "Maps the codebase", "color": "#22c0a0"},
    {"key": "issue", "label": "Issue", "agent": "issue-analyzer",
     "role": "Extracts the real problem", "color": "#3fa0ff"},
    {"key": "scoring", "label": "Scoring", "agent": "contribution-scorer",
     "role": "Rates the opportunity", "color": "#ffab24"},
    {"key": "planning", "label": "Planning", "agent": "planner",
     "role": "Writes the machine plan", "color": "#f265a0"},
    {"key": "implementation", "label": "Build", "agent": "implementer",
     "role": "Edits inside a worktree", "color": "#ff7a45"},
    {"key": "testing", "label": "Testing", "agent": "test-engineer",
     "role": "Runs the real suite", "color": "#a8d84e"},
    {"key": "review", "label": "Review", "agent": "code / security / maintainer",
     "role": "Three independent gates", "color": "#9b8bff"},
    {"key": "prgate", "label": "PR gate", "agent": "pr-manager",
     "role": "Opens the pull request", "color": "#ffc233"},
]

_STATE_RANK: dict[S, int] = {
    S.DISCOVERY: 0, S.REPOSITORY_ANALYSIS: 1, S.ISSUE_ANALYSIS: 2,
    S.SCORING: 3, S.SELECTED: 3, S.PLANNING: 4,
    S.IMPLEMENTATION: 5, S.DEBUGGING: 5, S.TESTING: 6,
    S.CODE_REVIEW: 7, S.SECURITY_REVIEW: 7, S.MAINTAINER_REVIEW: 7,
    S.READY_FOR_PR: 8, S.PR_CREATED: 8, S.PR_MONITORING: 8, S.MERGED: 8,
}


def _stage_done(snap: WorkflowSnapshot) -> list[bool]:
    return [
        snap.repository_full_name is not None,
        snap.repository_report is not None,
        snap.issue_analysis is not None,
        snap.score is not None,
        snap.plan is not None,
        snap.implementation is not None,
        snap.test_result is not None,
        bool(snap.code_review and snap.security_review and snap.maintainer_review),
        bool(snap.pull_request and snap.pull_request.created) or snap.state in (
            S.READY_FOR_PR, S.PR_CREATED, S.PR_MONITORING, S.MERGED),
    ]


def _evidence(snap: WorkflowSnapshot) -> list[str]:
    a, sc, pl, im, tr = snap.issue_analysis, snap.score, snap.plan, snap.implementation, snap.test_result
    su = snap.suitability
    rev = [snap.code_review, snap.security_review, snap.maintainer_review]
    pr = snap.pull_request
    # Scoring evidence folds in the suitability verdict (they share the stage).
    score_evi = "pending"
    if sc:
        score_evi = f"{sc.overall:.0f}/100 → {sc.recommendation.value}"
        if su:
            score_evi += f" · {su.category.value}"
    return [
        f"{snap.repository_full_name or '—'}#{snap.issue_number or '—'}",
        (f"build ok · tests {'yes' if snap.repository_report and snap.repository_report.has_tests else 'no'}"
         if snap.repository_report else "pending"),
        (f"{a.contribution_type.value} · ambiguity {a.ambiguity_score:.2f}" if a else "pending"),
        score_evi,
        (f"branch {pl.branch_name}" if pl else "pending"),
        (f"{len(im.files_changed)} file(s) changed" if im else "pending"),
        (f"{tr.total_tests_passed} passed" if tr and tr.passed else ("FAILED" if tr else "pending")),
        (" · ".join(v.verdict.value for v in rev if v) if any(rev) else "pending"),
        (f"PR #{pr.number} opened" if pr and pr.created else ("ready to open" if snap.state == S.READY_FOR_PR else "pending")),
    ]


def _logs(snap: WorkflowSnapshot) -> list[str]:
    rr, a, sc, pl, im, tr = (snap.repository_report, snap.issue_analysis, snap.score,
                             snap.plan, snap.implementation, snap.test_result)
    pr = snap.pull_request
    return [
        f"repository: {snap.repository_full_name or '—'}\nduplicate check: ok",
        (f"build={rr.build_system} · test cmd: {rr.test_command}\ninjection flags: {len(rr.injection_flags)}" if rr else ""),
        (f"probable files: {', '.join(a.probable_files[:2]) or '—'}\ninjection flags: {len(a.injection_flags)}" if a else ""),
        ((f"penalties -{sc.total_penalty:.0f} · {len(sc.components)} dimensions" if sc else "")
         + (f"\nsuitability: {snap.suitability.category.value} ({snap.suitability.score:.0f}/100)"
            if snap.suitability else "")),
        (f"affected: {', '.join(pl.affected_files[:2]) or '—'}\nrollback: {pl.rollback_strategy[:48]}" if pl else ""),
        (f"changed: {', '.join(f.path for f in im.files_changed[:2])}\nunexpected files: {len(im.unexpected_files)}" if im else ""),
        (f"{len(tr.executed_suites)} suite(s) run · {len(tr.skipped_suites)} skipped\nevidence captured (exit codes)" if tr else ""),
        (f"code: {snap.code_review.verdict.value if snap.code_review else '—'} · "
         f"sec: {snap.security_review.verdict.value if snap.security_review else '—'} · "
         f"maint: {snap.maintainer_review.verdict.value if snap.maintainer_review else '—'}"),
        ((f"branch {snap.branch or '—'} → {pr.url}" if pr and pr.url else "never merges automatically")
         + f"\nhuman approval: {'granted' if snap.human_approved else 'required before submit'}"
         + (" · learning report ready" if snap.learning_report else "")),
    ]


def build_workflow_data(snap: WorkflowSnapshot) -> dict:
    done = _stage_done(snap)
    evi, logs = _evidence(snap), _logs(snap)
    failed = snap.state in (S.FAILED, S.ABORTED)
    try:
        current = done.index(False)
    except ValueError:
        current = 8
    if snap.state == S.MERGED:
        current = 8
    stages = []
    for i, d in enumerate(STAGE_DEFS):
        if done[i]:
            status = "done"
        elif failed and i == current:
            status = "failed"
        elif i == current:
            status = "active"
        else:
            status = "pending"
        stages.append({
            "l": d["label"], "a": d["agent"], "r": d["role"], "c": d["color"],
            "e": evi[i], "log": logs[i], "status": status,
        })
    events = [{"t": e.type.value, "x": (e.action or e.type.value)[:60]} for e in snap.events[-9:]]
    pr = snap.pull_request
    return {
        "id": snap.id, "repo": snap.repository_full_name or "—", "issue": snap.issue_number,
        "state": snap.state.value.replace("_", " "),
        "prUrl": (pr.url if pr and pr.created else None),
        "prNum": (pr.number if pr and pr.created else None),
        "current": current, "failed": failed, "stages": stages, "events": events,
    }


def _demo_data() -> dict:
    snap = WorkflowSnapshot(id="demo-workflow", repository_full_name="octo-org/example",
                            issue_number=42, state=S.DISCOVERY)
    return build_workflow_data(snap)


def render_html(snapshot: Optional[WorkflowSnapshot] = None) -> str:
    data = build_workflow_data(snapshot) if snapshot is not None else _demo_data()
    title = f"OSS-Agent · {data['repo']} #{data['issue']}" if snapshot else "OSS-Agent visualizer (demo)"
    return _TEMPLATE.replace("__TITLE__", title).replace("__DATA__", json.dumps(data))


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#070812;color:#e7e9f5;font-family:ui-sans-serif,system-ui,'Segoe UI',Roboto,sans-serif;display:flex;justify-content:center;padding:22px 12px}
.wrap{width:100%;max-width:980px}
.hud{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.htitle{font-size:15px;font-weight:500;color:#cfd6ff}
.hmeta{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#8b90c0}
.live{font-family:ui-monospace,monospace;font-size:12px;color:#8fe0a8;background:#12261a;border:1px solid #2f6a44;border-radius:6px;padding:3px 10px}
.live.fail{color:#f0a0a0;background:#2a1414;border-color:#6a2f2f}
.stage{border-radius:14px;overflow:hidden;border:1px solid #23263f;background:#0b0d1a;box-shadow:0 0 60px rgba(80,90,220,.14)}
svg{display:block;width:100%;height:auto;image-rendering:pixelated}
.glow{animation:gl 1.1s ease-in-out infinite}@keyframes gl{0%,100%{opacity:.55}50%{opacity:1}}
.led{animation:led 1.4s steps(2) infinite}@keyframes led{50%{opacity:.25}}
.twk{animation:led 2.2s steps(2) infinite}
.ring{opacity:0;transition:.25s}.ws.on .ring{opacity:1}.ws{cursor:pointer}
.tok{transition:transform .55s cubic-bezier(.5,-.3,.4,1.4)}.spot{transition:.4s;pointer-events:none}
.controls{display:flex;align-items:center;gap:8px;margin:12px 2px 0}
.controls button{background:#1a1d38;color:#cfd3f5;border:1px solid #343a63;border-radius:8px;padding:7px 13px;font-size:13px;cursor:pointer}
.controls button:hover{background:#232750}
.prog{margin-left:auto;font-family:ui-monospace,monospace;font-size:12px;color:#8b90c0}
.cols{display:grid;grid-template-columns:1.5fr 1fr;gap:10px;margin-top:12px}
@media(max-width:620px){.cols{grid-template-columns:1fr}}
.card{background:#0b0d1c;border:1px solid #22253f;border-radius:12px;padding:12px 14px}
.dhead{display:flex;align-items:center;gap:10px}
.dot{width:12px;height:12px;border-radius:3px}
.dname{font-size:15px;font-weight:500;color:#fff}.drole{font-size:12px;color:#9095c4}
.devi{margin-top:9px;font-family:ui-monospace,monospace;font-size:12px;color:#8fe0a8;background:#12261a;border:1px solid #2f6a44;border-radius:6px;padding:5px 9px;display:inline-block}
.dlog{margin-top:9px;font-family:ui-monospace,monospace;font-size:11px;color:#7f84b3;white-space:pre-line;line-height:1.6}
.evh{font-size:12px;font-weight:500;color:#9095c4;margin:0 0 8px}
.ev{font-family:ui-monospace,monospace;font-size:11px;color:#8b90c0;padding:3px 0;border-bottom:1px solid #171a30}
a.prl{color:#ffd35c;text-decoration:none;border-bottom:1px dotted #ffd35c}
</style></head>
<body><div class="wrap">
  <div class="hud"><span class="htitle">oss-agent · github war room</span>
    <span class="hmeta" id="meta"></span><span class="live" id="live"></span></div>
  <div class="stage"><svg id="scene" viewBox="0 0 680 440" role="img"><title>OSS-Agent war room</title></svg></div>
  <div class="controls">
    <button id="prev">&#9664; prev</button><button id="play">&#9654; play run</button><button id="next">next &#9654;</button>
    <span class="prog" id="prog"></span></div>
  <div class="cols">
    <div class="card"><div class="dhead"><span class="dot" id="dot"></span><div><div class="dname" id="dname"></div><div class="drole" id="drole"></div></div></div>
      <div class="devi" id="devi"></div><div class="dlog" id="dlog"></div></div>
    <div class="card"><p class="evh">event stream</p><div id="ev"></div></div></div>
</div>
<script>
var WF=__DATA__;
var AB=["..HHHHHH..",".HHHHHHHH.",".HHHHHHHH.",".HHFFFFHH.","SSSSSSSSSS","SSSSSSSSSS","SSSSSSSSSS","SSSSSSSSSS"];
var LP=["KKKKKKKKKK","K........K","K...LL...K","K...LL...K","K........K","KKKKKKKKKK"];
function sh(hex,d){var n=parseInt(hex.slice(1),16),R=Math.max(0,Math.min(255,(n>>16)+d)),G=Math.max(0,Math.min(255,((n>>8)&255)+d)),B=Math.max(0,Math.min(255,(n&255)+d));return"#"+(1<<24|R<<16|G<<8|B).toString(16).slice(1);}
function R(x,y,w,h,f,cls){return '<rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" fill="'+f+'"'+(cls?' class="'+cls+'"':'')+'/>';}
function px(map,cols,cm,ox,oy,s,cls){var o='';for(var y=0;y<map.length;y++)for(var x=0;x<cols;x++){var ch=map[y][x];if(ch==='.'||ch===undefined)continue;var c=cm[ch];if(!c)continue;o+='<rect x="'+(ox+x*s)+'" y="'+(oy+y*s)+'" width="'+s+'" height="'+s+'" fill="'+c+'"'+(cls?' class="'+cls+'"':'')+'/>';}return o;}
var scene=document.getElementById('scene'),centers=[];
function room(){var o='';
 o+=R(0,0,680,180,'#141a33');o+=R(0,0,680,10,'#0e1226');
 for(var i=0;i<5;i++){o+=R(70+i*130,0,44,6,'#3b4680');o+=R(78+i*130,6,28,3,'#aeb8ff','led');}
 o+=R(150,26,380,132,'#0a0f24');o+='<rect x="150" y="26" width="380" height="132" fill="none" stroke="#3a6bd6" stroke-width="2"/>';
 o+=R(150,26,380,16,'#12213f');o+='<circle cx="162" cy="34" r="3" fill="#e24b4a"/><circle cx="173" cy="34" r="3" fill="#ffab24"/><circle cx="184" cy="34" r="3" fill="#57b877"/>';
 for(var k=0;k<132;k+=4){o+=R(150,26+k,380,1,'#0e1a33');}
 o+=px(["..XXXX..",".XXXXXX.","XXoXXoXX","XXXXXXXX","XXXXXXXX",".X.XX.X.","X.X..X.X"],8,{X:'#c7d1ff',o:'#141a33'},44,60,5);
 o+='<text x="44" y="150" fill="#7f8bd0" font-family="monospace" font-size="11">git.hub / control</text>';
 o+=R(596,52,60,96,'#0a1230');o+='<rect x="596" y="52" width="60" height="96" fill="none" stroke="#2c3566" stroke-width="2"/>';
 for(var w=0;w<14;w++){o+=R(602+((w*17)%50),58+((w*23)%84),2,2,'#9fb0ff','twk');}
 o+=R(24,52,60,96,'#0a1230');o+='<rect x="24" y="52" width="60" height="96" fill="none" stroke="#2c3566" stroke-width="2"/>';
 for(var w2=0;w2<14;w2++){o+=R(30+((w2*13)%50),58+((w2*29)%84),2,2,'#9fb0ff','twk');}
 o+=R(0,180,680,260,'#0d1024');o+=R(0,178,680,4,'#242a52');o+=R(0,250,680,3,'#1c2246');o+=R(0,332,680,3,'#1c2246');
 o+=R(8,196,16,150,'#10152e');o+=R(656,196,16,150,'#10152e');
 for(var r=0;r<8;r++){var cA=['#57b877','#ffab24','#3fa0ff'][r%3],cB=['#3fa0ff','#57b877','#ffab24'][r%3];o+=R(11,204+r*17,10,4,'#1b2350')+R(13,205+r*17,3,2,cA,'led')+R(659,204+r*17,10,4,'#1b2350')+R(661,205+r*17,3,2,cB,'led');}
 return o;}
function station(i){var s=WF.stages[i],st=s.status;
 var rowsY=[236,308,382],xs=[[205,340,475],[172,340,508],[140,340,540]],rowsS=[3.0,3.4,3.8];
 var row=Math.floor(i/3),col=i%3,cx=xs[row][col],dy=rowsY[row],sc=rowsS[row];
 centers[i]={x:cx,y:dy-16*sc/3};
 var deskW=64*sc/3.4,g='<g class="ws" data-i="'+i+'">';
 g+='<ellipse class="ring" cx="'+cx+'" cy="'+(dy+10)+'" rx="'+(deskW*0.75)+'" ry="10" fill="none" stroke="'+s.c+'" stroke-width="2"/>';
 g+=R(cx-11*sc/3,dy-30*sc/3,22*sc/3,26*sc/3,sh(s.c,-70));
 g+=px(AB,10,{H:sh(s.c,-30),F:'#f0c9a2',S:s.c},cx-10*sc/3,dy-28*sc/3,sc/1.0*0.66);
 if(st==='pending')g+=R(cx-10*sc/3,dy-28*sc/3,20*sc/3,17*sc/3,'#0d1024CC');
 g+=R(cx-deskW,dy,deskW*2,7*sc/3,'#3a2f26')+R(cx-deskW,dy+7*sc/3,deskW*2,15*sc/3,'#241d17');
 var lg=st==='active'?s.c:(st==='done'?sh(s.c,-40):(st==='failed'?'#e24b4a':'#20233a'));
 g+=px(LP,10,{K:'#15182b',L:lg},cx-10*sc/3.2,dy-9*sc/3,sc/3.2*1.0);
 if(st==='active')g+='<rect x="'+(cx-3*sc/3.2)+'" y="'+(dy-6*sc/3)+'" width="'+(6*sc/3.2)+'" height="'+(2*sc/3.2)+'" fill="'+s.c+'" class="glow"/>';
 g+='<text x="'+cx+'" y="'+(dy+16*sc/3)+'" text-anchor="middle" fill="#cfd6ff" font-family="monospace" font-size="10">'+s.l+'</text>';
 var bx=cx+deskW-6,by=dy-30*sc/3;
 if(st==='done')g+='<circle cx="'+bx+'" cy="'+by+'" r="6" fill="#173d28"/><text x="'+bx+'" y="'+(by+3)+'" text-anchor="middle" fill="#57e08a" font-size="9">&#10003;</text>';
 else if(st==='active')g+='<circle cx="'+bx+'" cy="'+by+'" r="6" fill="#3a2e12"/><text x="'+bx+'" y="'+(by+3)+'" text-anchor="middle" fill="#ffcf5c" font-size="9" class="glow">&#9679;</text>';
 else if(st==='failed')g+='<circle cx="'+bx+'" cy="'+by+'" r="6" fill="#3d1717"/><text x="'+bx+'" y="'+(by+3)+'" text-anchor="middle" fill="#ff8a8a" font-size="9">!</text>';
 else g+='<circle cx="'+bx+'" cy="'+by+'" r="6" fill="#1a1e34"/>';
 return g+'</g>';}
function build(){var o=room();o+='<polygon id="spot" class="spot" points="0,0 0,0 0,0" fill="#ffe08a" opacity="0.10"/>';
 for(var i=0;i<9;i++)o+=station(i);
 o+='<g class="tok" id="tok"><rect x="-6" y="-6" width="12" height="12" fill="#ffd35c" transform="rotate(45)"/><rect x="-3" y="-1" width="6" height="2" fill="#7a5a00"/></g>';
 scene.innerHTML=o;
 [].forEach.call(scene.querySelectorAll('.ws'),function(g){g.addEventListener('click',function(){stop();focus(+g.dataset.i);});});}
function screenText(i){var s=WF.stages[i];
 var pips='';for(var k=0;k<9;k++){var col=WF.stages[k].status!=='pending'?WF.stages[k].c:'#2a2f52';pips+='<rect x="'+(180+k*14)+'" y="132" width="10" height="10" fill="'+col+'"'+(k===i?' stroke="#fff" stroke-width="1"':'')+'/>';}
 var head=WF.prNum?(WF.repo+' · PR #'+WF.prNum):(WF.repo+' · issue #'+WF.issue);
 return '<g id="scr"><text x="196" y="38" fill="#8fa0e6" font-family="monospace" font-size="11">'+head+'</text>'+
  '<text x="340" y="82" text-anchor="middle" fill="#ffffff" font-family="monospace" font-size="22">'+(i+1)+'. '+s.l.toUpperCase()+'</text>'+
  '<text x="340" y="104" text-anchor="middle" fill="'+s.c+'" font-family="monospace" font-size="12">'+s.a+'</text>'+
  '<text x="340" y="124" text-anchor="middle" fill="#9fb0d8" font-family="monospace" font-size="11">'+s.e+'</text>'+pips+'</g>';}
function focus(i){cur=i;var old=scene.querySelector('#scr');if(old)old.remove();
 scene.insertAdjacentHTML('beforeend',screenText(i));
 [].forEach.call(scene.querySelectorAll('.ws'),function(g,k){g.classList.toggle('on',k===i);});
 var c=centers[i];document.getElementById('tok').setAttribute('transform','translate('+c.x+','+(c.y-6)+')');
 scene.querySelector('#spot').setAttribute('points','340,10 '+(c.x-40)+','+(c.y+18)+' '+(c.x+40)+','+(c.y+18));
 var s=WF.stages[i];document.getElementById('dot').style.background=s.c;
 document.getElementById('dname').textContent=(i+1)+'. '+s.a;document.getElementById('drole').textContent=s.r;
 document.getElementById('devi').textContent=s.e;
 var log=s.log||'';if(i===8&&WF.prUrl){log=log.replace(WF.prUrl,'<a class="prl" href="'+WF.prUrl+'" target="_blank" rel="noopener">'+WF.prUrl+'</a>');}
 document.getElementById('dlog').innerHTML=log;
 document.getElementById('prog').textContent='stage '+(i+1)+' / 9';}
var cur=WF.current,playing=false,timer=null;build();
document.getElementById('meta').textContent=WF.repo+(WF.issue?(' #'+WF.issue):'')+' · '+WF.id;
var live=document.getElementById('live');live.textContent='● '+WF.state;if(WF.failed)live.className='live fail';
var evc=document.getElementById('ev');(WF.events&&WF.events.length?WF.events:[{t:'note',x:'no events yet'}]).forEach(function(e){var d=document.createElement('div');d.className='ev';d.textContent='['+e.t+'] '+e.x;evc.appendChild(d);});
function stop(){playing=false;if(timer)clearInterval(timer);document.getElementById('play').innerHTML='&#9654; play run';}
document.getElementById('play').addEventListener('click',function(){if(playing){stop();return;}playing=true;this.innerHTML='&#9208; pause';var end=Math.max(WF.current,0);var k=0;focus(0);timer=setInterval(function(){k++;if(k>end)k=0;focus(k);},950);});
document.getElementById('prev').addEventListener('click',function(){stop();focus((cur+8)%9);});
document.getElementById('next').addEventListener('click',function(){stop();focus((cur+1)%9);});
focus(WF.current);
</script></body></html>
"""
