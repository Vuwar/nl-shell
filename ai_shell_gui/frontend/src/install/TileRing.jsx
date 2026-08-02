// A model takes minutes, so people click away and let the window fold to its
// 48px tile. The ring is the only thing that can be said at that size, and it
// is worth saying: the difference between "still going" and "stopped an hour
// ago" is otherwise a click away.
//
// A rounded rectangle rather than a circle, because the tile is one. A circle
// inscribed in a rounded square crosses its corners and touches its edges at
// four points, which reads as a mark drawn on the tile instead of the tile's
// own edge filling up.

// A viewBox rather than pixels, and stretched to the panel by CSS. The tile
// is 48px including a 1px border, and an absolutely positioned child anchors
// to the padding box - inside that border - so a hard-coded 48 starts a pixel
// in and loses its last pixel to the panel's overflow clip. Bottom and right
// simply vanish.
const BOX = 48;
const INSET = 2;          // clear of the border and its rounding, at any scale
const RADIUS = 8;         // --radius (10px) less the inset

export default function TileRing({ percent, title }) {
  const shown = Math.max(0, Math.min(100, percent));
  return (
    <svg className="tile-ring" viewBox={`0 0 ${BOX} ${BOX}`} preserveAspectRatio="none">
      <title>{title}</title>
      {/* The whole edge, faintly: without it the filled part is a stray mark
          with nothing to be a fraction of. */}
      <rect
        className="tile-ring-track"
        x={INSET} y={INSET}
        width={BOX - INSET * 2} height={BOX - INSET * 2}
        rx={RADIUS} fill="none"
      />
      {/* pathLength normalises the perimeter to 100, so the dash offset is
          the percentage itself and no one has to work out the arc length of
          a rounded rectangle. */}
      <rect
        className="tile-ring-fill"
        x={INSET} y={INSET}
        width={BOX - INSET * 2} height={BOX - INSET * 2}
        rx={RADIUS} fill="none"
        pathLength="100"
        strokeDasharray="100"
        strokeDashoffset={100 - shown}
      />
    </svg>
  );
}
