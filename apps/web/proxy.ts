import { NextRequest, NextResponse } from "next/server";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  TRADITIONAL_CHINESE_LOCALE,
  type SupportedLocale,
} from "./lib/i18n";

const LOCALE_HEADER = "x-open-signal-locale";
const ZH_ALIASES = ["/zh-TW", "/zh-HK"] as const;

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const inheritedLocale = request.headers.get(LOCALE_HEADER);
  // In development, Next may run Proxy again for the internal rewrite. Keep
  // the locale selected from the public URL instead of replacing it with en.
  if (isSupportedLocale(inheritedLocale)) {
    return nextWithLocale(request, inheritedLocale);
  }
  const alias = ZH_ALIASES.find(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (alias) {
    const target = request.nextUrl.clone();
    target.pathname = `/${TRADITIONAL_CHINESE_LOCALE}${pathname.slice(alias.length)}`;
    return NextResponse.redirect(target, 308);
  }

  if (
    pathname === `/${TRADITIONAL_CHINESE_LOCALE}` ||
    pathname.startsWith(`/${TRADITIONAL_CHINESE_LOCALE}/`)
  ) {
    const target = request.nextUrl.clone();
    target.pathname = pathname.slice(TRADITIONAL_CHINESE_LOCALE.length + 1) || "/";
    return rewriteWithLocale(request, target, TRADITIONAL_CHINESE_LOCALE);
  }

  return nextWithLocale(request, DEFAULT_LOCALE);
}

function requestHeaders(request: NextRequest, locale: SupportedLocale): Headers {
  const headers = new Headers(request.headers);
  headers.set(LOCALE_HEADER, locale);
  return headers;
}

function rewriteWithLocale(
  request: NextRequest,
  target: URL,
  locale: SupportedLocale,
) {
  return NextResponse.rewrite(target, {
    request: { headers: requestHeaders(request, locale) },
  });
}

function nextWithLocale(request: NextRequest, locale: SupportedLocale) {
  return NextResponse.next({
    request: { headers: requestHeaders(request, locale) },
  });
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|icon.svg|robots.txt|sitemap.xml).*)",
  ],
};
