/**
 * Markdown parsing for agent replies: text in, blocks out.
 *
 * Covers the narrow subset an LLM reaches for in prose — headings, bullet and
 * numbered lists (nesting included), bold, italic, inline code, links — and
 * leaves anything else as plain text, which is what the reader saw before this
 * existed. Hand-written rather than a markdown library, because the app has no
 * runtime dependencies beyond Next and React.
 *
 * Kept apart from the rendering in `components/Markdown.tsx` so it stays pure
 * and directly testable.
 */

export type MarkdownBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: MarkdownListItem[] };

export type MarkdownListItem = { text: string; children: MarkdownBlock[] };

const HEADING_PATTERN = /^\s{0,3}(#{1,6})\s+(.*)$/;
const UNORDERED_ITEM_PATTERN = /^(\s*)[-*+]\s+(.*)$/;
const ORDERED_ITEM_PATTERN = /^(\s*)(\d+)[.)]\s+(.*)$/;

type ItemMatch = { indent: number; ordered: boolean; number: number; text: string };

function matchItem(line: string): ItemMatch | null {
  const ordered = ORDERED_ITEM_PATTERN.exec(line);
  if (ordered) {
    return {
      indent: ordered[1].length,
      ordered: true,
      number: Number(ordered[2]),
      text: ordered[3],
    };
  }

  const unordered = UNORDERED_ITEM_PATTERN.exec(line);
  if (unordered) {
    return { indent: unordered[1].length, ordered: false, number: 1, text: unordered[2] };
  }

  return null;
}

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

/**
 * Splits lines into blocks. Nested lists recurse: an item's child lines keep
 * their original indentation, and the recursive call compares indents only
 * within the set of lines it was handed.
 */
export function parseMarkdown(text: string): MarkdownBlock[] {
  return parseLines(text.split("\n"));
}

function parseLines(lines: string[]): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const heading = HEADING_PATTERN.exec(line);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
      index += 1;
      continue;
    }

    const first = matchItem(line);
    if (first) {
      const items: { text: string; childLines: string[] }[] = [];

      while (index < lines.length) {
        const current = lines[index];

        if (!current.trim()) {
          index += 1;
          continue;
        }

        const item = matchItem(current);
        if (item && item.indent === first.indent && item.ordered === first.ordered) {
          items.push({ text: item.text, childLines: [] });
          index += 1;
          continue;
        }

        // Anything indented deeper than the marker belongs to the open item —
        // a nested list, or a continuation line of its text.
        if (items.length > 0 && indentOf(current) > first.indent) {
          items[items.length - 1].childLines.push(current);
          index += 1;
          continue;
        }

        break;
      }

      blocks.push({
        kind: "list",
        ordered: first.ordered,
        start: first.number,
        items: items.map((item) => ({
          text: item.text,
          children: parseLines(item.childLines),
        })),
      });
      continue;
    }

    // Paragraph: consecutive plain lines, kept as separate lines so a reply the
    // agent hard-wrapped is not reflowed into one run.
    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !matchItem(lines[index]) &&
      !HEADING_PATTERN.test(lines[index])
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraph.join("\n") });
  }

  return blocks;
}

/** One run of inline text: either plain, or wrapped in a single marker. */
export type InlineToken =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "em"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

/**
 * Bold before italic, so `**x**` is not read as an empty italic pair, and links
 * first because their label may itself contain emphasis markers. Italic content
 * may not begin or end with a space, which keeps a lone `*` in prose from
 * pairing with the next one several words later.
 *
 * Underscore emphasis (`_x_`, `__x__`) is deliberately unsupported: replies
 * quote product IDs and field names, and `snake_case_name` would otherwise come
 * out half italic. Models reach for the asterisk forms anyway.
 */
const INLINE_PATTERN =
  /(\[[^\]\n]+\]\([^)\s]+\)|\*\*[^*\n]+\*\*|\*[^\s*](?:[^*\n]*[^\s*])?\*|`[^`\n]+`)/g;
const LINK_PATTERN = /^\[([^\]\n]+)\]\(([^)\s]+)\)$/;

/** Only web and same-origin targets are linked; anything else stays as text. */
function isSafeHref(href: string): boolean {
  return /^https?:\/\//i.test(href) || href.startsWith("/") || href.startsWith("#");
}

export function parseInline(text: string): InlineToken[] {
  return text
    .split(INLINE_PATTERN)
    .filter((token) => token !== "")
    .map((token): InlineToken => {
      const link = LINK_PATTERN.exec(token);
      if (link && isSafeHref(link[2])) {
        return { kind: "link", text: link[1], href: link[2] };
      }

      if (token.startsWith("**") && token.endsWith("**")) {
        return { kind: "strong", text: token.slice(2, -2) };
      }

      if (token.startsWith("*") && token.endsWith("*")) {
        return { kind: "em", text: token.slice(1, -1) };
      }

      if (token.startsWith("`") && token.endsWith("`")) {
        return { kind: "code", text: token.slice(1, -1) };
      }

      return { kind: "text", text: token };
    });
}
