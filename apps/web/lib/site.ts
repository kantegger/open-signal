import "server-only";

export function siteUrl(): string {
  const configured =
    process.env.OPEN_SIGNAL_SITE_URL ??
    process.env.NEXT_PUBLIC_SITE_URL ??
    process.env.VERCEL_PROJECT_PRODUCTION_URL;
  if (!configured) return "http://localhost:3000";
  const value = configured.startsWith("http") ? configured : `https://${configured}`;
  return value.replace(/\/$/, "");
}

export function absoluteUrl(path: string): string {
  return `${siteUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}
