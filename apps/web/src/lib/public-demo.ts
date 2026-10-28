/** Slug of the public sample organization (`DEMO_ORG_SLUG` in the API). Kept free of the API
 * client so client components can compare against it. */
export const DEMO_ORG = "demo";

export const PUBLIC_DEMO_REPOSITORY = "https://github.com/CosturaAI/costura";
export const PUBLIC_DEMO_BAR_HEIGHT = "2.25rem";

export function isPublicDemo(): boolean {
  return process.env.COSTURA_PUBLIC_DEMO_HOME === "true";
}
