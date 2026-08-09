import Link from "next/link";
import type { ClaimPageData, JsonRecord } from "../lib/api";
import { formatDateTime, humanize } from "../lib/i18n";
import { topicPath } from "../lib/urls";
import { DirectionalStatement } from "./directional-statement";
import { Icon } from "./icons";

export function ClaimRecord({ page }: { page: ClaimPageData }) {
  const uncertainty = page.uncertainty ?? { unresolved_questions: [], known_limitations: [] };
  return (
    <article className="claim-record-page">
      <nav className="claim-breadcrumb" aria-label="Breadcrumb">
        <Link href="/">Current</Link><span>→</span>
        {page.topic ? (
          <><Link href={topicPath(page.topic.title, page.topic.id)}>{page.topic.title}</Link><span>→</span></>
        ) : null}
        <span>Claim {page.claim.id.slice(0, 8)}</span>
      </nav>

      <header className="claim-record-header">
        <div>
          <p className="eyebrow">Public Claim · {humanize(page.claim.claim_type)}</p>
          <h1><DirectionalStatement text={page.claim.public_statement || page.observation} /></h1>
          <p>{page.observation}</p>
        </div>
        <dl>
          <div><dt>Claim ID</dt><dd>{page.claim.id}</dd></div>
          <div><dt>Status</dt><dd className="verified-state">{humanize(page.claim.status)}</dd></div>
          <div><dt>Issued</dt><dd>{formatDateTime(page.claim.issued_at)}</dd></div>
          <div><dt>Valid until</dt><dd>{page.claim.valid_until ? formatDateTime(page.claim.valid_until) : "No fixed expiry"}</dd></div>
        </dl>
      </header>

      <section className="claim-epistemic" aria-label="Claim epistemic layers">
        <div><p className="eyebrow">Observation</p><h2>What was observed</h2><p>{page.observation}</p></div>
        <div><p className="eyebrow">Analysis</p><h2>What the pattern supports</h2><p>{page.analysis.summary || propositionSummary(page.analysis.structured_proposition)}</p></div>
        <div><p className="eyebrow">Assessment</p><h2>Open Signal’s judgment</h2><p>{page.assessment.summary || humanize(page.assessment.epistemic_status)}</p></div>
      </section>

      <section className="claim-assessment-grid">
        <div><span>Confidence</span><strong>{confidenceLabel(page)}</strong><p>{page.assessment.confidence === null || page.assessment.confidence === undefined ? "No numeric value published" : `${Math.round(page.assessment.confidence * 100)}% Claim confidence`}</p></div>
        <div><span>Evidence coverage</span><strong>{page.evidence.items.length + (page.supporting_evidence?.items.length ?? 0)} items</strong><p>Frozen with the published Claim version</p></div>
        <div><span>Open questions</span><strong>{uncertainty.unresolved_questions.length}</strong><p>{renderUnknown(uncertainty.unresolved_questions[0]) || "No open question recorded"}</p></div>
        <div><span>Counterevidence</span><strong>{page.counterevidence.items.length} items</strong><p>{page.counterevidence.items.length ? "Explicitly preserved below" : "None recorded in this bundle"}</p></div>
      </section>

      <section className="claim-evidence-section">
        <header><p className="eyebrow">Evidence</p><h2>Published evidence bundle</h2><p>Sources and counterevidence are shown as frozen for this Claim version.</p></header>
        <div className="claim-evidence-columns">
          <ClaimEvidenceList title="Primary and supporting" items={[...page.evidence.items, ...(page.supporting_evidence?.items ?? [])]} />
          <ClaimEvidenceList title="Counterevidence" items={page.counterevidence.items} />
        </div>
      </section>

      <section className="claim-method-lineage">
        <div>
          <p className="eyebrow">Method</p>
          <h2>Calculation and coverage</h2>
          <p>{methodSummary(page)}</p>
          {page.method?.calculation_ids.length ? <code>{page.method.calculation_ids.join(" · ")}</code> : null}
        </div>
        <div>
          <p className="eyebrow">Lineage</p>
          <h2>{page.agent_lineage.name || page.claim.desk_id}</h2>
          <dl>
            <div><dt>Lineage ID</dt><dd>{page.agent_lineage.lineage_id}</dd></div>
            <div><dt>Foundation model</dt><dd>{page.agent_lineage.foundation_model || "Recorded internally"}</dd></div>
            <div><dt>Model version</dt><dd>{page.agent_lineage.model_version || page.assessment.model_version || "Recorded internally"}</dd></div>
            <div><dt>Charter</dt><dd>{page.agent_lineage.charter_version || page.assessment.charter_version || "Recorded internally"}</dd></div>
          </dl>
        </div>
      </section>

      <section className="claim-history-section">
        <header><p className="eyebrow">History</p><h2>Immutable public versions</h2></header>
        <div className="claim-history-list">
          {page.version_history.map((version) => (
            <article key={version.version_number}>
              <strong>v{version.version_number}</strong>
              <div><span>{humanize(version.change_type)}</span><time>{formatDateTime(version.created_at)}</time></div>
              <p><DirectionalStatement text={version.public_statement} /></p>
              <small>{version.change_reason}</small>
            </article>
          ))}
          {page.version_history.length === 0 ? <p className="empty-copy">No additional public versions.</p> : null}
        </div>
      </section>

      <section className="claim-resolution-section">
        <div><p className="eyebrow">Resolution contract</p><h2>{page.resolution_contract ? "Locked before outcome" : "Not applicable"}</h2></div>
        <p>{page.resolution_contract ? `Evaluation deadline ${formatDateTime(stringValue(page.resolution_contract.evaluation_deadline))}.` : "This observation does not make a forecast that requires resolution."}</p>
        {page.resolution_contract ? <Icon name="lock" size={22} /> : null}
      </section>

      <footer className="claim-record-footer">
        <span>Evidence snapshot {page.evidence.snapshot_hash?.slice(0, 24) || "recorded in ledger"}</span>
        <Link href="/">Return to current front page <Icon name="arrow" size={16} /></Link>
      </footer>
    </article>
  );
}

