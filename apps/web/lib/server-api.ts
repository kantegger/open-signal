import "server-only";

import {
  ApiError,
  type ClaimPageData,
  type FrontPageData,
  type JsonRecord,
} from "./api";

const DEFAULT_API_BASE = "http://localhost:8000";
const CACHE_SECONDS = 86_400;

interface PublicationPointer extends JsonRecord {
  edition_id: string;
  locale: string;
  front_page_key: string;
}

export async function fetchCurrentFrontPageServer(
  locale = "en",
): Promise<FrontPageData> {
  const publicationBase = process.env.OPEN_SIGNAL_PUBLICATION_BASE_URL;
  if (publicationBase) {
    try {
      const pointer = await fetchJson<PublicationPointer>(
        joinUrl(
          publicationBase,
          `public/publications/channels/front-page/${encodeURIComponent(locale)}.json`,
        ),
        [`front-page:${locale}`, "publication-pointer"],
      );
      if (
        pointer.locale !== locale ||
        !safeObjectKey(pointer.front_page_key, "public/publications/editions/")
      ) {
        throw new Error("invalid publication pointer");
      }
      return await fetchJson<FrontPageData>(
        joinUrl(publicationBase, pointer.front_page_key),
        [`front-page:${locale}`, `edition:${pointer.edition_id}`],
      );
    } catch (error) {
      if (!process.env.OPEN_SIGNAL_API_URL) throw error;
    }
  }

  return fetchJson<FrontPageData>(
    `${apiBase()}/api/front-page/current?locale=${encodeURIComponent(locale)}`,
    [`front-page:${locale}`],
  );
}

export async function fetchClaimServer(
  claimId: string,
  locale = "en",
): Promise<ClaimPageData> {
  const publicationBase = process.env.OPEN_SIGNAL_PUBLICATION_BASE_URL;
  if (publicationBase) {
    try {
      return await fetchJson<ClaimPageData>(
        joinUrl(
          publicationBase,
          `public/publications/claims/${encodeURIComponent(claimId)}/${encodeURIComponent(locale)}.json`,
        ),
        [`claim:${claimId}:${locale}`],
      );
    } catch (error) {
      if (!process.env.OPEN_SIGNAL_API_URL) throw error;
    }
  }

  return fetchJson<ClaimPageData>(
    `${apiBase()}/api/claims/${encodeURIComponent(claimId)}?locale=${encodeURIComponent(locale)}`,
    [`claim:${claimId}:${locale}`],
  );
}

async function fetchJson<T>(url: string, tags: string[]): Promise<T> {
  const response = await fetch(url, {
    cache: "force-cache",
    next: { revalidate: CACHE_SECONDS, tags },
  });
  if (!response.ok) {
    throw new ApiError(`publication request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}

function apiBase(): string {
  return (process.env.OPEN_SIGNAL_API_URL ?? DEFAULT_API_BASE).replace(/\/$/, "");
}

function joinUrl(base: string, key: string): string {
  return `${base.replace(/\/$/, "")}/${key.replace(/^\//, "")}`;
}

function safeObjectKey(value: unknown, prefix: string): value is string {
  return (
    typeof value === "string" &&
    value.startsWith(prefix) &&
    !value.includes("..") &&
    !value.includes("\\")
  );
}
