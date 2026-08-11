import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "../../components/json-ld";
import { SiteShell } from "../../components/site-shell";
import { collectionDensity } from "../../lib/collection-density";
import { languageAlternates, localePath } from "../../lib/i18n";
import { getRequestLocale } from "../../lib/request-locale";
import { absoluteUrl } from "../../lib/site";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const canonical = localePath("/method", locale);
  const description = traditional
    ? "Open Signal 如何區分觀測、分析與判斷，驗證證據，編製不可變期次，並淘汰過時內容。"
    : "How Open Signal separates observation, analysis, and assessment; verifies evidence; compiles Editions; and retires stale material.";
  return {
    title: traditional ? "方法" : "Method",
    description,
    alternates: { canonical, languages: languageAlternates("/method") },
    openGraph: {
      title: traditional ? "方法 · Open Signal" : "Method · Open Signal",
      description: traditional
        ? "證據如何成為公開訊號、主題與不可變期次。"
        : "How evidence becomes a public Signal, Topic, and immutable Edition.",
      url: canonical,
    },
  };
}

const englishLayers = [
  {
    number: "01",
    title: "Observation",
    copy: "What the source directly records: a probability move, a rule-state change, a publication, a trial update, or another time-stamped event.",
  },
  {
    number: "02",
    title: "Analysis",
    copy: "What can be derived from those records: comparisons, persistence, relationships, calculations, and the limits of the available window.",
  },
  {
    number: "03",
    title: "Assessment",
    copy: "What Open Signal concludes, at what confidence, under which Charter and model version, with uncertainty and counterevidence left visible.",
  },
];

const traditionalLayers = [
  {
    number: "01",
    title: "觀測",
    copy: "來源直接記錄的事實：機率移動、規則狀態變更、論文發表、試驗更新，或其他帶時間戳的事件。",
  },
  {
    number: "02",
    title: "分析",
    copy: "可由紀錄推導的內容：比較、持續性、關係、計算，以及現有觀測視窗的限制。",
  },
  {
    number: "03",
    title: "判斷",
    copy: "Open Signal 在哪個信心程度、Charter 與模型版本下得出什麼結論；不確定性與反證必須保持可見。",
  },
];

