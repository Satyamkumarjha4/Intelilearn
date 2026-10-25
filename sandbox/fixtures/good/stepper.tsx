// required: Interactive_stepper
function Interactive_stepper() {
  const [i, setI] = useState(0);
  const items = [1, 3, 5, 7, 9];
  useEffect(() => {
    const id = setInterval(() => setI((n) => (n + 1) % items.length), 800);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="flex flex-col gap-2">
      <Button onClick={() => setI((i + 1) % items.length)}>Step</Button>
      <p>{items.map((x, k) => (k === i ? <b key={k}>{x}</b> : <span key={k}>{x} </span>))}</p>
    </div>
  );
}
