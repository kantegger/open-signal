"use client";

import Link from "next/link";
import { Icon } from "../../../components/icons";
import { useLocale } from "../../../components/locale-provider";
import { SiteShell } from "../../../components/site-shell";
import { localePath } from "../../../lib/i18n";

export default function EditionError({ reset }: { error: Error; reset: () => void }) {
  const { locale } = useLocale();
  const traditional = locale === "zh-Hant";
  return (
    <SiteShell active="archive" systemState="unavailable">
      <div className="claim-route-state" role="alert">
        <p className="eyebrow">{traditional ? "典藏暫時無法使用" : "Archive temporarily unavailable"}</p>
        <h1>{traditional ? "無法載入不可變期次。" : "The immutable Edition could not be loaded."}</h1>
        <p>{traditional ? "出版資料未被更動。請重試讀取，或返回目前版面。" : "No publication data was changed. Retry the read request or return to the current page."}</p>
        <div><button onClick={reset} type="button"><Icon name="refresh" size={17} /> {traditional ? "重試" : "Retry"}</button><Link href={localePath("/", locale)}>{traditional ? "即時版面" : "Current"}</Link></div>
      </div>
    </SiteShell>
  );
}
