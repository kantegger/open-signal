import type { Metadata } from "next";
import { cache } from "react";
import { FrontPage } from "../components/front-page";
import { JsonLd } from "../components/json-ld";
import { languageAlternates, localePath } from "../lib/i18n";
import { getRequestLocale } from "../lib/request-locale";
import { fetchCurrentFrontPageServer, fetchSeoIndexServer } from "../lib/server-api";
import { absoluteUrl } from "../lib/site";
import { excerpt, signalPath } from "../lib/urls";

export const revalidate = 3_600;

const getCurrentFrontPage = cache((locale: string) => fetchCurrentFrontPageServer(locale));

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  try {
    const page = await getCurrentFrontPage(locale);
    const lead = page.slots.find((slot) => slot.type === "lead")?.items[0];
    const description = lead
      ? excerpt(
          traditional
            ? `${lead.headline} Open Signal 追蹤預期、規則與研究中經驗證的重大變化。`
            : `${lead.headline} Open Signal tracks verified changes in expectations, rules, and research.`,
        )
      : traditional
        ? "公共預期、規則與研究中經驗證的變化，附帶證據、時間戳與永久紀錄。"
        : "Verified changes in public expectations, rules, and research — with evidence, timestamps, and permanent records.";
    const canonical = localePath("/", locale);
    return {
      title: traditional ? "即時全球訊號 · Open Signal" : "Live global signals · Open Signal",
      description,
      alternates: { canonical, languages: languageAlternates("/") },
      openGraph: {
        title: traditional ? "Open Signal · 即時全球訊號" : "Open Signal · Live global signals",
        description,
        url: canonical,
      },
      twitter: {
        card: "summary_large_image",
        title: traditional ? "Open Signal · 即時全球訊號" : "Open Signal · Live global signals",
        description,
      },
    };
  } catch {
    return {};
  }
}

export default async function HomePage() {
  const locale = await getRequestLocale();
  const [frontPageResult, indexResult] = await Promise.allSettled([
    getCurrentFrontPage(locale),
    fetchSeoIndexServer(),
  ]);
  const initialData = frontPageResult.status === "fulfilled" ? frontPageResult.value : null;
  const initialTopics = indexResult.status === "fulfilled" ? indexResult.value.topics : [];
  const signals = new Map<string, string>();
  for (const slot of initialData?.slots ?? []) {
    for (const item of slot.items) {
      const claimId = item.trust.claim_id;
      if (claimId && !signals.has(claimId)) signals.set(claimId, item.headline);
    }
  }
  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "WebSite",
          name: "Open Signal",
          inLanguage: locale,
          url: absoluteUrl(localePath("/", locale)),
          description:
            locale === "zh-Hant"
              ? "呈現公共預期、規則與研究中經驗證變化的即時版面。"
              : "A live front page of verified changes in public expectations, rules, and research.",
        }}
      />
      {initialData ? (
        <JsonLd
          value={{
            "@context": "https://schema.org",
            "@type": "ItemList",
            name: `Current Open Signal edition · ${initialData.snapshot.edition_date}`,
            numberOfItems: signals.size,
            itemListElement: [...signals.entries()].map(([claimId, headline], index) => ({
              "@type": "ListItem",
              position: index + 1,
              name: headline,
              url: absoluteUrl(signalPath(headline, claimId, locale)),
            })),
          }}
        />
      ) : null}
      <FrontPage initialData={initialData} initialTopics={initialTopics} />
    </>
  );
}
