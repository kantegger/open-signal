import { SiteShell } from "../../../components/site-shell";
import { getRequestLocale } from "../../../lib/request-locale";

export default async function TopicLoading() {
  const locale = await getRequestLocale();
  return (
    <SiteShell active="explore" systemState="checking">
      <div aria-busy="true" className="topic-page skeleton-page">
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-chart" />
        <span className="sr-only">{locale === "zh-Hant" ? "正在載入預期主題。" : "Loading expectation topic."}</span>
      </div>
    </SiteShell>
  );
}
