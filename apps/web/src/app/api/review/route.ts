import { loadReview, reviewMarkdown, reviewSections, reviewTitle } from "@/lib/review";
import { readViewCookie } from "@/lib/view-cookie";
import { api } from "@/lib/api";
import { resolveScope } from "@/lib/view";

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

function privateHeaders(extra: Record<string, string> = {}): Headers {
  return new Headers({
    "cache-control": "private, no-store, max-age=0",
    "x-content-type-options": "nosniff",
    ...extra,
  });
}

/** The month review as Markdown for the active organization (view cookie). */
export async function GET(request: Request): Promise<Response> {
  const view = await readViewCookie();
  if (view === null) {
    return Response.json(
      { detail: "no active organization" },
      { status: 404, headers: privateHeaders() },
    );
  }
  const params = new URL(request.url).searchParams;
  const month = params.get("month") ?? "";
  if (!MONTH.test(month)) {
    return Response.json(
      { detail: "month must be YYYY-MM" },
      { status: 400, headers: privateHeaders() },
    );
  }
  const scope = resolveScope(params.get("scope"));
  try {
    const [data, organization] = await Promise.all([
      loadReview(view.org, scope, month),
      api.org(view.org),
    ]);
    const body = reviewMarkdown(reviewTitle(organization.name, scope, month), reviewSections(data));
    return new Response(body, {
      headers: privateHeaders({
        "content-type": "text/markdown; charset=utf-8",
        "content-disposition": `attachment; filename="costura-${view.org}-${scope}-${month}.md"`,
      }),
    });
  } catch {
    return Response.json(
      { detail: "the review could not be built" },
      { status: 502, headers: privateHeaders() },
    );
  }
}
