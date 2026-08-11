import { SiteShell } from "../components/site-shell";
import { getRequestLocale } from "../lib/request-locale";

export default async function Loading() {
  const locale = await getRequestLocale();
  return (
    <SiteShell systemState="checking">
      <div aria-busy="true" className="front-page skeleton-page">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-headline short" />
        <div className="skeleton skeleton-chart" />
        <span className="sr-only">
          {locale === "zh-Hant" ? "正在載入最近的已驗證快照。" : "Loading the latest verified snapshot."}
        </span>
      </div>
    </SiteShell>
  );
}
