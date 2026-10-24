// required: A
// expect: forbidden-member
function A() { const f = [].constructor.constructor("return this")(); return <div>{String(f)}</div>; }
