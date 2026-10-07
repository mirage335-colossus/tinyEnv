// Preserve synchronous CLI output failure semantics in the Node target runtime.
// Emscripten converts a failed terminal write into the C/C++ stream error state.
// Node's default console buffers errors and cannot provide that contract.
Module['print'] = function (text) {
  require('node:fs').writeSync(1, text + '\n');
};
Module['printErr'] = function (text) {
  require('node:fs').writeSync(2, text + '\n');
};
