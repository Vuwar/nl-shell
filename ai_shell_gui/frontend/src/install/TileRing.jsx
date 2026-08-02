// A model takes minutes, so people click away and let the window fold to its
// 48px tile. The ring is the only thing that can be said at that size, and it
// is worth saying: the difference between "still going" and "stopped an hour
// ago" is otherwise a click away.
//
// A rounded rectangle rather than a circle, because the tile is one. A circle
// inscribed in a rounded square crosses its corners and touches its edges at
// four points, which reads as a mark drawn on the tile instead of the tile's
// own edge filling up.

const SIZE = 48;
const INSET = 1;          // half the stroke, so the line sits inside the tile
const RADIUS = 9;         // --radius (10px) less the inset

export default function TileRing({ percent, title }) {
  const shown = Math.max(0, Math.min(100, percent));
  return (
    <svg className="tile-ring" width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
      <title>{title}</title>
      {/* The whole edge, faintly: without it the filled part is a stray mark
          with nothing to be a fraction of. */}
      <rect
        className="tile-ring-track"
        x={INSET} y={INSET}
        width={SIZE - INSET * 2} height={SIZE - INSET * 2}
        rx={RADIUS} fill="none"
      />
      {/* pathLength normalises the perimeter to 100, so the dash offset is
          the percentage itself and no one has to work out the arc length of
          a rounded rectangle. */}
      <rect
        className="tile-ring-fill"
        x={INSET} y={INSET}
        width={SIZE - INSET * 2} height={SIZE - INSET * 2}
        rx={RADIUS} fill="none"
        pathLength="100"
        strokeDasharray="100"
        strokeDashoffset={100 - shown}
      />
    </svg>
  );
}
