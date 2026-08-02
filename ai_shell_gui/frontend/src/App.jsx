import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";
import "./install/install.css";
import InstallPanel from "./install/InstallPanel";
import InstallRow from "./install/InstallRow";
import TileRing from "./install/TileRing";
import { formatBytes } from "./install/format";
import { DEMO, useDemoProgress, useInstallProgress } from "./install/useInstallProgress";

let nextId = 1;
const uid = () => nextId++;

// The identity every report of a failed model start shares. See upsertEntry.
const STARTUP_ERROR = "startup-error";

// --- key sounds: tiny synthesized ticks via Web Audio, no asset files ---
// Each keystroke is a short bandpassed noise "tap" plus a decaying tone blip;
// pitch is slightly randomized so held/fast typing doesn't sound robotic.
// A theme is just a parameter set for that same tiny synth.
const SOUND_THEMES = {
  glass: {
    label: "Glass",
    desc: "soft ticks",
    type: { noiseFreq: 2300, toneFreq: 980, dur: 0.05, gain: 0.05 },
    delete: { noiseFreq: 950, toneFreq: 420, dur: 0.07, gain: 0.055 },
    enter: { noiseFreq: 1400, toneFreq: 640, dur: 0.1, gain: 0.06 },
  },
  click: {
    label: "Click",
    desc: "mechanical",
    type: { noiseFreq: 3400, toneFreq: 1600, dur: 0.028, gain: 0.065, q: 2.6, toneLevel: 0.18 },
    delete: { noiseFreq: 1700, toneFreq: 750, dur: 0.04, gain: 0.07, q: 2.6, toneLevel: 0.18 },
    enter: { noiseFreq: 2300, toneFreq: 950, dur: 0.06, gain: 0.075, q: 2.2, toneLevel: 0.25 },
  },
  thock: {
    label: "Thock",
    desc: "deep & muted",
    type: { noiseFreq: 850, toneFreq: 250, dur: 0.08, gain: 0.075, q: 0.8 },
    delete: { noiseFreq: 560, toneFreq: 170, dur: 0.1, gain: 0.08, q: 0.8 },
    enter: { noiseFreq: 700, toneFreq: 210, dur: 0.12, gain: 0.085, q: 0.8 },
  },
  retro: {
    label: "Retro",
    desc: "8-bit blips",
    type: { toneFreq: 1250, dur: 0.04, gain: 0.04, wave: "square", noiseLevel: 0 },
    delete: { toneFreq: 520, dur: 0.05, gain: 0.045, wave: "square", noiseLevel: 0 },
    enter: { toneFreq: 830, dur: 0.09, gain: 0.05, wave: "square", noiseLevel: 0 },
  },
  off: {
    label: "Off",
    desc: "silence",
  },
};

const DEFAULT_SETTINGS = { soundTheme: "glass", volume: 0.5, minimizeOnBlur: true };

// The bottom of the opacity slider. Mirrors ai_shell.config.MIN_OPACITY, which
// clamps whatever this sends anyway - this is only where the track starts.
const MIN_OPACITY = 30;

function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem("aishell.settings") || "{}") };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

// Read by playKey outside the React tree; kept in sync by saveSettings.
let soundPrefs = loadSettings();

function saveSettings(next) {
  soundPrefs = next;
  try {
    localStorage.setItem("aishell.settings", JSON.stringify(next));
  } catch {
    // storage unavailable: settings just won't persist across restarts
  }
}

let _audioCtx = null;

function playKey(kind) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const theme = SOUND_THEMES[soundPrefs.soundTheme] || SOUND_THEMES.glass;
    const spec = theme[kind];
    // volume 0.5 is the reference level, so 1.0 doubles the base gains
    const vol = soundPrefs.volume * 2;
    if (!spec || vol <= 0) return;
    if (!_audioCtx) _audioCtx = new Ctx();
    const ctx = _audioCtx;
    if (ctx.state === "suspended") ctx.resume();

    const t = ctx.currentTime;
    const master = ctx.createGain();
    master.gain.value = spec.gain * vol;
    master.connect(ctx.destination);

    if ((spec.noiseLevel ?? 1) > 0) {
      const noise = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * spec.dur), ctx.sampleRate);
      const data = noise.getChannelData(0);
      for (let i = 0; i < data.length; i++) {
        data[i] = (Math.random() * 2 - 1) * (1 - i / data.length) ** 2 * (spec.noiseLevel ?? 1);
      }
      const src = ctx.createBufferSource();
      src.buffer = noise;
      const bp = ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.value = spec.noiseFreq * (0.9 + Math.random() * 0.2);
      bp.Q.value = spec.q ?? 1.1;
      src.connect(bp);
      bp.connect(master);
      src.start(t);
    }

    const osc = ctx.createOscillator();
    osc.type = spec.wave ?? "sine";
    const f = spec.toneFreq * (0.95 + Math.random() * 0.1);
    osc.frequency.setValueAtTime(f, t);
    osc.frequency.exponentialRampToValueAtTime(f * 0.55, t + spec.dur);
    const og = ctx.createGain();
    og.gain.setValueAtTime(spec.toneLevel ?? 0.5, t);
    og.gain.exponentialRampToValueAtTime(0.001, t + spec.dur);
    osc.connect(og);
    og.connect(master);
    osc.start(t);
    osc.stop(t + spec.dur);
  } catch {
    // audio is a garnish - never let it break input handling
  }
}

// Must match WINDOW_WIDTH and MINI_SIZE in gui/app.py - the window is sized
// from here, so these are the two shapes it can have.
const PANEL_WIDTH = 560;
const MINI_SIZE = 48;

// .panel's 1px border, top and bottom. The body measures the content inside
// it; the window has to hold both, or the input row loses its last two pixels.
const PANEL_EDGES = 2;

const GROW_MS = 220; // content grew or shrank
const FOLD_MS = 300; // folding into, or out of, the collapsed tile

const measure = (el) => el.getBoundingClientRect().height + PANEL_EDGES;

