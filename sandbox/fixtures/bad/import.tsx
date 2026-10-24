// required: A
// expect: no-import
import axios from "axios";
function A() { return <div>{String(axios)}</div>; }
