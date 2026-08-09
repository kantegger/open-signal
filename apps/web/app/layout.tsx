import type { Metadata, Viewport } from "next";
import { JsonLd } from "../components/json-ld";
import { absoluteUrl, siteUrl } from "../lib/site";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: {
    default: "Open Signal — Live, Evidence-First Global Signals",
    template: "%s · Open Signal",
  },
  description:
    "A continuously updated, evidence-first dashboard of changing rules, expectations, and research signals.",
  applicationName: "Open Signal",
  authors: [{ name: "Open Signal", url: "/" }],
  creator: "Open Signal",
  publisher: "Open Signal",
  keywords: [
    "prediction markets",
    "policy changes",
    "research signals",
    "public evidence",
    "global dashboard",
  ],
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "Open Signal",
    title: "Open Signal — Live Global Signals",
    description:
      "Verified changes in public rules, expectations, and research — connected to evidence and preserved over time.",
    url: "/",
  },
  twitter: {
    card: "summary_large_image",
    title: "Open Signal — Live Global Signals",
    description: "An evidence-first front page of consequential public change.",
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

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0a1116",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" dir="ltr" data-scroll-behavior="smooth">
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
        {children}
      </body>
    </html>
  );
}
