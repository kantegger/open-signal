import "server-only";

import { headers } from "next/headers";
import { normalizeLocale, type SupportedLocale } from "./i18n";

export const LOCALE_REQUEST_HEADER = "x-open-signal-locale";

export async function getRequestLocale(): Promise<SupportedLocale> {
  const requestHeaders = await headers();
  return normalizeLocale(requestHeaders.get(LOCALE_REQUEST_HEADER));
}
