// Bounded content capability. Files and URLs stay in the host; only owned UTF-8
// text enters the ordered service reply. Export success means download offered.
const maximum = 65536;
function byteLimit(value) {
  const limit = Number(value);
  if (!Number.isSafeInteger(limit) || limit < 0 || limit > maximum) throw new Error('Invalid file service byte limit');
  return limit;
}
function checkCurrent(signal, isCurrent) {
  if (signal?.aborted || (isCurrent && !isCurrent())) throw new Error('File operation cancelled');
}
async function readSlice(file, begin, end, signal, isCurrent) {
  checkCurrent(signal, isCurrent);
  const slice = file.slice(begin, end);
  checkCurrent(signal, isCurrent);
  const bytes = await slice.arrayBuffer();
  checkCurrent(signal, isCurrent);
  return bytes;
}
export async function readTextFile(file, requestedLimit, {signal, isCurrent} = {}) {
  checkCurrent(signal, isCurrent);
  const limit = byteLimit(requestedLimit);
  if (!file || !Number.isSafeInteger(file.size) || file.size < 0 || file.size > limit)
    throw new Error(`Select a file no larger than ${limit} bytes`);
  // Slice and recheck protect against a provider returning more than advertised.
  const bytes = await readSlice(file, 0, limit + 1, signal, isCurrent);
  checkCurrent(signal, isCurrent);
  if (bytes.byteLength > limit) throw new Error('Selected file exceeds the byte limit');
  return new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes);
}
const chunkBytes = 4096;
const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
function unhex(value) {
  if (typeof value !== 'string' || value.length > chunkBytes * 2 || value.length % 2 || !/^[0-9a-f]*$/.test(value))
    throw new Error('Invalid export chunk');
  return Uint8Array.from(value.match(/../g) || [], pair => parseInt(pair, 16));
}
async function request(exchange, operation, signal, isCurrent) {
  checkCurrent(signal, isCurrent);
  const state = await exchange(operation);
  checkCurrent(signal, isCurrent);
  if (state.error && state.error !== 'Duplicate operation ignored') throw new Error(state.error);
  if (state.service?.id !== operation.id) throw new Error('File request was replaced');
  return state;
}
// One acknowledged chunk at a time bounds Worker/HTTP queues and gives the
// browser event loop a chance to process input between storage operations.
export async function uploadTextFile(file, service, exchange, signal, isCurrent) {
  checkCurrent(signal, isCurrent);
  const limit = byteLimit(service.byteLimit);
  if (!file || !Number.isSafeInteger(file.size) || file.size < 0 || file.size > limit)
    throw new Error(`Select a file no larger than ${limit} bytes`);
  await request(exchange, {type: 'fileBegin', id: service.id, total: String(file.size)}, signal, isCurrent);
  checkCurrent(signal, isCurrent);
  const decoder = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true});
  for (let offset = 0; offset < file.size; offset += chunkBytes) {
    const count = Math.min(chunkBytes, file.size - offset);
    const bytes = new Uint8Array(await readSlice(file, offset, offset + count, signal, isCurrent));
    checkCurrent(signal, isCurrent);
    if (bytes.length !== count) throw new Error('Selected file changed or was truncated');
    decoder.decode(bytes, {stream: true});
    await request(exchange, {type: 'fileChunk', id: service.id, offset: String(offset), hex: hex(bytes)}, signal, isCurrent);
    checkCurrent(signal, isCurrent);
  }
  decoder.decode();
  // The caller sends finish through the same ordered client after closing its
  // dialog. Only this final operation commits content to the application.
  return {type: 'fileFinish', id: service.id};
}
export async function downloadTextFile(service, exchange, signal, isCurrent) {
  checkCurrent(signal, isCurrent);
  const limit = byteLimit(service.byteLimit), total = Number(service.byteSize);
  if (!Number.isSafeInteger(total) || total < 0 || total > limit) throw new Error('Invalid export size');
  const chunks = [];
  for (let offset = 0; offset < total; offset += chunkBytes) {
    const state = await request(exchange, {type: 'fileRead', id: service.id, offset: String(offset)}, signal, isCurrent);
    checkCurrent(signal, isCurrent);
    const part = state.transfer;
    if (part?.id !== service.id || part.offset !== String(offset) || part.total !== String(total)) throw new Error('Wrong export chunk identity');
    const bytes = unhex(part.hex);
    if (bytes.length !== Math.min(chunkBytes, total - offset)) throw new Error('Truncated export chunk');
    chunks.push(bytes);
  }
  return chunks;
}
export async function executeFileService(service, host = globalThis) {
  const base = {type: 'service', id: service.id, value: '', error: ''};
  const current = () => !host.signal?.aborted && (!host.isCurrent || host.isCurrent());
  if (!current()) return {...base, status: 'cancelled'};
  if (!host.document || ![5, 6].includes(service.kind))
    return {...base, status: 'error', error: 'File content services are unavailable'};
  let limit;
  try {
    limit = byteLimit(service.byteLimit);
    if (typeof service.value !== 'string' || new TextEncoder().encode(service.value).length > limit)
      throw new Error('File content exceeds the byte limit');
  } catch (error) { return {...base, status: 'error', error: error.message}; }
  return new Promise(resolve => {
    const document = host.document, previous = document.activeElement;
    const dialog = document.createElement('dialog'), form = document.createElement('form');
    dialog.className = 'service-prompt';
    const title = document.createElement('p'), input = document.createElement('input');
    const status = document.createElement('p'), cancel = document.createElement('button'), accept = document.createElement('button');
    title.textContent = service.title; status.setAttribute('role', 'status');
    input.type = 'file'; input.setAttribute('aria-label', service.title);
    cancel.type = 'button'; cancel.textContent = 'Cancel'; accept.type = 'submit';
    accept.textContent = service.kind === 5 ? 'Import' : 'Download';
    form.append(title); if (service.kind === 5) form.append(input);
    form.append(status, cancel, accept); dialog.append(form);
    let settled = false, exportChunks = null;
    const signal = host.signal, capability = host.document.defaultView || globalThis;
    const abort = () => finish('cancelled');
    const finish = (result, value = '', error = '', operation = null) => {
      if (settled) return; settled = true;
      signal?.removeEventListener('abort', abort);
      if (dialog.open) dialog.close(); dialog.remove();
      if (current() && previous?.isConnected) previous.focus({preventScroll: true});
      resolve(operation || {...base, status: result, value, error});
    };
    const check = () => { if (settled) return false; if (current()) return true; abort(); return false; };
    if (!check()) return;
    signal?.addEventListener('abort', abort, {once: true});
    cancel.addEventListener('click', () => finish('cancelled'));
    dialog.addEventListener('cancel', event => { event.preventDefault(); finish('cancelled'); });
    dialog.addEventListener('close', () => finish('cancelled'));
    dialog.addEventListener('keydown', event => { event.stopPropagation(); });
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!check() || accept.disabled) return;
      accept.disabled = true;
      try {
        if (service.kind === 5) {
          if (service.chunked && host.exchange) {
            const operation = await uploadTextFile(input.files?.[0], service, host.exchange, signal, host.isCurrent);
            if (check()) finish('success', '', '', operation);
          } else {
            const value = await readTextFile(input.files?.[0], limit, {signal, isCurrent: host.isCurrent});
            if (check()) finish('success', value);
          }
        } else {
          // This runs directly from the user's Download action, retaining the
          // browser's user activation requirement even after a delayed poll.
          const urls = host.URL || capability.URL, BlobType = host.Blob || capability.Blob;
          if (!check()) return;
          const blob = new BlobType(exportChunks || [service.value], {type: 'text/plain;charset=utf-8'});
          if (!check()) return;
          const url = urls.createObjectURL(blob);
          let link,ownedURL;
          try {
            if (current() && host.ownDownloadURL) ownedURL = host.ownDownloadURL(url, () => urls.revokeObjectURL(url));
            if (!check()) return;
            link = document.createElement('a'); link.href = url; link.download = 'export.txt';
            if (!check()) return; dialog.append(link);
            if (!check()) return; link.click();
          } finally {
            link?.remove();
            // Revoking our URL is cleanup even after withdrawal. Only a live
            // request may schedule new work; obsolete owners revoke at once.
            if (ownedURL) {
              if (current()) ownedURL.schedule(1000);
              else ownedURL.revoke();
            } else if (current()) (host.setTimeout || capability.setTimeout.bind(capability))(() => urls.revokeObjectURL(url), 1000);
            else urls.revokeObjectURL(url);
          }
          if (check()) finish('success');
        }
      } catch (error) {
        if (check()) { status.textContent = error.message || 'File content operation failed'; if (check()) accept.disabled = false; }
      }
    });
    if (service.kind === 6 && service.chunked && host.exchange) {
      // Prefetch bounded chunks before enabling the user's Download action;
      // the eventual link click still executes directly under user activation.
      accept.disabled = true;
      if (!check()) return;
      downloadTextFile(service, host.exchange, signal, host.isCurrent).then(chunks => {
        if (check()) { exportChunks = chunks; accept.disabled = false; }
      }).catch(error => { if (check()) finish('error', '', error.message); });
    }
    try {
      if (!check()) return; (host.serviceRoot || document.querySelector?.('#stage') || document.body).append(dialog);
      if (!check()) return; dialog.showModal();
      if (check()) accept.focus();
    } catch (error) { finish(current() ? 'error' : 'cancelled', '', error.message || 'Could not open file dialog'); }
  });
}