export default async function MethodPage() {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const layers = traditional ? traditionalLayers : englishLayers;
  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "WebPage",
          name: traditional ? "Open Signal 方法" : "Open Signal Method",
          inLanguage: locale,
          url: absoluteUrl(localePath("/method", locale)),
          description: traditional
            ? "Open Signal 如何把公共來源紀錄轉化為經驗證、可追溯且具版本的訊號。"
            : "How Open Signal turns public source records into verified, versioned Signals.",
        }}
      />
      <SiteShell active="method">
        <article className="method-page">
          <header className="method-hero">
            <div>
              <p className="eyebrow">{traditional ? "證據先於呈現" : "Evidence before presentation"}</p>
              <h1>{traditional ? "Open Signal 如何形成公開主張" : "How Open Signal makes a public claim"}</h1>
            </div>
            <p>
              {traditional
                ? "介面不是權威。每個可見結論都指向具版本的 Claim、證據包、Agent 譜系，以及它首次出現的不可變快照。"
                : "The interface is not the authority. Every visible conclusion points back to a versioned Claim, its evidence bundle, its lineage, and the snapshot in which it appeared."}
            </p>
          </header>

          <section className="method-layers" aria-labelledby="epistemic-layers-title">
            <header>
              <p className="eyebrow">{traditional ? "認識論層級" : "The epistemic stack"}</p>
              <h2 id="epistemic-layers-title">
                {traditional ? "三個不可互相混同的層級" : "Three layers that must not collapse into one another"}
              </h2>
            </header>
            <div data-count={layers.length} data-density={collectionDensity(layers.length, "grid")}>
              {layers.map((layer) => (
                <article key={layer.number}>
                  <span>{layer.number}</span><h3>{layer.title}</h3><p>{layer.copy}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="method-flow" aria-labelledby="publication-flow-title">
            <header>
              <p className="eyebrow">{traditional ? "出版生命週期" : "Publication lifecycle"}</p>
              <h2 id="publication-flow-title">{traditional ? "從來源紀錄到公開介面" : "From source record to public surface"}</h2>
            </header>
            <ol data-count={5} data-density={collectionDensity(5, "grid")}>
              <li><span>{traditional ? "來源" : "Source"}</span><p>{traditional ? "適配器保留原始公共紀錄與來源時間戳。" : "Adapters preserve raw public records and source timestamps."}</p></li>
              <li><span>{traditional ? "候選" : "Candidate"}</span><p>{traditional ? "偵測器辨識重大變化，但不先替變化賦予意義。" : "Detectors identify material changes without deciding what they mean."}</p></li>
              <li><span>Claim</span><p>{traditional ? "Charter Agent 或確定性建構器產生有邊界的命題與證據包。" : "A Charter Agent or deterministic builder produces a bounded proposition and evidence bundle."}</p></li>
              <li><span>{traditional ? "驗證" : "Verification"}</span><p>{traditional ? "驗證門檢查來源、新鮮度、矛盾、重複、譜系與安全呈現。" : "Gates check provenance, freshness, contradiction, duplication, lineage, and display safety."}</p></li>
              <li><span>{traditional ? "期次" : "Edition"}</span><p>{traditional ? "編譯器選取已驗證的 Render Plan，發布完整且不可變的快照。" : "The compiler selects verified Render Plans and publishes a complete immutable snapshot."}</p></li>
            </ol>
          </section>

          <section className="method-principles" aria-labelledby="interface-contract-title">
            <header>
              <p className="eyebrow">{traditional ? "介面契約" : "Interface contract"}</p>
              <h2 id="interface-contract-title">{traditional ? "不同動作有不同目的地" : "Different actions have different destinations"}</h2>
            </header>
            <dl data-count={4} data-density={collectionDensity(4, "grid")}>
              <div><dt>{traditional ? "訊號標題" : "Signal title"}</dt><dd>{traditional ? "離開快照，前往永久且可被搜尋引擎索引的訊號紀錄。" : "Leaves the snapshot for the permanent, crawlable Signal record."}</dd></div>
              <div><dt>{traditional ? "證據" : "Evidence"}</dt><dd>{traditional ? "開啟暫時的浮層，讓讀者不離開當前脈絡即可快速驗證。" : "Opens a temporary Overlay for quick verification without losing reading context."}</dd></div>
              <div><dt>{traditional ? "主題" : "Topic"}</dt><dd>{traditional ? "開啟長期存在的標準問題、來源市場、規則與相關訊號。" : "Opens the long-lived canonical question, its source markets, rules, and related Signals."}</dd></div>
              <div><dt>{traditional ? "期次" : "Edition"}</dt><dd>{traditional ? "重建完整歷史出版狀態；它不是藏在首頁裡的區段。" : "Reconstructs a complete historical publication state; it is never a hidden homepage section."}</dd></div>
            </dl>
          </section>

          <section className="method-freshness" aria-labelledby="freshness-title">
            <div><p className="eyebrow">{traditional ? "新鮮度與淘汰" : "Freshness and retirement"}</p><h2 id="freshness-title">{traditional ? "不設人為的「今天」邊界" : "No artificial “today” boundary"}</h2></div>
            <p>
              {traditional
                ? "各 Section 在自己的管線產生已驗證材料時更新。仍然有效的 Section 可保留原始時間戳繼續顯示；到達政策定義的有效期或硬性淘汰界線後，編譯器會移除它並重新發布完整頁面，而不是捏造替代內容填補空位。"
                : "Sections refresh when their own pipelines produce verified material. A still-valid Section can remain visible with its original timestamp; once its policy-defined validity or hard retirement boundary is reached, the compiler removes it and republishes a complete page. It does not invent a replacement to fill an empty slot."}
            </p>
          </section>

          <footer className="method-footer">
            <p>{traditional ? "準備好檢視公開紀錄了嗎？" : "Ready to inspect the public record?"}</p>
            <div>
              <Link href={localePath("/explore", locale)}>{traditional ? "探索訊號與主題" : "Explore Signals and Topics"} →</Link>
              <Link href={localePath("/editions", locale)}>{traditional ? "瀏覽典藏期次" : "Browse Editions"} →</Link>
            </div>
          </footer>
        </article>
      </SiteShell>
    </>
  );
}
