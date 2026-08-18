/**
 * A markdown renderer small enough to read in one sitting.
 *
 * ── The decision ─────────────────────────────────────────────────────────────
 * The training log is 160 hand-written markdown files and `/api/v1/training/log`
 * serves them **raw**. Two options: a styled `<pre>`, or a mini renderer. A
 * `<pre>` was rejected on the data rather than on taste — a census of the whole
 * corpus (`omega/nodes/victoria/training_log/*.md`) counts **3,231 table lines**,
 * second only to prose, plus 2,054 list items, 1,755 headings and 206 code
 * fences. A pre block turns every one of those tables into ASCII pipe soup, and
 * the tables are where the numbers are. So: a renderer, covering exactly the
 * constructs the corpus uses, and nothing else.
 *
 * A markdown *dependency* was never on the table — `imports.test.ts` allows a
 * shell to name React and the kit and nothing more, and vendoring marked or
 * remark into the harness's bundle to render an internal changelog is not a
 * trade worth making.
 *
 * ── What it does NOT do ──────────────────────────────────────────────────────
 * No nested lists (flattened to their text), no reference links, no images, no
 * HTML passthrough (which is also the safety property: nothing here ever
 * produces raw HTML, so a markdown file cannot inject markup), no inline
 * emphasis beyond bold and code, and no link navigation — a link's text is
 * rendered with its target in the title attribute, because every link in the
 * corpus points at a sibling markdown file that this app has no route for.
 * Anything unrecognised falls through to a paragraph, so nothing is ever
 * silently dropped.
 */
import type { ReactNode } from 'react';

// ── Blocks ───────────────────────────────────────────────────────────────────

export type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'quote'; text: string }
  | { kind: 'rule' }
  | { kind: 'paragraph'; text: string };

