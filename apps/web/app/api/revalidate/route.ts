import { timingSafeEqual } from "node:crypto";
import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";
import { isSupportedLocale, localePath } from "../../../lib/i18n";

interface DeliveryNotice {
  edition_id?: unknown;
  locale?: unknown;
  claim_ids?: unknown;
  topic_ids?: unknown;
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
  const topicIds = Array.isArray(body.topic_ids) ? body.topic_ids : [];
  if (
    !validIdentifier(body.edition_id) ||
    !isSupportedLocale(body.locale) ||
    !Array.isArray(body.claim_ids) ||
    !body.claim_ids.every(validIdentifier) ||
    !topicIds.every(validIdentifier)
  ) {
    return NextResponse.json({ detail: "invalid delivery notice" }, { status: 400 });
  }
  const locale = body.locale;
  const claimIds = [...new Set(body.claim_ids)];
  const uniqueTopicIds = [...new Set(topicIds)];

  // This is a trusted publication webhook: the new pointer already exists, so
  // expire synchronously instead of serving the previous Edition once via SWR.
  revalidateTag(`front-page:${locale}`, { expire: 0 });
  revalidateTag("publication-pointer", { expire: 0 });
  revalidateTag("explore", { expire: 0 });
  revalidateTag("edition-archive", { expire: 0 });
  revalidateTag("seo-index", { expire: 0 });
  revalidatePath(localePath("/", locale));
  revalidatePath(localePath("/explore", locale));
  revalidatePath(localePath("/editions", locale));
  revalidatePath("/api/publication/current");
  for (const claimId of claimIds) {
    revalidateTag(`claim:${claimId}:${locale}`, { expire: 0 });
    revalidatePath(localePath(`/claims/${claimId}`, locale));
  }
  for (const topicId of uniqueTopicIds) {
    revalidateTag(`topic:${topicId}`, { expire: 0 });
    revalidatePath(localePath(`/topics/${topicId}`, locale));
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
