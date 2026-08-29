'use client';
import Link from 'next/link';
import React from 'react';
import { Logo } from '../components/Shell';
import {
  IcApps, IcArrowLeft, IcBook, IcDatabase, IcFlask, IcGrid, IcRocket,
  IcSettings, IcTrophy, IcX,
} from '../components/Icons';

/* ------------------------------------------------------------------ */
/* content model                                                       */
/* ------------------------------------------------------------------ */

const SECTIONS = [
  { id: 'start', label: 'Getting started', icon: IcBook },
  { id: 'signin', label: 'Signing in & roles', icon: IcGrid },
  { id: 'dashboard', label: 'The dashboard', icon: IcGrid },
  { id: 'curriculum', label: 'Curriculum', icon: IcBook },
  { id: 'authoring', label: 'Authoring lessons', icon: IcBook },
  { id: 'playground', label: 'Playground & GPUs', icon: IcFlask },
  { id: 'data', label: 'Datasets & decks', icon: IcDatabase },
  { id: 'deployment', label: 'Shipping your app', icon: IcRocket },
  { id: 'portal', label: 'App portal', icon: IcApps },
  { id: 'progress', label: 'XP & leaderboard', icon: IcTrophy },
  { id: 'settings', label: 'Settings & config', icon: IcSettings },
  { id: 'mobile', label: 'On mobile', icon: IcGrid },
  { id: 'trouble', label: 'Troubleshooting', icon: IcSettings },
  { id: 'glossary', label: 'Glossary', icon: IcBook },
];

/* ------------------------------------------------------------------ */
/* primitives                                                          */
/* ------------------------------------------------------------------ */

