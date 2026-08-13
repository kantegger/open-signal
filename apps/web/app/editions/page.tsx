import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "../../components/json-ld";
import { SiteShell } from "../../components/site-shell";
import type { EditionArchiveData } from "../../lib/api";
import { collectionDensity } from "../../lib/collection-density";
import { formatDateTime, humanize, languageAlternates, localePath, type SupportedLocale } from "../../lib/i18n";
import { getRequestLocale } from "../../lib/request-locale";
import { fetchEditionArchiveServer } from "../../lib/server-api";
import { absoluteUrl } from "../../lib/site";
import { editionPath } from "../../lib/urls";

export const revalidate = 900;
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const canonical = localePath("/editions", locale);
  return {
    title: traditional ? "期次典藏" : "Edition Archive",
    description: traditional
      ? "瀏覽 Open Signal 的不可變出版快照，包括涵蓋範圍、觸發原因與修正狀態。"
      : "Browse immutable Open Signal publication snapshots, including their coverage, trigger, and correction state.",
    alternates: { canonical, languages: languageAlternates("/editions") },
    openGraph: {
      title: traditional ? "期次典藏 · Open Signal" : "Edition Archive · Open Signal",
      description: traditional
        ? "依時間排列、不可變的 Open Signal 出版快照紀錄。"
        : "The chronological, immutable record of Open Signal publication snapshots.",
      url: canonical,
    },
  };
}

type Props = {
  searchParams: Promise<{
    cursor?: string | string[];
    year?: string | string[];
    section?: string | string[];
    status?: string | string[];
  }>;
};

