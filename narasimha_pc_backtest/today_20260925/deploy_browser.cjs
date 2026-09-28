// Uses a real user login; never creates or forges an authenticated session.
const {chromium}=require('../../frontend/node_modules/@playwright/test');
const fs=require('fs'),path=require('path');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false});
 const page=await browser.newPage();
 await page.goto('http://127.0.0.1:5000/python');
 console.log('Please log in to OpenAlgo in this browser window.');
 let ready=false;
 for(let i=0;i<1800;i++){
  if(browser.isConnected()===false)throw Error('Browser closed before upload');
  const auth=await page.evaluate(async()=>{try{const r=await fetch('/python/api/strategies');const j=await r.json();return Array.isArray(j.strategies)}catch{return false}});
  if(auth && !ready){console.log('AUTHENTICATED; waiting for verified deployment package.');ready=true;}
  if(auth && fs.existsSync(path.join(__dirname,'READY_TO_UPLOAD.json'))){
   const spec=JSON.parse(fs.readFileSync(path.join(__dirname,'READY_TO_UPLOAD.json')));
   const source=fs.readFileSync(path.join(__dirname,spec.file),'utf8');
   const result=await page.evaluate(async({source,spec})=>{
    const r=await fetch('/auth/csrf-token');const j=await r.json();
    const token=j.csrf_token||j.csrfToken;
    if(!token)throw Error('No CSRF token');
    const f=new FormData(); f.append('strategy_file',new Blob([source],{type:'text/x-python'}),spec.file);
    f.append('strategy_name',spec.name);f.append('exchange','NSE');f.append('schedule_start',spec.start);f.append('schedule_stop',spec.stop);f.append('schedule_days',JSON.stringify(spec.days));
    const response=await fetch('/python/new',{method:'POST',headers:{'X-CSRFToken':token,'X-Requested-With':'XMLHttpRequest'},body:f});
    const result=await response.json();if(!response.ok||result.status!=='success')throw Error(JSON.stringify(result));return result;
   },{source,spec});
   fs.writeFileSync(path.join(__dirname,'deployment.json'),JSON.stringify(result,null,2));
   await page.goto('http://127.0.0.1:5000/python');
   console.log('DEPLOYED '+JSON.stringify(result));
   return;
  }
  await page.waitForTimeout(1000);
 }
 throw Error('Login/package timeout; no upload performed');
})().catch(e=>{console.error(e.message);process.exitCode=1});
