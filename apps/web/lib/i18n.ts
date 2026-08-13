export const SUPPORTED_LOCALES = ["en", "zh-Hant"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = "en";
export const TRADITIONAL_CHINESE_LOCALE: SupportedLocale = "zh-Hant";

export interface UiCopy {
  brand: string;
  beta: string;
  current: string;
  explore: string;
  expectations: string;
  rules: string;
  research: string;
  method: string;
  archive: string;
  systemStatus: string;
  operational: string;
  unavailable: string;
  checking: string;
  composed: string;
  lastVerified: string;
  viewEvidence: string;
  liveFeed: string;
  recentFirst: string;
  secondarySignals: string;
  significantChanges: string;
  retry: string;
  skipToPublication: string;
  primaryNavigation: string;
  mobileNavigation: string;
  openNavigation: string;
  closeNavigation: string;
  homeLabel: string;
  language: string;
  english: string;
  traditionalChinese: string;
  originalEnglishNotice: string;
  notRecorded: string;
  timeNotRecorded: string;
  source: string;
  confidence: string;
  evidence: string;
  verified: string;
  status: string;
  updated: string;
  open: string;
  page: string;
  of: string;
  sections: string;
  claims: string;
  signal: string;
  topic: string;
  edition: string;
}

export const copy: Record<SupportedLocale, UiCopy> = {
  en: {
    brand: "Open Signal",
    beta: "Public Beta",
    current: "Current",
    explore: "Explore",
    expectations: "Expectations",
    rules: "Rules",
    research: "Research",
    method: "Method",
    archive: "Archive",
    systemStatus: "System status",
    operational: "operational",
    unavailable: "unavailable",
    checking: "checking",
    composed: "Composed",
    lastVerified: "Last verified update",
    viewEvidence: "View full evidence",
    liveFeed: "Live signal feed",
    recentFirst: "Most recent first",
    secondarySignals: "Secondary signals",
    significantChanges: "Significant changes",
    retry: "Retry",
    skipToPublication: "Skip to publication",
    primaryNavigation: "Primary navigation",
    mobileNavigation: "Mobile navigation",
    openNavigation: "Open navigation",
    closeNavigation: "Close navigation",
    homeLabel: "Open Signal home",
    language: "Language",
    english: "English",
    traditionalChinese: "繁體中文",
    originalEnglishNotice:
      "A verified Traditional Chinese presentation is not available for this record yet. The original English wording is preserved below.",
    notRecorded: "Not recorded",
    timeNotRecorded: "time not recorded",
    source: "Source",
    confidence: "Confidence",
    evidence: "Evidence",
    verified: "Verified",
    status: "Status",
    updated: "Updated",
    open: "Open",
    page: "Page",
    of: "of",
    sections: "Sections",
    claims: "Claims",
    signal: "Signal",
    topic: "Topic",
    edition: "Edition",
  },
  "zh-Hant": {
    brand: "Open Signal",
    beta: "公開測試版",
    current: "即時版面",
    explore: "探索",
    expectations: "預期變化",
    rules: "規則變化",
    research: "研究動向",
    method: "方法",
    archive: "典藏",
    systemStatus: "系統狀態",
    operational: "運作正常",
    unavailable: "暫時無法使用",
    checking: "檢查中",
    composed: "編製時間",
    lastVerified: "最近驗證更新",
    viewEvidence: "查看完整證據",
    liveFeed: "即時訊號",
    recentFirst: "最新在前",
    secondarySignals: "次要訊號",
    significantChanges: "重大變化",
    retry: "重試",
    skipToPublication: "跳至出版內容",
    primaryNavigation: "主要導覽",
    mobileNavigation: "行動版導覽",
    openNavigation: "開啟導覽",
    closeNavigation: "關閉導覽",
    homeLabel: "Open Signal 首頁",
    language: "語言",
    english: "English",
    traditionalChinese: "繁體中文",
    originalEnglishNotice:
      "此筆紀錄尚未有通過驗證的繁體中文呈現；以下保留不可變的英文原文，數字、日期與狀態均未改寫。",
    notRecorded: "尚未記錄",
    timeNotRecorded: "時間尚未記錄",
    source: "來源",
    confidence: "信心程度",
    evidence: "證據",
    verified: "已驗證",
    status: "狀態",
    updated: "更新",
    open: "仍有效",
    page: "第",
    of: "頁，共",
    sections: "區段",
    claims: "主張",
    signal: "訊號",
    topic: "主題",
    edition: "期次",
  },
};

export function isSupportedLocale(value: unknown): value is SupportedLocale {
  return typeof value === "string" && SUPPORTED_LOCALES.includes(value as SupportedLocale);
}

export function normalizeLocale(value: unknown): SupportedLocale {
  return isSupportedLocale(value) ? value : DEFAULT_LOCALE;
}

export function localePath(path: string, locale: SupportedLocale): string {
  const suffixIndex = path.search(/[?#]/u);
  const pathname = suffixIndex === -1 ? path : path.slice(0, suffixIndex);
  const suffix = suffixIndex === -1 ? "" : path.slice(suffixIndex);
  const normalizedPathname = stripLocalePrefix(pathname || "/");
  if (locale === DEFAULT_LOCALE) return `${normalizedPathname}${suffix}`;
  const localized = normalizedPathname === "/" ? `/${locale}` : `/${locale}${normalizedPathname}`;
  return `${localized}${suffix}`;
}

export function stripLocalePrefix(pathname: string): string {
  for (const locale of SUPPORTED_LOCALES) {
    if (locale === DEFAULT_LOCALE) continue;
    if (pathname === `/${locale}`) return "/";
    if (pathname.startsWith(`/${locale}/`)) return pathname.slice(locale.length + 1);
  }
  return pathname.startsWith("/") ? pathname : `/${pathname}`;
}

export function languageAlternates(path: string): Record<SupportedLocale, string> {
  return {
    en: localePath(path, "en"),
    "zh-Hant": localePath(path, "zh-Hant"),
  };
}

export function formatDateTime(
  iso: string | null | undefined,
  locale: string = DEFAULT_LOCALE,
): string {
  if (!iso) return copy[normalizeLocale(locale)].notRecorded;
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(value);
}

export function formatShortTime(
  iso: string | null | undefined,
  locale: string = DEFAULT_LOCALE,
): string {
  if (!iso) return "—";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(value);
}

export function formatRelativeTime(
  iso: string | null | undefined,
  locale: string = DEFAULT_LOCALE,
): string {
  if (!iso) return copy[normalizeLocale(locale)].timeNotRecorded;
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return iso;
  const seconds = Math.round((time - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const absolute = Math.abs(seconds);
  if (absolute < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return formatter.format(hours, "hour");
  const days = Math.round(hours / 24);
  if (Math.abs(days) < 60) return formatter.format(days, "day");
  const months = Math.round(days / 30);
  return formatter.format(months, "month");
}

const traditionalTerms: Record<string, string> = {
  "24h": "24小時",
  "30d": "30天",
  "7d": "7天",
  active: "有效",
  active_event: "活躍事件",
  aging: "較舊但仍有效",
  authoritative_primary: "權威一手來源",
  business: "商業",
  correction: "修正",
  create: "建立",
  credible_challenger: "可信挑戰者",
  crypto: "加密資產",
  current: "目前",
  derived: "衍生",
  derived_observation: "衍生觀測",
  detected: "已偵測",
  down: "下降",
  economy: "經濟",
  event_representative: "事件代表",
  expectations_moved: "預期變化",
  final: "已定案",
  freshness_reconcile: "新鮮度重整",
  generated: "已產生",
  geopolitics: "地緣政治",
  hard_expiry: "強制到期",
  health: "健康",
  high: "高",
  initial: "首次發布",
  institution_entry: "機構動態",
  investigated: "已調查",
  largest_material_move: "最大實質變動",
  latest_for_subject: "主題最新紀錄",
  leader: "領先項",
  low: "低",
  main_election: "主要選舉",
  manual: "人工觸發",
  material: "實質",
  material_repricing: "實質重新定價",
  medium: "中",
  middle_east: "中東",
  near_resolution: "接近結算",
  next_24_hours: "未來24小時",
  next_24h: "未來24小時",
  neutral: "中性",
  not_published: "未發布",
  observed_move: "已觀測變動",
  oil: "石油",
  operational: "運作正常",
  operational_ttl: "營運保留期",
  politics: "政治",
  previous: "先前",
  public_permanent: "永久公開紀錄",
  published: "已發布",
  recorded: "已記錄",
  research_frontier: "研究動向",
  rollback: "回復",
  rule: "規則",
  rules_moved: "規則變化",
  scheduled: "排程",
  science: "科學",
  section_refresh: "區段更新",
  shadow_investigation: "影子調查",
  source_fact: "來源事實",
  sports: "體育",
  stage_transition: "試驗階段",
  substantive: "實質變更",
  technology: "科技",
  up: "上升",
  update: "更新",
  verified: "已驗證",
  verified_signal: "已驗證訊號",
};

export function humanize(
  value: string | null | undefined,
  locale: SupportedLocale = DEFAULT_LOCALE,
): string {
  if (!value) return locale === "zh-Hant" ? "未記錄" : "Not recorded";
  const normalized = value.toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
  if (locale === "zh-Hant" && traditionalTerms[normalized]) {
    return traditionalTerms[normalized];
  }
  return value.replaceAll("_", " ").replaceAll("-", " ");
}
