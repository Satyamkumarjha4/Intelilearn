// Everything generated lesson code may refer to without defining it. This is the one list: check.mjs enforces it,
// and the browser runtime (src/scope, Phase 6) must provide every name in SCOPE_NAMES. Adding a library to the scope
// is a deliberate change: add the names here, provide them in the runtime, and document them in the prompts
// (backend/graph/prompts/scope.py).

export const REACT_NAMES = [
  "React", "useState", "useEffect", "useRef", "useMemo", "useCallback", "useReducer", "useLayoutEffect", "useId",
  "Fragment",
];

export const LESSON_NAMES = [
  "LESSON",
  // layout and content
  "PageFrame", "Section", "Markdown", "Callout", "KeyPoints", "WorkedExample", "FormulaCard", "CodeBlock",
  "InlineMath", "BlockMath", "Figure", "Button", "Slider", "Assessment", "LessonShell", "withBoundary", "render",
  // graphs (mafs)
  "Mafs", "Coordinates", "Plot", "Point", "Line", "Vector", "Circle", "Ellipse", "Polygon", "Polyline", "Text",
  "Theme", "Transform", "useMovablePoint", "vec",
  // animation (motion)
  "motion", "AnimatePresence",
];

// Standard JavaScript a component may use.
export const STANDARD_NAMES = [
  "undefined", "NaN", "Infinity", "Math", "Number", "String", "Boolean", "Array", "Object", "JSON", "Date", "Map", "Set",
  "WeakMap", "WeakSet", "Symbol", "RegExp", "Error", "TypeError", "RangeError", "Promise", "Intl", "parseInt",
  "parseFloat", "isNaN", "isFinite", "setTimeout", "clearTimeout", "setInterval", "clearInterval",
  "requestAnimationFrame", "cancelAnimationFrame", "performance", "console", "structuredClone",
];

export const SCOPE_NAMES = new Set([...REACT_NAMES, ...LESSON_NAMES, ...STANDARD_NAMES]);

// Names that reach outside the sandbox. Listed separately from "not in scope" so the message says why.
export const FORBIDDEN_GLOBALS = new Set([
  "fetch", "XMLHttpRequest", "WebSocket", "EventSource", "eval", "Function", "window", "document", "globalThis",
  "self", "top", "parent", "opener", "frames", "localStorage", "sessionStorage", "indexedDB", "caches", "navigator",
  "postMessage", "importScripts", "Worker", "SharedWorker", "ServiceWorker", "require", "process", "module",
  "exports", "Buffer", "location", "history", "open", "close", "alert", "confirm", "prompt", "Image", "Audio",
  "Notification", "WebAssembly", "Proxy", "Reflect", "AsyncFunction", "GeneratorFunction",
]);

// Property names that give access to constructors and prototypes (sandbox escapes).
export const FORBIDDEN_MEMBERS = new Set(["constructor", "__proto__", "prototype", "__defineGetter__", "__defineSetter__", "__lookupGetter__"]);

// JSX elements that load or run something. Media goes through <Figure asset>.
export const FORBIDDEN_ELEMENTS = new Set(["img", "iframe", "script", "link", "object", "embed", "form", "base", "meta", "style", "video", "audio", "source", "image", "foreignObject", "use", "portal"]);
