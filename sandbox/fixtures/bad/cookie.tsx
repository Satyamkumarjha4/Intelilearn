// required: A
// expect: forbidden-global
function A() { return <div>{document.cookie}</div>; }
