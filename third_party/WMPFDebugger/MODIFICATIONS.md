# Local modifications

This directory is based on
[WMPFDebugger](https://github.com/evi0s/WMPFDebugger) commit
`1d9f6e03a24dcd39baa223e25a883a85b84bd303`.

`src/index.ts` is modified by the 公众号整理 project to:

- bind the mini-program and CDP WebSocket servers to `127.0.0.1`;
- require the per-run local bridge token for CDP clients and reject browser origins;
- expose a local `LocalBridge.status` query used to distinguish cached data from a live mini-program connection;
- count connected mini-program clients; and
- detach Frida and close both servers on `SIGINT` or `SIGTERM`.

The npm lock file keeps the upstream dependency ranges but resolves known
security fixes, including `protobufjs` 7.6.6 and `ws` 8.21.3. `npm audit`
reports no known vulnerabilities at the time of this release.

The modified source is distributed under `GPL-2.0-only`, the same license as
the upstream project. The upstream README states that files in
`src/third-party` were extracted from WeChat Developer Tools and are
copyright Tencent Holdings Ltd.; that notice is preserved without alteration.
