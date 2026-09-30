import Link from "next/link";
import { Fragment, type ReactNode } from "react";

import { parseInline, parseMarkdown, type MarkdownBlock } from "@/lib/markdown";

/**
 * Renders the markdown an agent reply comes back in. Parsing lives in
 * `lib/markdown.ts`; this file is only the mapping from blocks to elements,
 * styled for a chat bubble.
 */

const LINK_CLASSNAME =
  "font-medium text-violet-700 underline underline-offset-2 hover:text-violet-900";

function renderInline(text: string): ReactNode[] {
  return parseInline(text).map((token, index) => {
    const key = `${index}-${token.text}`;

    switch (token.kind) {
      case "link":
        // In-app targets — the product pages the assistant links to — go through
        // next/link. A plain <a> would reload the document, and AppShell holds
        // the sign-in and this panel's open state in React state only, so the
        // shopper would land on the product logged out with the chat closed.
        return token.href.startsWith("/") ? (
          <Link key={key} href={token.href} className={LINK_CLASSNAME}>
            {token.text}
          </Link>
        ) : (
          <a key={key} href={token.href} className={LINK_CLASSNAME}>
            {token.text}
          </a>
        );
      case "strong":
        return <strong key={key}>{token.text}</strong>;
      case "em":
        return <em key={key}>{token.text}</em>;
      case "code":
        return (
          <code key={key} className="rounded bg-black/5 px-1 py-0.5 font-mono text-[0.9em]">
            {token.text}
          </code>
        );
      default:
        return <Fragment key={key}>{token.text}</Fragment>;
    }
  });
}

function renderBlocks(blocks: MarkdownBlock[]): ReactNode {
  return blocks.map((block, blockIndex) => {
    const key = blockIndex;

    if (block.kind === "heading") {
      // A heading inside a chat bubble is only a slight step up from body text;
      // the h3..h6 level is kept for semantics, not for size.
      const Tag = `h${Math.min(block.level + 2, 6)}` as "h3" | "h4" | "h5" | "h6";
      return (
        <Tag key={key} className="font-semibold">
          {renderInline(block.text)}
        </Tag>
      );
    }

    if (block.kind === "paragraph") {
      return (
        <p key={key} className="whitespace-pre-wrap">
          {renderInline(block.text)}
        </p>
      );
    }

    const ListTag = block.ordered ? "ol" : "ul";
    return (
      <ListTag
        key={key}
        start={block.ordered && block.start !== 1 ? block.start : undefined}
        className={`ml-5 list-outside space-y-1 ${block.ordered ? "list-decimal" : "list-disc"}`}
      >
        {block.items.map((item, itemIndex) => (
          <li key={itemIndex} className="space-y-1">
            <span className="whitespace-pre-wrap">{renderInline(item.text)}</span>
            {item.children.length > 0 ? renderBlocks(item.children) : null}
          </li>
        ))}
      </ListTag>
    );
  });
}

export default function Markdown({ content }: { content: string }) {
  return <div className="space-y-2">{renderBlocks(parseMarkdown(content))}</div>;
}
