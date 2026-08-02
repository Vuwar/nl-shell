import LayerGrid from "./LayerGrid";
import { formatBytes, formatEta, formatRate } from "./format";

// The first install, when there is no model on the disk at all. There is no
// shell to use yet, so the panel is the install screen rather than a line
// under an input nobody can type into.

function caption(install) {
  if (install.phase === "verifying") return "Checking what arrived";
  if (install.phase === "refetching") return "That copy didn't match, fetching it again";
  if (install.phase === "failed") return "The download stopped";
  if (install.phase === "retrying" && install.retry) {
    return `Connection lost, trying again in ${install.retry.wait}s `
      + `(attempt ${install.retry.attempt} of ${install.retry.of})`;
  }
  if (install.phase === "loading" && install.gpuLayers !== null) {
    if (install.gpuLayers === 0) return "Loading the model, to run on the processor";
    if (install.gpuLayers >= install.layers) {
      return `All ${install.layers} layers on your graphics card`;
    }
    return `${install.gpuLayers} of ${install.layers} layers on your graphics card`;
  }
  if (install.phase === "loading") return "Loading the model";
  const landed = Math.min(install.layers, Math.floor(install.filled));
  return `${landed} of ${install.layers} layers`;
}

export default function InstallPanel({ install, hint, hintShown, leaving }) {
  const stats = [
    `${formatBytes(install.bytesDone)} of ${formatBytes(install.bytesTotal)}`,
    formatRate(install.rate),
    formatEta(install.eta),
  ].filter(Boolean);

  return (
    <div className={`install${leaving ? " leaving" : ""}`}>
      <div className="install-head">
        <span className="install-title">Setting up {install.label}</span>
      </div>

      <LayerGrid
        layers={install.layers}
        filled={install.filled}
        phase={install.phase}
        gpuLayers={install.gpuLayers}
        animate={install.fresh}
      />

      <div className="install-caption">{caption(install)}</div>

      <div className="install-bar">
        <div className="install-bar-fill" style={{ width: `${install.percent}%` }} />
      </div>

      {install.phase !== "loading" && (
        <div className="install-stats">{stats.join(" · ")}</div>
      )}

      {/* The same hints the input rotates when it is idle. A wait this long is
          the one moment somebody will read them, and a second list of copy
          written only for this screen would drift from the first. */}
      <div className={`install-hint${hintShown ? "" : " out"}`}>
        {hint.key && <span className="input-hint-key">{hint.key}</span>}
        <span className="input-hint-text">{hint.text}</span>
      </div>
    </div>
  );
}
