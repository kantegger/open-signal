"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ClaimPageData, JsonRecord } from "../lib/api";
import { fetchClaim } from "../lib/api";
import { collectionDensity, collectionDetailBudget } from "../lib/collection-density";
import { formatDateTime, humanize, localePath } from "../lib/i18n";
import { DirectionalStatement } from "./directional-statement";
import { Icon } from "./icons";
import { useLocale } from "./locale-provider";

export default function EvidenceSheet({
  claimId,
  onClose,
}: {
  claimId: string;
  onClose: () => void;
}) {
  const { locale, text } = useLocale();
  const [page, setPage] = useState<ClaimPageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const claimRequestRef = useRef<{
    claimId: string;
    promise: ReturnType<typeof fetchClaim>;
  } | null>(null);

  const retry = useCallback(async () => {
    setRetrying(true);
    try {
      const result = await fetchClaim(claimId, undefined, locale);
      setPage(result);
      setError(null);
    } catch (reason) {
      setError(claimError(reason));
    } finally {
      setRetrying(false);
    }
  }, [claimId, locale]);

  useEffect(() => {
    let cancelled = false;
    const request = claimRequestRef.current?.claimId === claimId
      ? claimRequestRef.current.promise
      : fetchClaim(claimId, undefined, locale);
    claimRequestRef.current = { claimId, promise: request };
    void request
      .then((result) => {
        if (cancelled) return;
        setPage(result);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(claimError(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [claimId, locale]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  return (
    <div
      className="sheet-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="presentation"
    >
      <section
        aria-describedby="evidence-sheet-description"
        aria-labelledby="evidence-sheet-title"
        aria-modal="true"
        className="evidence-sheet"
        ref={panelRef}
        role="dialog"
      >
        <header className="sheet-header">
          <div>
            <h1 id="evidence-sheet-title">{locale === "zh-Hant" ? "證據與 Claim" : "Evidence and Claim"}</h1>
            <p id="evidence-sheet-description">{locale === "zh-Hant" ? "此訊號的完整透明紀錄。" : "Complete transparency for this signal."}</p>
          </div>
          <button aria-label={locale === "zh-Hant" ? "關閉證據" : "Close evidence"} className="sheet-close" onClick={onClose} ref={closeRef} type="button">
            <Icon name="close" size={21} /><span>{locale === "zh-Hant" ? "關閉" : "Close"}</span><kbd>Esc</kbd>
          </button>
        </header>

        {!page && !error ? <SheetSkeleton locale={locale} /> : null}
        {error ? (
          <div className="sheet-error" role="alert">
            <p className="eyebrow">{locale === "zh-Hant" ? "證據暫時無法使用" : "Evidence temporarily unavailable"}</p>
            <h2>{locale === "zh-Hant" ? "無法載入公開 Claim 紀錄。" : "The public Claim record could not be loaded."}</h2>
            <code>{error}</code>
            <button disabled={retrying} onClick={() => void retry()} type="button">
              <Icon name="refresh" size={17} /> {retrying ? text.checking : text.retry}
            </button>
          </div>
        ) : null}
        {page ? <SheetRecord page={page} /> : null}
      </section>
    </div>
  );
}

function SheetRecord({ page }: { page: ClaimPageData }) {
  const { locale } = useLocale();
  const traditional = locale === "zh-Hant";
  const confidence = page.assessment.confidence;
  const uncertainty = page.uncertainty ?? { unresolved_questions: [], known_limitations: [] };
  return (
    <div className="sheet-record">
      {traditional && page.locale?.fallback_used ? (
        <p className="translation-fallback-notice" role="note">
          此筆 Claim 尚未有通過驗證的繁體中文呈現；以下保留英文原文。
        </p>
      ) : null}
      <section className="claim-statement-block">
        <div>
          <p className="eyebrow">Claim <span>({traditional ? "公開陳述" : "public statement"})</span></p>
          <h2><DirectionalStatement text={page.claim.public_statement || page.observation} /></h2>
          <p className="claim-context">{page.observation}</p>
        </div>
        <dl className="claim-identity">
          <div><dt>Claim ID</dt><dd>{page.claim.id}</dd></div>
          <div><dt>{traditional ? "狀態" : "Status"}</dt><dd className="verified-state">{humanize(page.claim.status)}</dd></div>
          <div><dt>{traditional ? "最近實質更新" : "Last materially updated"}</dt><dd>{formatDateTime(page.claim.materially_updated_at ?? page.claim.issued_at, locale)}</dd></div>
        </dl>
      </section>

      <section className="epistemic-grid" aria-label={traditional ? "觀測、分析與判斷" : "Observation, analysis, and assessment"}>
        <div><p className="eyebrow">{traditional ? "觀測" : "Observation"}</p><p>{page.observation}</p></div>
        <div><p className="eyebrow">{traditional ? "分析" : "Analysis"}</p><p>{page.analysis.summary || propositionSummary(page.analysis.structured_proposition, locale)}</p></div>
        <div><p className="eyebrow">{traditional ? "Open Signal 判斷" : "Open Signal assessment"}</p><p>{page.assessment.summary || humanize(page.assessment.epistemic_status)}</p></div>
      </section>

      <section className="trust-rationale-grid">
        <div>
          <p className="eyebrow">{traditional ? "信心程度" : "Confidence"} <b>{confidenceLabel(page, locale)}</b></p>
          <p>{confidence === null || confidence === undefined ? traditional ? "未發布數值信心程度。" : "No numeric confidence was published." : `${Math.round(confidence * 100)}% ${traditional ? "（已發布 Claim 尺度）" : "on the published Claim scale."}`}</p>
        </div>
        <div>
          <p className="eyebrow">{traditional ? "證據涵蓋" : "Evidence coverage"} <b>{coverageLabel(page, locale)}</b></p>
          <p>{page.evidence.items.length + (page.supporting_evidence?.items.length ?? 0)} {traditional ? "筆支持證據保留於凍結證據包。" : "supporting evidence items in the frozen bundle."}</p>
        </div>
        <div>
          <p className="eyebrow">{traditional ? "主要不確定性" : "Main uncertainty"} <b>{uncertainty.unresolved_questions.length ? traditional ? "未解" : "Open" : traditional ? "有界" : "Bounded"}</b></p>
          <p>{renderUnknown(uncertainty.unresolved_questions[0] ?? uncertainty.known_limitations[0]) || (traditional ? "未發布其他不確定性說明。" : "No additional uncertainty statement was published.")}</p>
        </div>
      </section>

      <section className="evidence-columns">
        <EvidenceList title={traditional ? "主要證據" : "Primary evidence"} items={page.evidence.items} />
        <div>
          <EvidenceList title={traditional ? "反證" : "Counterevidence"} items={page.counterevidence.items} compact />
          <div className="alternative-explanation">
            <p className="eyebrow">{traditional ? "替代解釋" : "Alternative explanation"}</p>
            <p>{renderUnknown(page.counterevidence.items[0]) || renderUnknown(uncertainty.known_limitations[0]) || (traditional ? "沒有記錄具證據支持的替代解釋。" : "No supported alternative explanation was recorded.")}</p>
          </div>
        </div>
      </section>

      <section className="method-summary">
        <p className="eyebrow">{traditional ? "方法／計算摘要" : "Method / calculation summary"}</p>
        <p>{methodSummary(page, locale)}</p>
        {page.method?.calculation_ids.length ? <small>{traditional ? "計算紀錄" : "Calculation records"}: {page.method.calculation_ids.join(", ")}</small> : null}
      </section>

      <section className="lineage-grid" aria-label={traditional ? "Agent 與模型譜系" : "Agent and model lineage"}>
        <div><span>{traditional ? "Agent 編輯台" : "Agent desk"}</span><strong>{page.agent_lineage.name || page.claim.desk_id}</strong></div>
        <div><span>{traditional ? "譜系" : "Lineage"}</span><strong>{page.agent_lineage.lineage_id}</strong></div>
        <div><span>{traditional ? "模型" : "Model"}</span><strong>{page.agent_lineage.foundation_model || page.assessment.model_version || (traditional ? "已記錄於帳本" : "Recorded in ledger")}</strong></div>
        <div><span>Charter {traditional ? "版本" : "version"}</span><strong>{page.agent_lineage.charter_version || page.assessment.charter_version || (traditional ? "已記錄於帳本" : "Recorded in ledger")}</strong></div>
      </section>

      <section className="version-history">
        <p className="eyebrow">{traditional ? "版本歷史" : "Version history"}</p>
        {page.version_history.length ? (
          <div
            className="history-table"
            role="table"
            aria-label={traditional ? "Claim 版本歷史" : "Claim version history"}
            data-count={page.version_history.length}
            data-density={collectionDensity(page.version_history.length, "table")}
          >
            {page.version_history.map((version) => (
              <div className="history-row" role="row" key={version.version_number}>
                <strong role="cell">v{version.version_number}</strong>
                <time role="cell">{formatDateTime(version.created_at, locale)}</time>
                <span role="cell">{humanize(version.change_type)}</span>
                <span role="cell">{version.change_reason}</span>
              </div>
            ))}
          </div>
        ) : <p className="empty-copy">{traditional ? "沒有其他公開版本。" : "No additional public versions."}</p>}
      </section>

      <section className="resolution-contract">
        <p className="eyebrow">{traditional ? "結算契約" : "Resolution contract"}</p>
        {page.resolution_contract ? (
          <p>{traditional ? "此 Claim 具鎖定的結算契約。評估截止時間" : "This Claim has a locked resolution contract. Evaluation deadline"}: {formatDateTime(stringValue(page.resolution_contract.evaluation_deadline), locale)}。</p>
        ) : <p>{traditional ? "此觀測不適用結算契約。" : "No resolution contract applies to this observation."}</p>}
      </section>

      <footer className="sheet-footer">
        <span>{traditional ? "證據快照" : "Evidence snapshot"} {page.evidence.snapshot_hash?.slice(0, 16) || (traditional ? "已記錄於帳本" : "recorded in ledger")}</span>
        <Link href={localePath(`/claims/${page.claim.id}`, locale)}>{traditional ? "開啟完整 Claim 頁面" : "Open full Claim page"} <Icon name="arrow" size={16} /></Link>
      </footer>
    </div>
  );
}

function EvidenceList({ title, items, compact = false }: { title: string; items: unknown[]; compact?: boolean }) {
  const { locale } = useLocale();
  const detailLimit = collectionDetailBudget(items.length, "list");
  return (
    <div
      className={`evidence-list${compact ? " is-compact" : ""}`}
      data-count={items.length}
      data-density={collectionDensity(items.length, "list")}
    >
      <p className="eyebrow">{title}</p>
      {items.length ? (
        <ol>
          {items.map((item, index) => {
            const record = objectValue(item);
            const href = stringValue(record.url ?? record.source_url);
            return (
              <li key={`${evidenceTitle(item)}-${index}`}>
                <span>{index + 1}</span>
                <div>
                  <strong>{evidenceTitle(item)}</strong>
                  <small>{evidenceMeta(item, detailLimit)}</small>
                </div>
                {href ? <a href={href} rel="noreferrer" target="_blank">{locale === "zh-Hant" ? "來源" : "Source"}</a> : null}
              </li>
            );
          })}
        </ol>
      ) : <p className="empty-copy">{locale === "zh-Hant" ? "此證據角色沒有記錄。" : "None recorded in this evidence role."}</p>}
    </div>
  );
}

function SheetSkeleton({ locale }: { locale: "en" | "zh-Hant" }) {
  return (
    <div aria-busy="true" className="sheet-skeleton">
      <div className="skeleton skeleton-kicker" />
      <div className="skeleton skeleton-headline" />
      <div className="skeleton skeleton-headline short" />
      <div className="skeleton-row"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
      <div className="skeleton skeleton-table" />
      <span className="sr-only">{locale === "zh-Hant" ? "正在載入 Claim 證據。" : "Loading Claim evidence."}</span>
    </div>
  );
}

function propositionSummary(proposition: JsonRecord, locale: "en" | "zh-Hant"): string {
  const localized = objectValue(proposition[locale] ?? proposition.en);
  return stringValue(localized.analysis ?? proposition.predicate) || (locale === "zh-Hant" ? "結構化命題可在永久 Claim 紀錄中查閱。" : "The structured proposition is available in the permanent Claim record.");
}

function confidenceLabel(page: ClaimPageData, locale: "en" | "zh-Hant"): string {
  if (page.assessment.confidence_label) return humanize(page.assessment.confidence_label);
  const value = page.assessment.confidence;
  if (value === null || value === undefined) return locale === "zh-Hant" ? "未評分" : "Not scored";
  if (locale === "zh-Hant") return value >= 0.8 ? "高" : value >= 0.55 ? "中" : "低";
  return value >= 0.8 ? "High" : value >= 0.55 ? "Medium" : "Low";
}

function coverageLabel(page: ClaimPageData, locale: "en" | "zh-Hant"): string {
  const count = page.evidence.items.length + (page.supporting_evidence?.items.length ?? 0);
  if (locale === "zh-Hant") return count >= 5 ? "高" : count >= 2 ? "中" : "有限";
  return count >= 5 ? "High" : count >= 2 ? "Medium" : "Limited";
}

function methodSummary(page: ClaimPageData, locale: "en" | "zh-Hant"): string {
  const coverage = page.method?.source_coverage;
  const sourceCount = coverage ? coverage.sources : null;
  const count = typeof sourceCount === "number" ? `${sourceCount} source${sourceCount === 1 ? "" : "s"}` : "the frozen evidence bundle";
  if (locale === "zh-Hant") {
    const localizedCount = typeof sourceCount === "number" ? `${sourceCount} 個來源` : "已凍結的證據包";
    return `已發布判斷由${localizedCount}推導。觀測、分析與判斷各自保留版本；介面不會重新計算 Claim。`;
  }
  return `The published assessment is derived from ${count}. Observation, analysis, and assessment remain separately versioned; the interface does not recalculate the Claim.`;
}

function evidenceTitle(value: unknown): string {
  const record = objectValue(value);
  return stringValue(record.title ?? record.name ?? record.source ?? record.type ?? record.description) || renderUnknown(value) || "Evidence item";
}

function evidenceMeta(value: unknown, limit = 3): string {
  const record = objectValue(value);
  const excluded = new Set(["title", "name", "source", "type", "description", "url", "source_url"]);
  const details = Object.entries(record)
    .filter(([key, item]) => !excluded.has(key) && ["string", "number", "boolean"].includes(typeof item))
    .slice(0, limit)
    .map(([key, item]) => `${humanize(key)} ${String(item)}`);
  return details.join(" · ") || "Frozen in the evidence bundle";
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

function claimError(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Claim evidence did not respond.";
}
