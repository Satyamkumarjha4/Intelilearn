// required: A
// expect: forbidden-global
function A() { const f = new Function("return 1"); return <div>{f()}</div>; }
