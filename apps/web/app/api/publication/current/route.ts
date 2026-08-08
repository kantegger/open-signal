import { NextRequest, NextResponse } from "next/server";
import { ApiError } from "../../../../lib/api";
import { fetchCurrentFrontPageServer } from "../../../../lib/server-api";

export async function GET(request: NextRequest) {
  const locale = supportedLocale(request.nextUrl.searchParams.get("locale"));
  try {
    const page = await fetchCurrentFrontPageServer(locale);
    const etag = `"${page.snapshot.id}:${locale}"`;
    if (request.headers.get("if-none-match") === etag) {
      return new NextResponse(null, { status: 304, headers: { ETag: etag } });
    }
    return NextResponse.json(page, {
      headers: {
        ETag: etag,
        "Cache-Control": "public, max-age=0, s-maxage=300, stale-while-revalidate=3600",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 503;
    return NextResponse.json({ detail: "publication unavailable" }, { status });
  }
}

function supportedLocale(value: string | null): string {
  return value === "en" ? value : "en";
}
