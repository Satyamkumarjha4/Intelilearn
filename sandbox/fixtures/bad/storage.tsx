// required: A
// expect: forbidden-global
function A() { localStorage.setItem("a", "b"); return <div />; }
