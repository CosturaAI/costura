/**
 * Pure helpers of the `/new` page: the organization name proposed from the signed-in e-mail,
 * the slug derived from a name, and the next free slug after a 409. The API validates the slug
 * against `SLUG_PATTERN` as well; this file only keeps the form from asking twice.
 */

/** Same rule as `SLUG_PATTERN` in `apps/api/costura/models/organization.py`: 2 to 63 chars,
 * lowercase, hyphens inside. */
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}$/;

/** Domains shared by the public, where the domain says nothing about the organization. */
const PUBLIC_MAIL_DOMAINS = new Set([
  "gmail.com",
  "googlemail.com",
  "outlook.com",
  "hotmail.com",
  "live.com",
  "yahoo.com",
  "icloud.com",
  "me.com",
  "proton.me",
  "protonmail.com",
  "aol.com",
]);

function capitalize(word: string): string {
  return word ? word[0]!.toUpperCase() + word.slice(1) : word;
}

/**
 * `jane@acme.com` -> "Acme"; `jane@mail.acme.co.uk` -> "Mail" (the first label, the API has
 * no list of second-level TLDs); `jane.doe@gmail.com` -> "Jane.doe's organization".
 */
export function suggestOrgName(email: string): string {
  const trimmed = email.trim();
  const at = trimmed.lastIndexOf("@");
  const local = at >= 0 ? trimmed.slice(0, at) : trimmed;
  const domain = at >= 0 ? trimmed.slice(at + 1).toLowerCase() : "";
  const firstLabel = domain.split(".")[0] ?? "";
  if (domain && firstLabel && !PUBLIC_MAIL_DOMAINS.has(domain)) return capitalize(firstLabel);
  const owner = capitalize(local) || "My";
  return `${owner}'s organization`;
}

/** "Acme Corp." -> "acme-corp"; leading characters outside [a-z0-9] are dropped. */
export function slugify(name: string): string {
  const slug = name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63)
    .replace(/-+$/g, "");
  return slug.replace(/^[^a-z0-9]+/, "");
}

/** "acme" -> "acme-2"; "acme-2" -> "acme-3"; keeps the 63-char limit. */
export function nextSlug(slug: string): string {
  const match = /^(.*?)-(\d+)$/.exec(slug);
  const [base, counter] = match ? [match[1], Number.parseInt(match[2]!, 10) + 1] : [slug, 2];
  const suffix = `-${counter}`;
  return `${base!.slice(0, 63 - suffix.length).replace(/-+$/g, "")}${suffix}`;
}

export function isValidSlug(slug: string): boolean {
  return SLUG_PATTERN.test(slug);
}
