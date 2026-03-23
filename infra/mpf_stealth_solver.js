const fs=require('fs'),pup=require('puppeteer-extra'),S=require('puppeteer-extra-plugin-stealth');
pup.use(S());
const os=require('os');
const P=process.argv[2]||require('path').join(os.tmpdir(),'chrome_profile_mpf');
['SingletonLock','SingletonCookie','SingletonSocket'].forEach(l=>{try{fs.unlinkSync(P+'/'+l)}catch{}});
(async()=>{
  process.stderr.write('launch\n');
  const b=await pup.launch({headless:process.platform==='win32'?'new':false,executablePath:process.platform==='win32'?null:'/usr/bin/google-chrome',userDataDir:P,
    args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-first-run','--mute-audio',
          '--password-store=basic','--disable-blink-features=AutomationControlled'],
    ignoreDefaultArgs:['--enable-automation'],defaultViewport:null,ignoreHTTPSErrors:true});
  process.stderr.write('open\n');
  const pg=(await b.pages())[0];
  await pg.goto('https://aplicativos.mpf.mp.br/ouvidoria/app/cidadao/certidao',{waitUntil:'networkidle2',timeout:25000});
  process.stderr.write('loaded\n');
  await pg.evaluate(()=>{document.querySelectorAll('button').forEach(b=>{if(b.textContent?.includes('Emitir'))b.click()})});
  process.stderr.write('clicked\n');
  let tk='';const s=Date.now();
  while(Date.now()-s<15000){
    try{tk=await pg.evaluate(()=>{const i=document.querySelector('input[name="cf-turnstile-response"]');return(i&&i.value?.length>20)?i.value:''})}catch{}
    if(tk)break;await new Promise(r=>setTimeout(r,300));
  }
  await b.close();
  if(tk){process.stderr.write('OK '+tk.length+'ch in '+((Date.now()-s)/1000).toFixed(1)+'s\n');process.stdout.write(tk);process.exit(0)}
  else{process.stderr.write('FAIL after '+((Date.now()-s)/1000).toFixed(1)+'s\n');process.exit(1)}
})().catch(e=>{process.stderr.write('ERR:'+e.message+'\n');process.exit(1)});
