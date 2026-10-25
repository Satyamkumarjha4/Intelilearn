// required: Interactive_typed
function Interactive_typed() {
  const [n, setN] = useState<number>(0);
  const double = (x: number): number => x * 2;
  return <button type="button" onClick={() => setN(double(n + 1))}>{n}</button>;
}
