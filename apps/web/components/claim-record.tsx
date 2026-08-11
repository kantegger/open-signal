import Link from "next/link";
import type { ClaimPageData, JsonRecord } from "../lib/api";
import { collectionDensity, collectionDetailBudget } from "../lib/collection-density";
import { formatDateTime, humanize, localePath, type SupportedLocale } from "../lib/i18n";
import { topicPath } from "../lib/urls";
import { DirectionalStatement } from "./directional-statement";
import { Icon } from "./icons";

export function ClaimRecord({ page, locale }: { page: ClaimPageData; locale: SupportedLocale }) {
  const traditional = locale === "zh-Hant";
  const uncertainty = page.uncertainty ?? { unresolved_questions: [], known_limitations: [] };
  return (
    <article className="claim-record-page">
      <nav className="claim-breadcrumb" aria-label={traditional ? "麵包屑導覽" : "Breadcrumb"}>
        <Link href={localePath("/", locale)}>{traditional ? "即時版面" : "Current"}</Link><span>→</span>
        {page.topic ? (
          <><Link href={topicPath(page.topic.title, page.topic.id, locale)}>{page.topic.title}</Link><span>→</span></>
        ) : null}
        <span>Claim {page.claim.id.slice(0, 8)}</span>
      </nav>

      {traditional && page.locale?.fallback_used ? (
        <p className="translation-fallback-notice" role="note">
          此筆 Claim 尚未有通過驗證的繁體中文呈現；以下保留不可變的英文原文，數字、日期與狀態均未改寫。
        </p>
      ) : null}

      <header className="claim-record-header">
        <div>
          <p className="eyebrow">{traditional ? "公開 Claim" : "Public Claim"} · {humanize(page.claim.claim_type)}</p>
          <h1><DirectionalStatement text={page.claim.public_statement || page.observation} /></h1>
          <p>{page.observation}</p>
        </div>
        <dl>
          <div><dt>Claim ID</dt><dd>{page.claim.id}</dd></div>
          <div><dt>{traditional ? "狀態" : "Status"}</dt><dd className="verified-state">{humanize(page.claim.status)}</dd></div>
          <div><dt>{traditional ? "發布" : "Issued"}</dt><dd>{formatDateTime(page.claim.issued_at, locale)}</dd></div>
          <div><dt>{traditional ? "有效至" : "Valid until"}</dt><dd>{page.claim.valid_until ? formatDateTime(page.claim.valid_until, locale) : traditional ? "沒有固定到期日" : "No fixed expiry"}</dd></div>
        </dl>
      </header>

      <section className="claim-epistemic" aria-label={traditional ? "Claim 認識論層級" : "Claim epistemic layers"}>
        <div><p className="eyebrow">{traditional ? "觀測" : "Observation"}</p><h2>{traditional ? "觀測到什麼" : "What was observed"}</h2><p>{page.observation}</p></div>
        <div><p className="eyebrow">{traditional ? "分析" : "Analysis"}</p><h2>{traditional ? "此模式支持什麼" : "What the pattern supports"}</h2><p>{page.analysis.summary || propositionSummary(page.analysis.structured_proposition, locale)}</p></div>
        <div><p className="eyebrow">{traditional ? "判斷" : "Assessment"}</p><h2>{traditional ? "Open Signal 的判斷" : "Open Signal’s judgment"}</h2><p>{page.assessment.summary || humanize(page.assessment.epistemic_status)}</p></div>
      </section>

      <section className="claim-assessment-grid">
        <div><span>{traditional ? "信心程度" : "Confidence"}</span><strong>{confidenceLabel(page, locale)}</strong><p>{page.assessment.confidence === null || page.assessment.confidence === undefined ? traditional ? "未發布數值" : "No numeric value published" : `${Math.round(page.assessment.confidence * 100)}% ${traditional ? "Claim 信心程度" : "Claim confidence"}`}</p></div>
        <div><span>{traditional ? "證據涵蓋" : "Evidence coverage"}</span><strong>{page.evidence.items.length + (page.supporting_evidence?.items.length ?? 0)} {traditional ? "筆" : "items"}</strong><p>{traditional ? "與已發布 Claim 版本一同凍結" : "Frozen with the published Claim version"}</p></div>
        <div><span>{traditional ? "未解問題" : "Open questions"}</span><strong>{uncertainty.unresolved_questions.length}</strong><p>{renderUnknown(uncertainty.unresolved_questions[0]) || (traditional ? "沒有記錄未解問題" : "No open question recorded")}</p></div>
        <div><span>{traditional ? "反證" : "Counterevidence"}</span><strong>{page.counterevidence.items.length} {traditional ? "筆" : "items"}</strong><p>{page.counterevidence.items.length ? traditional ? "明確保留於下方" : "Explicitly preserved below" : traditional ? "此證據包沒有記錄" : "None recorded in this bundle"}</p></div>
      </section>

      <section className="claim-evidence-section">
        <header>
          <p className="eyebrow">{traditional ? "證據" : "Evidence"}</p>
          <h2>{traditional ? "已發布證據包" : "Published evidence bundle"}</h2>
          <p>{page.evidence_record
            ? traditional ? "此內容定址證據包在 Claim 可發布前已完成儲存與回讀驗證。" : "This content-addressed bundle was stored and read back before the Claim became publishable."
            : page.claim.evidence_policy_version === "sealed-v1"
              ? traditional ? "證據封存仍在等待中；此 Claim 尚不能進入公開期次。" : "Evidence sealing is pending; this Claim cannot enter a public Edition yet."
              : traditional ? "此舊 Claim 早於封存證據切換；其證據仍保留在已發布的 Claim 紀錄內。" : "This legacy Claim predates the sealed-evidence cutover; its evidence remains inside the published Claim record."}</p>
          {page.evidence_record?.url ? (
            <a className="sealed-evidence-link" href={page.evidence_record.url} rel="noreferrer" target="_blank">
              {traditional ? "開啟封存證據" : "Open sealed evidence"} <Icon name="arrow" size={15} />
            </a>
          ) : null}
        </header>
        <div className="claim-evidence-columns">
          <ClaimEvidenceList title={traditional ? "主要與支持證據" : "Primary and supporting"} items={[...page.evidence.items, ...(page.supporting_evidence?.items ?? [])]} locale={locale} />
          <ClaimEvidenceList title={traditional ? "反證" : "Counterevidence"} items={page.counterevidence.items} locale={locale} />
        </div>
      </section>

      <section className="claim-method-lineage">
        <div>
          <p className="eyebrow">{traditional ? "方法" : "Method"}</p>
          <h2>{traditional ? "計算與涵蓋" : "Calculation and coverage"}</h2>
          <p>{methodSummary(page, locale)}</p>
          {page.method?.calculation_ids.length ? <code>{page.method.calculation_ids.join(" · ")}</code> : null}
        </div>
        <div>
          <p className="eyebrow">{traditional ? "譜系" : "Lineage"}</p>
          <h2>{page.agent_lineage.name || page.claim.desk_id}</h2>
          <dl>
            <div><dt>{traditional ? "譜系 ID" : "Lineage ID"}</dt><dd>{page.agent_lineage.lineage_id}</dd></div>
            <div><dt>{traditional ? "基礎模型" : "Foundation model"}</dt><dd>{page.agent_lineage.foundation_model || (traditional ? "內部已有記錄" : "Recorded internally")}</dd></div>
            <div><dt>{traditional ? "模型版本" : "Model version"}</dt><dd>{page.agent_lineage.model_version || page.assessment.model_version || (traditional ? "內部已有記錄" : "Recorded internally")}</dd></div>
            <div><dt>Charter</dt><dd>{page.agent_lineage.charter_version || page.assessment.charter_version || (traditional ? "內部已有記錄" : "Recorded internally")}</dd></div>
          </dl>
        </div>
      </section>

      <section className="claim-history-section">
        <header><p className="eyebrow">{traditional ? "歷史" : "History"}</p><h2>{traditional ? "不可變的公開版本" : "Immutable public versions"}</h2></header>
        <div
          className="claim-history-list"
          data-count={page.version_history.length}
          data-density={collectionDensity(page.version_history.length, "list")}
        >
          {page.version_history.map((version) => (
            <article key={version.version_number}>
              <strong>v{version.version_number}</strong>
              <div><span>{humanize(version.change_type)}</span><time>{formatDateTime(version.created_at, locale)}</time></div>
              <p><DirectionalStatement text={version.public_statement} /></p>
              <small>{version.change_reason}</small>
            </article>
          ))}
          {page.version_history.length === 0 ? <p className="empty-copy">{traditional ? "沒有其他公開版本。" : "No additional public versions."}</p> : null}
        </div>
      </section>

      <section className="claim-resolution-section">
        <div><p className="eyebrow">{traditional ? "結算契約" : "Resolution contract"}</p><h2>{page.resolution_contract ? traditional ? "在結果發生前鎖定" : "Locked before outcome" : traditional ? "不適用" : "Not applicable"}</h2></div>
        <p>{page.resolution_contract ? traditional ? `評估截止時間：${formatDateTime(stringValue(page.resolution_contract.evaluation_deadline), locale)}。` : `Evaluation deadline ${formatDateTime(stringValue(page.resolution_contract.evaluation_deadline), locale)}.` : traditional ? "此觀測沒有提出需要結算的預測。" : "This observation does not make a forecast that requires resolution."}</p>
        {page.resolution_contract ? <Icon name="lock" size={22} /> : null}
      </section>

      <footer className="claim-record-footer">
        <span>{page.evidence_record ? `${traditional ? "封存物件" : "Sealed object"} ${page.evidence_record.object_hash.slice(0, 24)}` : `${traditional ? "證據快照" : "Evidence snapshot"} ${page.evidence.snapshot_hash?.slice(0, 24) || (traditional ? "已記錄於帳本" : "recorded in ledger")}`}</span>
        <Link href={localePath("/", locale)}>{traditional ? "返回目前即時版面" : "Return to current front page"} <Icon name="arrow" size={16} /></Link>
      </footer>
    </article>
  );
}