const reduceMotion = () =>
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Drives the OS window's size, since a frameless panel has no business being a
// fixed-size browser window: open, it hugs its content; collapsed, it is a
// MINI_SIZE tile.
//
// The observed element is the panel BODY, not the panel: the body is pinned to
// PANEL_WIDTH whatever the window is doing, so its height stays meaningful
// while the window is halfway through a fold - that measurement is what the
// unfold animates back to. Measuring anything window-width would instead
// report the height of the content reflowed into a 48px column.
function useWindowGeometry(bodyRef, ready, mini) {
  const rafRef = useRef(null);
  const appliedRef = useRef(null); // last geometry handed to Python
  const contentRef = useRef(MINI_SIZE); // last measured body height
  const miniRef = useRef(mini);

  const animate = (duration) => {
    cancelAnimationFrame(rafRef.current);
    const to = miniRef.current
      ? { w: MINI_SIZE, h: MINI_SIZE }
      : { w: PANEL_WIDTH, h: contentRef.current };
    const from = appliedRef.current ?? to;

    const apply = (w, h) => {
      appliedRef.current = { w, h };
      window.pywebview.api.resize(Math.round(w), Math.round(h));
    };
    if (duration === 0 || (Math.abs(from.w - to.w) < 1 && Math.abs(from.h - to.h) < 1)) {
      apply(to.w, to.h);
      return;
    }
    const startTime = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      apply(from.w + (to.w - from.w) * eased, from.h + (to.h - from.h) * eased);
      if (t < 1) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
  };

  useEffect(() => {
    if (!ready || !bodyRef.current) return;
    const el = bodyRef.current;
    contentRef.current = measure(el);
    appliedRef.current = { w: PANEL_WIDTH, h: contentRef.current };

    const ro = new ResizeObserver((entriesList) => {
      contentRef.current = measure(entriesList[0].target);
      // Collapsed, the window's size is the tile's, not the content's - the
      // new height is only recorded, to be unfolded to later.
      if (!miniRef.current) animate(reduceMotion() ? 0 : GROW_MS);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(rafRef.current);
    };
  }, [ready]);

  useEffect(() => {
    if (!ready) return;
    miniRef.current = mini;
    animate(reduceMotion() ? 0 : FOLD_MS);
  }, [mini, ready]);
}

const COMMANDS = [
  { name: "/settings", aliases: ["/config"], desc: "Open settings" },
  { name: "/clear", aliases: [], desc: "Clear the output" },
];

// Nothing here is discoverable from an empty box, so the empty box teaches it:
// instead of one static "Ask anything...", the placeholder cycles through the
// things you'd otherwise have to be told. `key` is the literal thing to press
// or type and gets highlighted; hints without one are plain sentences.
const HINTS = [
  { text: "Ask for anything in plain English" },
  { key: "exit", text: "on its own closes the window" },
  { key: "/", text: "opens the commands - /settings, /clear" },
  { key: "Esc", text: "clears the screen when you're done" },
  { key: "↑ ↓", text: "step back through what you've asked" },
  { key: "Tab", text: "fills in the highlighted command" },
  { key: "Enter", text: "sends it - no need to know the command" },
  { text: "Anything destructive asks you first" },
  { text: "Ask a follow-up - it remembers the conversation" },
  { key: "/settings", text: "has typing sounds, volume and which model runs" },
  // Precise on purpose: the model really is local, and a web search really
  // does send the query out. Overstating the first would make a liar of the
  // app the first time somebody asks it to look something up.
  { text: "Runs on a local model - only web searches leave this PC" },
  { text: "Ask about the world and it looks it up on the web" },
  { text: "Click a folder in a listing to open it" },
  { text: "Click a file in a listing to open it with Windows" },
  { text: "Click a folder in the path row to go back up" },
  { text: "“Show detailed” adds size, type and date" },
  { text: "Copy buttons put any output on the clipboard" },
  { text: "Drag anywhere on the panel to move the window" },
  { text: "Click away and it shrinks - click the tile to bring it back" },
  { text: "Not sure? Ask “what's taking up my disk space”" },
  { text: "When it asks something, click an answer or type your own" },
  { text: "The dot on the left shows what it's doing" },
];

// How long the window has to stay unfocused before it folds away.
const BLUR_GRACE = 380;

// How far a press on the tile may travel and still count as a click rather
// than a drag. Windows' own drag threshold is 4px.
const DRAG_SLOP = 4;

// How long focus waits for a press on the tile to claim it before the panel
// unfolds on its own. Only ever costs this much when the app is folded.
const OPEN_GRACE = 140;

const HINT_HOLD = 9000; // how long a hint stays up
const HINT_FADE = 320; // must match .input-hint's transition in App.css

// Rotates HINTS while the input is idle. A shuffled bag rather than a random
// pick each time, so you see every hint once before any of them repeat.
// Returns advance() so a send can turn the page too: you've just proved you
// know how to send something, and the next empty box is a fresh chance to
// show you something you don't know yet.
export function useRotatingHint(paused) {
  const bag = useRef([]);
  const fade = useRef(null);

  const draw = () => {
    if (bag.current.length === 0) {
      bag.current = HINTS.map((_, i) => i);
      for (let i = bag.current.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [bag.current[i], bag.current[j]] = [bag.current[j], bag.current[i]];
      }
    }
    return bag.current.pop();
  };

  const [idx, setIdx] = useState(draw);
  const [shown, setShown] = useState(true);

  // Deliberately not cancelled when the timer below is torn down: a swap
  // already in flight has to land, or the hint stays faded out forever.
  const advance = () => {
    clearTimeout(fade.current);
    setShown(false);
    fade.current = setTimeout(() => {
      setIdx(draw());
      setShown(true);
    }, HINT_FADE);
  };

  useEffect(() => () => clearTimeout(fade.current), []);

  useEffect(() => {
    if (paused) return;
    const cycle = setInterval(advance, HINT_HOLD);
    return () => clearInterval(cycle);
  }, [paused]);

  return { hint: HINTS[idx], shown, advance };
}

// pywebview's easy_drag makes a mousedown anywhere in the window start moving
// it, which is what a frameless panel wants everywhere except on a control
// that has its own idea of what dragging means - a slider, a scrollbar, a
// selectable block of text. It listens on `window`, and React hands us the
// native event on its way there, so stopping it here is enough to keep the
// two from fighting over the same gesture.
const keepGesture = (e) => e.stopPropagation();

// The confirmation for a risky command: what it is, and a chance to fix it.
// Its own component because the edit box holds state, and the entry list that
// renders it is otherwise stateless.
function ConfirmRow({ command, onDecide }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(command);
  const areaRef = useRef(null);

  useEffect(() => {
    if (editing && areaRef.current) {
      areaRef.current.focus();
      const end = areaRef.current.value.length;
      areaRef.current.setSelectionRange(end, end);
    }
  }, [editing]);

  function submitEdit() {
    const text = draft.trim();
    // An empty edit cancels rather than running an empty command - the same
    // rule the console REPL follows.
    onDecide(text ? { proceed: true, command: text } : { proceed: false, command: null });
  }

  function onKeyDown(e) {
    // Shift+Enter inserts a newline: a "command" may be a short script.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitEdit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onDecide({ proceed: false, command: null });
    }
  }

  return (
    <div className="entry confirm-block">
      {editing ? (
        <textarea
          ref={areaRef}
          className="confirm-edit"
          value={draft}
          spellCheck={false}
          rows={Math.min(6, draft.split("\n").length)}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onMouseDown={keepGesture}
        />
      ) : (
        <pre className="confirm-command" onMouseDown={keepGesture}>
          {command}
        </pre>
      )}
      <div className="confirm-row">
        <span>Run this? It can't easily be undone.</span>
        {editing ? (
          <button className="btn run" onClick={submitEdit}>
            Run it
          </button>
        ) : (
          <>
            <button
              className="btn run"
              onClick={() => onDecide({ proceed: true, command: null })}
            >
              Run it
            </button>
            <button className="btn" onClick={() => setEditing(true)}>
              Edit
            </button>
          </>
        )}
        <button
          className="btn cancel"
          onClick={() => onDecide({ proceed: false, command: null })}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

async function writeClipboard(text) {
  // Focus moves to the scratch textarea in the fallback path; the input has to
  // get it back or the next keystroke goes nowhere.
  const previous = document.activeElement;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // blocked or unavailable - the execCommand path below still works
  }
  try {
    const scratch = document.createElement("textarea");
    scratch.value = text;
    scratch.style.position = "fixed";
    scratch.style.top = "-1000px";
    scratch.style.opacity = "0";
    document.body.appendChild(scratch);
    scratch.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(scratch);
    return ok;
  } catch {
    return false;
  } finally {
    if (previous && previous.focus) previous.focus();
  }
}

function CopyButton({ text, floating }) {
  const [state, setState] = useState("idle"); // idle | copied | failed
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function copy() {
    const ok = await writeClipboard(text);
    setState(ok ? "copied" : "failed");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 1400);
  }

  return (
    <button
      type="button"
      className={`copy-btn${floating ? " floating" : ""} ${state}`}
      onClick={copy}
      title="Copy to clipboard"
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Couldn't copy" : "Copy"}
    </button>
  );
}

