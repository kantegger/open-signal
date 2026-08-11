import type { Metadata, Viewport } from "next";
import { JsonLd } from "../components/json-ld";
import { LocaleProvider } from "../components/locale-provider";
import { languageAlternates, localePath } from "../lib/i18n";
import { getRequestLocale } from "../lib/request-locale";
import { absoluteUrl, siteUrl } from "../lib/site";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const description = traditional
    ? "持續更新、以證據為先的全球公共訊號：追蹤規則、預期與研究的重大變化。"
    : "A continuously updated, evidence-first dashboard of changing rules, expectations, and research signals.";
  const socialDescription = traditional
    ? "經驗證的公共規則、預期與研究變化，連結原始證據並永久保存。"
    : "Verified changes in public rules, expectations, and research — connected to evidence and preserved over time.";
  const canonical = localePath("/", locale);
  return {
    metadataBase: new URL(siteUrl()),
    title: {
      default: traditional
        ? "Open Signal — 即時、證據優先的全球訊號"
        : "Open Signal — Live, Evidence-First Global Signals",
      template: "%s · Open Signal",
    },
    description,
    applicationName: "Open Signal",
    authors: [{ name: "Open Signal", url: canonical }],
    creator: "Open Signal",
    publisher: "Open Signal",
    keywords: traditional
      ? ["預測市場", "政策變化", "研究訊號", "公共證據", "全球訊號"]
      : [
          "prediction markets",
          "policy changes",
          "research signals",
          "public evidence",
          "global dashboard",
        ],
    alternates: { canonical, languages: languageAlternates("/") },
    openGraph: {
      type: "website",
      siteName: "Open Signal",
      title: traditional ? "Open Signal — 即時全球訊號" : "Open Signal — Live Global Signals",
      description: socialDescription,
      url: canonical,
      locale: traditional ? "zh_TW" : "en_US",
      alternateLocale: traditional ? ["en_US"] : ["zh_TW"],
    },
    twitter: {
      card: "summary_large_image",
      title: traditional ? "Open Signal — 即時全球訊號" : "Open Signal — Live Global Signals",
      description: traditional
        ? "以證據為先，呈現具影響力公共變化的即時版面。"
        : "An evidence-first front page of consequential public change.",
    },
    robots: {
      index: true,
      follow: true,
      googleBot: {
        index: true,
        follow: true,
        "max-image-preview": "large",
        "max-snippet": -1,
        "max-video-preview": -1,
      },
    },
  };
}

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0a1116",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getRequestLocale();
  return (
    <html lang={locale} dir="ltr" data-scroll-behavior="smooth">
      <body>
        <JsonLd
          value={{
            "@context": "https://schema.org",
            "@type": "Organization",
            name: "Open Signal",
            url: siteUrl(),
            logo: absoluteUrl("/icon.svg"),
          }}
        />
        <LocaleProvider locale={locale}>{children}</LocaleProvider>
      </body>
    </html>
  );
}
