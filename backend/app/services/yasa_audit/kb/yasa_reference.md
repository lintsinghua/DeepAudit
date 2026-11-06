# YASA engine reference (from the official YASA-Engine repo: CLI help, checker-config.json, example rule configs)

## CLI (wrapped by your yasa_run tool)
--sourcePath <dir>, --language java|javascript|typescript|golang|python, --analyzer <framework analyzer>,
--ruleConfigFile <json>, --checkerIds <ids>, --checkerPackIds <packs>, --entrypointMode BOTH|SELF_COLLECT|ONLY_CUSTOM.
Output: SARIF with per-hop trace (SOURCE -> Var Pass -> SINK) plus scan_summary counters:
fileCount, entryPointCount, markedSourceCount, matchedSinkCount, findingCount.

## Checkers (id: official description)
- taint_flow_java_input: Java taint checker, builds entrypoints from call-graph boundaries.
- taint_flow_spring_input / Spring collection is built into the Java checker (Spring entrypoints and sources).
- taint_flow_js_input: native JavaScript taint checker, builds entrypoints from call-graph boundaries.
- taint_flow_express_input: JavaScript Express framework taint checker.
- taint_flow_egg_input: JavaScript Egg framework taint checker.
- taint_flow_nodejs_cli_input: Node CLI script, marks command-line args as source.
- taint_flow_python_input (+ _django_input, _tornado_input, _httpserver_input, _script_input): Python checkers.
- taint_flow_go_input, taint_flow_gin_input, taint_flow_go_http_input, ...: Go checkers.
- callchain_java / callchain_js / callchain_python / callchain_go: only match sinks and print the call chain (no taint needed).
- sanitizer: applies sanitizer rules.
Checker packs: taint-flow-java-default, taint-flow-javascript-default, taint-flow-express, taint-flow-python-default, taint-flow-golang-default.

## ruleConfig format: a JSON array of objects, each:
{
  "checkerIds": ["taint_flow_java_input"],
  "entrypoints": [ {"filePath": "/src/http/agent.ts", "functionName": "agent", "attribute": "HTTP"} ],
  "sources": {
    "TaintSource": [ {"path": "req.query", "scopeFile": "all", "scopeFunc": "all"} ],        // a variable/member path that is tainted
    "FuncCallReturnValueTaintSource": [ {"fsig": "read", "calleeType": "", "values": ["0"], "scopeFile": "all", "scopeFunc": "all"} ],
    "FuncCallArgTaintSource": [ {"fsig": "handle", "args": ["0"], "scopeFile": "all", "scopeFunc": "all"} ]
  },
  "sinks": {
    "FuncCallTaintSink": [ {"fsig": "exec", "calleeType": "java.lang.Runtime", "args": ["0"], "attribute": "JavaCommandExec", "sanitizerIds": []} ]
  },
  "sanitizers": [
    {"id": "S1", "sanitizerType": "FunctionCallSanitizer", "sanitizerScenario": "SANITIZER.FILTER_BY_FUNCTIONCALL", "fsig": "escape", "args": ["0"]}
  ]
}
Notes from the examples:
- fsig is the called function/method name or dotted path (e.g. "child_process.exec", "Runtime.getRuntime().exec"); calleeType optionally constrains the receiver type.
- args lists the dangerous argument indexes ("*" = any).
- Sanitizer scenarios: FILTER_BY_FUNCTIONCALL (return value clean), VALIDATE_BY_FUNCTIONCALL (argument validated),
  VALIDATE_BY_BINARYOPERATION, CALLSTACK_HAS_FUNCTIONCALL, CONFIG_BY_FUNCTIONCALL, DEFAULT.
- Example JS config marks sources by path: req.query, req.params, req.body, req.headers, req.cookies, ctx.query, ctx.request.body ...
- Example Java config lists sinks such as Runtime.getRuntime().exec, java.net.URL.openConnection, java.sql.Statement.executeQuery.
