"""What generated TSX may use. Mirrors sandbox/src/scope (and the allow-list in sandbox/scripts/check.mjs)."""

SCOPE_REFERENCE = """\
Everything below is already in scope. There are NO imports: never write import/export/require.
- React hooks: useState, useEffect, useRef, useMemo, useCallback, useReducer (React is in scope for JSX).
- LESSON: the lesson data. LESSON.pages.<introduction|core|advanced> = {title, summary, sections: [{id, heading,
  body (Markdown), key_points, worked_examples: [{problem, solution}], formulas: [{latex, explanation}],
  code_snippets: [{language, code, explanation}], callouts: [{kind, text}]}]}. LESSON.media[assetId] =
  {url, alt, caption, attribution}. Read content from LESSON; never retype it.
- Layout: <PageFrame title subtitle?>…</PageFrame>; <Section section={sectionObject}>{children shown after the
  body}</Section> renders a whole section (heading, Markdown body, formulas, examples, code, callouts, key points);
  <Markdown>{markdownString}</Markdown>; <Callout kind="note|tip|warning|example">…</Callout>;
  <KeyPoints title? points={string[]} />; <WorkedExample example={{problem, solution}} />;
  <FormulaCard formula={{latex, explanation}} />; <CodeBlock code="…" language="python" />.
- Maths: <InlineMath>{"a^2+b^2"}</InlineMath>, <BlockMath>{"\\\\int_0^1 x\\\\,dx"}</BlockMath> (KaTeX).
- Media: <Figure asset="ASSET_ID" /> is the ONLY way to show an image or GIF.
- Controls: <Button onClick variant="default|outline">…</Button>, <Slider label min max step value onChange={(n)=>…} />.
- Graphs (mafs): Mafs, Coordinates (Coordinates.Cartesian), Plot (Plot.OfX, Plot.OfY, Plot.Parametric), Point,
  Line (Line.Segment, Line.ThroughPoints, Line.PointSlope), Vector, Circle, Ellipse, Polygon, Polyline, Text,
  Theme, Transform, useMovablePoint, vec. Example: <Mafs height={300}><Coordinates.Cartesian />
  <Plot.OfX y={(x) => Math.sin(x)} /></Mafs>.
- Animation (motion): motion.div, motion.circle, motion.rect, motion.path…, AnimatePresence.
- Standard JS: Math, Number, String, Array, Object, JSON, Date, Map, Set, parseInt, parseFloat, isNaN,
  setTimeout/clearTimeout, requestAnimationFrame/cancelAnimationFrame, performance.now, console.
- Styling: Tailwind CSS classes work (light and dark mode: use dark: variants or neutral colours).
FORBIDDEN (the code is rejected): fetch, XMLHttpRequest, WebSocket, EventSource, eval, Function, import(),
window, document, globalThis, localStorage, sessionStorage, indexedDB, cookies, postMessage, navigator,
dangerouslySetInnerHTML, raw <img>/<iframe>/<script>/<link>/<object>/<embed>, any http:// or https:// string,
.constructor / __proto__ / prototype access, setInterval without clearInterval in the useEffect cleanup."""
