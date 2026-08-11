import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { localePath } from "../../../lib/i18n";
import { getRequestLocale } from "../../../lib/request-locale";

export default async function TopicNotFound() {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  return (
    <SiteShell active="explore">
      <div className="claim-route-state">
        <p className="eyebrow">{traditional ? "找不到主題" : "Topic not found"}</p>
        <h1>{traditional ? "此識別碼沒有公開的標準預期。" : "No public canonical expectation exists for this identifier."}</h1>
        <Link href={localePath("/", locale)}>{traditional ? "返回即時版面" : "Return to the current front page"} →</Link>
      </div>
    </SiteShell>
  );
}
