import type { Metadata } from "next";
import { cache } from "react";
import { FrontPage } from "../components/front-page";
import { JsonLd } from "../components/json-ld";
import { fetchCurrentFrontPageServer, fetchSeoIndexServer } from "../lib/server-api";
import { absoluteUrl } from "../lib/site";
import { excerpt, signalPath } from "../lib/urls";

export const revalidate = 3_600;

const getCurrentFrontPage = cache(fetchCurrentFrontPageServer);

export async function generateMetadata(): Promise<Metadata> {
  try {
    const page = await getCurrentFrontPage();
    const lead = page.slots.find((slot) => slot.type === "lead")?.items[0];
    const description = lead
      ? excerpt(`${lead.headline} Open Signal tracks verified changes in expectations, rules, and research.`)
      : "Verified changes in public expectations, rules, and research — with evidence, timestamps, and permanent records.";
    return {
      title: "Live global signals · Open Signal",
      description,
      alternates: { canonical: "/" },
      openGraph: { title: "Open Signal · Live global signals", description, url: "/" },
      twitter: { card: "summary_large_image", title: "Open Signal · Live global signals", description },
    };
  } catch {
    return {};
  }
}

export default async function HomePage() {
  const [frontPageResult, indexResult] = await Promise.allSettled([
    getCurrentFrontPage(),
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
          url: absoluteUrl("/"),
          description: "A live front page of verified changes in public expectations, rules, and research.",
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
              url: absoluteUrl(signalPath(headline, claimId)),
            })),
          }}
        />
      ) : null}
      <FrontPage initialData={initialData} initialTopics={initialTopics} />
    </>
  );
}
