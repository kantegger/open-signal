import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "../../components/json-ld";
import { SiteShell } from "../../components/site-shell";
import { collectionDensity } from "../../lib/collection-density";
import { absoluteUrl } from "../../lib/site";

export const metadata: Metadata = {
  title: "Method",
  description: "How Open Signal separates observation, analysis, and assessment; verifies evidence; compiles Editions; and retires stale material.",
  alternates: { canonical: "/method" },
  openGraph: {
    title: "Method · Open Signal",
    description: "How evidence becomes a public Signal, Topic, and immutable Edition.",
    url: "/method",
  },
};

const layers = [
  {
    number: "01",
    title: "Observation",
    copy: "What the source directly records: a probability move, a rule-state change, a publication, a trial update, or another time-stamped event.",
  },
  {
    number: "02",
    title: "Analysis",
    copy: "What can be derived from those records: comparisons, persistence, relationships, calculations, and the limits of the available window.",
  },
  {
    number: "03",
    title: "Assessment",
    copy: "What Open Signal concludes, at what confidence, under which Charter and model version, with uncertainty and counterevidence left visible.",
  },
];

export default function MethodPage() {
  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "WebPage",
          name: "Open Signal Method",
          url: absoluteUrl("/method"),
          description: "How Open Signal turns public source records into verified, versioned Signals.",
        }}
      />
      <SiteShell active="method">
        <article className="method-page">
          <header className="method-hero">
            <div><p className="eyebrow">Evidence before presentation</p><h1>How Open Signal makes a public claim</h1></div>
            <p>
              The interface is not the authority. Every visible conclusion points back to a
              versioned Claim, its evidence bundle, its lineage, and the snapshot in which it appeared.
            </p>
          </header>

          <section className="method-layers" aria-labelledby="epistemic-layers-title">
            <header>
              <p className="eyebrow">The epistemic stack</p>
              <h2 id="epistemic-layers-title">Three layers that must not collapse into one another</h2>
            </header>
            <div data-count={layers.length} data-density={collectionDensity(layers.length, "grid")}>
              {layers.map((layer) => (
                <article key={layer.number}>
                  <span>{layer.number}</span><h3>{layer.title}</h3><p>{layer.copy}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="method-flow" aria-labelledby="publication-flow-title">
            <header><p className="eyebrow">Publication lifecycle</p><h2 id="publication-flow-title">From source record to public surface</h2></header>
            <ol data-count={5} data-density={collectionDensity(5, "grid")}>
              <li><span>Source</span><p>Adapters preserve raw public records and source timestamps.</p></li>
              <li><span>Candidate</span><p>Detectors identify material changes without deciding what they mean.</p></li>
              <li><span>Claim</span><p>A Charter Agent or deterministic builder produces a bounded proposition and evidence bundle.</p></li>
              <li><span>Verification</span><p>Gates check provenance, freshness, contradiction, duplication, lineage, and display safety.</p></li>
              <li><span>Edition</span><p>The compiler selects verified Render Plans and publishes a complete immutable snapshot.</p></li>
            </ol>
          </section>

          <section className="method-principles" aria-labelledby="interface-contract-title">
            <header><p className="eyebrow">Interface contract</p><h2 id="interface-contract-title">Different actions have different destinations</h2></header>
            <dl data-count={4} data-density={collectionDensity(4, "grid")}>
              <div><dt>Signal title</dt><dd>Leaves the snapshot for the permanent, crawlable Signal record.</dd></div>
              <div><dt>Evidence</dt><dd>Opens a temporary Overlay for quick verification without losing reading context.</dd></div>
              <div><dt>Topic</dt><dd>Opens the long-lived canonical question, its source markets, rules, and related Signals.</dd></div>
              <div><dt>Edition</dt><dd>Reconstructs a complete historical publication state; it is never a hidden homepage section.</dd></div>
            </dl>
          </section>

          <section className="method-freshness" aria-labelledby="freshness-title">
            <div><p className="eyebrow">Freshness and retirement</p><h2 id="freshness-title">No artificial “today” boundary</h2></div>
            <p>
              Sections refresh when their own pipelines produce verified material. A still-valid Section
              can remain visible with its original timestamp; once its policy-defined validity or hard
              retirement boundary is reached, the compiler removes it and republishes a complete page.
              It does not invent a replacement to fill an empty slot.
            </p>
          </section>

          <footer className="method-footer">
            <p>Ready to inspect the public record?</p>
            <div><Link href="/explore">Explore Signals and Topics →</Link><Link href="/editions">Browse Editions →</Link></div>
          </footer>
        </article>
      </SiteShell>
    </>
  );
}
