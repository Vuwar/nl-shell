import { useEffect, useRef, useState } from "react";

// Phases that mean "there is a download to draw". Everything else the startup
// says - fetching llama.cpp, starting the server, a switch to weights that are
// already here - stays with the boot row it has always used. This screen is
// for the one wait that takes minutes, not for every wait.
const DRAWN = new Set([
  "resolving", "downloading", "verifying", "retrying",
  "refetching", "loading", "failed",
]);

// Reads the payload the Python side polls out, and keeps the two things a
// payload cannot carry: how far the grid has actually been filled, and whether
// this is the first payload of the session - because bytes already on disk did
// not arrive just now, and animating them would say they did.
//
// No state of its own. The poll that produces a new payload is already causing
// a render; a second source would only be a second way to be out of date.
export function useInstallProgress(status) {
  const filledRef = useRef(0);
  const seenRef = useRef(false);

  const payload = status && status.progress;
  if (!payload || !DRAWN.has(payload.phase)) {
    filledRef.current = 0;
    seenRef.current = false;
    return null;
  }

  const layers = payload.layers || 32;
  const target = ((payload.percent || 0) / 100) * layers;
  const fresh = seenRef.current;

  // Backward only where the backend says so. Bytes on disk can genuinely
  // fall, once, when a checksum fails and the file starts again; any other
  // decrease is two polls landing out of order, and a grid that flickers
  // backward reads as a bug.
  if (payload.phase === "refetching") filledRef.current = 0;
  else if (target > filledRef.current) filledRef.current = target;
  seenRef.current = true;

  return {
    phase: payload.phase,
    label: payload.label || "",
    layers,
    filled: filledRef.current,
    percent: payload.percent || 0,
    bytesDone: payload.bytes_done || 0,
    bytesTotal: payload.bytes_total || 0,
    rate: payload.rate || null,
    eta: payload.eta === undefined ? null : payload.eta,
    gpuLayers: payload.gpu_layers === undefined ? null : payload.gpu_layers,
    retry: payload.retry || null,
    firstInstall: !!payload.first_install,
    fresh,
  };
}

// Every phase in about forty seconds, driven by a timer instead of a
// multi-gigabyte download. Without this, looking at a change to the grid costs
// an evening. Reached with ?install=demo, and never in a build the user runs,
// because pywebview opens index.html with no query string.
export function useDemoProgress() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 200);
    return () => clearInterval(timer);
  }, []);

  const seconds = tick * 0.2;
  const total = 4.7e9;
  const layers = 28;

  let phase = "downloading";
  let percent = Math.min(100, Math.round((seconds / 30) * 100));
  let retry = null;
  if (seconds < 1) phase = "resolving";
  else if (seconds > 8 && seconds < 11) {
    phase = "retrying";
    percent = 27;
    retry = { attempt: 2, of: 8, wait: 3 };
  } else if (seconds > 18 && seconds < 20) {
    phase = "refetching";
    percent = 0;
  } else if (seconds > 30 && seconds < 33) {
    phase = "verifying";
    percent = 100;
  } else if (seconds >= 33 && seconds < 40) {
    phase = "loading";
    percent = 100;
  } else if (seconds >= 40) {
    return { progress: null };  // ready, so the panel plays its exit
  }

  return {
    progress: {
      phase, label: "Qwen2.5-Coder-7B", layers, first_install: true,
      bytes_done: Math.round((percent / 100) * total), bytes_total: total,
      percent, rate: 3.1e6, eta: Math.round(((100 - percent) / 100) * 780),
      gpu_layers: phase === "loading" ? 19 : undefined, retry,
    },
  };
}

export const DEMO = typeof location !== "undefined"
  && location.search.includes("install=demo");
