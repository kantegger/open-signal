import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "../../components/json-ld";
import { SiteShell } from "../../components/site-shell";
import { collectionDensity } from "../../lib/collection-density";
import { formatDateTime, humanize } from "../../lib/i18n";
import { fetchSeoIndexServer } from "../../lib/server-api";
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

export default async function EditionsPage() {
  let editions;
  try {
    editions = (await fetchSeoIndexServer()).editions;
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
            numberOfItems: editions.length,
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
            <div><dt>Published Editions</dt><dd>{editions.length}</dd></div>
            <div><dt>Ordering</dt><dd>Newest first</dd></div>
            <div><dt>Mutation policy</dt><dd>Append only</dd></div>
            <div><dt>Corrections</dt><dd>Versioned</dd></div>
          </dl>

          <section className="directory-section" aria-labelledby="edition-list-title">
            <header className="directory-section-heading">
              <div><p className="eyebrow">Chronology</p><h2 id="edition-list-title">All public Editions</h2></div>
              <p>Open any row to reconstruct that publication state.</p>
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
                  <span role="columnheader">Corrections</span><span role="columnheader">State</span>
                  <span role="columnheader">Edition</span>
                </div>
                {editions.map((edition) => (
                  <div className="edition-directory-row" role="row" key={edition.id}>
                    <time role="cell">{formatDateTime(edition.updated_at)}</time>
                    <span role="cell">
                      {edition.sections.length} Sections
                      <small className="collection-detail collection-detail-balanced">
                        {edition.sections.map(humanize).join(" · ") || "No active Sections"}
                      </small>
                    </span>
                    <span role="cell">{edition.claim_count}</span>
                    <span role="cell">{humanize(edition.trigger_type)}</span>
                    <span role="cell">{edition.correction_count}</span>
                    <span role="cell">{humanize(edition.status)}</span>
                    <span role="cell"><Link href={editionPath(edition.id)}>{edition.id.slice(0, 8)} →</Link></span>
                  </div>
                ))}
              </div>
            ) : <p className="empty-copy">No Editions are public yet.</p>}
          </section>
        </article>
      </SiteShell>
    </>
  );
}
