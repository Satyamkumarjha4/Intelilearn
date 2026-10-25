// required: A
// expect: forbidden-element
function A() { return <img src="data:image/png;base64,AAAA" alt="x" />; }
