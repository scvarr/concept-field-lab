/* Verify the documented Windows cmd.exe entrypoint in an isolated database. */
const {spawn,execFile}=require('node:child_process');
const fs=require('node:fs/promises');
const path=require('node:path');
const root=path.resolve(__dirname,'..'),port=8877;
(async()=>{
  const folder=path.join(root,'test-output',`cmd smoke ${Date.now()}`);await fs.mkdir(folder,{recursive:true});
  const db=path.join(folder,'workspace.sqlite3');
  const child=spawn('cmd.exe',['/d','/s','/c',`start.cmd --no-browser --port ${port} --db "${db}"`],{cwd:root,windowsHide:true,windowsVerbatimArguments:true,env:{...process.env,PYTHONUTF8:'1'}});
  let output='';child.stdout.on('data',c=>output+=c);child.stderr.on('data',c=>output+=c);
  try{
    for(let i=0;i<100&&!output.includes(`http://127.0.0.1:${port}`);i++){if(child.exitCode!==null)throw Error('start.cmd exited early: '+output);await new Promise(r=>setTimeout(r,100));}
    if(!output.includes(`http://127.0.0.1:${port}`))throw Error('start.cmd timed out: '+output);
    const response=await fetch(`http://127.0.0.1:${port}/api/state`),state=await response.json();
    if(!response.ok||state.revision!==0||state.state.studies.length)throw Error('Unexpected cmd.exe startup state');
    await fs.writeFile(path.join(root,'test-output','cmd-report.json'),JSON.stringify({result:'passed',command:'start.cmd --no-browser --port 8877 --db <isolated project test directory>',shell:'cmd.exe',revision:state.revision},null,2));
    console.log('Windows cmd.exe entrypoint passed.');
  }finally{
    // This PID is the exact cmd.exe process created by this test; stop its Python descendants too.
    if(child.exitCode===null)await new Promise((resolve,reject)=>execFile('taskkill',['/pid',String(child.pid),'/t','/f'],{windowsHide:true},e=>e?reject(e):resolve()));
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
