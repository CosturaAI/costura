import { notFound } from "next/navigation";

/**
 * Where `/o/{slug}` sends an unknown or foreign slug. A route handler cannot render the 404
 * page (`notFound()` there answers an empty 404), a page can. The leading `-` keeps the
 * address out of the slug alphabet, so it never shadows an organization.
 */
export default function MissingOrganization(): never {
  notFound();
}
