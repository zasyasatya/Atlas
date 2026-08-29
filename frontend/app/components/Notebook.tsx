'use client';
/**
 * A notebook rendered the way Jupyter renders one.
 *
 * Interns move between this playground and real Jupyter/Colab constantly, so
 * the closer this looks to the thing they already know, the less there is to
 * learn. That means the classic layout: an `In [ ]:` prompt in the left gutter,
 * a bordered input area, `Out[ ]:` for results, markdown flowing full-width
 * with no chrome at all.
 *
 * Everything is self-contained - no highlight.js, no markdown library, no
 * network fetch. The workspace preview runs in a sandboxed iframe without
 * network access, so a CDN stylesheet would silently do nothing.
 */
import React from 'react';

// Jupyter's actual palette, so the muscle memory transfers.
const J = {
  inPrompt: '#303F9F',      // In  [n]:
  outPrompt: '#D84315',     // Out [n]:
  cellBg: '#F7F7F7',        // input area
  cellBorder: '#CFCFCF',
  cellBorderActive: '#66BB6A',
  text: '#000000',
  errBg: '#FDD',
  errText: '#A00',
  streamText: '#000000',
  mono: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
};

// ------------------------------------------------------------------ syntax
const KEYWORDS = new Set([
  'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break',
  'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally',
  'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal',
  'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield',
]);
const BUILTINS = new Set([
  'abs', 'all', 'any', 'bool', 'dict', 'dir', 'enumerate', 'eval', 'filter',
  'float', 'format', 'getattr', 'hasattr', 'id', 'int', 'isinstance', 'len',
  'list', 'map', 'max', 'min', 'next', 'open', 'print', 'range', 'repr',
  'reversed', 'round', 'set', 'setattr', 'sorted', 'str', 'sum', 'super',
  'tuple', 'type', 'zip', 'self',
]);

const TOK = {
  comment: '#408080',
  string: '#BA2121',
  keyword: '#008000',
  builtin: '#008000',
  number: '#666666',
  decorator: '#AA22FF',
  operator: '#666666',
  def: '#0000FF',
};

/**
 * Pygments-flavoured Python highlighting.
 *
 * Deliberately a single regex pass rather than a real lexer: it has to be
 * right on the shapes that actually appear in teaching notebooks (strings,
 * comments, f-strings, decorators, numbers, def/class names) and it must never
 * throw or drop characters on the ones it does not understand.
 */
function highlightPython(code: string): React.ReactNode[] {
  const pattern = new RegExp(
    [
      '(#[^\\n]*)',                                      // 1 comment
      '([fFrRbBuU]{0,2}"""[\\s\\S]*?"""|[fFrRbBuU]{0,2}\'\'\'[\\s\\S]*?\'\'\')', // 2 triple
      '([fFrRbBuU]{0,2}"(?:\\\\.|[^"\\\\\\n])*"|[fFrRbBuU]{0,2}\'(?:\\\\.|[^\'\\\\\\n])*\')', // 3 string
      '(@[A-Za-z_][\\w.]*)',                             // 4 decorator
      '\\b(\\d+\\.?\\d*(?:[eE][+-]?\\d+)?|0[xX][\\da-fA-F]+)\\b', // 5 number
      '\\b([A-Za-z_]\\w*)\\b',                           // 6 word
    ].join('|'), 'g');

  const out: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;

  const push = (text: string, color?: string, italic?: boolean, bold?: boolean) => {
    if (!text) return;
    out.push(color
      ? <span key={key++} style={{ color, fontStyle: italic ? 'italic' : undefined, fontWeight: bold ? 700 : undefined }}>{text}</span>
      : <React.Fragment key={key++}>{text}</React.Fragment>);
  };

  while ((m = pattern.exec(code)) !== null) {
    push(code.slice(last, m.index));
    last = m.index + m[0].length;

    if (m[1]) push(m[1], TOK.comment, true);
    else if (m[2] || m[3]) push(m[2] || m[3], TOK.string);
    else if (m[4]) push(m[4], TOK.decorator);
    else if (m[5]) push(m[5], TOK.number);
    else if (m[6]) {
      const w = m[6];
      const before = code.slice(0, m.index);
      // A name directly after def/class is the thing being defined.
      if (/\b(def|class)\s+$/.test(before)) push(w, TOK.def, false, true);
      else if (KEYWORDS.has(w)) push(w, TOK.keyword, false, true);
      else if (BUILTINS.has(w)) push(w, TOK.builtin);
      else push(w);
    }
  }
  push(code.slice(last));
  return out;
}

