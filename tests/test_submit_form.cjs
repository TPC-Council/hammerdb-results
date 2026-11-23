"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const html=fs.readFileSync(path.join(__dirname,"../site/submit.html"),"utf8");
const config=fs.readFileSync(path.join(__dirname,"../site/submission-service-config.js"),"utf8");
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
const script=scripts.at(-1)[1];
class Element {
  constructor(id){this.id=id;this.value="";this.textContent="";this.hidden=false;
    this.disabled=false;this.className="";this.style={};this.dataset={};this.events=new Map();
    this.tagName=["workload-class","uaw-setting","durability-setting","theme-select"].includes(id)?"SELECT":"DIV";
    this.classList={add(){},remove(){}};
    if(this.tagName==="SELECT")this.selectedIndex=0;
  }
  set selectedIndex(n){this._selected=n;
    this.value={"workload-class":"unclassified","uaw-setting":"unknown",
      "durability-setting":"unknown","theme-select":"system"}[this.id]||"";}
  get selectedIndex(){return this._selected||0;}
  addEventListener(kind,fn){const rows=this.events.get(kind)||[];rows.push(fn);this.events.set(kind,rows);}
  append(){}
  replaceChildren(){}
  querySelector(name){this._children ||=new Map();if(!this._children.has(name))
    this._children.set(name,new Element(name));return this._children.get(name);}
}
const sample={
  schema:"hammerdb-job-report-v1",
  job:{jobid:"FAKEABC123",benchmark:"TPROC-C",database:"MariaDB",
    database_display:"MariaDB",timestamp:"2026-11-13 12:00:00",hdb_version:"v6.0",
    release:"12.3"},
  result:{nopm:800000,tpm:1500000},benchmark_config:{warehouses:1000,virtual_users:32}
};
async function mount({api="https://submissions.example.workers.dev",
  oauth="https://github.com/login/oauth/authorize?client_id=test&state=123",
  failService=false,preload=true,clipboardBlocked=false}={}){
  const elements=new Map(),requests=[],navigations=[],pageEvents=new Map(),openedTabs=[],clipboardWrites=[];
  const get=id=>{
    if(!elements.has(id))elements.set(id,new Element(id));
    return elements.get(id);
  };
  for(const id of ["details-section","workload-section","submit-section","preview","manual-pr-actions"])get(id).hidden=true;
  const document={
    documentElement:{dataset:{}},getElementById:get,
    createElement:tag=>new Element(tag),
    querySelector:sel=>get(sel),
    body:{appendChild(){}},
  };
  const fakeUrl="https://example.com/result.json";
  let handoffHandler;
  const location={search:preload?"?artifact_url="+encodeURIComponent(fakeUrl):""};
  const window={
    HammerDBResultsRepo:{owner:"TPC-Council",repo:"hammerdb-results",branch:"main"},
    HammerDBSubmissionAPI:{endpoint:api},location:{assign(url){navigations.push(url)}},
    HammerDBResultHandoff:{receive(options){handoffHandler=options;}},
    open(url,target,features){openedTabs.push({url,target,features});},
    addEventListener(name,callback){const list=pageEvents.get(name)||[];list.push(callback);pageEvents.set(name,list);},
    matchMedia(){return {matches:false,addEventListener(){}}}
  };
  const fetch=async(url,opts={})=>{
    const value=String(url);requests.push({url:value,opts});
    if(value===fakeUrl)return {ok:true,status:200,text:async()=>JSON.stringify(sample)};
    if(value.startsWith("https://raw.githubusercontent.com/"))return {ok:false,status:404};
    if(value===api+"/submissions"){
      if(failService)return {ok:false,status:503,json:async()=>({error:"Service offline"})};
      return {ok:true,status:200,json:async()=>({authorizeUrl:oauth})};
    }
    throw Error("Unexpected request "+value);
  };
  const localStorage={getItem(){return null},setItem(){},removeItem(){}};
  const navigator={clipboard:{async writeText(json){
    if(clipboardBlocked)throw Error("Clipboard blocked");
    clipboardWrites.push(json);
  }}};
  vm.runInNewContext(script,{document,window,location,URL,URLSearchParams,
    fetch,localStorage,navigator,console,encodeURIComponent,setTimeout},
    {filename:"site/submit.html"});
  for(let i=0;i<5;i++)await new Promise(setImmediate);
  async function submit(login="ls250"){
    get("github-username").value=login;
    for(const callback of get("continue-github").events.get("click")||[])
      await callback();
    await new Promise(setImmediate);
  }
  async function click(id){
    const handlers=get(id).events.get("click")||[];
    assert.ok(handlers.length,"No handler for "+id);
    for(const fn of handlers)await fn();
    await new Promise(setImmediate);
  }
  return {get,requests,navigations,openedTabs,clipboardWrites,submit,click,
    receive(raw){return handoffHandler.load(raw);},
    pageShow(){for(const callback of pageEvents.get("pageshow")||[])callback();}
  };
}

