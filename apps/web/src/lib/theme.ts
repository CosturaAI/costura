/** Host-selected presentation. Read only from the server (layout and server pages). */

type ColorScheme = "light" | "dark" | "system";

export function brandName(): string {
  const name = process.env.COSTURA_BRAND_NAME?.trim();
  return name || "Costura";
}

export function colorScheme(): ColorScheme {
  const value = process.env.COSTURA_COLOR_SCHEME;
  if (value === "dark" || value === "system") return value;
  return "light";
}

/** `data-theme` on `<html>`. Light is the default `:root` and needs no attribute. */
export function themeAttribute(scheme: ColorScheme = colorScheme()): "dark" | "system" | undefined {
  if (scheme === "light") return undefined;
  return scheme;
}

/** Theme file stem. Only letters, digits and hyphens, so it cannot leave `src/themes/`. */
export function themeName(): string {
  const raw = process.env.COSTURA_THEME?.trim() || "costura";
  const safe = raw.replace(/[^a-z0-9-]/gi, "");
  return safe || "costura";
}
