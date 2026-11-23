import {test} from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync,webcrypto} from "node:crypto";
import {handleRequest} from "./worker.mjs";

if(!globalThis.crypto)globalThis.crypto=webcrypto;
const keys=generateKeyPairSync("rsa",{modulusLength:2048,
  privateKeyEncoding:{type:"pkcs1",format:"pem"},
  publicKeyEncoding:{type:"spki",format:"pem"}});
const artifact={
  schema:"hammerdb-job-report-v1",
  job:{jobid:"FAKEABC123",benchmark:"TPROC-C",database:"MariaDB",
    database_display:"MariaDB",timestamp:"2026-11-13 12:30:00",hdb_version:"v6.0"},
  result:{nopm:800000,tpm:1500000},
  benchmark_config:{warehouses:1000,virtual_users:24},
  submission:{github_username:"ls250",company:{name:"Test",logo_url:"",description:""}}
};
function setup({login="ls250",duplicate=false,configured=true,origin="https://tpc-council.github.io"}={}){
  const saved=new Map(),requests=[];
  const PENDING={
    async get(key){return saved.get(key)||null},
    async put(key,value){saved.set(key,value)},
    async delete(key){saved.delete(key)}
  };
  const env={PENDING,ALLOWED_ORIGIN:"https://tpc-council.github.io",
    GITHUB_TARGET_OWNER:"TPC-Council",GITHUB_TARGET_REPO:"hammerdb-results",
    GITHUB_APP_CLIENT_ID:configured?"client-id":"",
    GITHUB_APP_CLIENT_SECRET:configured?"client-secret":"",
    GITHUB_APP_PRIVATE_KEY:configured?keys.privateKey:""
  };
  const resp=(value,status=200)=>new Response(JSON.stringify(value),{
    status,headers:{"Content-Type":"application/json"}
  });
  async function fetchImpl(url,opts={}){
    const u=new URL(String(url));
    const method=opts.method||"GET";
    requests.push({url:String(url),method,body:opts.body||null,headers:opts.headers||{}});
    if(u.hostname==="github.com"&&u.pathname==="/login/oauth/access_token")
      return resp({access_token:"github-user-token"});
    if(u.pathname==="/user")return resp({login});
    if(u.pathname.endsWith("/installation"))return resp({id:999});
    if(u.pathname.endsWith("/access_tokens"))return resp({token:"installation-token"});
    if(u.pathname.includes("/contents/")&&method==="GET")
      return resp(duplicate?{name:"FAKEABC123.json"}:{message:"Not Found"},duplicate?200:404);
    if(u.pathname.endsWith("/git/ref/heads/main"))
      return resp({ref:"refs/heads/main",object:{sha:"aa".repeat(20)}});
    if(u.pathname.endsWith("/git/refs")&&method==="POST")
      return resp({ref:"refs/heads/submission/..."},201);
    if(u.pathname.includes("/contents/")&&method==="PUT")
      return resp({content:{name:"FAKEABC123.json"}},201);
    if(u.pathname.endsWith("/pulls")&&method==="POST")
      return resp({html_url:"https://github.com/TPC-Council/hammerdb-results/pull/123"},201);
    throw Error("Unexpected GitHub request: "+method+" "+url);
  }
  async function start(data=artifact,target="TPC-Council/hammerdb-results"){
    const response=await handleRequest(new Request("https://submissions.example.workers.dev/submissions",{
      method:"POST",headers:{"Content-Type":"application/json","Origin":origin},
      body:JSON.stringify({artifact:data,target})
    }),env,fetchImpl);
    return response;
  }
  async function callback(authUrl){
    const oauth=new URL(authUrl),state=oauth.searchParams.get("state");
    return handleRequest(new Request(
      "https://submissions.example.workers.dev/oauth/callback?state="+state+"&code=test-code"
    ),env,fetchImpl);
  }
  return {env,saved,requests,start,callback,fetchImpl};
}

test("one Submit click stages JSON and produces a GitHub OAuth hand-off",async()=>{
  const p=setup();
  const response=await p.start();
  assert.equal(response.status,200);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"),p.env.ALLOWED_ORIGIN);
  const data=await response.json();
  const url=new URL(data.authorizeUrl);
  assert.equal(url.origin,"https://github.com");
  assert.equal(url.pathname,"/login/oauth/authorize");
  assert.equal(url.searchParams.get("client_id"),"client-id");
  assert.ok(p.saved.has("submission:"+url.searchParams.get("state")));
  assert.equal(p.requests.length,0,"Do not require contributor fork/write access");
});

