import type { ClaimPageData } from "../../../lib/api";
import { fetchClaim } from "../../../lib/api";

export const metadata = { title: "Claim" };

export default async function ClaimPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let page: ClaimPageData;
  try {
    page = await fetchClaim(id);
  } catch {
    return (
      <main style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
        <h1>Claim not found</h1>
        <p>No claim with id {id} is publicly available.</p>
      </main>
    );
  }

  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif", maxWidth: 820, margin: "0 auto" }}>
      <header>
        <p style={{ color: "#666", fontSize: 13 }}>
          Claim ID <code>{page.claim.id}</code> · {page.claim.claim_type} ·{" "}
          <span data-testid="status">{page.claim.status}</span>
        </p>
        <h1 style={{ fontSize: 24 }}>{page.observation}</h1>
        <p style={{ color: "#666", fontSize: 13 }}>
          {page.claim.desk_id} · issued {new Date(page.claim.issued_at).toLocaleString()}
        </p>
      </header>

      <Section title="Analysis">
        <pre data-testid="analysis" style={{ whiteSpace: "pre-wrap", background: "#f6f6f6", padding: 12, borderRadius: 8 }}>
          {JSON.stringify(page.analysis.structured_proposition, null, 2)}
        </pre>
      </Section>

      <Section title="Assessment">
        <dl>
          <dt>Confidence</dt>
          <dd data-testid="confidence">
            {page.assessment.confidence?.toFixed(3)} ({page.assessment.confidence_label})
          </dd>
          <dt>Epistemic status</dt>
          <dd>{page.assessment.epistemic_status}</dd>
          <dt>Model / Charter</dt>
          <dd>
            {page.assessment.model_version} / {page.assessment.charter_version}
          </dd>
        </dl>
      </Section>

      <Section title="Evidence">
        <ul data-testid="evidence">
          {page.evidence.items.map((item, i) => (
            <li key={i}>
              <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(item)}</pre>
            </li>
          ))}
          {page.evidence.items.length === 0 && <li>No primary evidence listed.</li>}
        </ul>
        {page.evidence.snapshot_hash && (
          <p style={{ color: "#888", fontSize: 12 }}>
            snapshot {page.evidence.snapshot_hash.slice(0, 16)}…
          </p>
        )}
      </Section>

      <Section title="Counterevidence">
        <ul data-testid="counterevidence">
          {page.counterevidence.items.map((item, i) => (
            <li key={i}>
              <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(item)}</pre>
            </li>
          ))}
          {page.counterevidence.items.length === 0 && <li>None recorded.</li>}
        </ul>
      </Section>

      <Section title="Agent lineage">
        <p data-testid="lineage">
          {page.agent_lineage.name ?? page.agent_lineage.lineage_id}
          {page.agent_lineage.foundation_model
            ? ` · ${page.agent_lineage.foundation_model} ${page.agent_lineage.model_version ?? ""}`
            : ""}
          {page.agent_lineage.status ? ` · ${page.agent_lineage.status}` : ""}
        </p>
      </Section>

      <Section title="Version history">
        <ol data-testid="version-history">
          {page.version_history.map((v) => (
            <li key={v.version_number}>
              <strong>v{v.version_number}</strong> ({v.change_type}: {v.change_reason}) —{" "}
              {v.public_statement}
              <span style={{ color: "#888", fontSize: 12 }}>
                {" "}
                · conf {v.confidence?.toFixed(3)} · {new Date(v.created_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ol>
      </Section>
    </main>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginTop: 28 }}>
      <h2 style={{ fontSize: 16, borderBottom: "1px solid #ddd", paddingBottom: 6 }}>
        {title}
      </h2>
      {children}
    </section>
  );
}
