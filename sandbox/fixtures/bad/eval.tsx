// required: A
// expect: forbidden-global
function A() { const f = eval("1+1"); return <div>{f}</div>; }
