// required: Interactive_graph
function Interactive_graph() {
  const point = useMovablePoint([1, 1]);
  return (
    <Mafs height={300}>
      <Coordinates.Cartesian />
      <Plot.OfX y={(x) => Math.sin(x)} />
      {point.element}
    </Mafs>
  );
}