// ------------------------------------------------------------------ ANSI
const ANSI_COLORS: Record<string, string> = {
  '30': '#3E424D', '31': '#E75C58', '32': '#00A250', '33': '#DDB62B',
  '34': '#208FFB', '35': '#D160C4', '36': '#60C6C8', '37': '#C5C1B4',
  '90': '#282C36', '91': '#B22B31', '92': '#007427', '93': '#B27D12',
  '94': '#0065CA', '95': '#A03196', '96': '#258F8F', '97': '#A1A6B2',
};

/** Tracebacks arrive full of ANSI escapes; render the colours, drop the codes. */
function renderAnsi(text: string): React.ReactNode[] {
  const parts = text.split(/(\x1b\[[0-9;]*m)/g);
  const out: React.ReactNode[] = [];
  let color: string | undefined;
  let bold = false;
  parts.forEach((p, i) => {
    const esc = p.match(/^\x1b\[([0-9;]*)m$/);
    if (esc) {
      const codes = esc[1].split(';').filter(Boolean);
      if (codes.length === 0 || codes.includes('0')) { color = undefined; bold = false; }
      codes.forEach((c) => {
        if (c === '1') bold = true;
        else if (ANSI_COLORS[c]) color = ANSI_COLORS[c];
      });
      return;
    }
    if (p) out.push(<span key={i} style={{ color, fontWeight: bold ? 700 : undefined }}>{p}</span>);
  });
  return out;
}

// ------------------------------------------------------------------ markdown
const inlineMd = (t: string, k0 = 0): React.ReactNode[] =>
  t.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g).map((s, k) => {
    const key = `${k0}-${k}`;
    if (s.startsWith('**') && s.endsWith('**')) return <strong key={key}>{s.slice(2, -2)}</strong>;
    if (s.startsWith('`') && s.endsWith('`')) {
      return <code key={key} style={{
        background: '#F7F7F7', border: '1px solid #E0E0E0', borderRadius: 3,
        padding: '1px 4px', fontFamily: J.mono, fontSize: '0.9em', color: '#BA2121',
      }}>{s.slice(1, -1)}</code>;
    }
    if (s.startsWith('*') && s.endsWith('*') && s.length > 2) return <em key={key}>{s.slice(1, -1)}</em>;
    const link = s.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      return <a key={key} href={link[2]} target="_blank" rel="noreferrer"
        style={{ color: '#0071BC', textDecoration: 'underline' }}>{link[1]}</a>;
    }
    return <React.Fragment key={key}>{s}</React.Fragment>;
  });

