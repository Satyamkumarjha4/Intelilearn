// required: A
// expect: no-dynamic-import
function A() { useEffect(() => { import("https://x.y/z.js"); }, []); return <div />; }
