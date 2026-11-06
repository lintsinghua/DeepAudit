# YASA playbook (engine know-how; every item was verified by a test run, ids refer to the
# verification log in backend/benchmarks/yasa_audit/README.md)

Diagnose with the counters after every run:
- fileCount lower than the number of app source files -> some code is not parsed. JSP is not parsed:
  use preprocess_jsp=true for JSP apps. [V1]
- Java: taint_flow_java_input only self-collects main() and Spring sources. Plain Servlets/JSP need explicit
  sources, e.g. FuncCallReturnValueTaintSource {"fsig":"getParameter","values":["0"],"scopeFile":"all","scopeFunc":"all"}. [V2]
- Second-order sources (session/DB values) can be added as FuncCallReturnValueTaintSource (e.g. getAttribute),
  but label those findings second-order; the triage stage verifies the write path. [V3]
- JavaScript/TypeScript:
  * taint_flow_express_input only uses entrypoints you list in ruleConfig; with none, entryPointCount=0 and nothing
    is found. Prefer taint_flow_js_input, which builds entrypoints from the call graph. [V4]
  * --analyzer makes no difference to these checkers. [V4]
  * Handlers returned by factory functions (app.get('/x', handler())) are found only when the file that registers
    the routes (server.ts / app.ts) is inside sourcePath. Scanning only routes/ gives markedSourceCount>0 but
    findingCount=0. [V5]
  * Member-call sinks match by the dotted path written at the call site, e.g. "models.sequelize.query". [V4]
  * SPEED: by default taint_flow_js_input treats every call-graph boundary function (lib helpers included) as an
    entrypoint, which is slow. Set entrypoint_mode="ONLY_CUSTOM" and list the bootstrap file as the only entrypoint,
    file-level (no functionName): "entrypoints": [{"filePath": "/server.ts", "attribute": "HTTP"}]. [V6]
    A bootstrap *function* (start / configureApp) as entrypoint found nothing when routes are registered inside a
    promise callback. [V6]
- matchedSinkCount very large -> generic sinks like res.send/console.log/JSON.stringify are in the config; drop them. [V7]
- findingCount counts one result per source; the tool output already groups them per sink (R<run>-F<i>).