function Figure({
  src, num, caption, onZoom,
}: { src: string; num: string; caption: string; onZoom: (s: string, c: string) => void }) {
  return (
    <figure className="my-7">
      <button
        onClick={() => onZoom(src, caption)}
        className="group block w-full overflow-hidden rounded-2xl border border-line bg-paper-card
                   shadow-[0_1px_2px_rgba(18,22,15,0.04)] transition-all duration-200
                   hover:border-sage-300 hover:shadow-[0_8px_28px_rgba(18,22,15,0.10)]"
        aria-label={`Enlarge figure ${num}`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={caption} loading="lazy" className="block w-full" />
      </button>
      <figcaption className="mt-2.5 flex gap-2 text-[12.5px] leading-relaxed text-ink-muted">
        <span className="mono shrink-0 font-semibold text-sage-600">{num}</span>
        <span>{caption}</span>
      </figcaption>
    </figure>
  );
}

function Section({
  id, eyebrow, title, lead, children,
}: { id: string; eyebrow: string; title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-line pt-14 first:border-0 first:pt-0">
      <div className="eyebrow mb-2.5">{eyebrow}</div>
      <h2 className="mb-3 text-[30px] font-extrabold leading-[1.12] tracking-[-0.032em] text-ink">
        {title}
      </h2>
      {lead && <p className="mb-6 max-w-[68ch] text-[15.5px] leading-relaxed text-ink-soft">{lead}</p>}
      <div className="prose-manual">{children}</div>
    </section>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="mb-5 flex gap-4">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full
                      bg-sage-600 text-[13px] font-bold text-white">{n}</div>
      <div className="min-w-0 flex-1">
        <div className="mb-1 text-[15px] font-bold text-ink">{title}</div>
        <div className="text-[14.5px] leading-relaxed text-ink-soft">{children}</div>
      </div>
    </div>
  );
}

function Note({ kind = 'info', title, children }:
  { kind?: 'info' | 'warn' | 'ok'; title?: string; children: React.ReactNode }) {
  const tone = {
    info: 'border-signal-info/25 bg-signal-info/[0.07]',
    warn: 'border-signal-warn/30 bg-signal-warn/[0.09]',
    ok: 'border-signal-ok/25 bg-signal-ok/[0.07]',
  }[kind];
  const dot = { info: 'bg-signal-info', warn: 'bg-signal-warn', ok: 'bg-signal-ok' }[kind];
  return (
    <div className={`my-5 rounded-2xl border px-4 py-3.5 ${tone}`}>
      {title && (
        <div className="mb-1 flex items-center gap-2 text-[13px] font-bold text-ink">
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />{title}
        </div>
      )}
      <div className="text-[14px] leading-relaxed text-ink-soft">{children}</div>
    </div>
  );
}

function Code({ children }: { children: string }) {
  return (
    <pre className="my-4 overflow-x-auto rounded-2xl border border-line bg-ink px-4 py-3.5">
      <code className="mono whitespace-pre text-[12.5px] leading-[1.75] text-[#D8E2D8]">{children}</code>
    </pre>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="mono rounded-md border border-line-strong bg-paper-deep px-1.5 py-0.5
                    text-[11.5px] font-semibold text-ink-soft">{children}</kbd>
  );
}

function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="my-5 overflow-x-auto rounded-2xl border border-line">
      <table className="w-full border-collapse text-[13.5px]">
        <thead>
          <tr className="bg-paper-deep">
            {head.map((h) => (
              <th key={h} className="whitespace-nowrap border-b border-line px-4 py-2.5
                                     text-left text-[11px] font-bold uppercase tracking-[0.09em] text-ink-muted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line last:border-0">
              {r.map((c, j) => (
                <td key={j} className="px-4 py-2.5 align-top leading-relaxed text-ink-soft">{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const M = ({ children }: { children: React.ReactNode }) => (
  <code className="mono rounded-md bg-paper-deep px-1.5 py-0.5 text-[12.5px] text-sage-700">{children}</code>
);

/* ------------------------------------------------------------------ */
/* page                                                                */
/* ------------------------------------------------------------------ */

export default function Manual() {
  const [active, setActive] = React.useState('start');
  const [zoom, setZoom] = React.useState<{ src: string; cap: string } | null>(null);
  const [navOpen, setNavOpen] = React.useState(false);

  // scrollspy
  React.useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (vis[0]) setActive(vis[0].target.id);
      },
      { rootMargin: '-80px 0px -65% 0px', threshold: 0 },
    );
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    });
    return () => obs.disconnect();
  }, []);

  // esc closes the lightbox
  React.useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setZoom(null); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  const fig = (src: string, cap: string) => setZoom({ src, cap });

  return (
    <div className="min-h-screen bg-paper">
      {/* ---------------- top bar ---------------- */}
      <header className="sticky top-0 z-40 border-b border-line bg-paper/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1240px] items-center gap-3 px-5 py-3">
          <Link href="/login" className="flex items-center gap-2.5">
            <Logo size={30} />
            <div className="leading-none">
              <div className="text-[15px] font-extrabold tracking-[-0.02em] text-ink">ATLAS</div>
              <div className="mt-0.5 text-[9.5px] tracking-wide text-ink-faint">USER MANUAL</div>
            </div>
          </Link>
          <div className="flex-1" />
          <button
            onClick={() => window.print()}
            className="hidden rounded-xl border border-line px-3 py-1.5 text-[12.5px] font-semibold
                       text-ink-soft transition-colors hover:border-sage-300 hover:text-sage-700 sm:block print:hidden"
          >
            Print / PDF
          </button>
          <Link
            href="/login"
            className="rounded-xl bg-sage-600 px-3.5 py-1.5 text-[12.5px] font-semibold text-white
                       transition-colors hover:bg-sage-700 print:hidden"
          >
            Back to sign in
          </Link>
          <button
            onClick={() => setNavOpen((v) => !v)}
            className="rounded-xl border border-line px-2.5 py-1.5 text-[12.5px] font-semibold
                       text-ink-soft lg:hidden print:hidden"
          >
            {navOpen ? 'Close' : 'Contents'}
          </button>
        </div>
      </header>

      {/* ---------------- hero ---------------- */}
      <div className="grid-canvas border-b border-line">
        <div className="mx-auto max-w-[1240px] px-5 py-14">
          <div className="eyebrow mb-3">Complete guide · v1.0</div>
          <h1 className="max-w-[20ch] text-[clamp(34px,5.6vw,54px)] font-extrabold leading-[1.03]
                         tracking-[-0.04em] text-ink">
            How to run your internship on ATLAS
          </h1>
          <p className="mt-4 max-w-[66ch] text-[16.5px] leading-relaxed text-ink-soft">
            Everything the platform does, in the order you will need it: learn the architecture,
            train on a borrowed GPU, upload your data, then ship a web app that passes all five
            graduation checks. Every screenshot below is the real interface.
          </p>
          <div className="mt-7 flex flex-wrap gap-2.5">
            {[
              ['14', 'chapters'], ['18', 'screenshots'], ['6', 'topics'], ['5', 'rubric rules'],
            ].map(([n, l]) => (
              <div key={l} className="rounded-xl border border-line bg-paper-card px-3.5 py-2">
                <span className="text-[17px] font-extrabold text-ink">{n}</span>
                <span className="ml-1.5 text-[12.5px] text-ink-muted">{l}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ---------------- body ---------------- */}
      <div className="mx-auto flex max-w-[1240px] gap-10 px-5 py-12">
        {/* sidebar */}
        {/* overflow-y-auto powers the mobile drawer, but an overflow ancestor
            disables position:sticky in its descendants - so it is cleared at lg. */}
        <aside className={`${navOpen ? 'block' : 'hidden'} lg:block print:hidden
                           fixed inset-x-0 bottom-0 top-[57px] z-30 overflow-y-auto border-b border-line
                           bg-paper px-5 py-5 lg:static lg:z-auto lg:w-[228px] lg:shrink-0
                           lg:overflow-visible lg:border-0 lg:px-0 lg:py-0`}>
          <div className="lg:sticky lg:top-[85px] lg:max-h-[calc(100vh-105px)] lg:overflow-y-auto">
            <div className="eyebrow mb-3">Contents</div>
            <nav className="space-y-0.5">
              {SECTIONS.map((s, i) => {
                const on = active === s.id;
                return (
                  <a
                    key={s.id}
                    href={`#${s.id}`}
                    onClick={() => setNavOpen(false)}
                    className={`flex items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-[13px]
                                font-semibold transition-colors ${
                      on ? 'bg-sage-600 text-white' : 'text-ink-soft hover:bg-sage-50 hover:text-sage-800'
                    }`}
                  >
                    <span className={`mono text-[10.5px] ${on ? 'text-white/70' : 'text-ink-faint'}`}>
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span className="truncate">{s.label}</span>
                  </a>
                );
              })}
            </nav>
          </div>
        </aside>

        {/* article */}
        <article className="min-w-0 flex-1 space-y-14">

          {/* ============ 01 GETTING STARTED ============ */}
          <Section
            id="start" eyebrow="Chapter 01" title="Getting started"
            lead="ATLAS runs as a single program. One command sets up everything and serves the whole platform on one port — no Docker required."
          >
            <Step n={1} title="Check you have Python 3.10 or newer">
              Run <M>python --version</M>. If that fails, try <M>python3 --version</M>. Install from{' '}
              <a className="text-sage-700 underline underline-offset-2" href="https://python.org/downloads"
                 target="_blank" rel="noreferrer">python.org</a> if needed — on Windows, tick
              <strong> “Add Python to PATH”</strong> during setup.
            </Step>
            <Step n={2} title="Start the platform">
              From the project folder:
              <Code>python run.py</Code>
              On Windows you can double-click <M>start.bat</M>; on macOS or Linux, <M>./start.sh</M>.
            </Step>
            <Step n={3} title="Wait for the first build">
              The first run creates a virtual environment, installs dependencies, compiles the web
              interface and seeds the database. That takes roughly 3–6 minutes. Later starts take
              a few seconds.
            </Step>
            <Step n={4} title="Open the app">
              Go to <M>http://localhost:8000</M>. You should land on the sign-in page.
            </Step>

            <Note kind="info" title="Node.js is optional">
              Node 18+ is only needed to compile the web interface. Without it ATLAS still runs as
              an API — the docs live at <M>/api/docs</M> — and serves a prebuilt interface if one
              ships with your copy.
            </Note>

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">Other ways to run it</h3>
            <Table
              head={['Command', 'What it does']}
              rows={[
                [<M key="a">python run.py --check</M>, 'Diagnose the environment and change nothing. Start here when something looks wrong.'],
                [<M key="b">python run.py --build</M>, 'Force a rebuild of the interface. Use after editing frontend code.'],
                [<M key="c">python run.py --dev</M>, 'Hot-reload development mode: interface on :3000, API on :8000.'],
                [<M key="d">python run.py --backend-only</M>, 'API only, skip the interface build.'],
                [<M key="e">python run.py --port 9000</M>, 'Serve on a different port when 8000 is taken.'],
                [<M key="f">python run.py --host 0.0.0.0</M>, 'Expose the platform to others on your network.'],
                [<M key="g">docker compose up --build</M>, 'Run as a container instead, if you do have Docker.'],
              ]}
            />
          </Section>

          {/* ============ 02 SIGN IN ============ */}
          <Section
            id="signin" eyebrow="Chapter 02" title="Signing in & roles"
            lead="ATLAS ships with four demo accounts. Click any card on the sign-in page to fill the form instantly."
          >
            <Figure num="Fig. 2.1" src="/manual/01-login.jpg" onZoom={fig}
              caption="The sign-in page. Demo account cards sit below the form — clicking one fills in the credentials for you." />

            <Table
              head={['Role', 'Email', 'Password', 'What they can do']}
              rows={[
                ['Supervisor', <M key="1">supervisor@atlas.id</M>, <M key="2">supervisor123</M>, 'Author curriculum, review apps, upload decks and datasets.'],
                ['Intern', <M key="3">intern@atlas.id</M>, <M key="4">intern123</M>, 'Learn, run notebooks, upload data, ship the graduation app.'],
                ['Admin', <M key="5">admin@atlas.id</M>, <M key="6">admin123</M>, 'Everything a supervisor can do, plus platform configuration.'],
                ['Viewer', <M key="7">viewer@atlas.id</M>, <M key="8">viewer123</M>, 'Read-only access for guests and external reviewers.'],
              ]}
            />

            <Note kind="warn" title="Change these before real use">
              The demo accounts exist so you can explore immediately. Before running an actual
              cohort, set <M>ATLAS_SEED_DEMO_DATA=false</M> and create real users, or at minimum
              change every password.
            </Note>

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">Google sign-in</h3>
            <p>
              Set <M>ATLAS_GOOGLE_CLIENT_ID</M> and <M>ATLAS_GOOGLE_CLIENT_SECRET</M> to enable the
              “Continue with Google” button. Until then the button explains that SSO is not
              configured rather than failing silently.
            </p>
          </Section>

          {/* ============ 03 DASHBOARD ============ */}
          <Section
            id="dashboard" eyebrow="Chapter 03" title="The dashboard"
            lead="Your control room. Four counters across the top, your six topics down the middle, level and activity on the right."
          >
            <Figure num="Fig. 3.1" src="/manual/02-dashboard.jpg" onZoom={fig}
              caption="The dashboard after signing in as a supervisor. Progress bars on each topic reflect completed stages; GPU badges mark the two heavy computer-vision tracks." />

            <Table
              head={['Card', 'Meaning']}
              rows={[
                ['Lessons completed', 'Stages you have finished out of 18 across all six topics.'],
                ['Notebook runs', 'Training runs you have launched, and how many used a GPU.'],
                ['Live apps', 'Deployed apps currently running out of the total you created.'],
                ['Graduation ready', 'Apps scoring 80% or higher against the five rubric rules.'],
              ]}
            />
            <p>
              The <strong>Library</strong> panel counts datasets, PPT decks, notebooks and
              deployments. <strong>Activity</strong> is a live audit trail — every upload, run and
              deployment across the whole cohort, newest first.
            </p>
          </Section>

          {/* ============ 04 CURRICULUM ============ */}
          <Section
            id="curriculum" eyebrow="Chapter 04" title="Curriculum"
            lead="Six tracks, each with three stages. The material explains AI architecture for people who are not engineers."
          >
            <Figure num="Fig. 4.1" src="/manual/03-curriculum.jpg" onZoom={fig}
              caption="All six topics. Each card shows difficulty, estimated hours, task type and whether the track needs a GPU." />

            <Table
              head={['#', 'Topic', 'Task type', 'Compute']}
              rows={[
                ['1', 'Predictive Maintenance', 'Classification', 'CPU'],
                ['2', 'P&ID Extractor', 'Extraction (vision)', <strong key="g1" className="text-sage-700">GPU</strong>],
                ['3', 'Inspection Report NLP', 'Classification', 'CPU'],
                ['4', 'Production Forecasting', 'Forecasting', 'CPU'],
                ['5', 'SOP RAG Assistant', 'Extraction', 'CPU'],
                ['6', 'Corrosion Type Segmentation', 'Segmentation (vision)', <strong key="g2" className="text-sage-700">GPU</strong>],
              ]}
            />

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">The three stages</h3>
            <p>
              Every topic follows the same rhythm, so you always know where you are:
            </p>
            <ul className="my-4 space-y-2">
              {[
                ['Stage 1 — Mission Briefing', 'Why this problem matters and what “done” looks like. 20 XP.'],
                ['Stage 2 — Read the Blueprint', 'How the model actually works, step by step. 30 XP.'],
                ['Stage 3 — Boss Fight', 'Build it yourself and prove it works. 50 XP.'],
              ].map(([t, d]) => (
                <li key={t} className="flex gap-2.5">
                  <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-sage-400" />
                  <span><strong className="text-ink">{t}</strong> — {d}</span>
                </li>
              ))}
            </ul>

            <Figure num="Fig. 4.2" src="/manual/04-topic-detail.jpg" onZoom={fig}
              caption="Inside a topic. The stage rail on the left tracks progress; the Complete button awards XP and unlocks the next stage." />

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">Interactive architecture diagrams</h3>
            <p>
              The Blueprint stage contains clickable pipeline diagrams. Select any step to read a
              plain-language explanation of what happens there and why it matters — this is the
              part designed for laypeople.
            </p>
            <Figure num="Fig. 4.3" src="/manual/05-architecture.jpg" onZoom={fig}
              caption="The architecture block inside Corrosion Type Segmentation. Each node expands into an explanation written for a non-technical reader." />
          </Section>

          {/* ============ 05 AUTHORING ============ */}
          <Section
            id="authoring" eyebrow="Chapter 05" title="Authoring lessons"
            lead="Supervisors write material through the interface. No code, no repository access, no developer in the loop."
          >
            <Note kind="info" title="Who can edit">
              The editing controls only appear for Supervisor and Admin accounts. Interns and
              viewers see the published result.
            </Note>

            <Step n={1} title="Open a topic and choose a stage">
              Go to <strong>Curriculum</strong>, open any topic, then click the pencil icon on a
              stage — or <strong>Add</strong> to create a new one.
            </Step>
            <Step n={2} title="Set the stage details">
              Give it a title, a one-line hook, an estimated duration and an XP reward.
            </Step>
            <Step n={3} title="Compose the body from blocks">
              Click <strong>Add block</strong> and pick a type. Blocks can be reordered with the
              arrows or removed with the bin icon.
            </Step>
            <Step n={4} title="Preview, then publish">
              <strong>Preview</strong> renders the lesson exactly as interns will see it.
              <strong> Save stage</strong> publishes it immediately.
            </Step>

            <Figure num="Fig. 5.1" src="/manual/06-cms-editor.jpg" onZoom={fig}
              caption="Editing an existing stage. Title, hook, duration and XP sit at the top; the content blocks follow underneath." />

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">The eight block types</h3>
            <Table
              head={['Block', 'Use it for']}
              rows={[
                ['Text', 'Paragraphs with **bold**, *italic*, `code` and - bullet lists.'],
                ['Callout', 'A highlighted box: quest, warning, info or success.'],
                ['Architecture diagram', 'A clickable pipeline where each step has its own explanation.'],
                ['Quiz checkpoint', 'Multiple choice with an explanation revealed after answering.'],
                ['Flashcards', 'Flip cards for jargon and terminology.'],
                ['Code sample', 'A syntax-styled snippet.'],
                ['Image', 'A diagram or screenshot by URL.'],
                ['Video embed', 'A YouTube or Drive embed URL.'],
              ]}
            />
            <Figure num="Fig. 5.2" src="/manual/07-block-palette.jpg" onZoom={fig}
              caption="The block palette open inside the editor. Pick a type and it is appended to the lesson body." />
          </Section>

          {/* ============ 06 PLAYGROUND ============ */}
          <Section
            id="playground" eyebrow="Chapter 06" title="Playground & GPUs"
            lead="Every topic has its own notebook. Heavy vision training is routed to a borrowed GPU automatically — this server has none, and needs none."
          >
            <Figure num="Fig. 6.1" src="/manual/08-playground.jpg" onZoom={fig}
              caption="The playground. Topic tabs across the top, the notebook preview in the middle, and the launch panel on the right." />

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">Choosing where it runs</h3>
            <Table
              head={['Target', 'Hardware', 'Best for']}
              rows={[
                ['Platform CPU', 'Built-in kernel on this server', 'Tabular and NLP work. Instant, no setup.'],
                ['Google Colab GPU', 'Free T4', 'Vision training. One click, then Run all in the browser tab.'],
                ['Kaggle GPU', 'T4 or P100, 30 h/week', 'Fully headless vision training — no browser tab needed.'],
              ]}
            />

            <Note kind="ok" title="You cannot accidentally train a vision model on CPU">
              Topics 2 and 6 are flagged as GPU work. If you pick CPU, ATLAS reroutes the run to
              the topic&apos;s GPU target and tells you it did. A vision model on CPU would appear
              to work while taking hours, so the platform refuses to let that happen quietly.
            </Note>

            <Figure num="Fig. 6.2" src="/manual/09-playground-gpu.jpg" onZoom={fig}
              caption="Corrosion Type Segmentation selected. The notebook is marked GPU required and Colab is pre-selected in the launch panel." />

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">How the bridge works</h3>
            <p>
              ATLAS injects a small helper cell at the top of your notebook before sending it
              anywhere. That helper talks back to the platform, so a run on someone else&apos;s
              GPU still reports into your timeline here:
            </p>
            <Table
              head={['Helper', 'What it does']}
              rows={[
                [<M key="1">atlas.log(&quot;...&quot;)</M>, 'Append a line to the run log.'],
                [<M key="2">atlas.metric(accuracy=0.93)</M>, 'Push a metric to the dashboard.'],
                [<M key="3">atlas.dataset()</M>, 'Download the dataset attached to this run.'],
                [<M key="4">atlas.artifact(&quot;model.pkl&quot;)</M>, 'Upload a trained file back to ATLAS.'],
                [<M key="5">atlas.finish()</M>, 'Mark the run complete.'],
              ]}
            />
            <p>
              Artifacts you upload land back in the dataset library tagged as <M>model</M>, so a
              trained file is never stranded on a Colab machine that is about to disconnect.
            </p>

            <Note kind="warn" title="Remote GPUs need a reachable address">
              Colab and Kaggle call back to whatever <M>ATLAS_PUBLIC_BASE_URL</M> says. On
              <M>localhost</M> that is fine because you open the notebook yourself, but on a
              deployed server it must be the public URL or results will never arrive.
            </Note>
          </Section>

          {/* ============ 07 DATA ============ */}
          <Section
            id="data" eyebrow="Chapter 07" title="Datasets & decks"
            lead="Upload data and slides, and the platform reads them for you: spreadsheet schema, row counts, slide titles — all captured automatically."
          >
            <Figure num="Fig. 7.1" src="/manual/10-datasets.jpg" onZoom={fig}
              caption="The dataset library. Every upload records its schema, size, pipeline stage, version and who uploaded it." />

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">Pipeline stages</h3>
            <p>
              Tag every upload with the step it belongs to, so the history of a dataset stays
              readable months later:
            </p>
            <div className="my-4 flex flex-wrap gap-2">
              {[
                ['raw', 'straight from the source'],
                ['cleaned', 'nulls and outliers handled'],
                ['features', 'engineered columns'],
                ['split', 'train / test partitions'],
                ['model', 'trained artifacts'],
              ].map(([s, d]) => (
                <div key={s} className="rounded-xl border border-line bg-paper-card px-3 py-1.5">
                  <span className="mono text-[12px] font-bold text-sage-700">{s}</span>
                  <span className="ml-2 text-[12.5px] text-ink-muted">{d}</span>
                </div>
              ))}
            </div>

            <Note kind="info" title="What gets read automatically">
              CSV and XLSX files are inspected for row count, column count and column names.
              PowerPoint decks have their slide count and slide titles extracted. You do not
              describe the file by hand.
            </Note>

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">Preparation decks</h3>
            <p>
              The <strong>Decks</strong> tab holds the PowerPoint walkthroughs that explain how
              each topic&apos;s dataset was prepared, so an intern joining mid-programme can see
              the reasoning rather than guessing from the file.
            </p>
            <Figure num="Fig. 7.2" src="/manual/11-decks.jpg" onZoom={fig}
              caption="The decks tab. Slide titles are pulled out of the file on upload and listed under each deck." />
          </Section>

          {/* ============ 08 DEPLOYMENT ============ */}
          <Section
            id="deployment" eyebrow="Chapter 08" title="Shipping your app"
            lead="The graduation deliverable. ATLAS checks your app against five requirements, generates a Dockerfile and deploys it in one click."
          >
            <Figure num="Fig. 8.1" src="/manual/12-deployment.jpg" onZoom={fig}
              caption="A deployment scoring 100%. All five rubric rules pass, and the Whimsical board URL required by R5 has been saved." />

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">The five requirements</h3>
            <Table
              head={['Rule', 'Requirement', 'How it is checked']}
              rows={[
                [<strong key="r1">R1</strong>, 'Framework must be Streamlit or Gradio.', 'Imports are scanned in your entry file.'],
                [<strong key="r2">R2</strong>, 'Input form: single entry AND bulk spreadsheet upload.', 'Looks for both a form and a file uploader accepting CSV/XLSX.'],
                [<strong key="r3">R3</strong>, 'Documentation page covering model limitations, dataset details, model architecture and evaluation results.', 'All four headings must be present.'],
                [<strong key="r4">R4</strong>, 'Output: confidence score for classification, MAPE for forecasting, plus a chart.', 'Switches on the topic task type.'],
                [<strong key="r5">R5</strong>, 'Deployed app URL attached in Whimsical.', 'You paste the board URL into the deployment.'],
              ]}
            />

            <Note kind="ok" title="Start from a template that already passes">
              ATLAS ships Streamlit and Gradio starters that score 100% out of the box. Download
              one, replace the model with yours, and keep the structure — the rubric is satisfied
              by construction.
            </Note>

            <h3 className="mb-2 mt-8 text-[17px] font-bold text-ink">Shipping it</h3>
            <Step n={1} title="Create the deployment">
              Click <strong>New deployment</strong>, name it, pick the topic and framework, and
              upload your app as a zip or a single <M>app.py</M>.
            </Step>
            <Step n={2} title="Run the checks">
              <strong>Re-check</strong> scores your bundle and lists exactly what is missing for
              any rule that fails. Fix, re-upload with <strong>Replace bundle</strong>, check again.
            </Step>
            <Step n={3} title="Paste the Whimsical URL">
              Rule R5 needs the board where reviewers will see your app. Paste it and press
              <strong> Save</strong>.
            </Step>
            <Step n={4} title="Deploy">
              <strong>One-click deploy</strong> builds and launches your app, then re-runs the
              rubric against the live version. A cold deploy takes roughly 30 seconds.
            </Step>

            <p>
              Need the container recipe? <strong>Dockerfile</strong> downloads the exact file ATLAS
              generated for your app — useful when you deploy elsewhere.
            </p>
            <Note kind="warn" title="80% is the graduation line">
              Rules score 1 for a pass and 0.5 for a warning. Anything at or above 80% counts as
              graduation ready on the dashboard, but aim for 5/5 — reviewers see the breakdown.
            </Note>
          </Section>

          {/* ============ 09 PORTAL ============ */}
          <Section
            id="portal" eyebrow="Chapter 09" title="App portal"
            lead="Every app that reaches the running state is published here automatically, so the cohort's work documents itself."
          >
            <Figure num="Fig. 9.1" src="/manual/13-portal.jpg" onZoom={fig}
              caption="The portal. Each entry shows its framework, owner, topic, rubric score and a direct link to the live app." />
            <p>
              You never add anything to the portal by hand. When a deployment starts running it is
              published; when it is stopped the entry stays, marked accordingly, so the record of
              what was built survives the app being switched off.
            </p>
          </Section>

          {/* ============ 10 PROGRESS ============ */}
          <Section
            id="progress" eyebrow="Chapter 10" title="XP & leaderboard"
            lead="Progress is scored so the cohort can see momentum without anyone chasing a spreadsheet."
          >
            <Figure num="Fig. 10.1" src="/manual/14-leaderboard.jpg" onZoom={fig}
              caption="The cohort leaderboard, ranked by total XP with each member's level alongside." />
            <Table
              head={['Action', 'Reward']}
              rows={[
                ['Complete Stage 1 — Mission Briefing', '20 XP'],
                ['Complete Stage 2 — Read the Blueprint', '30 XP'],
                ['Complete Stage 3 — Boss Fight', '50 XP'],
                ['Finish an entire topic', '100 XP total'],
                ['All six topics', '600 XP'],
              ]}
            />
            <p>
              Your level is <M>1 + XP ÷ 200</M>, so every 200 XP is a level. The dashboard shows
              how far you are from the next one.
            </p>
          </Section>

          {/* ============ 11 SETTINGS ============ */}
          <Section
            id="settings" eyebrow="Chapter 11" title="Settings & configuration"
            lead="Settings shows which integrations are live. Everything is driven by environment variables, so nothing sensitive lives in the database."
          >
            <Figure num="Fig. 11.1" src="/manual/15-settings.jpg" onZoom={fig}
              caption="The settings page. Each integration reports whether it is configured, without ever revealing the secret itself." />
            <Table
              head={['Variable', 'Purpose']}
              rows={[
                [<M key="1">ATLAS_SECRET_KEY</M>, 'Signs login tokens. Must be changed before production.'],
                [<M key="2">ATLAS_PUBLIC_BASE_URL</M>, 'Where remote notebooks call back. Wrong value silently breaks the GPU bridge.'],
                [<M key="3">ATLAS_SEED_DEMO_DATA</M>, 'Set false to stop seeding demo accounts and topics.'],
                [<M key="4">ATLAS_GITHUB_TOKEN</M>, 'Enables the Colab bridge, together with the repo and branch settings.'],
                [<M key="5">ATLAS_KAGGLE_USERNAME / _KEY</M>, 'Enables fully headless Kaggle GPU runs.'],
                [<M key="6">ATLAS_DEPLOY_DRIVER</M>, 'local_process, coolify or manifest.'],
                [<M key="7">ATLAS_GOOGLE_CLIENT_ID / _SECRET</M>, 'Enables Google sign-in.'],
                [<M key="8">ATLAS_DATABASE_URL</M>, 'Leave empty for SQLite; set for PostgreSQL.'],
              ]}
            />
            <Note kind="info" title="Where to put them">
              Copy <M>.env.example</M> to <M>.env</M> and edit. On first run <M>run.py</M> creates
              that file for you with a freshly generated secret key.
            </Note>
          </Section>

          {/* ============ 12 MOBILE ============ */}
          <Section
            id="mobile" eyebrow="Chapter 12" title="On mobile"
            lead="The full platform works on a phone. Navigation collapses into a menu and every table scrolls rather than overflowing."
          >
            <div className="my-7 flex flex-wrap items-start gap-7">
              <button onClick={() => fig('/manual/16-mobile.jpg', 'The dashboard at 390 px, signed in as an intern.')}
                className="overflow-hidden rounded-[22px] border border-line bg-paper-card
                           shadow-[0_1px_2px_rgba(18,22,15,0.04)] transition-all hover:border-sage-300
                           hover:shadow-[0_8px_28px_rgba(18,22,15,0.10)]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/manual/16-mobile.jpg" alt="ATLAS dashboard on a phone"
                     loading="lazy" className="block w-[260px]" />
              </button>
              <div className="min-w-[260px] flex-1">
                <div className="mono mb-2 text-[12.5px] font-semibold text-sage-600">Fig. 12.1</div>
                <p className="text-[14.5px] leading-relaxed text-ink-soft">
                  The dashboard at 390 px wide, signed in as an intern. Reading lessons, completing
                  stages and browsing the portal all work on a phone.
                </p>
                <Note kind="info" title="Best done on a laptop">
                  Uploading datasets, authoring lessons and deploying apps involve file pickers and
                  wide tables. They work on mobile, but they are considerably easier on a larger screen.
                </Note>
              </div>
            </div>
          </Section>

          {/* ============ 13 TROUBLESHOOTING ============ */}
          <Section
            id="trouble" eyebrow="Chapter 13" title="Troubleshooting"
            lead="The failures people actually hit, and what each one really means."
          >
            {[
              {
                q: 'I sign in successfully but get thrown back to the login page',
                a: (
                  <>
                    <p>Almost always a stale interface bundle, so the page never becomes interactive.</p>
                    <ol className="my-3 ml-4 list-decimal space-y-1.5">
                      <li>Hard-refresh: <Kbd>Ctrl</Kbd>+<Kbd>Shift</Kbd>+<Kbd>R</Kbd>, or <Kbd>Cmd</Kbd>+<Kbd>Shift</Kbd>+<Kbd>R</Kbd> on a Mac.</li>
                      <li>Rebuild so the served files match the code: <M>python run.py --build</M></li>
                      <li>Open DevTools → Console. 404s for <M>/_next/static/chunks/*.js</M> confirm it.</li>
                    </ol>
                    <p>
                      Two other causes: <strong>blocked site storage</strong> (private mode, a
                      sandboxed preview frame, or a strict cookie policy) — ATLAS falls back to a
                      temporary session and warns you, so open a normal tab to stay signed in; and
                      <strong> a badly wrong system clock</strong>, which makes every token look expired.
                    </p>
                  </>
                ),
              },
              {
                q: '“Cannot reach the ATLAS API”',
                a: <p>The backend is not running, or it is on another port. Start it with <M>python run.py</M> and confirm <M>http://localhost:8000/api/health</M> returns <M>{'{"status":"ok"}'}</M>.</p>,
              },
              {
                q: 'python: command not found',
                a: <p>Try <M>python3 run.py</M>. On Windows, reinstall Python with <strong>“Add Python to PATH”</strong> ticked.</p>,
              },
              {
                q: 'ensurepip is not available, or the virtualenv will not build',
                a: <>
                  <p>Debian and Ubuntu ship Python without the venv module:</p>
                  <Code>sudo apt install python3-venv python3-pip</Code>
                </>,
              },
              {
                q: 'I only see JSON at the home page, no interface',
                a: <>
                  <p>Node.js was missing when the interface was built. Install Node 18+, then rebuild:</p>
                  <Code>python run.py --build</Code>
                </>,
              },
              {
                q: 'Port 8000 is already in use',
                a: <p>Run on another port: <M>python run.py --port 8080</M></p>,
              },
              {
                q: 'My Colab run never reports back',
                a: <p><M>ATLAS_PUBLIC_BASE_URL</M> must be an address the Colab machine can actually reach. A <M>localhost</M> value works only when you run the notebook on the same machine.</p>,
              },
              {
                q: 'How do I reset everything?',
                a: <p>Delete <M>storage/atlas.db</M> and restart. Demo data is re-seeded on boot. This erases uploaded datasets, runs and deployments.</p>,
              },
            ].map((f, i) => (
              <details key={i} className="group mb-2.5 rounded-2xl border border-line bg-paper-card px-4 py-3
                                          transition-colors open:border-sage-200 open:bg-sage-50/40">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3
                                    text-[14.5px] font-bold text-ink marker:content-none">
                  {f.q}
                  <span className="shrink-0 text-ink-faint transition-transform group-open:rotate-45">+</span>
                </summary>
                <div className="mt-2.5 text-[14.5px] leading-relaxed text-ink-soft">{f.a}</div>
              </details>
            ))}
          </Section>

          {/* ============ 14 GLOSSARY ============ */}
          <Section
            id="glossary" eyebrow="Chapter 14" title="Glossary"
            lead="Terms used across the platform, in plain language."
          >
            <Table
              head={['Term', 'Meaning']}
              rows={[
                ['Topic', 'One of the six learning tracks, each with lessons, a notebook and a deliverable.'],
                ['Stage', 'A single lesson inside a topic. Three per topic.'],
                ['Block', 'One piece of a lesson: text, callout, diagram, quiz, flashcards, code, image or video.'],
                ['Run', 'One execution of a notebook, with its logs, metrics and artifacts.'],
                ['Target', 'Where a run executes: platform CPU, Colab GPU or Kaggle GPU.'],
                ['Bridge', 'The helper cell ATLAS injects so a remote notebook can report back.'],
                ['Artifact', 'A file produced by a run — usually the trained model.'],
                ['Asset', 'Anything uploaded to the library: a dataset, a deck or an artifact.'],
                ['Stage (data)', 'The pipeline step a dataset belongs to: raw, cleaned, features, split or model.'],
                ['Rubric', 'The five requirements a web app must satisfy to graduate.'],
                ['Readiness score', 'Rubric result as a percentage. 80% or higher counts as ready.'],
                ['Deployment', 'A packaged Streamlit or Gradio app that ATLAS can build and launch.'],
                ['Portal', 'The catalogue where running apps are published automatically.'],
                ['XP', 'Points from completing stages. Every 200 XP is one level.'],
                ['MAPE', 'Mean absolute percentage error — the accuracy measure required for forecasting.'],
                ['Confidence score', 'How certain a classifier is about a prediction. Mandatory for classification apps.'],
              ]}
            />
          </Section>

          {/* footer */}
          <div className="border-t border-line pt-8 print:hidden">
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl
                            border border-line bg-paper-card px-5 py-4">
              <div>
                <div className="text-[15px] font-bold text-ink">Ready to start?</div>
                <div className="mt-0.5 text-[13.5px] text-ink-muted">
                  Sign in with a demo account and open Curriculum.
                </div>
              </div>
              <Link href="/login"
                className="rounded-xl bg-sage-600 px-4 py-2 text-[13.5px] font-semibold text-white
                           transition-colors hover:bg-sage-700">
                Go to sign in
              </Link>
            </div>
            <p className="mt-6 text-[12.5px] text-ink-faint">
              ATLAS — AI Internship Operating System · Manual v1.0 · every screenshot captured from
              the running application.
            </p>
          </div>
        </article>
      </div>

      {/* ---------------- lightbox ---------------- */}
      {zoom && (
        <div
          onClick={() => setZoom(null)}
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3
                     bg-ink/85 p-4 backdrop-blur-sm sm:p-8"
        >
          <button
            onClick={() => setZoom(null)}
            className="absolute right-4 top-4 rounded-xl bg-white/10 p-2 text-white
                       transition-colors hover:bg-white/20"
            aria-label="Close"
          >
            <IcX size={18} />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={zoom.src} alt={zoom.cap}
            onClick={(e) => e.stopPropagation()}
            className="max-h-[85vh] max-w-full rounded-xl border border-white/10 object-contain shadow-2xl"
          />
          <p className="max-w-[70ch] text-center text-[13px] leading-relaxed text-white/75">{zoom.cap}</p>
        </div>
      )}

      <style jsx global>{`
        .prose-manual p { margin: 0 0 14px; font-size: 15px; line-height: 1.72; color: #3E463A; max-width: 68ch; }
        .prose-manual ul { max-width: 68ch; font-size: 15px; line-height: 1.72; color: #3E463A; }
        .prose-manual ol { max-width: 68ch; font-size: 15px; line-height: 1.72; color: #3E463A; }
        .prose-manual strong { color: #12160F; font-weight: 700; }
        .prose-manual a { color: #487058; }
        @media print {
          aside, header { display: none !important; }
          .grid-canvas { background: none !important; }
          article { max-width: 100% !important; }
          figure { break-inside: avoid; page-break-inside: avoid; }
          details { open: true; }
          details > div { display: block !important; }
        }
      `}</style>
    </div>
  );
}
