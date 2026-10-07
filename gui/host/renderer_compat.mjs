// Compatibility points toward the trusted host and the DOM implementation.
// Isolated composition imports neither this wrapper nor the DOM module.
export {Renderer,identity,byteOffset,utf16Offset} from './renderer_dom.mjs';
export {Client,MAX_OPERATION_BYTES,MAX_QUEUED_BYTES} from './browser_client.mjs';
export {executeService} from './browser_services.mjs';
