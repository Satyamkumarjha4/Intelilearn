// required: A
// expect: forbidden-attribute
function A() { return <div dangerouslySetInnerHTML={{ __html: "<b>x</b>" }} />; }