test("GitHub auth generates same-repo result branch, content, and ready-to-review PR",async()=>{
  const p=setup();
  const start=await p.start();
  const {authorizeUrl}=await start.json();
  const result=await p.callback(authorizeUrl);
  assert.equal(result.status,303);
  assert.equal(result.headers.get("Location"),
    "https://github.com/TPC-Council/hammerdb-results/pull/123");
  const branch=p.requests.find(x=>x.url.endsWith("/git/refs")&&x.method==="POST");
  const body=JSON.parse(branch.body);
  assert.match(body.ref,/^refs\/heads\/submission\/fakeabc123-/);
  const wrote=p.requests.find(x=>x.method==="PUT");
  assert.match(wrote.url,/\/results\/tproc-c\/mariadb\/2026\/11\/FAKEABC123\.json$/);
  const stored=JSON.parse(atob(JSON.parse(wrote.body).content));
  assert.equal(stored.submission.github_username,"ls250");
  assert.deepEqual(stored.result,artifact.result);
  assert.equal(p.requests.some(r=>r.url.includes("/forks")),false,"Never ask a user to fork");
  assert.equal(p.requests.filter(r=>r.method==="POST"&&r.url.endsWith("/pulls")).length,1);
  const submittedPR=JSON.parse(p.requests.find(r=>r.method==="POST"&&r.url.endsWith("/pulls")).body);
  assert.match(submittedPR.body,/^HammerDB result submission to TPC-Council, authorised using the HammerDB GitHub App\./);
  assert.ok(submittedPR.body.includes("\n\nJob ID: FAKEABC123\nResult file: "));
  assert.equal(submittedPR.body.includes("\\n"),false,"PR description must use real newlines");
  assert.equal(submittedPR.body.includes("@ls250"),false,"Verified contributor belongs in JSON, not PR heading");
  assert.equal(p.saved.size,0,"Pending submission must not persist after successful PR");
});

test("different GitHub login blocks changes and explains account mismatch",async()=>{
  const p=setup({login:"sm-shaw"});
  const {authorizeUrl}=await (await p.start()).json();
  const r=await p.callback(authorizeUrl);
  assert.equal(r.status,400);
  assert.match(await r.text(),/signed into GitHub as @sm-shaw/);
  assert.equal(p.requests.some(q=>q.method==="PUT"),false);
});

test("duplicate results never create branches or PRs",async()=>{
  const p=setup({duplicate:true});
  const {authorizeUrl}=await (await p.start()).json();
  const r=await p.callback(authorizeUrl);
  assert.equal(r.status,400);
  assert.match(await r.text(),/already submitted/);
  assert.equal(p.requests.some(q=>q.method==="PUT"||q.url.endsWith("/git/refs")),false);
});

test("wrong target is rejected before storing data",async()=>{
  const p=setup();
  const r=await p.start(artifact,"HammerDBLtd/hammerdb-results");
  assert.equal(r.status,400);
  assert.match((await r.json()).error,/different repository/);
  assert.equal(p.saved.size,0);
});

test("external-origin browser POST is rejected",async()=>{
  const p=setup({origin:"https://evil.example"});
  const r=await p.start();
  assert.equal(r.status,403);
  assert.equal(p.saved.size,0);
});

test("malformed job paths and report schemas never start OAuth",async()=>{
  const p=setup();
  const bad=structuredClone(artifact);
  bad.job.jobid="../other";
  let r=await p.start(bad);
  assert.equal(r.status,400);
  bad.job.jobid="FAKEABC123";
  bad.schema="unexpected-schema";
  r=await p.start(bad);
  assert.equal(r.status,400);
  assert.equal(p.saved.size,0);
});

test("service rejects submission before credentials are configured",async()=>{
  const p=setup({configured:false});
  const r=await p.start();
  assert.equal(r.status,503);
  assert.equal(p.saved.size,0);
});

test("unknown OAuth state cannot create a PR",async()=>{
  const p=setup();
  const r=await handleRequest(new Request(
    "https://submissions.example.workers.dev/oauth/callback?state="+crypto.randomUUID()+"&code=test"
  ),p.env,p.fetchImpl);
  assert.equal(r.status,400);
  assert.equal(p.requests.length,0);
});

test("preflight limits cross-origin access",async()=>{
  const p=setup();
  const ok=await handleRequest(new Request(
    "https://submissions.example.workers.dev/submissions",
    {method:"OPTIONS",headers:{Origin:p.env.ALLOWED_ORIGIN}}
  ),p.env,p.fetchImpl);
  assert.equal(ok.status,204);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"),p.env.ALLOWED_ORIGIN);
  const denied=await handleRequest(new Request(
    "https://submissions.example.workers.dev/submissions",
    {method:"OPTIONS",headers:{Origin:"https://other.example"}}
  ),p.env,p.fetchImpl);
  assert.equal(denied.status,403);
});

test("readiness is visible only to the official TPC-Council submission site",async()=>{
  const p=setup();
  const url="https://submissions.example.workers.dev/health";
  const official=await handleRequest(new Request(url,{
    headers:{Origin:"https://tpc-council.github.io"}
  }),p.env,p.fetchImpl);
  assert.equal(official.status,200);
  assert.equal(official.headers.get("Access-Control-Allow-Origin"),p.env.ALLOWED_ORIGIN);
  assert.deepEqual(await official.json(),{status:"ok",configured:true});
  const external=await handleRequest(new Request(url,{
    headers:{Origin:"https://unrelated.example"}
  }),p.env,p.fetchImpl);
  assert.equal(external.headers.has("Access-Control-Allow-Origin"),false);
  const unavailable=setup({configured:false});
  const off=await handleRequest(new Request(url,{
    headers:{Origin:"https://tpc-council.github.io"}
  }),unavailable.env,unavailable.fetchImpl);
  assert.equal((await off.json()).configured,false);
});
