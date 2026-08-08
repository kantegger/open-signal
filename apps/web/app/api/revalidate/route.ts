import { timingSafeEqual } from "node:crypto";
import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

interface DeliveryNotice {
  edition_id?: unknown;
  locale?: unknown;
  claim_ids?: unknown;
}

export async function POST(request: NextRequest) {
  if (!authorized(request.headers.get("authorization"))) {
    return NextResponse.json(
      { detail: "revalidation authentication required" },
      { status: 401, headers: { "WWW-Authenticate": "Bearer" } },
    );
  }

  let body: DeliveryNotice;
  try {
    body = (await request.json()) as DeliveryNotice;
  } catch {
    return NextResponse.json({ detail: "invalid JSON" }, { status: 400 });
  }
  if (
    !validIdentifier(body.edition_id) ||
    body.locale !== "en" ||
    !Array.isArray(body.claim_ids) ||
    !body.claim_ids.every(validIdentifier)
  ) {
    return NextResponse.json({ detail: "invalid delivery notice" }, { status: 400 });
  }
  const locale = body.locale;
  const claimIds = [...new Set(body.claim_ids)];

  // This is a trusted publication webhook: the new pointer already exists, so
  // expire synchronously instead of serving the previous Edition once via SWR.
  revalidateTag(`front-page:${locale}`, { expire: 0 });
  revalidateTag("publication-pointer", { expire: 0 });
  revalidatePath("/");
  revalidatePath("/api/publication/current");
  for (const claimId of claimIds) {
    revalidateTag(`claim:${claimId}:${locale}`, { expire: 0 });
    revalidatePath(`/claims/${claimId}`);
  }
  return NextResponse.json({ revalidated: true, locale, claim_count: claimIds.length });
}

function authorized(header: string | null): boolean {
  const expected = process.env.OPEN_SIGNAL_REVALIDATE_TOKEN;
  if (!expected || !header?.startsWith("Bearer ")) return false;
  const actualBuffer = Buffer.from(header.slice(7));
  const expectedBuffer = Buffer.from(expected);
  return (
    actualBuffer.length === expectedBuffer.length &&
    timingSafeEqual(actualBuffer, expectedBuffer)
  );
}

function validIdentifier(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9-]{1,128}$/.test(value);
}
