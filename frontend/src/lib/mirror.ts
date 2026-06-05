/**
 * Build-time flag that flips the SPA into read-only "public mirror" mode.
 *
 * When `VITE_MIRROR=1` is set at build time the app reads pre-exported static
 * JSON (served from `/data`) instead of the live REST API, and every write /
 * admin surface (add, settings, stats, queue, subscriptions, favorite, archive,
 * folders editing, comments) is hidden. See `mirror/` for the exporter.
 */
export const MIRROR = import.meta.env.VITE_MIRROR === "1";
