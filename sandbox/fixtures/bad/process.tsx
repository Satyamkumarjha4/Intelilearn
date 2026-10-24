// required: A
// expect: forbidden-global
function A() { return <div>{String(process.env.SECRET)}</div>; }
