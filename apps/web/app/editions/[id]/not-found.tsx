import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { localePath } from "../../../lib/i18n";
import { getRequestLocale } from "../../../lib/request-locale";

export default async function EditionNotFound() {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  return (
    <SiteShell active="archive">
      <div className="claim-route-state">
        <p className="eyebrow">{traditional ? "找不到期次" : "Edition not found"}</p>
        <h1>{traditional ? "此期次識別碼沒有公開快照。" : "No public snapshot exists for this Edition identifier."}</h1>
        <p>{traditional ? "目前出版內容與所有已建立索引的典藏快照仍可使用。" : "The current publication and all indexed archive snapshots remain available."}</p>
        <Link href={localePath("/editions", locale)}>{traditional ? "返回典藏" : "Return to the archive"} →</Link>
      </div>
    </SiteShell>
  );
}
