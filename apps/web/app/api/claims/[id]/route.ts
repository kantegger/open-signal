import { NextRequest, NextResponse } from "next/server";
import { ApiError } from "../../../../lib/api";
import { fetchClaimServer } from "../../../../lib/server-api";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const locale = request.nextUrl.searchParams.get("locale") === "en" ? "en" : "en";
  try {
    const page = await fetchClaimServer(id, locale);
    const updated = page.claim.materially_updated_at ?? page.claim.issued_at;
    const etag = `"${page.claim.id}:${updated}:${locale}"`;
    if (request.headers.get("if-none-match") === etag) {
      return new NextResponse(null, { status: 304, headers: { ETag: etag } });
    }
    return NextResponse.json(page, {
      headers: {
        ETag: etag,
        "Cache-Control": "public, max-age=0, s-maxage=86400, stale-while-revalidate=604800",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 503;
    return NextResponse.json({ detail: "claim unavailable" }, { status });
  }
}
