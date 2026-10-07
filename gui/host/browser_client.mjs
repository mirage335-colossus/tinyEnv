import {MAX_OPERATION_BYTES,MAX_QUEUED_BYTES} from './browser_limits.mjs';
const encoder = new TextEncoder();
// Serial transport preserves command order and bounds pending work. On an
// uncertain delivery, retry uses the identical epoch/sequence/payload. Never
// reconnect by replaying commands into a fresh application session.
export {MAX_OPERATION_BYTES,MAX_QUEUED_BYTES} from './browser_limits.mjs';
const serializedOperation=operation=>{
  const text=JSON.stringify(operation);
  if(typeof text!=="string"||text.length>MAX_OPERATION_BYTES-512||encoder.encode(text).length>MAX_OPERATION_BYTES-512)
    throw Error("Input exceeds the operation byte limit.");
  return text;
};
export class Client {
  constructor(exchange, apply, status = () => {}) {
    this.exchange = exchange; this.apply = apply; this.status = status;
    this.queue = []; this.running = false; this.failed = false;
    this.epoch = null; this.ack = 0n; this.state = null; this.inflight = null; this.closed = false;
    // Includes the in-flight retry reservation. Dynamic operations reserve a
    // full request; the renderer bounds its captured editor value separately.
    this.queuedBytes = 0;
  }
  accept(state) {
    if (this.epoch !== null && state.epoch !== this.epoch) throw Error("Session changed; reload to start a new session.");
    const ack = BigInt(state.ack);
    if (ack < this.ack) return false;
    this.epoch = state.epoch; this.ack = ack; this.state = state;
    this.apply(state);
    if (state.error && state.error !== "Duplicate operation ignored") this.status(state.error);
    return true;
  }
  send(operation, coalesce = null, beforePrepare = null) {
    return new Promise((resolve, reject) => {
      if (this.closed) { reject(Error("Session closed")); return; }
      let bytes=MAX_OPERATION_BYTES;
      try {
        if(typeof operation!=="function"){
          const text=serializedOperation(operation);bytes=encoder.encode(text).length+512;
          operation=JSON.parse(text); // Caller mutation cannot alter a queued/retried command.
        }
      }catch(error){this.status(error.message);reject(error);return;}
      const last=this.queue.at(-1),previous=coalesce&&last?.coalesce===coalesce?last:null;
      if(this.queuedBytes-(previous?.bytes||0)+bytes>MAX_QUEUED_BYTES||
          (previous?previous.completions.length>=128:this.queue.length>=128)){
        const error=Error("Input queue is full; wait for the backend.");this.status(error.message);reject(error);return;
      }
      if(previous){
        this.queuedBytes+=bytes-previous.bytes;previous.bytes=bytes;previous.operation=operation;previous.beforePrepare=beforePrepare;
        previous.completions.push({resolve,reject});this.pump();return;
      }
      this.queuedBytes+=bytes;
      this.queue.push({operation,coalesce,bytes,beforePrepare,completions:[{resolve,reject}]});this.pump();
    });
  }
  async pump() {
    if (this.closed || this.running || this.failed || !this.state) return;
    this.running = true;
    try {
      while (this.inflight || this.queue.length) {
        if (!this.inflight) {
          const task=this.queue[0];
          try {
            if(task.beforePrepare?.(this.state,task.operation)===false)throw Error("Input is no longer current.");
            const operation=typeof task.operation==="function"?JSON.parse(serializedOperation(task.operation(this.state.snapshot))):task.operation;
            const envelope={epoch:this.epoch,seq:String(this.ack+1n),operation};
            const text=JSON.stringify(envelope);
            if(text.length>MAX_OPERATION_BYTES||encoder.encode(text).length>MAX_OPERATION_BYTES)throw Error("Input envelope exceeds the byte limit.");
            this.inflight={task,envelope};this.queue.shift();
          }catch(error){
            // Local preparation failure has no uncertain backend side effect.
            // Reject while the task is still owned; never strand its completions.
            this.queue.shift();this.queuedBytes-=task.bytes;
            for(const completion of task.completions)completion.reject(error);
            this.status(error.message);continue;
          }
        }
        const {task, envelope} = this.inflight;
        const state = await this.exchange(envelope);
        if (this.closed) return;
        if (state.epoch !== this.epoch || BigInt(state.ack) < BigInt(envelope.seq)) throw Error(state.error || "Operation was not acknowledged.");
        this.accept(state);
        if (this.closed) return; // An accepted-state observer may dispose synchronously.
        this.inflight = null;this.queuedBytes-=task.bytes;
        for (const completion of task.completions) completion.resolve(state);
      }
    } catch (error) {
      if(this.closed)return;
      this.failed = true; this.status(`Connection paused: ${error.message}. Retry preserves operation identity.`, true);
    } finally { this.running = false; }
  }
  close() {
    if(this.closed)return;this.closed=true;
    const tasks=[...this.queue];if(this.inflight)tasks.push(this.inflight.task);
    this.queue=[];this.inflight=null;this.queuedBytes=0;
    for(const task of tasks)for(const completion of task.completions)completion.reject(Error("Session closed"));
  }
  retry() { if(this.closed)return;this.failed = false; this.status(""); this.pump(); }
}
