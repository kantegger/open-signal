import { SiteShell } from "../../../components/site-shell";
import { getRequestLocale } from "../../../lib/request-locale";

export default async function ClaimLoading() {
  const locale = await getRequestLocale();
  return (
    <SiteShell active="explore" systemState="checking">
      <div aria-busy="true" className="claim-record-page claim-loading">
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-headline short" />
        <div className="skeleton-row"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
        <div className="skeleton skeleton-table" />
        <span className="sr-only">{locale === "zh-Hant" ? "正在載入 Claim 紀錄。" : "Loading Claim record."}</span>
      </div>
    </SiteShell>
  );
}
