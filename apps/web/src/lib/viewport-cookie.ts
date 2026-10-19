/** Cookie the browser writes with its viewport width, so the server's first paint picks the
 * same table, chart or navigation layout the client would. Not a tracking cookie: one number,
 * first party, read only to choose a layout. Shared by the server layout and the client hook. */
export const VIEWPORT_COOKIE = "costura_vw";

/** The cookie value as a width; anything else reads as unknown. */
export function parseViewportWidth(raw: string | undefined): number | null {
  if (!raw || !/^\d{2,5}$/.test(raw)) return null;
  return Number(raw);
}
