"use client";

import { createContext, useContext } from "react";
import {
  copy,
  DEFAULT_LOCALE,
  type SupportedLocale,
  type UiCopy,
} from "../lib/i18n";

interface LocaleContextValue {
  locale: SupportedLocale;
  text: UiCopy;
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: DEFAULT_LOCALE,
  text: copy[DEFAULT_LOCALE],
});

export function LocaleProvider({
  children,
  locale,
}: {
  children: React.ReactNode;
  locale: SupportedLocale;
}) {
  return (
    <LocaleContext.Provider value={{ locale, text: copy[locale] }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}
