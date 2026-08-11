import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "../../components/json-ld";
import { SiteShell } from "../../components/site-shell";
import type { EditionArchiveData } from "../../lib/api";
import { collectionDensity } from "../../lib/collection-density";
import { formatDateTime, humanize } from "../../lib/i18n";
import { fetchEditionArchiveServer } from "../../lib/server-api";
import { absoluteUrl } from "../../lib/site";
import { editionPath } from "../../lib/urls";

export const revalidate = 900;
export const metadata: Metadata = {
  title: "Edition Archive",
  description: "Browse immutable Open Signal publication snapshots, including their coverage, trigger, and correction state.",
  alternates: { canonical: "/editions" },
  openGraph: {
    title: "Edition Archive · Open Signal",
    description: "The chronological, immutable record of Open Signal publication snapshots.",
    url: "/editions",
  },
};

type Props = {
  searchParams: Promise<{
    cursor?: string | string[];
    year?: string | string[];
    section?: string | string[];
    status?: string | string[];
  }>;
};

export default async function EditionsPage({ searchParams }: Props) {
  const params = await searchParams;
  const filters = {
    cursor: first(params.cursor),
    year: parseYear(first(params.year)),
    section: first(params.section),
    status: first(params.status),
  };
  let archive: EditionArchiveData;
  try {
    archive = await fetchEditionArchiveServer(filters);
  } catch {
    return (
      <SiteShell active="archive" systemState="unavailable">
        <div className="claim-route-state">
          <p className="eyebrow">Archive index unavailable</p>
          <h1>The Edition record could not be loaded.</h1>
          <p>Published snapshots remain immutable. This directory will return when the read service recovers.</p>
          <Link href="/">Return to Current</Link>
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
          name: "Open Signal Edition Archive",
          url: absoluteUrl("/editions"),
          mainEntity: {
            "@type": "ItemList",
            numberOfItems: archive.total_count,
            itemListElement: editions.map((edition, index) => ({
              "@type": "ListItem",
              position: index + 1,
              name: `Open Signal edition · ${edition.edition_date}`,
              url: absoluteUrl(editionPath(edition.id)),
            })),
          },
        }}
      />
      <SiteShell active="archive">
        <article className="directory-page editions-page">
          <header className="directory-header">
            <div><p className="eyebrow">Immutable publication record</p><h1>Edition Archive</h1></div>
            <p>
              Each Edition is a complete compiled snapshot. A later refresh can supersede it, but
              cannot silently rewrite what readers previously saw.
            </p>
          </header>
          <dl className="directory-metrics" aria-label="Edition archive coverage">
            <div><dt>Published Editions</dt><dd>{archive.total_count}</dd></div>
            <div><dt>Ordering</dt><dd>Newest first</dd></div>
            <div><dt>Mutation policy</dt><dd>Append only</dd></div>
            <div><dt>Corrections</dt><dd>Versioned</dd></div>
          </dl>

          <form className="archive-filters" action="/editions" method="get">
            <label>
              <span>Year</span>
              <select name="year" defaultValue={filters.year ?? ""}>
                <option value="">All years</option>
                {archive.facets.years.map((year) => (
                  <option value={year} key={year}>{year}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Section</span>
              <select name="section" defaultValue={filters.section ?? ""}>
                <option value="">All Sections</option>
                {archive.facets.sections.map((section) => (
                  <option value={section} key={section}>{humanize(section)}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Compile state</span>
              <select name="status" defaultValue={filters.status ?? ""}>
                <option value="">All compile states</option>
                {archive.facets.statuses.map((status) => (
                  <option value={status} key={status}>{humanize(status)}</option>
                ))}
              </select>
            </label>
            <button type="submit">Apply filters</button>
            {(filters.year || filters.section || filters.status) ? (
              <Link href="/editions">Clear</Link>
            ) : null}
          </form>

          <section className="directory-section" aria-labelledby="edition-list-title">
            <header className="directory-section-heading">
              <div><p className="eyebrow">Chronology</p><h2 id="edition-list-title">All public Editions</h2></div>
              <p>{editions.length} shown · open any row to reconstruct that publication state.</p>
            </header>
            {editions.length ? (
              <div
                className="edition-directory-table"
                role="table"
                aria-label="Edition archive"
                data-count={editions.length}
                data-density={collectionDensity(editions.length, "table")}
              >
                <div className="edition-directory-row edition-directory-head" role="row">
                  <span role="columnheader">Composed</span><span role="columnheader">Coverage</span>
                  <span role="columnheader">Claims</span><span role="columnheader">Trigger</span>
                  <span role="columnheader">Corrections</span><span role="columnheader">Lifecycle</span>
                  <span role="columnheader">Edition</span>
                </div>
                {editions.map((edition) => (
                  <div className="edition-directory-row" role="row" key={edition.id}>
                    <time role="cell">{formatDateTime(edition.generated_at)}</time>
                    <span role="cell">
                      {edition.sections.length} Sections
                      <small className="collection-detail collection-detail-balanced">
                        {edition.sections.map(humanize).join(" · ") || "No active Sections"}
                      </small>
                    </span>
                    <span role="cell">{edition.claim_count}</span>
                    <span role="cell">{humanize(edition.trigger_type)}</span>
                    <span role="cell">{edition.correction_count}</span>
                    <span role="cell">
                      {humanize(edition.latest_event_type ?? edition.status)}
                      <small>{humanize(edition.status)} compile</small>
                    </span>
                    <span role="cell"><Link href={editionPath(edition.id)}>{edition.id.slice(0, 8)} →</Link></span>
                  </div>
                ))}
              </div>
            ) : <p className="empty-copy">No Editions are public yet.</p>}
            {(filters.cursor || archive.has_more) ? (
              <nav className="directory-pagination" aria-label="Edition archive pagination">
                {filters.cursor ? (
                  <Link href={archiveHref(filters)}>← Back to newest</Link>
                ) : <span />}
                <span>{archive.total_count} permanent records</span>
                {archive.has_more && archive.next_cursor ? (
                  <Link href={archiveHref(filters, archive.next_cursor)}>Older Editions →</Link>
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
): string {
  const query = new URLSearchParams();
  if (filters.year) query.set("year", String(filters.year));
  if (filters.section) query.set("section", filters.section);
  if (filters.status) query.set("status", filters.status);
  if (cursor) query.set("cursor", cursor);
  const encoded = query.toString();
  return encoded ? `/editions?${encoded}` : "/editions";
}
