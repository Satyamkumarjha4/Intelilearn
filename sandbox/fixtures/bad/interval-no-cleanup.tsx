// required: A
// expect: interval-cleanup
function A() { useEffect(() => { setInterval(() => {}, 100); }, []); return <div />; }
