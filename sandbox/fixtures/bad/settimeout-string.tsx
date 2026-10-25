// required: A
// expect: forbidden-global
function A() { setTimeout("alert(1)", 10); return <div />; }
