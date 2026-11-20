# ONNX Runtime Web 1.24.3

Vendored from the npm package `onnxruntime-web@1.24.3` (`dist/`), MIT licence,
Copyright (c) Microsoft Corporation. No CDN (AGENTS.md §1).

| File | Role |
|---|---|
| `ort.min.js` | The runtime, loaded by the three inference workers with `importScripts`. |
| `ort.min.js.map` | Its source map. Required: the production static storage (manifest) resolves the `sourceMappingURL` of every script and stops `collectstatic` when the file is missing. |
| `ort-wasm-simd-threaded.jsep.mjs` | Its WebAssembly loader (WASM and WebGPU back ends). |
| `ort-wasm-simd-threaded.jsep.wasm` | The WebAssembly binary (Git LFS). |

The workers (`js/gel-viewer/inference/*-worker.js`) find this folder relative to
their own URL and point `ort.env.wasm.wasmPaths` at it. The band model's
browser/Python parity was measured on this version: upgrading means measuring
it again.
