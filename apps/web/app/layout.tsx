import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Open Signal",
  description: "A live front page of public signals.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
