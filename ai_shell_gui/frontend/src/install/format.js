// Numbers a person reads for minutes at a time, so they are rounded to what
// is worth reading. A download that says "2.243 GB" is telling the truth in a
// way nobody asked for.

export function formatBytes(bytes) {
  if (!bytes) return "0 GB";
  const gb = bytes / 1e9;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1e6))} MB`;
}

export function formatRate(bytesPerSecond) {
  if (!bytesPerSecond) return "";
  const mb = bytesPerSecond / 1e6;
  if (mb >= 1) return `${mb.toFixed(1)} MB/s`;
  return `${Math.max(1, Math.round(bytesPerSecond / 1e3))} KB/s`;
}

// Coarse on purpose. An ETA is a guess, and "~13m" is an honest guess where
// "12m 47s" claims a precision the number does not have.
export function formatEta(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds < 60) return "under a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `~${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `~${hours}h ${rest}m` : `~${hours}h`;
}
