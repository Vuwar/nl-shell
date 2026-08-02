// One brick per layer of the model, filled by the bytes that have actually
// landed. A brick per file would be one brick: every model in the registry is
// a single GGUF. Layers are a real property of the thing being installed, and
// they are also what the last phase has to say - which of them fit on the
// card - so the grid ends by answering a question instead of vanishing.
//
// Nothing here polls or fetches. It is handed a number and draws it, which is
// what makes it possible to look at with ?install=demo.

// Kept roughly square across the layer counts the registry actually has:
// 28 -> 7x4, 36 -> 6x6, 48 -> 8x6, 64 -> 8x8.
function columnsFor(layers) {
  for (const columns of [8, 7, 6]) {
    if (layers % columns === 0 && layers / columns <= columns) return columns;
  }
  return 8;
}

export default function LayerGrid({ layers, filled, phase, gpuLayers, animate = true }) {
  const columns = columnsFor(layers);
  const bricks = [];

  for (let i = 0; i < layers; i += 1) {
    const fill = Math.max(0, Math.min(1, filled - i));
    const onCard = gpuLayers !== null && gpuLayers !== undefined && i < gpuLayers;
    const classes = ["brick"];
    if (fill >= 1) classes.push("full");
    else if (fill > 0) classes.push("partial");
    if (phase === "loading" && fill >= 1) classes.push(onCard ? "card" : "cpu");

    // Diagonal: the breath enters at the top-left corner and travels to the
    // bottom-right, so neighbours are near each other in the cycle and the
    // block moves as one thing. The first version delayed by (i % 17), which
    // has no relation to a grid seven wide, so adjacent bricks sat at
    // unrelated points in the cycle and it read as noise.
    const row = Math.floor(i / columns);
    const column = i % columns;
    const step = row + column;

    bricks.push(
      <span
        key={i}
        className={classes.join(" ")}
        style={{
          "--fill": fill,
          // Negative, and this is the whole trick. A positive delay would
          // only offset a brick from its own start, and a brick starts when
          // it fills - so one that lands a minute in runs a minute out of
          // phase with the rest. Negative starts every brick partway into a
          // cycle they all began together at mount, which is how the lights
          // on a keyboard stay in step: one clock, a phase per position.
          "--delay": `-${step * 260}ms`,
          // The handoff to the card gets its own, much tighter stagger. It
          // has to finish inside the seconds a model takes to load, where the
          // breath has a four second cycle to play with.
          "--warm-delay": `${step * 45}ms`,
        }}
      />
    );
  }

  return (
    <div
      className={`layer-grid ${phase}${animate ? "" : " instant"}`}
      style={{ "--columns": columns }}
      aria-hidden="true"
    >
      {bricks}
    </div>
  );
}
