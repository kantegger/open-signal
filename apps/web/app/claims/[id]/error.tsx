"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { Icon } from "../../../components/icons";
import { useLocale } from "../../../components/locale-provider";
import { localePath } from "../../../lib/i18n";

export default function ClaimError({ reset }: { error: Error; reset: () => void }) {
  const { locale } = useLocale();
  const traditional = locale === "zh-Hant";
  return (
    <SiteShell active="explore" systemState="unavailable">
      <div className="claim-route-state" role="alert">
        <p className="eyebrow">{traditional ? "Claim 服務暫時無法使用" : "Claim service unavailable"}</p>
        <h1>{traditional ? "無法載入永久 Claim 紀錄。" : "The permanent Claim record could not be loaded."}</h1>
        <p>{traditional ? "帳本未被更動。請重試讀取，或返回目前快照。" : "The ledger has not been changed. Retry the read request or return to the current snapshot."}</p>
        <div><button onClick={reset} type="button"><Icon name="refresh" size={17} /> {traditional ? "重試" : "Retry"}</button><Link href={localePath("/", locale)}>{traditional ? "目前快照" : "Current"}</Link></div>
      </div>
    </SiteShell>
  );
}
