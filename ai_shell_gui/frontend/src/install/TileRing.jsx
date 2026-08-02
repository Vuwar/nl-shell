// A model takes minutes, so people click away and let the window fold to its
// 48px tile. The ring is the only thing that can be said at that size, and it
// is worth saying: the difference between "still going" and "stopped an hour
// ago" is otherwise a click away.

const SIZE = 48;
const RADIUS = 22;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function TileRing({ percent, title }) {
  const shown = Math.max(0, Math.min(100, percent));
  return (
    <svg className="tile-ring" width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
      <title>{title}</title>
      <circle
        className="tile-ring-track"
        cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none"
      />
      <circle
        className="tile-ring-fill"
        cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none"
        strokeDasharray={CIRCUMFERENCE}
        strokeDashoffset={CIRCUMFERENCE * (1 - shown / 100)}
        transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
      />
    </svg>
  );
}