function ClaimEvidenceList({ title, items }: { title: string; items: unknown[] }) {
  return (
    <div className="claim-evidence-list">
      <h3>{title}</h3>
      {items.length ? items.map((item, index) => {
        const record = objectValue(item);
        const href = stringValue(record.url ?? record.source_url);
        return (
          <article key={`${evidenceTitle(item)}-${index}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div><strong>{evidenceTitle(item)}</strong><p>{evidenceMeta(item)}</p></div>
            {href ? <a href={href} rel="noreferrer" target="_blank">Source ↗</a> : null}
          </article>
        );
      }) : <p className="empty-copy">None recorded in this evidence role.</p>}
    </div>
  );
}

function propositionSummary(proposition: JsonRecord): string {
  const localized = objectValue(proposition.en);
  return stringValue(localized.analysis ?? proposition.predicate) || "The typed proposition is preserved in the public ledger.";
}

function confidenceLabel(page: ClaimPageData): string {
  if (page.assessment.confidence_label) return humanize(page.assessment.confidence_label);
  const value = page.assessment.confidence;
  if (value === null || value === undefined) return "Not scored";
  return value >= 0.8 ? "High" : value >= 0.55 ? "Medium" : "Low";
}

function methodSummary(page: ClaimPageData): string {
  const sourceCount = page.method?.source_coverage.sources;
  const sourceText = typeof sourceCount === "number" ? `${sourceCount} source${sourceCount === 1 ? "" : "s"}` : "the frozen evidence bundle";
  return `This Claim was assembled from ${sourceText}. The page presents the stored result and never recomputes or silently updates the published judgment.`;
}

function evidenceTitle(value: unknown): string {
  const record = objectValue(value);
  return stringValue(record.title ?? record.name ?? record.source ?? record.type ?? record.description) || renderUnknown(value) || "Evidence item";
}

function evidenceMeta(value: unknown): string {
  const record = objectValue(value);
  const values = Object.entries(record)
    .filter(([key, item]) => !["title", "name", "source", "type", "description", "url", "source_url"].includes(key) && ["string", "number", "boolean"].includes(typeof item))
    .slice(0, 4)
    .map(([key, item]) => `${humanize(key)}: ${String(item)}`);
  return values.join(" · ") || "Frozen in the evidence bundle";
}

function renderUnknown(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value && typeof value === "object") {
    const record = value as JsonRecord;
    return stringValue(record.summary ?? record.description ?? record.title ?? record.value ?? record.type);
  }
  return "";
}

function objectValue(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}
