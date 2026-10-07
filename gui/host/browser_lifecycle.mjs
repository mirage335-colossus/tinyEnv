// One outstanding poll is sufficient: transport order also orders task steps.
export function startPolling(client, scheduler=globalThis, interval=25) {
  let stopped=false, timer=null;
  const schedule=()=>{if(!stopped)timer=scheduler.setTimeout(run,interval);};
  const run=()=>{
    timer=null;if(stopped||client.closed)return;
    if(client.failed){schedule();return;}
    client.send({type:'poll'}).catch(()=>{}).finally(schedule);
  };
  schedule();
  return ()=>{stopped=true;if(timer!==null)scheduler.clearTimeout(timer);timer=null;};
}
