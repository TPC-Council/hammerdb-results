// HammerDB one-click submission service. GitHub App credentials stay server-side.
// A contributor clicks Submit once; the service authenticates with GitHub,
// creates a result branch/file/PR in the target repository, then opens the PR.
const API_ROOT = "https://api.github.com";
const OAUTH_ROOT = "https://github.com";
const GITHUB_HEADERS = {"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"HammerDB-result-submission"};
const MAX_SUBMISSION_BYTES = 2_000_000;
const GH_LOGIN = /^[a-z\d](?:[a-z\d-]{0,37}[a-z\d])?$/i;
const JOB_ID = /^[\w-]{1,128}$/;

class PublicError extends Error {
  constructor(message,status=400){super(message);this.status=status;}
}
const slug = s => String(s||"").toLowerCase().trim().replace(/[^a-z0-9]+/g,"-").replace(/^-|-+$/g,"");
function resultPath(artifact){
  if(!artifact || artifact.schema!=="hammerdb-job-report-v1" ||
      !artifact.job || !artifact.result || typeof artifact.result!=="object")
    throw new PublicError("Not a valid HammerDB result JSON.");
  const j=artifact.job;
  if(!JOB_ID.test(String(j.jobid||"")) ||
     !["TPROC-C","TPROC-H"].includes(j.benchmark) ||
     !j.database || !j.database_display || !j.hdb_version)
    throw new PublicError("The JSON is missing required HammerDB result fields.");
  const date=String(j.timestamp||"").replace("T"," ").match(/^(\d{4})-(\d{2})-\d{2}/);
  if(!date || Number(date[2])<1 || Number(date[2])>12)
    throw new PublicError("The result has an invalid run date.");
  return "results/"+slug(j.benchmark)+"/"+slug(j.database_display||j.database)+
    "/"+date[1]+"/"+date[2]+"/"+j.jobid+".json";
}
function withCors(response,origin){
  const headers=new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin",origin);
  headers.set("Vary","Origin");
  headers.set("Access-Control-Allow-Methods","POST, OPTIONS");
  headers.set("Access-Control-Allow-Headers","Content-Type");
  return new Response(response.body,{status:response.status,headers});
}
function asJSON(data,status=200){
  return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"}});
}
function concatBytes(parts){
  const n=parts.reduce((acc,b)=>acc+b.length,0),out=new Uint8Array(n);
  let offset=0;for(const b of parts){out.set(b,offset);offset+=b.length;}
  return out;
}
function asn1(tag,bytes){
  const len=bytes.length;
  const lengths=len<128?[len]:(()=>{
    const values=[];let current=len;
    while(current>0){values.unshift(current&255);current>>>=8;}
    return [128|values.length,...values];
  })();
  return concatBytes([Uint8Array.from([tag,...lengths]),bytes]);
}
function decodePem(pem){
  const raw=String(pem||"").replace(/\\n/g,"\n");
  const b64=raw.replace(/-----BEGIN [^-]+-----|-----END [^-]+-----|\s+/g,"");
  if(!b64)throw new Error("Missing GitHub App private key");
  const pk=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
  if(raw.includes("BEGIN PRIVATE KEY"))return pk; // PKCS8
  if(!raw.includes("BEGIN RSA PRIVATE KEY"))throw new Error("Unsupported GitHub App private key format");
  // GitHub usually issues PKCS#1 RSA keys. WebCrypto requires PKCS#8.
  const rsaAlgorithm=Uint8Array.from([0x30,0x0d,0x06,0x09,0x2a,0x86,0x48,0x86,
    0xf7,0x0d,0x01,0x01,0x01,0x05,0x00]);
  return asn1(0x30,concatBytes([
    Uint8Array.from([0x02,0x01,0x00]),rsaAlgorithm,asn1(0x04,pk)
  ]));
}
function base64url(bytes){
  let binary="";
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(binary).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
}
const enc=new TextEncoder();
async function appJWT(env){
  const now=Math.floor(Date.now()/1000);
  const header=base64url(enc.encode(JSON.stringify({alg:"RS256",typ:"JWT"})));
  const claims=base64url(enc.encode(JSON.stringify({iat:now-60,exp:now+540,iss:env.GITHUB_APP_CLIENT_ID})));
  const data=header+"."+claims;
  const key=await crypto.subtle.importKey("pkcs8",decodePem(env.GITHUB_APP_PRIVATE_KEY),
    {name:"RSASSA-PKCS1-v1_5",hash:"SHA-256"},false,["sign"]);
  const signature=new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5",key,enc.encode(data)));
  return data+"."+base64url(signature);
}
async function gh(fetchImpl,url,token,options={}){
  const resp=await fetchImpl(url,{
    ...options,headers:{...GITHUB_HEADERS,"Authorization":"Bearer "+token,
      "Content-Type":"application/json",...(options.headers||{})}
  });
  let body={};
  const text=await resp.text();
  try{body=text?JSON.parse(text):{};}catch{body={};}
  if(!resp.ok)throw new PublicError("GitHub rejected the submission ("+resp.status+"): "+
    String(body.message||"Please retry."),resp.status===404?404:502);
  return body;
}
async function installationToken(env,fetchImpl){
  const jwt=await appJWT(env);
  const repo="/repos/"+encodeURIComponent(env.GITHUB_TARGET_OWNER)+"/"+
    encodeURIComponent(env.GITHUB_TARGET_REPO);
  const installation=await gh(fetchImpl,API_ROOT+repo+"/installation",jwt);
  if(!installation.id)throw new Error("GitHub App is not installed on the target repository");
  const token=await gh(fetchImpl,API_ROOT+"/app/installations/"+installation.id+"/access_tokens",
    jwt,{method:"POST",body:JSON.stringify({
      repositories:[env.GITHUB_TARGET_REPO],
      permissions:{contents:"write",pull_requests:"write"}
    })});
  if(!token.token)throw new Error("GitHub App installation did not return an access token");
  return token.token;
}
function errorHtml(title,message,env){
  const safe=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
  const back=env.ALLOWED_ORIGIN+"/hammerdb-results/submit.html";
  return new Response(`<!doctype html><html lang="en"><meta charset="utf-8">
    <title>${safe(title)} - HammerDB</title><body style="font:18px system-ui;max-width:50rem;margin:5rem auto;padding:1rem">
    <h1>${safe(title)}</h1><p>${safe(message)}</p>
    <p><a href="${safe(back)}">Return to HammerDB submission form</a></p></body></html>`,
    {status:400,headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store"}});
}
async function oauthCallback(request,env,fetchImpl){
  const url=new URL(request.url);
  const state=url.searchParams.get("state")||"",code=url.searchParams.get("code")||"";
  if(!/^[0-9a-f-]{36}$/.test(state)||!code)
    return errorHtml("GitHub authorization incomplete","No result was submitted.",env);
  const saved=await env.PENDING.get("submission:"+state);
  if(!saved)return errorHtml("Submission expired",
    "Please return to the form and submit again. No results were changed.",env);
  const {artifact,target,path}=JSON.parse(saved);
  if(target!==env.GITHUB_TARGET_OWNER+"/"+env.GITHUB_TARGET_REPO ||
     path!==resultPath(artifact))
    return errorHtml("Invalid submission","The result could not be verified.",env);
  const callbackUrl=new URL("/oauth/callback",request.url).toString();
  try{
    const exchange=await fetchImpl(OAUTH_ROOT+"/login/oauth/access_token",{
      method:"POST",headers:{"Accept":"application/json","Content-Type":"application/json"},
      body:JSON.stringify({client_id:env.GITHUB_APP_CLIENT_ID,
        client_secret:env.GITHUB_APP_CLIENT_SECRET,code,redirect_uri:callbackUrl})
    });
    const tokens=await exchange.json();
    if(!exchange.ok||!tokens.access_token)
      throw new PublicError("GitHub sign-in could not be completed.");
    const user=await gh(fetchImpl,API_ROOT+"/user",tokens.access_token);
    if(!GH_LOGIN.test(user.login||""))throw new PublicError("Invalid GitHub account.");
    const typed=String(artifact.submission?.github_username||"");
    if(typed.toLowerCase()!==user.login.toLowerCase())
      throw new PublicError("You signed into GitHub as @"+user.login+
        ", but the form specifies @"+typed+". Please use the same account.");
    // Identity comes from GitHub, never from user-edited JSON.
    artifact.submission={...(artifact.submission||{}),github_username:user.login};
    const repo="/repos/"+encodeURIComponent(env.GITHUB_TARGET_OWNER)+"/"+
      encodeURIComponent(env.GITHUB_TARGET_REPO);
    const token=await installationToken(env,fetchImpl);
    const encodedPath=path.split("/").map(encodeURIComponent).join("/");
    const existing=await fetchImpl(API_ROOT+repo+"/contents/"+encodedPath+"?ref=main",{
      headers:{...GITHUB_HEADERS,Authorization:"Bearer "+token}
    });
    if(existing.status!==404){
      if(existing.ok)throw new PublicError("This benchmark result was already submitted.");
      throw new PublicError("GitHub could not check for duplicate results.");
    }
    const base=await gh(fetchImpl,API_ROOT+repo+"/git/ref/heads/main",token);
    const sha=base.object?.sha;
    if(!sha)throw new Error("No main branch SHA was returned");
    const branch="submission/"+String(artifact.job.jobid).toLowerCase().slice(0,35)+
      "-"+state.slice(0,8);
    await gh(fetchImpl,API_ROOT+repo+"/git/refs",token,{
      method:"POST",body:JSON.stringify({ref:"refs/heads/"+branch,sha})
    });
    const raw=enc.encode(JSON.stringify(artifact,null,2));
    let binary="";
    for(let i=0;i<raw.length;i+=8192)binary+=String.fromCharCode(...raw.subarray(i,i+8192));
    await gh(fetchImpl,API_ROOT+repo+"/contents/"+encodedPath,token,{
      method:"PUT",body:JSON.stringify({message:"Submit benchmark result "+artifact.job.jobid,
        content:btoa(binary),branch})
    });
    const prs=await gh(fetchImpl,API_ROOT+repo+"/pulls",token,{
      method:"POST",body:JSON.stringify({
        title:"TPC-Council HammerDB: "+artifact.job.benchmark+" "+artifact.job.database_display+
          " result "+artifact.job.jobid,
        body:"HammerDB result submission to TPC-Council, authorised using the HammerDB GitHub App.\n\n"+
          "Job ID: "+artifact.job.jobid+"\nResult file: "+path+
          "\n\nCommunity-submitted, unaudited result. Review before merging.",
        head:branch,base:"main",draft:false,maintainer_can_modify:true
      })
    });
    if(!/^https:\/\/github\.com\//.test(prs.html_url||""))
      throw new Error("GitHub did not provide a pull request URL");
    await env.PENDING.delete("submission:"+state);
    return Response.redirect(prs.html_url,303);
  }catch(error){
    return errorHtml("Could not create the pull request",
      error instanceof PublicError ? error.message :
        "The GitHub submission service encountered an error. No result has been approved.",env);
  }
}
async function submit(request,env){
  const origin=request.headers.get("Origin");
  if(!origin || origin!==env.ALLOWED_ORIGIN)
    return asJSON({error:"This submission must come from the HammerDB result form."},403);
  if(!/application\/json/i.test(request.headers.get("Content-Type")||""))
    return withCors(asJSON({error:"Expected JSON."},415),origin);
  try{
    const raw=await request.text();
    if(enc.encode(raw).byteLength>MAX_SUBMISSION_BYTES)
      throw new PublicError("This result is too large (maximum 2 MB).",413);
    const payload=JSON.parse(raw),artifact=payload?.artifact;
    if(payload?.target!==env.GITHUB_TARGET_OWNER+"/"+env.GITHUB_TARGET_REPO)
      throw new PublicError("The form is pointing to a different repository.");
    const path=resultPath(artifact);
    if(!GH_LOGIN.test(artifact.submission?.github_username||""))
      throw new PublicError("Enter your GitHub username on the submission form.");
    if(!env.GITHUB_APP_CLIENT_ID||!env.GITHUB_APP_CLIENT_SECRET||
       !env.GITHUB_APP_PRIVATE_KEY||!env.PENDING)
      throw new PublicError("Submission service is not configured.",503);
    const state=crypto.randomUUID();
    await env.PENDING.put("submission:"+state,
      JSON.stringify({artifact,path,target:payload.target}),{expirationTtl:900});
    const callbackUrl=new URL("/oauth/callback",request.url);
    const authorize=new URL(OAUTH_ROOT+"/login/oauth/authorize");
    authorize.searchParams.set("client_id",env.GITHUB_APP_CLIENT_ID);
    authorize.searchParams.set("redirect_uri",callbackUrl.toString());
    authorize.searchParams.set("state",state);
    return withCors(asJSON({authorizeUrl:authorize.toString()}),origin);
  }catch(error){
    return withCors(asJSON({error:error instanceof PublicError?
      error.message:"Invalid submission JSON."},
      error instanceof PublicError?error.status:400),origin);
  }
}
export async function handleRequest(request,env,fetchImpl=fetch){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/health"){
    const result=asJSON({status:"ok",configured:Boolean(env.PENDING&&
      env.GITHUB_APP_CLIENT_ID&&env.GITHUB_APP_CLIENT_SECRET&&env.GITHUB_APP_PRIVATE_KEY)});
    const origin=request.headers.get("Origin");
    return origin===env.ALLOWED_ORIGIN?withCors(result,origin):result;
  }
  if(url.pathname==="/oauth/callback"&&request.method==="GET")
    return oauthCallback(request,env,fetchImpl);
  if(url.pathname==="/submissions"&&request.method==="OPTIONS"){
    const origin=request.headers.get("Origin");
    if(origin!==env.ALLOWED_ORIGIN)return new Response(null,{status:403});
    return withCors(new Response(null,{status:204}),origin);
  }
  if(url.pathname==="/submissions"&&request.method==="POST")return submit(request,env);
  return asJSON({error:"Not found"},404);
}
export default {fetch(request,env){return handleRequest(request,env);}};
