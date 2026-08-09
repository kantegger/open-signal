import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Open Signal",
    template: "%s · Open Signal",
  },
  description: "A living, evidence-first front page of consequential public signals.",
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
      <body>{children}</body>
    </html>
  );
}
