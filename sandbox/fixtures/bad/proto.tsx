// required: A
// expect: forbidden-member
function A() { const o = {}; o["__proto__"].x = 1; return <div />; }