export default async function EditionsPage({ searchParams }: Props) {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const params = await searchParams;
  const filters = {
    cursor: first(params.cursor),
    year: parseYear(first(params.year)),
    section: first(params.section),
    status: first(params.status),
  };
  let archive: EditionArchiveData;
  try {
    archive = await fetchEditionArchiveServer({ ...filters, locale });
  } catch {
    return (
      <SiteShell active="archive" systemState="unavailable">
        <div className="claim-route-state">
          <p className="eyebrow">{traditional ? "典藏索引暫時無法使用" : "Archive index unavailable"}</p>
          <h1>{traditional ? "無法載入期次紀錄。" : "The Edition record could not be loaded."}</h1>
          <p>{traditional ? "已發布快照仍保持不可變；讀取服務恢復後，本目錄會重新顯示。" : "Published snapshots remain immutable. This directory will return when the read service recovers."}</p>
          <Link href={localePath("/", locale)}>{traditional ? "返回即時版面" : "Return to Current"}</Link>
        </div>
      </SiteShell>
    );
  }
  const editions = archive.items;

  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "CollectionPage",
          name: traditional ? "Open Signal 期次典藏" : "Open Signal Edition Archive",
          inLanguage: locale,
          url: absoluteUrl(localePath("/editions", locale)),
          mainEntity: {
            "@type": "ItemList",
            numberOfItems: archive.total_count,
            itemListElement: editions.map((edition, index) => ({
              "@type": "ListItem",
              position: index + 1,
              name: `${traditional ? "Open Signal 期次" : "Open Signal edition"} · ${edition.edition_date}`,
              url: absoluteUrl(editionPath(edition.id, locale)),
            })),
          },
        }}
      />
      <SiteShell active="archive">
        <article className="directory-page editions-page">
          <header className="directory-header">
            <div><p className="eyebrow">{traditional ? "不可變的出版紀錄" : "Immutable publication record"}</p><h1>{traditional ? "期次典藏" : "Edition Archive"}</h1></div>
            <p>
              {traditional
                ? "每個期次都是完整編製的快照。後續更新可以取代它，但不能暗中改寫讀者曾經看到的內容。"
                : "Each Edition is a complete compiled snapshot. A later refresh can supersede it, but cannot silently rewrite what readers previously saw."}
            </p>
          </header>
          <dl className="directory-metrics" aria-label={traditional ? "期次典藏涵蓋範圍" : "Edition archive coverage"}>
            <div><dt>{traditional ? "已發布期次" : "Published Editions"}</dt><dd>{archive.total_count}</dd></div>
            <div><dt>{traditional ? "排序" : "Ordering"}</dt><dd>{traditional ? "最新在前" : "Newest first"}</dd></div>
            <div><dt>{traditional ? "變更政策" : "Mutation policy"}</dt><dd>{traditional ? "只可追加" : "Append only"}</dd></div>
            <div><dt>{traditional ? "修正" : "Corrections"}</dt><dd>{traditional ? "具版本" : "Versioned"}</dd></div>
          </dl>

          <form className="archive-filters" action={localePath("/editions", locale)} method="get">
            <label>
              <span>{traditional ? "年份" : "Year"}</span>
              <select name="year" defaultValue={filters.year ?? ""}>
                <option value="">{traditional ? "所有年份" : "All years"}</option>
                {archive.facets.years.map((year) => (
                  <option value={year} key={year}>{year}</option>
                ))}
              </select>
            </label>
            <label>
              <span>{traditional ? "區段" : "Section"}</span>
              <select name="section" defaultValue={filters.section ?? ""}>
                <option value="">{traditional ? "所有區段" : "All Sections"}</option>
                {archive.facets.sections.map((section) => (
                  <option value={section} key={section}>{humanize(section, locale)}</option>
                ))}
              </select>
            </label>
            <label>
              <span>{traditional ? "編製狀態" : "Compile state"}</span>
              <select name="status" defaultValue={filters.status ?? ""}>
                <option value="">{traditional ? "所有編製狀態" : "All compile states"}</option>
                {archive.facets.statuses.map((status) => (
                  <option value={status} key={status}>{humanize(status, locale)}</option>
                ))}
              </select>
            </label>
            <button type="submit">{traditional ? "套用篩選" : "Apply filters"}</button>
            {(filters.year || filters.section || filters.status) ? (
              <Link href={localePath("/editions", locale)}>{traditional ? "清除" : "Clear"}</Link>
            ) : null}
          </form>

          <section className="directory-section" aria-labelledby="edition-list-title">
            <header className="directory-section-heading">
              <div><p className="eyebrow">{traditional ? "時間序列" : "Chronology"}</p><h2 id="edition-list-title">{traditional ? "所有公開期次" : "All public Editions"}</h2></div>
              <p>{traditional ? `顯示 ${editions.length} 筆 · 開啟任一列即可重建該出版狀態。` : `${editions.length} shown · open any row to reconstruct that publication state.`}</p>
            </header>
            {editions.length ? (
              <div
                className="edition-directory-table"
                role="table"
                aria-label={traditional ? "期次典藏" : "Edition archive"}
                data-count={editions.length}
                data-density={collectionDensity(editions.length, "table")}
              >
                <div className="edition-directory-row edition-directory-head" role="row">
                  <span role="columnheader">{traditional ? "編製" : "Composed"}</span><span role="columnheader">{traditional ? "涵蓋" : "Coverage"}</span>
                  <span role="columnheader">{traditional ? "主張" : "Claims"}</span><span role="columnheader">{traditional ? "觸發" : "Trigger"}</span>
                  <span role="columnheader">{traditional ? "修正" : "Corrections"}</span><span role="columnheader">{traditional ? "生命週期" : "Lifecycle"}</span>
                  <span role="columnheader">{traditional ? "期次" : "Edition"}</span>
                </div>
                {editions.map((edition) => (
                  <div className="edition-directory-row" role="row" key={edition.id}>
                    <time role="cell">{formatDateTime(edition.generated_at, locale)}</time>
                    <span role="cell">
                      {edition.sections.length} {traditional ? "個區段" : "Sections"}
                      <small className="collection-detail collection-detail-balanced">
                        {edition.sections.map((section) => humanize(section, locale)).join(" · ") || (traditional ? "沒有有效區段" : "No active Sections")}
                      </small>
                    </span>
                    <span role="cell">{edition.claim_count}</span>
                    <span role="cell">{humanize(edition.trigger_type, locale)}</span>
                    <span role="cell">{edition.correction_count}</span>
                    <span role="cell">
                      {humanize(edition.latest_event_type ?? edition.status, locale)}
                      <small>{humanize(edition.status, locale)} {traditional ? "編製" : "compile"}</small>
                    </span>
                    <span role="cell"><Link href={editionPath(edition.id, locale)}>{edition.id.slice(0, 8)} →</Link></span>
                  </div>
                ))}
              </div>
            ) : <p className="empty-copy">{traditional ? "目前尚無公開期次。" : "No Editions are public yet."}</p>}
            {(filters.cursor || archive.has_more) ? (
              <nav className="directory-pagination" aria-label={traditional ? "期次典藏分頁" : "Edition archive pagination"}>
                {filters.cursor ? (
                  <Link href={archiveHref(filters, undefined, locale)}>← {traditional ? "回到最新" : "Back to newest"}</Link>
                ) : <span />}
                <span>{archive.total_count} {traditional ? "筆永久紀錄" : "permanent records"}</span>
                {archive.has_more && archive.next_cursor ? (
                  <Link href={archiveHref(filters, archive.next_cursor, locale)}>{traditional ? "較早期次" : "Older Editions"} →</Link>
                ) : <span />}
              </nav>
            ) : null}
          </section>
        </article>
      </SiteShell>
    </>
  );
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseYear(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 2000 && parsed <= 2100
    ? parsed
    : undefined;
}

function archiveHref(
  filters: { year?: number; section?: string; status?: string },
  cursor?: string,
  locale: SupportedLocale = "en",
): string {
  const query = new URLSearchParams();
  if (filters.year) query.set("year", String(filters.year));
  if (filters.section) query.set("section", filters.section);
  if (filters.status) query.set("status", filters.status);
  if (cursor) query.set("cursor", cursor);
  const encoded = query.toString();
  return localePath(encoded ? `/editions?${encoded}` : "/editions", locale);
}