function ClaimEvidenceList({ title, items, locale }: { title: string; items: unknown[]; locale: SupportedLocale }) {
  const detailLimit = collectionDetailBudget(items.length, "list");
  return (
    <div
      className="claim-evidence-list"
      data-count={items.length}
      data-density={collectionDensity(items.length, "list")}
    >
      <h3>{title}</h3>
      {items.length ? items.map((item, index) => {
        const record = objectValue(item);
        const href = stringValue(record.url ?? record.source_url);
        return (
          <article key={`${evidenceTitle(item)}-${index}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div><strong>{evidenceTitle(item)}</strong><p>{evidenceMeta(item, detailLimit)}</p></div>
            {href ? <a href={href} rel="noreferrer" target="_blank">{locale === "zh-Hant" ? "來源" : "Source"} ↗</a> : null}
          </article>
        );
      }) : <p className="empty-copy">{locale === "zh-Hant" ? "此證據角色沒有記錄。" : "None recorded in this evidence role."}</p>}
    </div>
  );
}

function propositionSummary(proposition: JsonRecord, locale: SupportedLocale): string {
  const localized = objectValue(proposition[locale] ?? proposition.en);
  return stringValue(localized.analysis ?? proposition.predicate) || (locale === "zh-Hant" ? "類型化命題已保留在公開帳本中。" : "The typed proposition is preserved in the public ledger.");
}

function confidenceLabel(page: ClaimPageData, locale: SupportedLocale): string {
  if (page.assessment.confidence_label) return humanize(page.assessment.confidence_label);
  const value = page.assessment.confidence;
  if (value === null || value === undefined) return locale === "zh-Hant" ? "未評分" : "Not scored";
  if (locale === "zh-Hant") return value >= 0.8 ? "高" : value >= 0.55 ? "中" : "低";
  return value >= 0.8 ? "High" : value >= 0.55 ? "Medium" : "Low";
}

function methodSummary(page: ClaimPageData, locale: SupportedLocale): string {
  const sourceCount = page.method?.source_coverage.sources;
  const sourceText = typeof sourceCount === "number" ? `${sourceCount} source${sourceCount === 1 ? "" : "s"}` : "the frozen evidence bundle";
  if (locale === "zh-Hant") {
    const localizedSource = typeof sourceCount === "number" ? `${sourceCount} 個來源` : "已凍結的證據包";
    return `此 Claim 由${localizedSource}組成。頁面只呈現已儲存結果，不會重新計算或暗中更新已發布判斷。`;
  }
  return `This Claim was assembled from ${sourceText}. The page presents the stored result and never recomputes or silently updates the published judgment.`;
}

function evidenceTitle(value: unknown): string {
  const record = objectValue(value);
  return stringValue(record.title ?? record.name ?? record.source ?? record.type ?? record.description) || renderUnknown(value) || "Evidence item";
}

function evidenceMeta(value: unknown, limit = 4): string {
  const record = objectValue(value);
  const values = Object.entries(record)
    .filter(([key, item]) => !["title", "name", "source", "type", "description", "url", "source_url"].includes(key) && ["string", "number", "boolean"].includes(typeof item))
    .slice(0, limit)
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
