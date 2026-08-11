import "server-only";

import {
  ApiError,
  type ClaimPageData,
  type EditionArchiveData,
  type EditionRecordData,
  type ExploreData,
  type FrontPageData,
  type JsonRecord,
  type SeoIndexData,
  type TopicPageData,
} from "./api";

const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const CACHE_SECONDS = 86_400;
const LIVE_CACHE_SECONDS = 3_600;
const INDEX_CACHE_SECONDS = 900;

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
        LIVE_CACHE_SECONDS,
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
        LIVE_CACHE_SECONDS,
      );
    } catch (error) {
      if (!process.env.OPEN_SIGNAL_API_URL) throw error;
    }
  }

  return fetchJson<FrontPageData>(
    `${apiBase()}/api/front-page/current?locale=${encodeURIComponent(locale)}`,
    [`front-page:${locale}`],
    LIVE_CACHE_SECONDS,
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

export async function fetchTopicServer(
  topicId: string,
): Promise<TopicPageData> {
  return fetchJson<TopicPageData>(
    `${apiBase()}/api/topics/${encodeURIComponent(topicId)}`,
    [`topic:${topicId}`],
    LIVE_CACHE_SECONDS,
  );
}

export async function fetchEditionFrontPageServer(
  editionId: string,
  locale = "en",
): Promise<FrontPageData> {
  return fetchJson<FrontPageData>(
    `${apiBase()}/api/editions/${encodeURIComponent(editionId)}/front-page?locale=${encodeURIComponent(locale)}`,
    [`edition:${editionId}`, `edition:${editionId}:${locale}`],
  );
}

export async function fetchSeoIndexServer(): Promise<SeoIndexData> {
  return fetchJson<SeoIndexData>(
    `${apiBase()}/api/seo-index?limit=1000`,
    ["seo-index"],
    INDEX_CACHE_SECONDS,
  );
}

export async function fetchEditionRecordServer(
  editionId: string,
): Promise<EditionRecordData> {
  return fetchJson<EditionRecordData>(
    `${apiBase()}/api/editions/${encodeURIComponent(editionId)}`,
    [`edition-record:${editionId}`],
    300,
  );
}

export async function fetchEditionArchiveServer(params: {
  cursor?: string;
  year?: number;
  section?: string;
  status?: string;
  limit?: number;
} = {}): Promise<EditionArchiveData> {
  const query = new URLSearchParams({ limit: String(params.limit ?? 50) });
  if (params.cursor) query.set("cursor", params.cursor);
  if (params.year) query.set("year", String(params.year));
  if (params.section) query.set("section", params.section);
  if (params.status) query.set("status", params.status);
  return fetchJson<EditionArchiveData>(
    `${apiBase()}/api/editions?${query.toString()}`,
    [
      "edition-archive",
      `edition-archive:${params.year ?? "all"}:${params.section ?? "all"}:${params.status ?? "all"}`,
    ],
    INDEX_CACHE_SECONDS,
  );
}

export async function fetchExploreServer(params: {
  topicPage?: number;
  signalPage?: number;
  asOf?: string;
} = {}): Promise<ExploreData> {
  const query = new URLSearchParams({
    topic_page: String(params.topicPage ?? 1),
    signal_page: String(params.signalPage ?? 1),
  });
  if (params.asOf) query.set("as_of", params.asOf);
  return fetchJson<ExploreData>(
    `${apiBase()}/api/explore?${query.toString()}`,
    ["explore", `explore:${params.asOf ?? "current"}`],
    INDEX_CACHE_SECONDS,
  );
}

async function fetchJson<T>(
  url: string,
  tags: string[],
  revalidate = CACHE_SECONDS,
): Promise<T> {
  const response = await fetch(url, {
    cache: "force-cache",
    next: { revalidate, tags },
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