/** Jupyter renders markdown cells with browser-default-ish typography. */
function MarkdownCell({ src }: { src: string }) {
  const lines = src.split('\n');
  const out: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim().startsWith('```')) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) buf.push(lines[i++]);
      i++;
      out.push(
        <pre key={out.length} style={{
          background: J.cellBg, border: `1px solid ${J.cellBorder}`, borderRadius: 2,
          padding: '8px 10px', overflowX: 'auto', fontFamily: J.mono,
          fontSize: 13, lineHeight: 1.45, margin: '10px 0',
        }}>{highlightPython(buf.join('\n'))}</pre>);
      continue;
    }

    if (line.trim().startsWith('|')) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        const cells = lines[i].split('|').slice(1, -1).map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      if (rows.length) {
        const [head, ...body] = rows;
        out.push(
          <table key={out.length} style={{
            borderCollapse: 'collapse', margin: '12px 0', fontSize: 13,
            border: '1px solid #CFCFCF',
          }}>
            <thead>
              <tr style={{ background: '#F5F5F5' }}>
                {head.map((h, k) => (
                  <th key={k} style={{
                    border: '1px solid #CFCFCF', padding: '5px 10px',
                    textAlign: 'left', fontWeight: 700,
                  }}>{inlineMd(h, k)}</th>))}
              </tr>
            </thead>
            <tbody>
              {body.map((r, k) => (
                <tr key={k}>{r.map((c, j) => (
                  <td key={j} style={{ border: '1px solid #CFCFCF', padding: '5px 10px' }}>
                    {inlineMd(c, j)}</td>))}</tr>))}
            </tbody>
          </table>);
      }
      continue;
    }

    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const size = [26, 21.5, 18, 16, 14.5, 13.5][level - 1];
      out.push(React.createElement(
        `h${level}`,
        {
          key: out.length,
          style: {
            fontSize: size, fontWeight: 700, color: J.text,
            margin: level <= 2 ? '14px 0 8px' : '12px 0 6px',
            lineHeight: 1.3,
            borderBottom: level === 1 ? '1px solid #E5E5E5' : undefined,
            paddingBottom: level === 1 ? 6 : undefined,
          },
        },
        inlineMd(h[2])));
      i++; continue;
    }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const items: { text: string; ordered: boolean }[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push({
          text: lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ''),
          ordered: /^\s*\d+\./.test(lines[i]),
        });
        i++;
      }
      const ordered = items[0].ordered;
      out.push(React.createElement(
        ordered ? 'ol' : 'ul',
        { key: out.length, style: { margin: '8px 0', paddingLeft: 26, fontSize: 14, lineHeight: 1.6 } },
        items.map((it, k) => <li key={k} style={{ marginBottom: 2 }}>{inlineMd(it.text, k)}</li>)));
      continue;
    }

    if (line.trim().startsWith('> ')) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('> ')) {
        buf.push(lines[i].replace(/^\s*>\s?/, '')); i++;
      }
      out.push(
        <blockquote key={out.length} style={{
          borderLeft: '4px solid #DDD', margin: '10px 0', padding: '2px 0 2px 14px',
          color: '#555', fontSize: 14, lineHeight: 1.6,
        }}>{inlineMd(buf.join(' '))}</blockquote>);
      continue;
    }

    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) {
      out.push(<hr key={out.length} style={{ border: 0, borderTop: '1px solid #E0E0E0', margin: '14px 0' }} />);
      i++; continue;
    }

    if (!line.trim()) { i++; continue; }

    // Consume a paragraph.
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim()
           && !/^\s*([-*+]|\d+\.)\s+/.test(lines[i])
           && !lines[i].trim().startsWith('|')
           && !lines[i].trim().startsWith('```')
           && !lines[i].trim().startsWith('> ')
           && !/^#{1,6}\s/.test(lines[i])) {
      buf.push(lines[i]); i++;
    }
    out.push(
      <p key={out.length} style={{ margin: '8px 0', fontSize: 14, lineHeight: 1.65, color: J.text }}>
        {inlineMd(buf.join(' '))}
      </p>);
  }

  return <div style={{ padding: '4px 0' }}>{out}</div>;
}

// ------------------------------------------------------------------ prompts
function Prompt({ label, color }: { label: string; color: string }) {
  return (
    <div style={{
      flex: '0 0 72px', width: 72, textAlign: 'right', paddingRight: 8, paddingTop: 5,
      fontFamily: J.mono, fontSize: 12.5, color, userSelect: 'none', lineHeight: 1.45,
    }}>{label}</div>
  );
}

// ------------------------------------------------------------------ outputs
const asText = (v: any): string => (Array.isArray(v) ? v.join('') : v || '');