// .lnk/.url files are shortcuts - the extension is plumbing, so it's dropped
// from the displayed name and surfaced as a "Shortcut" type instead.
const SHORTCUT_EXT = /\.(lnk|url)$/i;
const SIZE_UNITS = ["KB", "MB", "GB", "TB", "PB"];

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return "";
  if (bytes < 1024) return `${bytes} B`;
  let value = bytes / 1024;
  for (let i = 0; i < SIZE_UNITS.length; i++) {
    if (value < 1024 || i === SIZE_UNITS.length - 1) {
      return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${SIZE_UNITS[i]}`;
    }
    value /= 1024;
  }
}

function fileKind(item) {
  if (item.dir) return "Folder";
  if (SHORTCUT_EXT.test(item.name)) return "Shortcut";
  const dot = item.name.lastIndexOf(".");
  return dot > 0 ? item.name.slice(dot + 1).toUpperCase() : "File";
}

function formatModified(iso) {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// The rows are divs, and everything outside an input/pre has user-select:none,
// so this is the only way a listing leaves the window.
function listingToText(path, items, detailed) {
  const rows = items.map((item) => ({
    name: item.dir ? item.name : item.name.replace(SHORTCUT_EXT, ""),
    size: item.dir ? "-" : formatSize(item.size),
    kind: fileKind(item),
    date: formatModified(item.modified),
  }));
  const width = (key) => Math.max(...rows.map((row) => row[key].length));
  const [nameWidth, sizeWidth, kindWidth] = [width("name"), width("size"), width("kind")];
  const lines = rows.map((row) => {
    const head = `${row.name.padEnd(nameWidth)}  ${row.size.padStart(sizeWidth)}`;
    return detailed ? `${head}  ${row.kind.padEnd(kindWidth)}  ${row.date}` : head;
  });
  return (path ? `${path}\n` : "") + lines.join("\n");
}

// Each segment of the current folder navigates to that level, which is also
// how you go back up. Drive-letter and POSIX paths both split cleanly, so
// anything else (a UNC share) is shown as plain text rather than mis-parsed
// into links.
function Crumbs({ path, onGo, disabled }) {
  const drive = /^[a-zA-Z]:\\/.test(path);
  const rooted = path.startsWith("/");
  if (!drive && !rooted) {
    return <div className="listing-path">{path}</div>;
  }
  const sep = drive ? "\\" : "/";
  const segments = path.split(sep).filter(Boolean);
  // A POSIX path starts at the root, which is somewhere you can navigate to
  // but isn't a named segment, so it gets a crumb of its own.
  const parts = rooted ? ["/", ...segments] : segments;
  const targetOf = (i) => {
    if (rooted) return i === 0 ? "/" : "/" + parts.slice(1, i + 1).join("/");
    // The drive needs its trailing slash - "C:" alone means something else
    // to PowerShell (the current directory on that drive).
    return i === 0 ? `${parts[0]}\\` : parts.slice(0, i + 1).join("\\");
  };
  return (
    <div className="listing-path">
      {parts.map((part, i) => {
        const last = i === parts.length - 1;
        const target = targetOf(i);
        return (
          <span key={target}>
            {/* the root crumb is itself a separator, so it never takes one */}
            {i > (rooted ? 1 : 0) && <span className="crumb-sep">{sep}</span>}
            {last ? (
              <span className="crumb current">{part}</span>
            ) : (
              <button
                type="button"
                className="crumb"
                disabled={disabled}
                onClick={() => onGo(target)}
              >
                {part}
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}

function Listing({ path, items, kind, busy }) {
  // Name + size is what a listing is usually asked for; the timestamp and file
  // type are one click away rather than in every row.
  const [detailed, setDetailed] = useState(false);
  // Navigation replaces the rows in place instead of pushing a new entry, so
  // browsing a few folders deep doesn't bury the conversation under listings.
  const [view, setView] = useState({ path, items, kind });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const locked = busy || loading;
  const { path: here, items: rows, kind: rowKind } = view;

  async function go(target) {
    if (locked) return;
    setLoading(true);
    setError("");
    try {
      const res = await window.pywebview.api.browse(target);
      if (res && res.ok) setView({ path: res.path, items: res.listing, kind: res.kind });
      else setError((res && res.reason) || "Couldn't open that folder.");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function activate(item) {
    if (locked) return;
    if (item.dir) return go(item.path);
    setLoading(true);
    setError("");
    try {
      const res = await window.pywebview.api.open_path(item.path);
      if (!(res && res.ok)) setError((res && res.reason) || "Couldn't open that.");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={`entry listing${loading ? " loading" : ""}`}>
      {here && <Crumbs path={here} onGo={go} disabled={locked} />}
      {rows.length === 0 ? (
        // Still inside the frame, so the breadcrumbs above remain - an empty
        // folder must not be a dead end.
        <div className="listing-empty">
          {rowKind === "item" ? "Nothing there." : `No ${rowKind}s there.`}
        </div>
      ) : (
        <div className={`listing-rows${detailed ? " detailed" : ""}`}>
          {rows.map((item) => (
            <button
              type="button"
              className="listing-row"
              key={item.path}
              disabled={locked}
              title={item.dir ? `Open ${item.name}` : `Open ${item.name} with Windows`}
              onClick={() => activate(item)}
            >
              <span className={`listing-name${item.dir ? " dir" : ""}`}>
                {item.dir ? item.name : item.name.replace(SHORTCUT_EXT, "")}
              </span>
              {/* A folder's size slot carries the chevron instead - it says
                  "this one goes somewhere" where a size would say nothing. */}
              <span className="listing-size">
                {item.dir ? <span className="listing-chevron">›</span> : formatSize(item.size)}
              </span>
              {detailed && <span className="listing-kind">{fileKind(item)}</span>}
              {detailed && <span className="listing-date">{formatModified(item.modified)}</span>}
            </button>
          ))}
        </div>
      )}
      {error && <div className="listing-error">{error}</div>}
      {rows.length > 0 && (
        <div className="listing-foot">
          <button type="button" className="listing-toggle" onClick={() => setDetailed(!detailed)}>
            {detailed ? "Hide details" : "Show detailed"}
          </button>
          <CopyButton text={listingToText(here, rows, detailed)} />
          <span className="listing-count">
            {rows.length} {rowKind}
            {rows.length === 1 ? "" : "s"}
          </span>
        </div>
      )}
    </div>
  );
}

// A web answer as text, for the copy button - the answer plus the numbered
// sources, so what leaves the window still says where it came from. The read
// marks come too: pasted somewhere else, they're what says which of these the
// answer was actually drawn out of.
function answerToText(answer, sources) {
  const lines = sources.map(
    (s, i) => `[${i + 1}] ${s.title}\n    ${s.url}${s.read ? "  · read" : ""}`
  );
  return (answer ? `${answer}\n\n` : "") + lines.join("\n");
}

// The host is what tells you whether to believe a result at a glance, and it's
// the part of a URL that fits on one line of a 560px panel.
function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function WebAnswer({ answer, sources, caveat, busy }) {
  const [error, setError] = useState("");

  async function open(url) {
    if (busy) return;
    setError("");
    try {
      const res = await window.pywebview.api.open_url(url);
      if (!(res && res.ok)) setError((res && res.reason) || "Couldn't open that page.");
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="entry answer">
      {/* Selectable like command output is - an answer people will want to
          quote out of, not just read. */}
      {answer && (
        <div className="answer-text" onMouseDown={keepGesture}>
          {answer}
        </div>
      )}
      {caveat && <div className="answer-caveat">{caveat}</div>}
      {/* Always shown, whether or not the model managed a summary: the
          sources are the result, and the sentence above them is the
          convenience. A model that came back with nothing still leaves the
          user somewhere to click. */}
      <div className="answer-sources">
        {sources.map((source, i) => (
          <button
            type="button"
            className="answer-source"
            key={source.url + i}
            disabled={busy}
            onClick={() => open(source.url)}
            title={source.url}
          >
            <span className="source-index">[{i + 1}]</span>
            <span className="source-title">{source.title}</span>
            {/* Only on the ones whose page was opened and read. There's no
                matching mark for the others, deliberately: nothing went wrong
                when a page won't read, and a row of failure badges would say
                it did. */}
            {source.read && <span className="source-read">read</span>}
            <span className="source-host">{hostOf(source.url)}</span>
          </button>
        ))}
      </div>
      {error && <div className="listing-error">{error}</div>}
      <div className="answer-foot">
        <CopyButton text={answerToText(answer, sources)} />
        <span className="answer-count">from the web</span>
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="thinking-dots">
      <span />
      <span />
      <span />
    </div>
  );
}

function Entry({ entry, onConfirm, onChoose, onRetry, busy }) {
  switch (entry.kind) {
    case "user":
      return (
        <div className="entry entry-user">
          <span className="arrow">›</span>
          {entry.text}
        </div>
      );
    case "system":
      return <div className="entry system-line">{entry.text}</div>;
    case "error":
      return (
        <div className="entry system-line error-line" style={{ color: "var(--danger)" }}>
          <span>{entry.text}</span>
          {entry.retry ? (
            <button type="button" className="btn retry" onClick={onRetry}>
              Try again
            </button>
          ) : null}
        </div>
      );
    case "explanation":
      return <div className="entry entry-explanation">{entry.text}</div>;
    case "choices":
      return (
        <div className="entry entry-explanation">
          {entry.text}
          <div className="choice-row">
            {entry.options.map((opt) => (
              <button
                key={opt}
                type="button"
                className={`choice-chip${entry.chosen === opt ? " chosen" : ""}`}
                disabled={entry.answered}
                onClick={() => onChoose(entry.id, opt)}
              >
                {opt}
              </button>
            ))}
            <button
              type="button"
              className={`choice-chip other${entry.chosen === null && entry.answered ? " chosen" : ""}`}
              disabled={entry.answered}
              onClick={() => onChoose(entry.id, null)}
            >
              Other…
            </button>
          </div>
        </div>
      );
    case "fail":
      return (
        <div className="entry fail-line">
          <span className="fail-mark">✕</span>
          {entry.text}
        </div>
      );
    case "confirm":
      return (
        <ConfirmRow
          command={entry.command}
          onDecide={(decision) => onConfirm(entry.id, decision)}
        />
      );
    case "skipped":
      return <div className="entry system-line">Skipped.</div>;
    case "notice":
      // Why that took so long. Said once a session, and never urgent enough
      // to be dismissable - it goes away with everything else on /clear.
      return <div className="entry entry-notice">{entry.text}</div>;
    case "output":
      return (
        <div className="entry entry-output">
          {/* Selectable (see index.css), which it can only actually be if
              dragging across it selects instead of moving the window. */}
          <pre className="output-block" onMouseDown={keepGesture}>
            {entry.text}
          </pre>
          <CopyButton text={entry.text} floating />
        </div>
      );
    case "listing":
      // entry.kind is the entry type ("listing"); kindLabel is what the rows
      // are - "folder", "file" or "item".
      return (
        <Listing path={entry.path} items={entry.items} kind={entry.kindLabel} busy={busy} />
      );
    case "answer":
      return (
        <WebAnswer
          answer={entry.text}
          sources={entry.sources}
          caveat={entry.caveat}
          busy={busy}
        />
      );
    case "done":
      return (
        <div className="entry done-line">
          <span className="done-mark">✓</span>
          Done
        </div>
      );
    case "thinking":
      return (
        <div className="entry">
          <ThinkingDots />
        </div>
      );
    default:
      return null;
  }
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [entries, setEntries] = useState([]);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | thinking | ok | error
  // What the model server is doing while it starts, or null once it's up.
  const [booting, setBooting] = useState(null);
  // The same start as numbers, when there is a weights download worth
  // drawing. Null for every other kind of wait, which is most of them.
  const [startup, setStartup] = useState(null);
  // The version waiting to be installed, once one has finished downloading.
  // Null until then - a check nobody asked for shouldn't be visible while
  // it's happening, only when it has something to offer.
  const [updateReady, setUpdateReady] = useState(null);
  const [updating, setUpdating] = useState(false);
  const [focused, setFocused] = useState(false);
  // Folded into the corner tile because the app isn't the one being used.
  const [minimized, setMinimized] = useState(false);
  const [clearing, setClearing] = useState(false);
  // Where the tile was pressed, whether that press is holding it folded, and
  // whether it is folded right now - all read from callbacks that must not be
  // rebuilt every time one of them changes.
  const pressAt = useRef(null);
  const holdFolded = useRef(false);
  const foldedRef = useRef(false);
  const [view, setView] = useState("shell"); // shell | settings
  const [prefs, setPrefs] = useState(soundPrefs);
  // What this machine can run, for the settings screen's model list. Fetched
  // when that screen opens rather than at startup: it reads the filesystem,
  // and nothing needs it until somebody is looking at it.
  const [modelList, setModelList] = useState({ models: [], editable: true, model_dir: "" });
  // How see-through the window is, 30-100. Python owns this one rather than
  // localStorage: it is a native window property, applied before this page
  // exists so the panel doesn't flash solid on every launch. Null until read.
  const [opacity, setOpacity] = useState(null);
  const [selIdx, setSelIdx] = useState(0);
  // Everything the user has sent, oldest first, for Up/Down recall.
  const sent = useRef([]);
  // Where Up/Down currently sits in `sent`; null means editing a fresh line.
  const recallIdx = useRef(null);
  // What was typed before the first Up, so Down can come back to it.
  const draft = useRef("");

  // Slash-command suggestions shown while the input starts with "/".
  const slashQuery = value.trim().toLowerCase();
  const suggestions =
    view === "shell" && slashQuery.startsWith("/")
      ? COMMANDS.filter((c) => [c.name, ...c.aliases].some((n) => n.startsWith(slashQuery)))
      : [];

  useEffect(() => setSelIdx(0), [value]);

  // Hints only rotate on an idle, empty, visible input - never while you're
  // typing into it, reading a result, or looking at the collapsed tile.
  const { hint, shown: hintShown, advance: nextHint } = useRotatingHint(
    view !== "shell" || value !== "" || busy || entries.length > 0 || minimized
  );

  // The weights download, as something to draw. Null unless one is running.
  const demo = useDemoProgress();
  const install = useInstallProgress(DEMO ? demo : startup);

  // The install screen outlives its payload by the length of its own exit.
  // Unmounting the moment the server is ready would cut the grid off at the
  // frame it finally had something good to say.
  const [leaving, setLeaving] = useState(false);
  const wasInstalling = useRef(false);
  useEffect(() => {
    if (install) {
      wasInstalling.current = true;
      return undefined;
    }
    if (!wasInstalling.current) return undefined;
    wasInstalling.current = false;
    setLeaving(true);
    const timer = setTimeout(() => setLeaving(false), 260); // installCollapse
    return () => clearTimeout(timer);
  }, [install]);

  // What to render: the live install, or the one being seen out.
  const lastInstall = useRef(null);
  if (install) lastInstall.current = install;
  const shownInstall = install || (leaving ? lastInstall.current : null);

  // Settings view: Esc closes it; returning to the shell refocuses the input.
  useEffect(() => {
    if (view === "settings") {
      const onKey = (e) => {
        if (e.key === "Escape") setView("shell");
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
    inputRef.current?.focus();
  }, [view]);

  useEffect(() => {
    if (view !== "settings" || !window.pywebview) return;
    window.pywebview.api.list_models().then(setModelList).catch(() => {});
  }, [view]);

  // Read once the bridge exists. The window is already at this opacity - this
  // is the slider catching up with it, and the CSS below dressing to match.
  useEffect(() => {
    const load = () => window.pywebview.api.opacity().then(setOpacity).catch(() => {});
    if (window.pywebview) {
      load();
      return;
    }
    window.addEventListener("pywebviewready", load);
    return () => window.removeEventListener("pywebviewready", load);
  }, []);

  // The panel's own glass is thinned to match. Below full opacity the sheen
  // gradient is sitting on top of somebody's wallpaper rather than on a dark
  // panel, where it reads as a smear.
  useEffect(() => {
    if (opacity == null) return;
    document.documentElement.style.setProperty("--panel-alpha", opacity / 100);
  }, [opacity]);

  // Dragging: the window follows every frame, nothing is written down. The
  // value the user lets go of is the only one worth keeping, and set_opacity
  // on the change event is what keeps a drag off the disk.
  function dragOpacity(percent) {
    setOpacity(percent);
    if (!window.pywebview) return;
    window.pywebview.api.preview_opacity(percent).catch(() => {});
  }

  function saveOpacity(percent) {
    if (!window.pywebview) return;
    window.pywebview.api.set_opacity(percent).then(setOpacity).catch(() => {});
  }

  function updatePrefs(partial) {
    const next = { ...prefs, ...partial };
    saveSettings(next);
    setPrefs(next);
  }

  // The graphics-card explanation, wherever it came from. The route out of it
  // is added here rather than in Python: the console's answer to the same
  // situation is a typed word, and the shared text names neither.
  function showNotice(notice) {
    if (notice) {
      addEntry({ kind: "notice", text: `${notice} Open /settings to switch model.` });
    }
  }

  function switchModel(model) {
    if (model.current || modelList.editable === false) return;
    const size = model.installed ? "" : ` It's a ${model.weights_gb}GB download.`;
    if (!window.confirm(`Switch to ${model.label}?${size}`)) return;
    setView("shell");
    window.pywebview.api.switch_model(model.id).then((result) => {
      if (result && result.ok === false) {
        addEntry({ kind: "error", text: result.reason });
        return;
      }
      // The swap runs on a Python thread and reports through the same startup
      // status the app's own launch does, so the boot row is what shows it.
      watchStartup();
    });
  }

  // The backend keeps the history, folder context and last listing that a
  // follow-up like "open it" resolves against. None of that may outlive the
  // output on screen: a session that survives a clear answers the next
  // message against a conversation the user can no longer see.
  function forgetSession() {
    window.pywebview?.api?.clear?.().catch(() => {});
  }

  function execCommand(cmd) {
    setValue("");
    if (cmd.name === "/settings") {
      setView("settings");
    } else if (cmd.name === "/clear") {
      setEntries([]);
      setStatus("idle");
      forgetSession();
      nextHint();
    }
  }

  const panelRef = useRef(null);
  const bodyRef = useRef(null);
  const outputRef = useRef(null);
  const inputRef = useRef(null);
  const mirrorRef = useRef(null);
  const confirmResolvers = useRef({});

  // The visible text lives in the mirror overlay (so each character can
  // animate in); keep its horizontal scroll locked to the real input's.
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      if (inputRef.current && mirrorRef.current) {
        mirrorRef.current.scrollLeft = inputRef.current.scrollLeft;
      }
    });
    return () => cancelAnimationFrame(id);
  }, [value]);

  useWindowGeometry(bodyRef, ready, minimized);

  // An always-on-top panel that keeps its full width while you're working in
  // another window is just something in the way, so it folds into a corner
  // tile the moment it stops being the thing being used, and unfolds when it
  // gets focus back (or when the tile is clicked, which does both).
  //
  // The grace period is what keeps it from flickering: focus bounces for a
  // moment when a native dialog opens or the panel opens a file with Windows,
  // and folding on those would be noise.
  useEffect(() => {
    if (!ready) return;
    if (!prefs.minimizeOnBlur) {
      setMinimized(false);
      return;
    }
    let foldTimer = null;
    let openTimer = null;
    const sync = (hasFocus) => {
      if (hasFocus) {
        clearTimeout(foldTimer);
        foldTimer = null;
        if (!foldedRef.current || holdFolded.current || openTimer !== null) return;
        // Not opened on the spot: Windows activates a window on mouse DOWN
        // and the focus event beats the mousedown to the page, so opening
        // here immediately would open the panel before it could be told the
        // press was somebody picking the tile up to move it. This is the
        // moment that press gets to say so (see onTilePress) - and it's
        // short enough that returning by Alt-Tab still feels instant.
        openTimer = setTimeout(() => {
          openTimer = null;
          if (!holdFolded.current) setMinimized(false);
        }, OPEN_GRACE);
      } else {
        clearTimeout(openTimer);
        openTimer = null;
        // Whatever the hold was for, it ended when the app stopped being the
        // one in front; coming back should open the panel like normal.
        holdFolded.current = false;
        if (foldTimer === null) foldTimer = setTimeout(() => setMinimized(true), BLUR_GRACE);
      }
    };
    const onBlur = () => sync(false);
    const onFocus = () => sync(true);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    // The events above are the fast path, not the truth: the document's focus
    // is the web view's, and it drifts from the window's (observed: another
    // app takes the foreground and no blur ever arrives, leaving the panel
    // open over someone else's work). So the state is reconciled against the
    // window the OS actually has in front - the events just get there sooner.
    const check = async () => {
      let active;
      try {
        active = await window.pywebview.api.window_focused();
      } catch {
        return; // window closing - nothing left to fold
      }
      sync(active === null ? document.hasFocus() : active);
    };
    const poll = setInterval(check, 700);
    check();
    return () => {
      clearTimeout(foldTimer);
      clearTimeout(openTimer);
      clearInterval(poll);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
    };
  }, [ready, prefs.minimizeOnBlur]);

  // Unfolding is only useful if you can type into what came back. Folding
  // drops the caret the other way, so what's hidden isn't also what's focused.
  useEffect(() => {
    foldedRef.current = minimized;
    if (minimized) {
      inputRef.current?.blur();
      return;
    }
    if (view !== "shell") return;
    inputRef.current?.focus();
    // The window is still tile-width for the length of the unfold, so that
    // focus lands on an input hanging off the side of the viewport, and an
    // engine that scrolls to reveal it leaves the panel shifted left for good
    // (App.css stops this at source where `overflow: clip` is supported).
    const id = requestAnimationFrame(() => {
      if (panelRef.current) panelRef.current.scrollLeft = 0;
    });
    return () => cancelAnimationFrame(id);
  }, [minimized]);

  // Pressing the tile has two meanings - open it, or pick it up and move it
  // somewhere - and they start identically. So a press holds the fold shut
  // and only a release that didn't travel counts as opening it.
  //
  // The hold is what makes dragging work at all: moving the window means
  // clicking it, clicking it hands it focus, and focus is otherwise exactly
  // what opens the panel. Screen coordinates, not client ones, because the
  // window is moving with the pointer - relative to it, nothing travels.
  function onTilePress(e) {
    pressAt.current = { x: e.screenX, y: e.screenY };
    holdFolded.current = true;
  }

  function onTileRelease(e) {
    const from = pressAt.current;
    pressAt.current = null;
    const travelled =
      from && Math.max(Math.abs(e.screenX - from.x), Math.abs(e.screenY - from.y)) > DRAG_SLOP;
    if (travelled) return; // a move, not an open - the hold stays on
    holdFolded.current = false;
    setMinimized(false);
  }

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [entries]);

  // The window opens before the model server is up, so the first thing to do
  // is watch that start rather than assume it happened. Polled rather than
  // pushed: pywebview's bridge only calls in this direction, and a 400ms tick
  // on a line of text costs nothing next to what it's waiting for.
  // `stopped` is the window closing; `running` stops a Retry click starting a
  // second poll alongside the first. Both live in a ref because the watcher
  // outlives the render that started it - it is restarted by the Retry button
  // as well as by the effect below.
  const startupWatch = useRef({ stopped: false, running: false });

  const watchStartup = useCallback(async () => {
    const watch = startupWatch.current;
    if (watch.running) return;
    watch.running = true;
    try {
      while (!watch.stopped) {
        let state;
        try {
          state = await window.pywebview.api.startup_status();
        } catch {
          return; // window closing - nothing left to report to
        }
        if (watch.stopped) return;
        if (state.state === "starting") {
          setBooting(state.message);
          setStartup(state);
          await new Promise((r) => setTimeout(r, 400));
          continue;
        }
        setBooting(null);
        if (state.state === "failed") {
          setStatus("error");
          // Kept rather than cleared: the payload still carries how far the
          // download got, and the grid freezes there instead of vanishing at
          // the moment there is something to explain.
          setStartup(state);
          upsertEntry(STARTUP_ERROR, { kind: "error", text: state.message, retry: true });
          return;
        }
        setStartup(null);
        // The graphics card has room for the model, or it hasn't. Said here
        // rather than during the wait: it describes how the app will behave
        // from now on, not what it is doing at this second.
        if (state.notice) {
          addEntry({ kind: "notice", text: `${state.notice} Open /settings to switch model.` });
        }
        // Ready - confirm it can actually be talked to, which is a different
        // question from whether the process started.
        const res = await window.pywebview.api.check_connection();
        if (!res.ok && !watch.stopped) {
          setStatus("error");
          upsertEntry(STARTUP_ERROR, { kind: "error", text: res.error, retry: true });
        }
        return;
      }
    } finally {
      watch.running = false;
    }
  }, []);

  useEffect(() => {
    function onReady() {
      setReady(true);
      watchStartup();
    }
    if (window.pywebview) onReady();
    else window.addEventListener("pywebviewready", onReady);
    return () => {
      startupWatch.current.stopped = true;
      window.removeEventListener("pywebviewready", onReady);
    };
  }, [watchStartup]);

  // Starting the model again after a start that failed. The backend refuses
  // unless there is a failure to retry, so a double-click costs nothing; and
  // because the partial download survives, this resumes rather than restarts.
  async function onRetryStartup() {
    let res;
    try {
      res = await window.pywebview.api.retry_startup();
    } catch {
      return; // window closing
    }
    if (!res || !res.ok) return;
    setStatus("idle");
    setEntries((prev) => prev.filter((e) => e.key !== STARTUP_ERROR));
    watchStartup();
  }

  // The other thing happening in the background at startup: a look for a
  // newer version of the app. Nothing is shown while it checks or downloads -
  // an update the user can't act on yet is noise - so this watches for the
  // one state that has anything to say, and then stops watching.
  useEffect(() => {
    if (!ready) return;
    let stopped = false;
    let idleTicks = 0;

    async function watchUpdate() {
      while (!stopped) {
        let state;
        try {
          state = await window.pywebview.api.update_status();
        } catch {
          return; // window closing
        }
        if (stopped) return;
        if (state.state === "ready") {
          setUpdateReady(state);
          return;
        }
        // "failed" is the end of it too, and deliberately silent: a failed
        // update check is not the user's problem to solve mid-sentence.
        if (state.state === "failed") return;
        // "idle" is both "nothing to update" and "the thread hasn't started
        // yet", so a few ticks of it are given before taking it as the answer.
        if (state.state === "idle" && ++idleTicks > 4) return;
        await new Promise((r) => setTimeout(r, 3000));
      }
    }

    watchUpdate();
    return () => {
      stopped = true;
    };
  }, [ready]);

  async function onInstallUpdate() {
    if (updating) return;
    setUpdating(true);
    try {
      const result = await window.pywebview.api.install_update();
      // Success closes the window from the Python side, so anything that
      // comes back here is a failure worth showing.
      if (!result.ok) {
        setUpdateReady(null);
        addEntry({ kind: "error", text: result.error });
      }
    } catch {
      setUpdateReady(null);
    } finally {
      setUpdating(false);
    }
  }

  function addEntry(partial) {
    const entry = { id: uid(), ...partial };
    setEntries((prev) => [...prev, entry]);
    return entry.id;
  }

  // A startup failure is reported by two different paths - the watcher below,
  // and a request that was held while the server started and has to be
  // answered somehow. Both are right; only the display was duplicated. Giving
  // the entry a stable key makes the second report replace the first.
  function upsertEntry(key, partial) {
    setEntries((prev) => {
      const at = prev.findIndex((e) => e.key === key);
      if (at < 0) return [...prev, { id: uid(), key, ...partial }];
      const next = [...prev];
      next[at] = { ...next[at], ...partial };
      return next;
    });
  }

  function askConfirmation(command) {
    return new Promise((resolve) => {
      const id = addEntry({ kind: "confirm", command });
      confirmResolvers.current[id] = resolve;
    });
  }

  function onConfirmClick(id, decision) {
    setEntries((prev) => prev.filter((e) => e.id !== id));
    const resolve = confirmResolvers.current[id];
    delete confirmResolvers.current[id];
    if (resolve) resolve(decision);
  }

  function onChooseOption(id, option) {
    if (busy) return;
    // Lock the question's chips so old questions can't be re-answered later.
    setEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, answered: true, chosen: option } : e))
    );
    if (option === null) {
      // "Other" - let the user type what they actually want.
      inputRef.current?.focus();
      return;
    }
    // Chips submit as if the option had been typed, so recall should have it.
    remember(option);
    runRequest(option);
  }

  // cmd-style recall: remember what was sent, and start each new line fresh
  // rather than wherever Up had wandered to.
  function remember(text) {
    if (sent.current[sent.current.length - 1] !== text) sent.current.push(text);
    recallIdx.current = null;
    draft.current = "";
  }

  function recall(step) {
    const list = sent.current;
    if (list.length === 0) return;
    let idx = recallIdx.current;
    if (idx === null) {
      if (step > 0) return; // Down on an untouched line has nothing newer
      draft.current = value;
      idx = list.length - 1;
    } else {
      idx += step;
    }
    if (idx >= list.length) {
      // Past the newest entry - back to whatever was being typed.
      recallIdx.current = null;
      setValue(draft.current);
    } else {
      recallIdx.current = Math.max(0, idx);
      setValue(list[recallIdx.current]);
    }
    // A controlled input can leave the caret mid-string; recall should behave
    // like the line was just typed, so put it at the end.
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) el.setSelectionRange(el.value.length, el.value.length);
    });
  }

  function handleSubmit(e) {
    e.preventDefault();
    const text = value.trim();
    if (!text || busy) return;
    remember(text);
    // Bare "exit" closes the window. Exact match only - "exit window" or
    // "exit vim" are real requests and still go to the model.
    if (text.toLowerCase() === "exit") {
      setValue("");
      window.pywebview.api.quit();
      return;
    }
    if (text.startsWith("/")) {
      const lower = text.toLowerCase();
      const exact = COMMANDS.find((c) => c.name === lower || c.aliases.includes(lower));
      const target = exact || suggestions[selIdx];
      if (!target) {
        setValue("");
        addEntry({ kind: "error", text: `Unknown command: ${text}` });
        return;
      }
      execCommand(target);
      return;
    }
    setValue("");
    runRequest(text);
  }

  // Also entered by clicking a choice chip, which submits the chosen option
  // as if the user had typed it (the session's history makes it a follow-up
  // answer to the model's question).
  async function runRequest(text) {
    // The box is about to be empty again - show something new in it rather
    // than the hint that was already sitting there while they typed.
    nextHint();
    addEntry({ kind: "user", text });
    setBusy(true);
    setStatus("thinking");
    const thinkingId = addEntry({ kind: "thinking" });

    try {
      const data = await window.pywebview.api.submit(text);
      setEntries((prev) => prev.filter((e) => e.id !== thinkingId));

      // The request was held while the server started, and the start failed.
      // Same entry as the watcher's, not a second copy of it.
      if (data.error) {
        upsertEntry(STARTUP_ERROR, { kind: "error", text: data.explanation, retry: true });
        setStatus("error");
        return;
      }

      // Nothing to carry out: a question answered, or a question asked back.
      if (!data.command && !data.search) {
        if (data.options && data.options.length > 0) {
          addEntry({ kind: "choices", text: data.explanation, options: data.options });
        } else {
          addEntry({ kind: "explanation", text: data.explanation });
        }
        showNotice(data.notice);
        setStatus("ok");
        return;
      }

      addEntry({ kind: "explanation", text: data.explanation });
      showNotice(data.notice);

      // None means run what the model wrote; a string is the user's own
      // version, which the session records as a correction.
      let edited = null;
      if (data.risk === "risky") {
        const decision = await askConfirmation(data.command);
        if (!decision.proceed) {
          addEntry({ kind: "skipped" });
          setStatus("ok");
          return;
        }
        edited = decision.command;
      }

      // Keep the dots up while the command (and, on failure, the model's
      // explanation of why) runs - both can take a few seconds.
      const runningId = addEntry({ kind: "thinking" });
      const result = await window.pywebview.api.confirm(edited);
      setEntries((prev) => prev.filter((e) => e.id !== runningId));

      if (result && result.ok) {
        if (result.results) {
          addEntry({
            kind: "answer",
            text: result.answer,
            sources: result.results,
            caveat: result.caveat,
          });
        } else if (result.listing) {
          addEntry({
            kind: "listing",
            path: result.path,
            items: result.listing,
            kindLabel: result.kind,
          });
        } else if (result.output) {
          addEntry({ kind: "output", text: result.output });
        } else {
          addEntry({ kind: "done" });
        }
        setStatus("ok");
      } else {
        addEntry({ kind: "fail", text: (result && result.reason) || "Couldn't do that." });
        setStatus("error");
      }
    } catch (err) {
      setEntries((prev) => prev.filter((e) => e.id !== thinkingId));
      addEntry({ kind: "error", text: String(err) });
      setStatus("error");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.focus();
    }
  }

  function handleKeyDown(e) {
    if (suggestions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelIdx((i) => (i + 1) % suggestions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelIdx((i) => (i - 1 + suggestions.length) % suggestions.length);
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        setValue(suggestions[selIdx].name);
        return;
      }
      if (e.key === "Escape") {
        setValue("");
        return;
      }
    } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      // Only once the slash-command list has had its turn with the arrows.
      e.preventDefault(); // otherwise the caret jumps to the start/end instead
      recall(e.key === "ArrowUp" ? -1 : 1);
      return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      playKey("type");
    } else if (e.key === "Backspace" || e.key === "Delete") {
      if (value.length > 0) playKey("delete");
    } else if (e.key === "Enter" && value.trim() && !busy) {
      playKey("enter");
    }
    if (e.key === "Escape" && !busy && entries.length > 0 && !clearing) {
      // Fade the output out first, then actually drop the entries so the
      // window shrink (animated by the resize hook) starts from the fade end.
      setClearing(true);
      forgetSession();
      nextHint();
      setTimeout(() => {
        setEntries([]);
        setClearing(false);
        setStatus("idle");
      }, 190);
    }
  }

  // A press on the output's scrollbar targets the scrolling element itself and
  // lands past its content width - that gesture belongs to the scrollbar, not
  // to the window. Anywhere else in the output still drags the panel.
  function onOutputPress(e) {
    if (e.target === e.currentTarget && e.nativeEvent.offsetX > e.currentTarget.clientWidth) {
      e.stopPropagation();
    }
  }

  function handleMouseMove(e) {
    // Feeds the cursor position to CSS so the glass highlight refracts
    // toward the pointer (see .panel::before in App.css).
    const el = panelRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - rect.left}px`);
    el.style.setProperty("--my", `${e.clientY - rect.top}px`);
  }

  return (
    <div className="shell">
      <div
        className={`panel${focused ? " focused" : ""}${minimized ? " mini" : ""}`}
        ref={panelRef}
        onMouseMove={handleMouseMove}
      >
        <div className="panel-sheen" />
        {/* Folded, the tile is all there is to say it with. Nothing is drawn
            while the panel is open - the grid inside is already saying it. */}
        {shownInstall && (
          <TileRing
            percent={shownInstall.percent}
            title={
              `${formatBytes(shownInstall.bytesDone)} of `
              + `${formatBytes(shownInstall.bytesTotal)}`
            }
          />
        )}
        {/* Kept mounted while collapsed rather than swapped out: everything on
            screen - the conversation, a listing browsed three folders deep, a
            half-typed line - has to be exactly where it was when the tile is
            opened again. It is only moved out of the layout and faded. */}
        <div className="panel-body" ref={bodyRef} aria-hidden={minimized}>
          {/* The very first install takes the whole panel: there is no model
              yet, so there is nothing else the window could usefully be. Any
              later download is a line above a shell that still works, and is
              handled further down beside the boot row. */}
          {shownInstall && shownInstall.firstInstall ? (
            <InstallPanel
              install={shownInstall}
              hint={hint}
              hintShown={hintShown}
              leaving={leaving}
            />
          ) : view === "settings" ? (
            <div className="settings">
              <div className="settings-head">
                <span className="settings-title">Settings</span>
                <span className="hint" onClick={() => setView("shell")}>esc to close</span>
              </div>
              <div className="settings-label">Typing sounds</div>
              <div className="theme-grid">
                {Object.entries(SOUND_THEMES).map(([key, theme]) => (
                  <button
                    key={key}
                    type="button"
                    className={`theme-card${prefs.soundTheme === key ? " active" : ""}`}
                    onClick={() => {
                      updatePrefs({ soundTheme: key });
                      playKey("type");
                    }}
                  >
                    <span className="theme-name">{theme.label}</span>
                    <span className="theme-desc">{theme.desc}</span>
                  </button>
                ))}
              </div>
              <div className="settings-label">Sound volume</div>
              <div className="volume-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={Math.round(prefs.volume * 100)}
                  style={{ "--fill": `${Math.round(prefs.volume * 100)}%` }}
                  onChange={(e) => updatePrefs({ volume: e.target.value / 100 })}
                  onMouseDown={keepGesture}
                  onMouseUp={() => playKey("type")}
                />
                <span className="volume-value">{Math.round(prefs.volume * 100)}%</span>
              </div>
              <div className="settings-label">Window</div>
              <button
                type="button"
                className={`switch-row${prefs.minimizeOnBlur ? " on" : ""}`}
                onClick={() => updatePrefs({ minimizeOnBlur: !prefs.minimizeOnBlur })}
              >
                <span className="switch-text">
                  <span className="switch-name">Shrink when unfocused</span>
                  <span className="switch-desc">
                    Folds into a small tile while you're working elsewhere
                  </span>
                </span>
                <span className="switch-track">
                  <span className="switch-knob" />
                </span>
              </button>
              <div className="settings-label">Opacity</div>
              <div className="volume-row">
                <input
                  type="range"
                  min={MIN_OPACITY}
                  max="100"
                  value={opacity ?? 100}
                  style={{
                    "--fill": `${(((opacity ?? 100) - MIN_OPACITY) / (100 - MIN_OPACITY)) * 100}%`,
                  }}
                  onChange={(e) => dragOpacity(Number(e.target.value))}
                  onMouseUp={(e) => saveOpacity(Number(e.target.value))}
                  onKeyUp={(e) => saveOpacity(Number(e.target.value))}
                  onMouseDown={keepGesture}
                />
                <span className="volume-value">{opacity ?? 100}%</span>
              </div>
              <div className="settings-label">Model</div>
              {modelList.editable === false && (
                <div className="model-note">
                  This app is using a model server you started yourself, so the model is yours to choose.
                </div>
              )}
              <div className="model-grid">
                {(modelList.models || []).map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    disabled={m.current || modelList.editable === false}
                    className={`model-row${m.current ? " active" : ""}${m.fits ? "" : " unfit"}`}
                    onClick={() => switchModel(m)}
                  >
                    <span className="model-name">{m.label}</span>
                    {/* Two separate facts, and both matter: what switching
                        costs, and whether this machine runs it slower. A
                        downloaded model is a free switch even where it
                        doesn't fit, and one that doesn't fit is no longer
                        unusable - as much of it as fits goes on the card. */}
                    <span className="model-meta">
                      {m.current
                        ? "in use"
                        : `${m.installed ? "downloaded" : `${m.weights_gb}GB download`}${
                            m.speed === "partial"
                              ? " · slower here"
                              : m.speed === "poor"
                              ? " · far too big"
                              : ""
                          }`}
                    </span>
                  </button>
                ))}
              </div>
              {modelList.model_dir && (
                <div className="model-note">
                  Models you've downloaded stay in {modelList.model_dir}, so switching back is instant.
                </div>
              )}
            </div>
          ) : (
            <>
          <form className="input-row" onSubmit={handleSubmit}>
            <span className={`status-dot ${booting ? "thinking" : status}`} />
            <div className="input-wrap">
              <input
                ref={inputRef}
                type="text"
                autoFocus
                autoComplete="off"
                aria-label="Ask anything"
                disabled={busy}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                onKeyDown={handleKeyDown}
              />
              <div className="input-mirror" ref={mirrorRef} aria-hidden="true">
                {value.split("").map((ch, i) => (
                  <span key={i}>{ch === " " ? " " : ch}</span>
                ))}
              </div>
              {/* Stands in for the native placeholder so hints can cross-fade. */}
              {value === "" && (
                <div
                  className={
                    `input-hint${hintShown ? "" : " out"}` +
                    `${focused ? " lit" : ""}${entries.length > 0 ? " hushed" : ""}`
                  }
                  aria-hidden="true"
                >
                  {hint.key && <span className="input-hint-key">{hint.key}</span>}
                  <span className="input-hint-text">{hint.text}</span>
                </div>
              )}
            </div>
            {entries.length > 0 && !busy && <span className="hint">esc to clear</span>}
          </form>

          {/* Only while the model server is coming up. Typing is deliberately
              still allowed: the request waits on the Python side and runs the
              moment the server answers.

              Two shapes, because the waits are two sizes. A weights download
              runs for minutes and gets the strip; everything else a start
              does - fetching llama.cpp, loading the model, a switch to
              weights already on disk - keeps the line it has always had. */}
          {shownInstall && !shownInstall.firstInstall ? (
            <InstallRow install={shownInstall} />
          ) : booting ? (
            <div className="boot-row">
              <ThinkingDots />
              <span className="boot-text">{booting}</span>
            </div>
          ) : null}

          {/* A new version is already downloaded and waiting. It is never
              applied without this click: the app closes, swaps itself out and
              comes back, which is not something to do to someone mid-thought.
              Nothing here is dismissable because nothing here is urgent - the
              row goes away by being acted on, or by closing the app. */}
          {updateReady && (
            <div className="update-row">
              <span className="update-dot" />
              <span className="update-text">
                Version {updateReady.version} is ready to install
              </span>
              <button
                type="button"
                className="btn update"
                disabled={updating}
                onClick={onInstallUpdate}
              >
                {updating ? "Restarting…" : "Restart"}
              </button>
            </div>
          )}

          {suggestions.length > 0 && (
            <div className="cmd-suggest">
              {suggestions.map((cmd, i) => (
                <button
                  key={cmd.name}
                  type="button"
                  className={`cmd-item${i === selIdx ? " active" : ""}`}
                  onMouseEnter={() => setSelIdx(i)}
                  onClick={() => execCommand(cmd)}
                >
                  <span className="cmd-name">{cmd.name}</span>
                  {cmd.aliases.length > 0 && (
                    <span className="cmd-alias">{cmd.aliases.join(" ")}</span>
                  )}
                  <span className="cmd-desc">{cmd.desc}</span>
                </button>
              ))}
            </div>
          )}

          {entries.length > 0 && (
            <div
            className={`output${clearing ? " closing" : ""}`}
            ref={outputRef}
            onMouseDown={onOutputPress}
          >
              {entries.map((entry) => (
                <Entry
                  key={entry.id}
                  entry={entry}
                  onConfirm={onConfirmClick}
                  onChoose={onChooseOption}
                  onRetry={onRetryStartup}
                  busy={busy}
                />
              ))}
            </div>
          )}
            </>
          )}
        </div>

        {/* The collapsed state, painted over the folded-away panel: the same
            "›" the panel answers with, and the same status dot, so a glance
            at the tile says whether anything is still running. */}
        <button
          type="button"
          className="mini-orb"
          tabIndex={minimized ? 0 : -1}
          aria-hidden={!minimized}
          title="Open - or drag to move it"
          onMouseDown={onTilePress}
          onClick={onTileRelease}
        >
          {busy || booting ? (
            <ThinkingDots />
          ) : (
            <>
              {/* Drawn rather than typed: the panel's "›" is a mono glyph, and
                  a glyph is centred by its advance box and its font's idea of
                  where a quotation mark sits - neither of which is the middle
                  of a 48px tile. A path is exactly where it says it is. */}
              <svg className="mini-mark" viewBox="0 0 24 24" aria-hidden="true">
                <defs>
                  <linearGradient id="miniMark" x1="0" y1="0" x2="0.7" y2="1">
                    <stop offset="0%" stopColor="#b3a8ff" />
                    <stop offset="100%" stopColor="#7a68ff" />
                  </linearGradient>
                </defs>
                {/* Round caps, so the ink's own bounds stay centred too: they
                    add the same 1.2 at the tip as at both arm ends. */}
                <path
                  d="M8.5 5 L15.5 12 L8.5 19"
                  fill="none"
                  stroke="url(#miniMark)"
                  strokeWidth="2.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {entries.length > 0 && <span className={`mini-badge ${status}`} />}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
