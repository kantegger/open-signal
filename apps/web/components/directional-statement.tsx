const directionPattern = /\b(increased|rose|gained|moved up|decreased|fell|lost|moved down|became(?:\s+\d+(?:\.\d+)?\s+(?:percentage\s+)?points?)?\s+(?:more|less)\s+likely)\b/i;
const contextPattern = /\s+(over|during|since|within|across)\b/i;

const upwardWords = new Set([
  "increased",
  "rose",
  "gained",
  "moved up",
  "became more likely",
]);

export function DirectionalStatement({ text }: { text: string }) {
  const direction = directionPattern.exec(text);
  if (!direction) {
    return (
      <span className="directional-statement">
        <span className="statement-subject">{text}</span>
      </span>
    );
  }

  const directionStart = direction.index;
  const directionEnd = directionStart + direction[0].length;
  const remainder = text.slice(directionEnd);
  const context = contextPattern.exec(remainder);
  const movementEnd = context?.index ?? remainder.length;
  const directionWord = direction[0].toLowerCase();
  const directionClass = upwardWords.has(directionWord) || directionWord.endsWith("more likely")
    ? "trend-up"
    : "trend-down";

  return (
    <span className="directional-statement">
      <span className="statement-subject">{text.slice(0, directionStart)}</span>
      <em className={`statement-movement ${directionClass}`}>
        {text.slice(directionStart, directionEnd + movementEnd)}
      </em>
      {context ? <span className="statement-context">{remainder.slice(movementEnd)}</span> : null}
    </span>
  );
}