function Output({ out }: { out: any }) {
  const type = out.output_type;

  if (type === 'stream') {
    const isErr = out.name === 'stderr';
    return (
      <pre style={{
        margin: 0, padding: '3px 0', fontFamily: J.mono, fontSize: 12.5, lineHeight: 1.45,
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        color: isErr ? J.errText : J.streamText,
        background: isErr ? J.errBg : 'transparent',
      }}>{renderAnsi(asText(out.text))}</pre>
    );
  }

  if (type === 'error') {
    const tb = (out.traceback || []).join('\n') || `${out.ename}: ${out.evalue}`;
    return (
      <pre style={{
        margin: 0, padding: '8px 10px', background: J.errBg, fontFamily: J.mono,
        fontSize: 12.5, lineHeight: 1.45, whiteSpace: 'pre-wrap',
        wordBreak: 'break-word', overflowX: 'auto',
      }}>{renderAnsi(tb)}</pre>
    );
  }

  if (type === 'execute_result' || type === 'display_data') {
    const data = out.data || {};
    if (data['image/png']) {
      const b64 = asText(data['image/png']).replace(/\s/g, '');
      // eslint-disable-next-line @next/next/no-img-element
      return <img src={`data:image/png;base64,${b64}`} alt="output"
        style={{ maxWidth: '100%', margin: '4px 0' }} />;
    }
    if (data['text/html']) {
      return <div style={{ fontSize: 13, overflowX: 'auto' }}
        dangerouslySetInnerHTML={{ __html: asText(data['text/html']) }} />;
    }
    if (data['text/plain']) {
      return (
        <pre style={{
          margin: 0, padding: '3px 0', fontFamily: J.mono, fontSize: 12.5,
          lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>{renderAnsi(asText(data['text/plain']))}</pre>);
    }
  }

  return null;
}

// ------------------------------------------------------------------ cells
function CodeCell({ cell }: { cell: any }) {
  const src = asText(cell.source);
  const count = cell.execution_count;
  const outputs: any[] = cell.outputs || [];
  // Jupyter shows Out[n] only for a returned value, not for printed output.
  const resultIdx = outputs.findIndex(
    (o) => o.output_type === 'execute_result' || o.output_type === 'display_data');

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start' }}>
        <Prompt label={`In [${count ?? ' '}]:`} color={J.inPrompt} />
        <div style={{
          flex: 1, minWidth: 0, background: J.cellBg, border: `1px solid ${J.cellBorder}`,
          borderRadius: 2, padding: '5px 8px',
        }}>
          <pre style={{
            margin: 0, fontFamily: J.mono, fontSize: 13, lineHeight: 1.45,
            overflowX: 'auto', whiteSpace: 'pre', color: J.text,
          }}>{highlightPython(src)}</pre>
        </div>
      </div>

      {outputs.map((o, k) => (
        <div key={k} style={{ display: 'flex', alignItems: 'flex-start', marginTop: 3 }}>
          <Prompt
            label={k === resultIdx && count != null ? `Out[${count}]:` : ''}
            color={J.outPrompt} />
          <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}><Output out={o} /></div>
        </div>
      ))}
    </div>
  );
}

function Cell({ cell }: { cell: any }) {
  if (cell.cell_type === 'markdown') {
    return (
      <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 4 }}>
        <div style={{ flex: '0 0 72px', width: 72 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <MarkdownCell src={asText(cell.source)} />
        </div>
      </div>
    );
  }
  if (cell.cell_type === 'raw') {
    return (
      <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 4 }}>
        <div style={{ flex: '0 0 72px', width: 72 }} />
        <pre style={{
          flex: 1, minWidth: 0, margin: 0, fontFamily: J.mono, fontSize: 12.5,
          lineHeight: 1.45, whiteSpace: 'pre-wrap', color: '#555',
        }}>{asText(cell.source)}</pre>
      </div>
    );
  }
  return <CodeCell cell={cell} />;
}

/**
 * The notebook surface: white page, Jupyter prompts, nothing else.
 *
 * `kernel` is shown in the top-right the way the real toolbar does, because it
 * is the one piece of state that changes what a run will actually do.
 */
export function NotebookView({ doc, kernel }: { doc: any; kernel?: string }) {
  const cells: any[] = doc?.cells || [];
  const kernelName =
    kernel
    || doc?.metadata?.kernelspec?.display_name
    || doc?.metadata?.kernelspec?.name
    || 'Python 3';

  return (
    <div style={{ background: '#FFFFFF', border: '1px solid #E2E8E2', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '6px 12px', borderBottom: '1px solid #E5E5E5', background: '#FAFAFA',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%', background: '#BDBDBD', display: 'inline-block',
          }} />
          <span style={{ fontSize: 11.5, color: '#616161', fontFamily: J.mono }}>
            {cells.length} cells
          </span>
        </div>
        <span style={{ fontSize: 11.5, color: '#616161', fontFamily: J.mono }}>{kernelName} ○</span>
      </div>

      <div style={{
        padding: '14px 14px 20px',
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
        color: J.text,
      }}>
        {cells.map((cell, i) => <Cell key={cell.id || i} cell={cell} />)}
      </div>
    </div>
  );
}

export default NotebookView;
