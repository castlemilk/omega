/**
 * The markdown mini-renderer, construct by construct.
 *
 * The parser is asserted on its *blocks* rather than on rendered HTML: a block
 * list is a value, and a test that asserted "the output contains an <h2>" would
 * pass while the heading text was silently dropped. The rendering pass gets one
 * pair of tests — that a table survives to markup, and that no markdown input
 * can produce raw HTML.
 *
 * The inputs below are real lines from `omega/nodes/victoria/training_log/`
 * (V270.md and its verdict), because the corpus is what this renderer exists
 * for and invented markdown would let it pass while failing on the files it
 * actually gets.
 */
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Markdown, parseInline, parseMarkdown } from './markdown.js';

describe('parseMarkdown', () => {
  it('reads ATX headings at every level the corpus uses', () => {
    expect(parseMarkdown('# V270 — spread-budget confirmation scoring\n\n## 1. The one question\n\n### 3.1 The join is SYMBOL-DAY')).toEqual([
      { kind: 'heading', level: 1, text: 'V270 — spread-budget confirmation scoring' },
      { kind: 'heading', level: 2, text: '1. The one question' },
      { kind: 'heading', level: 3, text: '3.1 The join is SYMBOL-DAY' },
    ]);
  });

  it('joins wrapped prose into one paragraph and splits on the blank line', () => {
    // The corpus hard-wraps at ~80 columns; rendering each wrapped line as its
    // own paragraph would double-space every document in the log.
    expect(parseMarkdown('V269 landed a real per-minute\nquoted-spread artefact.\n\nSecond para.')).toEqual([
      { kind: 'paragraph', text: 'V269 landed a real per-minute quoted-spread artefact.' },
      { kind: 'paragraph', text: 'Second para.' },
    ]);
  });

  it('keeps a fenced block verbatim, including lines that look like other constructs', () => {
    const blocks = parseMarkdown('```python\n# not a heading\n- not a list\n```');
    expect(blocks).toEqual([{ kind: 'code', lang: 'python', text: '# not a heading\n- not a list' }]);
  });

  it('treats an unterminated fence as code to the end, rather than losing it', () => {
    expect(parseMarkdown('```\nedge_bps = 1e4 * pnl / notional')).toEqual([
      { kind: 'code', lang: '', text: 'edge_bps = 1e4 * pnl / notional' },
    ]);
  });

  it('groups consecutive bullets into one list, and keeps ordered separate', () => {
    expect(parseMarkdown('- first\n- second\n\n1. one\n2. two')).toEqual([
      { kind: 'list', ordered: false, items: ['first', 'second'] },
      { kind: 'list', ordered: true, items: ['one', 'two'] },
    ]);
  });

  it('joins a wrapped bullet back into one item, bold and all', () => {
    // From V270.md: the corpus hard-wraps inside bullets, and a `**bold**` that
    // straddles the wrap rendered as literal asterisks until this existed.
    expect(
      parseMarkdown('- **G4a (rule fidelity):** re-implement V267’s rule on the **full\n  1,225-trade ledger**\n- second'),
    ).toEqual([
      {
        kind: 'list',
        ordered: false,
        items: ['**G4a (rule fidelity):** re-implement V267’s rule on the **full 1,225-trade ledger**', 'second'],
      },
    ]);
  });

  it('ends a list at a blank line or the next construct, not at the next wrap', () => {
    expect(parseMarkdown('- one\n\nloose paragraph')).toEqual([
      { kind: 'list', ordered: false, items: ['one'] },
      { kind: 'paragraph', text: 'loose paragraph' },
    ]);
    expect(parseMarkdown('- one\n## heading')).toEqual([
      { kind: 'list', ordered: false, items: ['one'] },
      { kind: 'heading', level: 2, text: 'heading' },
    ]);
  });

  it('reads a pipe table, which is the second most common construct in the corpus', () => {
    // 3,231 table lines across the 160 files — the reason this is a renderer
    // and not a <pre>.
    const blocks = parseMarkdown('| gate | result |\n|------|:------:|\n| pnl_floor | FAIL |\n| regime_parity | FAIL |');
    expect(blocks).toEqual([
      {
        kind: 'table',
        header: ['gate', 'result'],
        rows: [
          ['pnl_floor', 'FAIL'],
          ['regime_parity', 'FAIL'],
        ],
      },
    ]);
  });

  it('needs the divider — pipes in prose stay prose', () => {
    expect(parseMarkdown('| this is not | a table')).toEqual([
      { kind: 'paragraph', text: '| this is not | a table' },
    ]);
  });

  it('reads a rule and a blockquote', () => {
    expect(parseMarkdown('---\n\n> a quoted line\n> continued')).toEqual([
      { kind: 'rule' },
      { kind: 'quote', text: 'a quoted line continued' },
    ]);
  });

  it('falls through to a paragraph for anything it does not know', () => {
    // The whole failure mode of the parser: unrecognised input is rendered as
    // text, never dropped.
    expect(parseMarkdown('<div>raw html</div>\n\n    indented code')).toEqual([
      { kind: 'paragraph', text: '<div>raw html</div>' },
      { kind: 'paragraph', text: 'indented code' },
    ]);
  });

  it('is empty for empty input', () => {
    expect(parseMarkdown('')).toEqual([]);
    expect(parseMarkdown('\n\n  \n')).toEqual([]);
  });
});

describe('parseInline', () => {
  it('reads bold, code and links, keeping the text between them', () => {
    expect(parseInline('pooled median half-spread **0.480 bps** vs `1.6475`')).toEqual([
      { kind: 'text', text: 'pooled median half-spread ' },
      { kind: 'strong', text: '0.480 bps' },
      { kind: 'text', text: ' vs ' },
      { kind: 'code', text: '1.6475' },
    ]);
  });

  it('reads a link as text plus target, because there is nowhere to navigate to', () => {
    expect(parseInline('Parent: [`V269`](V269_DEPTH_ACQUISITION_VERDICT.md)')).toEqual([
      { kind: 'text', text: 'Parent: ' },
      { kind: 'link', text: '`V269`', href: 'V269_DEPTH_ACQUISITION_VERDICT.md' },
    ]);
  });

  it('lets code win over emphasis, because a backtick here is always literal', () => {
    expect(parseInline('`**literal**`')).toEqual([{ kind: 'code', text: '**literal**' }]);
  });

  it('returns plain text unchanged, and nothing for an empty string', () => {
    expect(parseInline('no markup here')).toEqual([{ kind: 'text', text: 'no markup here' }]);
    expect(parseInline('')).toEqual([]);
  });
});

describe('<Markdown>', () => {
  it('renders a table as a table, with its cells', () => {
    const html = renderToStaticMarkup(
      <Markdown source={'| gate | result |\n|---|---|\n| pnl_floor | FAIL |'} />,
    );
    expect(html).toContain('<table');
    expect(html).toContain('pnl_floor');
    expect(html).toContain('FAIL');
  });

  it('cannot emit raw HTML from the document, whatever the document says', () => {
    // The safety property of having no HTML passthrough: a markdown file is
    // text, and text is all it can ever become.
    const html = renderToStaticMarkup(<Markdown source={'<script>alert(1)</script>'} />);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('says a document is empty rather than rendering nothing at all', () => {
    expect(renderToStaticMarkup(<Markdown source="" />)).toContain('(empty document)');
  });
});
