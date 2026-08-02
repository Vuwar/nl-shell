import LayerGrid from "./LayerGrid";
import { formatEta } from "./format";

// A download that happens while the app is already usable: a model switched
// from settings, or a start where some other model is already on the disk. It
// takes the boot row's place and nothing else moves. The input stays live, and
// anything typed during it still queues on the Python side.

export default function InstallRow({ install }) {
  const eta = formatEta(install.eta);
  return (
    <div className="boot-row install-row">
      <LayerGrid
        layers={install.layers}
        filled={install.filled}
        phase={install.phase}
        gpuLayers={install.gpuLayers}
        animate={install.fresh}
      />
      <span className="install-row-text">
        {install.label} · {install.percent}%{eta ? ` · ${eta}` : ""}
      </span>
    </div>
  );
}
