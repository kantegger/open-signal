import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { localePath } from "../../../lib/i18n";
import { getRequestLocale } from "../../../lib/request-locale";

export default async function ClaimNotFound() {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  return (
    <SiteShell active="explore">
      <div className="claim-route-state">
        <p className="eyebrow">{traditional ? "找不到 Claim" : "Claim not found"}</p>
        <h1>{traditional ? "此 Claim 識別碼沒有公開紀錄。" : "No public record exists for this Claim identifier."}</h1>
        <p>{traditional ? "它可能從未發布，或不屬於公開帳本。" : "It may never have been published, or it may not be part of the public ledger."}</p>
        <Link href={localePath("/", locale)}>{traditional ? "返回即時版面" : "Return to the current front page"} →</Link>
      </div>
    </SiteShell>
  );
}
