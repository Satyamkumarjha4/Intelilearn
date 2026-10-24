// required: A
// expect: forbidden-global
function A() { useEffect(() => { window.parent.postMessage("x", "*"); }, []); return <div />; }