test("one submission form offers automatic PR and expert manual PR",()=>{
  assert.match(html,/id="continue-github">Submit result/);
  assert.match(html,/id="pr-auto"[^>]*checked/);
  assert.match(html,/id="pr-manual"/);
  assert.match(html,/I'll create my own PR/);
  assert.match(html,/id="copy-json">Copy enriched JSON/);
  assert.match(html,/id="manual-continue-github">Continue to GitHub/);
  assert.doesNotMatch(html,/id="fork-repository"|id="open-fork-page"/);
  assert.match(script,/navigator\.clipboard\.writeText\(json\)/);
  assert.match(script,/window\.open\(url, "_blank", "noopener"\)/);
  assert.doesNotMatch(script,/submit-manual\.html|resolveFork\(/);
  assert.match(html,/Select your result artifact/);
  assert.match(html,/Who is submitting this result/);
});

test("TPCI baseline still validates artifact and requires benchmark details",()=>{
  assert.match(script,/buildSubmission\(\)/);
  assert.match(script,/artifactPath\(job\)/);
  assert.match(script,/workload\.classification/);
  assert.match(script,/existsInRepo\(path\)/);
});

test("one click POSTs result and then opens only GitHub authorization",async()=>{
  const p=await mount();
  assert.equal(p.get("submit-section").hidden,false);
  await p.submit();
  const post=p.requests.find(q=>q.url.includes("/submissions"));
  assert.ok(post);
  assert.equal(post.opts.method,"POST");
  const request=JSON.parse(post.opts.body);
  assert.equal(request.target,"TPC-Council/hammerdb-results");
  assert.deepEqual(JSON.parse(JSON.stringify(request.artifact.job)),sample.job);
  assert.equal(request.artifact.submission.github_username,"ls250");
  assert.equal(p.navigations.length,1);
  assert.match(p.navigations[0],/^https:\/\/github\.com\/login\/oauth\/authorize/);
  assert.equal(p.get("continue-github").disabled,true);
});

test("unconfigured endpoint is a clear error, never a fallback fork link",async()=>{
  const p=await mount({api:""});
  await p.submit();
  assert.equal(p.requests.some(q=>q.url.includes("/submissions")),false);
  assert.equal(p.navigations.length,0);
  assert.match(p.get("status").querySelector("strong").textContent,/not configured/);
});

test("service outage retains the completed form",async()=>{
  const p=await mount({failService:true});
  await p.submit();
  assert.equal(p.navigations.length,0);
  assert.equal(p.get("continue-github").disabled,false);
  assert.equal(p.get("submit-section").hidden,false);
  assert.match(p.get("status").querySelector("p").textContent,/Service offline/);
});

test("normal refresh starts empty and does not load a saved JSON",async()=>{
  const p=await mount({preload:false});
  assert.equal(p.get("preview").hidden,true);
  assert.equal(p.get("submit-section").hidden,true);
  assert.equal(p.requests.length,0);
  assert.doesNotMatch(script,/restoreDraft|localStorage\.setItem\(.*submission/);
});

test("the TPC-Council form has a deliberate automatic-service approval gate",()=>{
  assert.match(config,/endpoint:\s*""/,"TPC production must not use the HammerDB Ltd Worker");
  assert.doesNotMatch(config,/ghp_|ghs_|BEGIN RSA PRIVATE KEY|client_secret\s*:/);
  assert.match(html,/submission-service-config\.js/);
});


test("manual choice does exactly the TPC-Council copy JSON + GitHub editor flow",async()=>{
  const p=await mount();
  p.get("github-username").value="sm-shaw";
  p.get("pr-manual").checked=true;
  p.get("pr-auto").checked=false;
  for(const change of p.get("pr-manual").events.get("change")||[])change();
  assert.equal(p.get("auto-pr-actions").hidden,true);
  assert.equal(p.get("manual-pr-actions").hidden,false);
  await p.click("copy-json");
  assert.equal(p.clipboardWrites.length,1);
  const enriched=JSON.parse(p.clipboardWrites[0]);
  assert.equal(enriched.submission.github_username,"sm-shaw");
  assert.deepEqual(JSON.parse(JSON.stringify(enriched.job)),sample.job);
  assert.deepEqual(JSON.parse(JSON.stringify(enriched.result)),sample.result);
  assert.match(p.get("status").querySelector("strong").textContent,/JSON copied/);
  await p.click("manual-continue-github");
  assert.equal(p.clipboardWrites.length,2,"Continue to GitHub copies the same JSON again");
  assert.equal(p.clipboardWrites[0],p.clipboardWrites[1]);
  assert.equal(p.openedTabs.length,1);
  assert.equal(p.openedTabs[0].url,
    "https://github.com/TPC-Council/hammerdb-results/new/main?filename="+
    encodeURIComponent("results/tproc-c/mariadb/2026/11/FAKEABC123.json"));
  assert.equal(p.openedTabs[0].target,"_blank");
  assert.equal(p.openedTabs[0].features,"noopener");
  assert.equal(p.navigations.length,0,"Manual choice must not start OAuth");
  assert.equal(p.requests.some(r=>r.url.endsWith("/submissions")),false);
  assert.match(p.get("status").querySelector("p").textContent,/paste the generated JSON into the editor/i);
});

test("manual copy failure exposes JSON preview, same as TPC-Council",async()=>{
  const p=await mount({clipboardBlocked:true});
  p.get("github-username").value="sm-shaw";
  p.get("pr-manual").checked=true;
  for(const change of p.get("pr-manual").events.get("change")||[])change();
  await p.click("copy-json");
  assert.equal(p.get(".raw-preview").open,true);
  assert.match(p.get("status").querySelector("strong").textContent,/Clipboard unavailable/);
  assert.equal(p.openedTabs.length,0);
  await p.click("manual-continue-github");
  assert.equal(p.openedTabs.length,1);
  assert.equal(p.get(".raw-preview").open,true);
});

test("returning from GitHub OAuth unlocks the automatic button and keeps manual choice working",async()=>{
  const p=await mount();
  await p.submit("ls250");
  assert.equal(p.get("continue-github").disabled,true);
  assert.equal(p.navigations.length,1);
  p.pageShow();
  assert.equal(p.get("continue-github").disabled,false);
  assert.equal(p.get("submit-section").hidden,false);
  assert.equal(p.get("github-username").value,"ls250");
  p.get("pr-manual").checked=true;
  for(const cb of p.get("pr-manual").events.get("change")||[])cb();
  assert.equal(p.get("auto-pr-actions").hidden,true);
  assert.equal(p.get("manual-pr-actions").hidden,false);
  await p.click("manual-continue-github");
  assert.equal(p.openedTabs.length,1);
  assert.equal(p.navigations.length,1,"Manual route does not perform another OAuth");
  assert.equal(p.requests.filter(r=>r.url.endsWith("/submissions")).length,1);
});

test("switching from automatic to manual PR unlocks an OAuth-disabled button",async()=>{
  const p=await mount();
  await p.submit("ls250");
  assert.equal(p.get("continue-github").disabled,true);
  p.get("pr-manual").checked=true;
  for(const cb of p.get("pr-manual").events.get("change")||[])cb();
  assert.equal(p.get("continue-github").disabled,false);
  assert.equal(p.get("manual-pr-actions").hidden,false);
  assert.equal(p.get("auto-pr-actions").hidden,true);
});

test('loaded results offer an optional replacement rather than asking for the file again',async()=>{
  const p=await mount();
  assert.equal(p.get('artifact-load-title').textContent,'Result loaded');
  assert.equal(p.get('choose-file').textContent,'Choose a different result');
  assert.match(p.get('artifact-load-hint').textContent,/FAKEABC123/);
});

test('direct transfer fills the form without posting and respects the configured submission route',async()=>{
  for(const api of ['https://submissions.example.workers.dev','']){
    const p=await mount({api,preload:false});
    await p.receive(JSON.stringify(sample));
    assert.equal(p.get('artifact-load-title').textContent,'Result received from HammerDB');
    assert.equal(p.get('choose-file').textContent,'Choose a different result');
    assert.equal(p.get('pr-auto').checked,Boolean(api));
    assert.equal(p.get('pr-manual').checked,!api);
    assert.equal(p.requests.some(r=>r.opts.method==='POST'),false);
    assert.deepEqual(p.navigations,[]);assert.deepEqual(p.openedTabs,[]);
  }
});

test('direct transfer preserves an administrator-disabled automatic route',async()=>{
  const p=await mount({preload:false});p.get('pr-auto').disabled=true;
  await p.receive(JSON.stringify(sample));
  assert.equal(p.get('pr-auto').checked,false);assert.equal(p.get('pr-manual').checked,true);
  assert.equal(p.requests.some(r=>r.opts.method==='POST'),false);
});

// Reviewed-result browser handoff security checks run in the existing CI suite.
{
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{createHash}=require('node:crypto');
const receiver=require('../site/submission-handoff.js');
function fixture(origin='http://localhost:18093'){
 const nonce='b'.repeat(64),raw='{"result":{"nopm":1234.5}}',hash=createHash('sha256').update(raw).digest('hex');
 const events=new Map(),replies=[],loads=[],timers=new Map();let timeout=0;
 const source={postMessage:(message,origin)=>replies.push({message,origin})};
 const win={location:{href:'https://tpc-council.github.io/hammerdb-results/submit.html?handoff='+nonce},addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name),setTimeout:fn=>{timers.set(++timeout,fn);return timeout;},clearTimeout:id=>timers.delete(id)};
 const stop=receiver.receive({window:win,allowedOrigins:[origin],crypto:globalThis.crypto,load:async text=>loads.push(text)});
 const send=async(stage,extra={})=>events.get('message')?.({origin,source,data:{type:'hammerdb-result-handoff',version:1,nonce,stage,raw,sha256:hash},...extra});
 return {win,source,raw,hash,replies,loads,events,timers,stop,send,nonce};
}
test('receiver accepts one checked exact-text draft and never submits it',async()=>{
 const f=fixture();await f.send('artifact');assert.equal(f.loads.length,0);
 await f.send('hello');assert.equal(f.replies[0].message.stage,'ready');assert.equal(f.replies[0].origin,'http://localhost:18093');
 await f.send('artifact');assert.deepEqual(f.loads,[f.raw]);assert.equal(f.replies.at(-1).message.stage,'accepted');assert.equal(f.replies.at(-1).message.sha256,f.hash);assert.equal(f.events.size,0);
});
test('AWS SSH test origins accept reviewed drafts with the same checks',async()=>{
 for(const origin of ['http://localhost:18194','http://127.0.0.1:18194']){
  const f=fixture(origin);await f.send('hello');await f.send('artifact');
  assert.deepEqual(f.loads,[f.raw]);assert.equal(f.replies.at(-1).origin,origin);
 }
});

test('wrong origins, token, window and checksum cannot load a result',async()=>{
 const f=fixture();await f.send('hello',{origin:'https://wrong.example'});await f.send('hello',{data:{type:'hammerdb-result-handoff',version:1,nonce:'wrong',stage:'hello'}});assert.equal(f.replies.length,0);
 await f.send('hello');await f.send('artifact',{source:{postMessage(){throw Error('Wrong source');}}});assert.equal(f.loads.length,0);
 await f.send('artifact',{data:{type:'hammerdb-result-handoff',version:1,nonce:f.nonce,stage:'artifact',raw:f.raw,sha256:'a'.repeat(64)}});assert.equal(f.loads.length,0);assert.equal(f.replies.at(-1).message.stage,'rejected');
});
test('expired or unconfigured handoffs do not load drafts',async()=>{
 const f=fixture();for(const fn of f.timers.values())fn();assert.equal(f.events.size,0);
 const g=fixture();g.stop();receiver.receive({window:g.win,allowedOrigins:[],load:()=>{throw Error('Unconfigured origins must not load');}});await g.send('hello');assert.equal(g.replies.length,0);g.stop();
});

}

test("before TPC administrator approval the manual PR workflow is default and available",async()=>{
  const p=await mount({api:"",preload:false});
  assert.equal(p.get("pr-auto").disabled,true);
  assert.equal(p.get("pr-auto").checked,false);
  assert.equal(p.get("pr-manual").checked,true);
  assert.equal(p.get("manual-pr-actions").hidden,false);
  assert.equal(p.get("auto-pr-actions").hidden,true);
  assert.match(p.get("pr-mode-description").textContent,/TPC-Council administrator approval/);
  assert.equal(p.requests.some(x=>x.opts.method==="POST"),false);
});
test("TPC form links only to Council and never posts to the HammerDB Ltd target",async()=>{
  const p=await mount({api:"https://tpc-only.example.workers.dev"});
  await p.submit("ls250");
  const post=p.requests.find(x=>x.opts.method==="POST"&&x.url.endsWith("/submissions"));
  assert.ok(post);
  assert.equal(JSON.parse(post.opts.body).target,"TPC-Council/hammerdb-results");
  assert.match(html,/href="https:\/\/github\.com\/TPC-Council\/hammerdb-results"/);
  assert.doesNotMatch(config,/endpoint:\s*"https:\/\/hammerdb-results-submit\.hammerdb\.workers\.dev"/);
});
