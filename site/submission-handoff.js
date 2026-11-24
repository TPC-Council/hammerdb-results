/* Optional reviewed-result transfer. No credentials, storage or automatic PR. */
(function(root,factory){
  'use strict';const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.HammerDBResultHandoff=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function receive({load,window:win=globalThis,crypto:cryptoAPI=globalThis.crypto,status=()=>{}}){
    const nonce=new URL(win.location.href).searchParams.get('handoff');
    if(!/^[a-f0-9]{64}$/.test(nonce||''))return ()=>{};
    let sender=null,sourceOrigin='',used=false;
    const timer=win.setTimeout(stop,120000);
    function stop(){win.removeEventListener('message',message);win.clearTimeout(timer);}
    function reply(stage,sha256){sender.postMessage({type:'hammerdb-result-handoff',version:1,nonce,stage,...(sha256?{sha256}:{})},sourceOrigin);}
    async function message(event){
      const data=event.data;
      // Any HTTP(S) website or port may send a reviewed draft. The originating
      // site is not an authority for publication: the person must still inspect
      // the form and explicitly submit/authorise a reviewable GitHub PR.
      let parsedOrigin;
      try{parsedOrigin=new URL(event.origin);}catch{return;}
      if((parsedOrigin.protocol!=='https:'&&parsedOrigin.protocol!=='http:')||
          parsedOrigin.origin!==event.origin||!event.source||event.source===win||
          !data||data.type!=='hammerdb-result-handoff'||data.version!==1||data.nonce!==nonce)return;
      // A single sender window AND its actual origin are bound by the handshake.
      if(sender&&(event.source!==sender||event.origin!==sourceOrigin))return;
      if(data.stage==='hello'&&!used){sender=event.source;sourceOrigin=event.origin;reply('ready');return;}
      if(data.stage!=='artifact'||!sender||used)return;
      used=true;
      try{
        if(typeof data.raw!=='string'||new TextEncoder().encode(data.raw).length>2000000||!/^[a-f0-9]{64}$/.test(data.sha256||''))throw Error('Invalid transferred result.');
        const digest=await cryptoAPI.subtle.digest('SHA-256',new TextEncoder().encode(data.raw));
        const hash=[...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
        if(hash!==data.sha256)throw Error('The transferred result checksum does not match.');
        await load(data.raw);
        reply('accepted',hash);status('Reviewed result received','Check the details below, then choose Submit result to authorise your GitHub PR. Nothing has been submitted yet.','success');
      }catch(error){reply('rejected');status('Unable to receive result','The result was not accepted. Check the form validation or select a saved file.','error');}
      finally{stop();}
    }
    win.addEventListener('message',message);return stop;
  }
  return Object.freeze({receive});
});
