import type { ClaimPageData } from "../../lib/api";
import { fetchClaim } from "../../lib/api";

export const metadata = { title: "Signal" };

function timeStr(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

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
      <main className="claim-page">
        <h1>SIGNAL NOT FOUND</h1>
        <p style={{ color: "var(--text-secondary)", marginTop: "1rem" }}>
          No public record for <code>{id}</code>.
        </p>
      </main>
    );
  }

  return (
    <main className="claim-page">
      {/* header */}
      <header>
        <p style={{ color: "var(--text-secondary)", fontSize: 11, marginBottom: 4 }}>
          CLAIM {page.claim.id.slice(0, 8)}… · {page.claim.claim_type} ·{" "}
          <span style={{ color: "var(--accent-up)" }}>{page.claim.status.toUpperCase()}</span>
        </p>
        <h1>{page.observation}</h1>
      </header>

      {/* headline-style probability statement */}
      <div className="headline-statement">{page.observation}</div>

      {/* Analysis */}
      <section>
        <h2>▸ Analysis</h2>
        <pre>{JSON.stringify(page.analysis.structured_proposition, null, 2)}</pre>
      </section>

      {/* Assessment */}
      <section>
        <h2>▸ Assessment</h2>
        <dl>
          <dt>Confidence</dt>
          <dd>
            {page.assessment.confidence?.toFixed(3)} · {page.assessment.confidence_label}
          </dd>
          <dt>Epistemic</dt>
          <dd>{page.assessment.epistemic_status}</dd>
          <dt>Model · Charter</dt>
          <dd>
            {page.assessment.model_version} / {page.assessment.charter_version}
          </dd>
        </dl>
      </section>

      {/* Evidence */}
      <section>
        <h2>▸ Evidence</h2>
        <ul style={{ paddingLeft: 18 }}>
          {page.evidence.items.map((item, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              <pre>{JSON.stringify(item)}</pre>
            </li>
          ))}
          {page.evidence.items.length === 0 && (
            <li style={{ color: "var(--text-secondary)" }}>No evidence.</li>
          )}
        </ul>
        {page.evidence.snapshot_hash && (
          <p style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            snap: {page.evidence.snapshot_hash.slice(0, 16)}…
          </p>
        )}
      </section>

      {/* Counterevidence */}
      <section>
        <h2>▸ Counterevidence</h2>
        <ul style={{ paddingLeft: 18 }}>
          {page.counterevidence.items.map((item, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              <pre>{JSON.stringify(item)}</pre>
            </li>
          ))}
          {page.counterevidence.items.length === 0 && (
            <li style={{ color: "var(--text-secondary)" }}>None recorded.</li>
          )}
        </ul>
      </section>

      {/* Agent Lineage */}
      <section>
        <h2>▸ Lineage</h2>
        <p>
          {page.agent_lineage.name ?? page.agent_lineage.lineage_id}
          {page.agent_lineage.foundation_model
            ? ` · ${page.agent_lineage.foundation_model} ${page.agent_lineage.model_version ?? ""}`
            : ""}
          {page.agent_lineage.status ? ` · ${page.agent_lineage.status}` : ""}
        </p>
      </section>

      {/* Version History */}
      <section>
        <h2>▸ History</h2>
        <ol style={{ paddingLeft: 18 }}>
          {page.version_history.map((v) => (
            <li key={v.version_number} style={{ marginBottom: 8 }}>
              <strong>v{v.version_number}</strong> ({v.change_type}: {v.change_reason}){" "}
              — {v.public_statement}
              <br />
              <span style={{ color: "var(--text-secondary)", fontSize: 11 }}>
                conf {v.confidence?.toFixed(3)} · {timeStr(v.created_at)}
              </span>
            </li>
          ))}
        </ol>
      </section>

      {/* meta footer */}
      <footer style={{ marginTop: "2rem", paddingTop: "1rem", borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--text-secondary)" }}>
        {page.claim.desk_id} · issued {timeStr(page.claim.issued_at)}
      </footer>
    </main>
  );
}
