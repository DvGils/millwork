// The row of a combobox that takes what was typed as the value.

export interface Choice {
  value: string;
  label?: string | null;
  typed?: boolean;
}

// The row for `text`, or null when there is nothing to offer: no text, or
// text that names an option by its value or label. What is chosen is an
// option too when it goes by another name than its value, though it may not
// be among those listed. Text that was typed and chosen keeps its row, so the
// list is not empty when the text is brought back to it.
export function typedOption<T extends Choice>(options: readonly T[], text: string, chosen: Choice | null): Choice | null {
  const typed = text.trim();
  if (!typed) return null;
  const named = chosen && chosen.label != null && chosen.label !== chosen.value;
  if (chosen && named && (typed === chosen.label || typed === chosen.value)) return null;
  if (options.some((o) => o.value === typed || o.label === typed)) return null;
  return { value: typed, label: typed, typed: true };
}