const HEADING = /^(#{1,6})\s+(.*)$/;
const UNORDERED = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*\d+[.)]\s+(.*)$/;
const RULE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;
const FENCE = /^\s*```\s*(\S*)\s*$/;

/** A `| a | b |` row split into its cells, outer pipes discarded. */
function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());
}

/** `|---|:--:|` — the separator that makes the line above a table header. */
function isTableDivider(line: string): boolean {
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.includes('-');
}

/**
 * Whether a line continues the list item above it rather than starting
 * something new. Blank ends the list; every other construct ends it too.
 */
function isContinuation(line: string): boolean {
  if (line.trim() === '') return false;
  if (HEADING.test(line) || RULE.test(line) || FENCE.test(line)) return false;
  if (UNORDERED.test(line) || ORDERED.test(line)) return false;
  if (line.trim().startsWith('|') || line.trimStart().startsWith('>')) return false;
  return true;
}

/**
 * Markdown source → blocks.
 *
 * Deliberately a line loop rather than a grammar: the corpus is machine-adjacent
 * prose written to a template, the constructs are line-oriented, and a line loop
 * is the version whose failure mode is "renders as a paragraph" rather than
 * "throws on input 47".
 */
export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length > 0) {
      blocks.push({ kind: 'paragraph', text: paragraph.join(' ').trim() });
      paragraph = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // A fence swallows everything up to its closer, verbatim — including lines
    // that would otherwise parse as headings, which is the whole point of it.
    const fence = FENCE.exec(line);
    if (fence) {
      flush();
      const body: string[] = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) {
        body.push(lines[i]);
        i++;
      }
      blocks.push({ kind: 'code', lang: fence[1], text: body.join('\n') });
      continue;
    }

    if (line.trim() === '') {
      flush();
      continue;
    }

    if (RULE.test(line)) {
      flush();
      blocks.push({ kind: 'rule' });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() });
      continue;
    }

    // A table needs its divider on the next line; without one this is just a
    // paragraph that happens to contain pipes.
    if (line.trim().startsWith('|') && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      flush();
      const header = tableCells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(tableCells(lines[i]));
        i++;
      }
      i--;
      blocks.push({ kind: 'table', header, rows });
      continue;
    }

    const unordered = UNORDERED.exec(line);
    const ordered = ORDERED.exec(line);
    if (unordered ?? ordered) {
      flush();
      const isOrdered = ordered !== null && unordered === null;
      const items: string[] = [];
      while (i < lines.length) {
        const item = isOrdered ? ORDERED.exec(lines[i]) : UNORDERED.exec(lines[i]);
        if (item) {
          items.push(item[1].trim());
          i++;
          continue;
        }
        // Lazy continuation. The corpus hard-wraps at ~80 columns, so a single
        // bullet routinely spans three lines — and without this a wrapped item
        // becomes a stray paragraph AND any `**bold**` straddling the wrap
        // renders as literal asterisks, both of which the first live walk of
        // the Journal showed happening in V270.md. A continuation is any
        // non-blank line that does not start a construct of its own.
        if (items.length > 0 && isContinuation(lines[i])) {
          items[items.length - 1] += ` ${lines[i].trim()}`;
          i++;
          continue;
        }
        break;
      }
      i--;
      blocks.push({ kind: 'list', ordered: isOrdered, items });
      continue;
    }

    if (line.trimStart().startsWith('>')) {
      flush();
      const quoted: string[] = [];
      while (i < lines.length && lines[i].trimStart().startsWith('>')) {
        quoted.push(lines[i].trimStart().replace(/^>\s?/, ''));
        i++;
      }
      i--;
      blocks.push({ kind: 'quote', text: quoted.join(' ').trim() });
      continue;
    }

    paragraph.push(line.trim());
  }

  flush();
  return blocks;
}

// ── Inline spans ─────────────────────────────────────────────────────────────

export type Span =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'link'; text: string; href: string };

// One pass, alternation ordered so `` `**not bold**` `` stays code: a code span
// wins over emphasis because a backtick in this corpus is always a literal.
const INLINE = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)]+)\)/g;

export function parseInline(text: string): Span[] {
  const spans: Span[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    // `index` is optional on the type but always present on a matchAll result.
    const at = match.index ?? last;
    if (at > last) spans.push({ kind: 'text', text: text.slice(last, at) });
    if (match[1] !== undefined) spans.push({ kind: 'code', text: match[1] });
    else if (match[2] !== undefined) spans.push({ kind: 'strong', text: match[2] });
    else spans.push({ kind: 'link', text: match[3], href: match[4] });
    last = at + match[0].length;
  }
  if (last < text.length) spans.push({ kind: 'text', text: text.slice(last) });
  return spans;
}

function Inline({ text }: { text: string }): ReactNode {
  return (
    <>
      {parseInline(text).map((span, i) => {
        switch (span.kind) {
          case 'strong':
            return (
              <strong key={i} className="font-semibold text-ink">
                {span.text}
              </strong>
            );
          case 'code':
            return (
              <code key={i} className="rounded-[3px] bg-cardAlt px-1 py-px font-mono text-[10px] text-ink2">
                {span.text}
              </code>
            );
          case 'link':
            // Not an <a>: every href in the corpus is a sibling .md file with no
            // route in this app. The target is disclosed rather than followed.
            return (
              <span
                key={i}
                title={span.href}
                className="underline decoration-dotted underline-offset-2 text-ink2"
              >
                {span.text}
              </span>
            );
          default:
            return <span key={i}>{span.text}</span>;
        }
      })}
    </>
  );
}

// ── Renderer ─────────────────────────────────────────────────────────────────

const HEADING_CLASS: Record<number, string> = {
  1: 'text-[13.5px] font-semibold text-ink',
  2: 'text-[12.5px] font-semibold text-ink',
  3: 'text-[11.5px] font-semibold text-ink2',
};

export function Markdown({ source }: { source: string }) {
  const blocks = parseMarkdown(source);
  if (blocks.length === 0) {
    return <p className="font-mono text-[10.5px] text-faint">(empty document)</p>;
  }
  return (
    <div className="flex flex-col gap-2.5 text-[11px] leading-relaxed text-ink3">
      {blocks.map((block, i) => {
        switch (block.kind) {
          case 'heading':
            return (
              <div
                key={i}
                className={`${HEADING_CLASS[block.level] ?? 'text-[11px] font-semibold text-ink3'} ${
                  block.level <= 2 ? 'mt-1.5 border-b border-hair pb-1' : ''
                }`}
              >
                <Inline text={block.text} />
              </div>
            );
          case 'code':
            return (
              <pre
                key={i}
                className="overflow-x-auto rounded-md border border-line bg-cardAlt px-3 py-2 font-mono text-[10px] leading-relaxed text-ink2"
              >
                {block.text}
              </pre>
            );
          case 'list':
            return block.ordered ? (
              <ol key={i} className="ml-4 list-decimal space-y-1">
                {block.items.map((item, j) => (
                  <li key={j}>
                    <Inline text={item} />
                  </li>
                ))}
              </ol>
            ) : (
              <ul key={i} className="ml-4 list-disc space-y-1">
                {block.items.map((item, j) => (
                  <li key={j}>
                    <Inline text={item} />
                  </li>
                ))}
              </ul>
            );
          case 'table':
            return (
              <div key={i} className="overflow-x-auto">
                <table className="w-full border-collapse text-[10.5px]">
                  <thead>
                    <tr className="border-b border-line">
                      {block.header.map((cell, j) => (
                        <th
                          key={j}
                          className="whitespace-nowrap px-2 py-1.5 text-left font-mono text-[9.5px] font-semibold uppercase tracking-[.06em] text-faint"
                        >
                          <Inline text={cell} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, j) => (
                      <tr key={j} className="border-b border-hair last:border-0">
                        {row.map((cell, k) => (
                          <td key={k} className="px-2 py-1 align-top tabular-nums">
                            <Inline text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case 'quote':
            return (
              <blockquote key={i} className="border-l-2 border-line pl-3 text-muted">
                <Inline text={block.text} />
              </blockquote>
            );
          case 'rule':
            return <hr key={i} className="border-0 border-t border-hair" />;
          default:
            return (
              <p key={i}>
                <Inline text={block.text} />
              </p>
            );
        }
      })}
    </div>
  );
}
