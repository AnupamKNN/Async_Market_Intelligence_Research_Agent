import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  BrainCircuit,
  Check,
  ChevronRight,
  Database,
  Globe2,
  Layers3,
  Menu,
  MessageSquareText,
  Network,
  ShieldCheck,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";

import "./LandingPage.css";

const capabilities = [
  {
    icon: BrainCircuit,
    number: "01",
    title: "Agentic research",
    description:
      "Turn complex questions into coordinated research workflows that plan, retrieve, analyze and synthesize evidence.",
    tag: "LANGGRAPH ORCHESTRATION",
  },
  {
    icon: BarChart3,
    number: "02",
    title: "Retail intelligence",
    description:
      "Explore revenue patterns, product performance, customer behavior and changes across retail markets.",
    tag: "BUSINESS ANALYTICS",
  },
  {
    icon: MessageSquareText,
    number: "03",
    title: "Sentiment intelligence",
    description:
      "Interpret customer feedback and discover the sentiment and themes behind unstructured text.",
    tag: "NLP & SENTIMENT",
  },
  {
    icon: Globe2,
    number: "04",
    title: "Economic research",
    description:
      "Bring economic indicators and external market information into a broader research perspective.",
    tag: "MARKET CONTEXT",
  },
  {
    icon: ShieldCheck,
    number: "05",
    title: "Evidence-led analysis",
    description:
      "Keep quantitative findings grounded in data, validated calculations, source references and clear limitations.",
    tag: "TRACEABLE FINDINGS",
  },
  {
    icon: Network,
    number: "06",
    title: "Connected intelligence",
    description:
      "Bring internal analytics and external research together in one coordinated research experience.",
    tag: "INTEGRATED WORKFLOWS",
  },
];

const researchStages = [
  {
    number: "01",
    title: "Ask",
    description:
      "Describe the business question, market trend or research problem you want to investigate.",
    icon: MessageSquareText,
  },
  {
    number: "02",
    title: "Coordinate",
    description:
      "The research workflow organizes retrieval, analysis and supporting evidence.",
    icon: Workflow,
  },
  {
    number: "03",
    title: "Validate",
    description:
      "Quantitative results are calculated against available data and checked for consistency.",
    icon: ShieldCheck,
  },
  {
    number: "04",
    title: "Understand",
    description:
      "Explore a structured report with findings, context and supporting information.",
    icon: Sparkles,
  },
];

const chartBars = [34, 48, 40, 59, 52, 72, 62, 86, 68, 93, 77, 100];

const CURRENT_YEAR = new Date().getFullYear();

function Brand() {
  return (
    <Link className="lp-brand" to="/" aria-label="ASYNC Market Intelligence home">
      <span className="lp-brand-mark">
        <Activity size={21} strokeWidth={2.1} />
      </span>
      <span className="lp-brand-copy">
        <strong>ASYNC</strong>
        <small>MARKET INTELLIGENCE</small>
      </span>
    </Link>
  );
}

function WorkspacePreview() {
  return (
    <div className="lp-preview-wrap" aria-label="Illustrative product interface preview">
      <div className="lp-preview-glow" />

      <div className="lp-preview-window">
        <div className="lp-window-topbar">
          <div className="lp-window-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <span className="lp-window-title">ASYNC / RESEARCH WORKSPACE</span>
          <span className="lp-window-status">
            <i />
            LIVE VIEW
          </span>
        </div>

        <div className="lp-window-body">
          <aside className="lp-window-sidebar" aria-hidden="true">
            <div className="lp-window-logo">
              <Activity size={17} />
            </div>
            <span className="active"><Layers3 size={15} /></span>
            <span><BarChart3 size={15} /></span>
            <span><Globe2 size={15} /></span>
            <span><Database size={15} /></span>
          </aside>

          <div className="lp-window-content">
            <div className="lp-preview-heading">
              <div>
                <span className="lp-preview-overline">INTELLIGENCE OVERVIEW</span>
                <h3>Research at a glance</h3>
              </div>
              <span className="lp-preview-filter">Illustrative preview</span>
            </div>

            <div className="lp-preview-metrics">
              <div className="lp-preview-metric">
                <span>Retail analytics</span>
                <strong><BarChart3 size={16} /> Performance</strong>
                <small>Revenue & products</small>
              </div>
              <div className="lp-preview-metric">
                <span>Customer signals</span>
                <strong><MessageSquareText size={16} /> Sentiment</strong>
                <small>Feedback & themes</small>
              </div>
              <div className="lp-preview-metric">
                <span>Market context</span>
                <strong><Globe2 size={16} /> Research</strong>
                <small>External indicators</small>
              </div>
            </div>

            <div className="lp-preview-lower">
              <div className="lp-chart-card">
                <div className="lp-chart-heading">
                  <div>
                    <span>ANALYTICS PREVIEW</span>
                    <strong>Trend exploration</strong>
                  </div>
                  <span className="lp-chart-menu">•••</span>
                </div>

                <div className="lp-chart">
                  <div className="lp-chart-y-axis" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="lp-chart-bars" aria-hidden="true">
                    {chartBars.map((height, index) => (
                      <span
                        className={index === 9 ? "highlight" : ""}
                        key={`${height}-${index}`}
                        style={{ height: `${height}%` }}
                      />
                    ))}
                  </div>
                </div>
                <div className="lp-chart-labels">
                  <span>PERIOD 01</span>
                  <span>PERIOD 06</span>
                  <span>PERIOD 12</span>
                </div>
              </div>

              <div className="lp-agent-card">
                <div className="lp-agent-card-heading">
                  <span className="lp-agent-icon"><Sparkles size={15} /></span>
                  <div>
                    <strong>Research workflow</strong>
                    <small>Coordinated execution</small>
                  </div>
                </div>

                {["Planning", "Evidence retrieval", "Analysis", "Synthesis"].map(
                  (stage, index) => (
                    <div className="lp-agent-stage" key={stage}>
                      <span className="lp-agent-check"><Check size={11} /></span>
                      <span>{stage}</span>
                      <small>0{index + 1}</small>
                    </div>
                  ),
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="lp-floating-note lp-floating-note-top">
        <span className="lp-floating-icon"><ShieldCheck size={16} /></span>
        <span>
          <strong>Evidence-aware</strong>
          <small>Findings grounded in data</small>
        </span>
      </div>

      <div className="lp-floating-note lp-floating-note-bottom">
        <span className="lp-floating-icon"><Workflow size={16} /></span>
        <span>
          <strong>Agentic workflows</strong>
          <small>Research coordinated in one place</small>
        </span>
      </div>
    </div>
  );
}

export default function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  function closeMobileMenu() {
    setMobileMenuOpen(false);
  }

  return (
    <div className="lp-page">
      <header className="lp-header">
        <div className="lp-header-inner">
          <Brand />

          <nav
            className={`lp-nav ${mobileMenuOpen ? "is-open" : ""}`}
            aria-label="Main navigation"
          >
            <a href="#platform" onClick={closeMobileMenu}>Platform</a>
            <a href="#capabilities" onClick={closeMobileMenu}>Capabilities</a>
            <a href="#workflow" onClick={closeMobileMenu}>How it works</a>
            <a href="#about" onClick={closeMobileMenu}>About</a>

            <div className="lp-mobile-actions">
              <Link to="/login" className="lp-mobile-login" onClick={closeMobileMenu}>
                Log in
              </Link>
              <Link to="/signup" className="lp-button lp-button-primary" onClick={closeMobileMenu}>
                Get started <ArrowUpRight size={16} />
              </Link>
            </div>
          </nav>

          <div className="lp-header-actions">
            <Link to="/login" className="lp-login-link">Log in</Link>
            <Link to="/signup" className="lp-button lp-button-primary">
              Get started <ArrowUpRight size={16} />
            </Link>
          </div>

          <button
            type="button"
            className="lp-menu-toggle"
            aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
            aria-expanded={mobileMenuOpen}
            onClick={() => setMobileMenuOpen((open) => !open)}
          >
            {mobileMenuOpen ? <X size={21} /> : <Menu size={21} />}
          </button>
        </div>
      </header>

      <main>
        <section className="lp-hero" id="platform">
          <div className="lp-hero-backdrop" />
          <div className="lp-hero-grid" />

          <div className="lp-hero-inner">
            <div className="lp-hero-copy">
              <div className="lp-eyebrow">
                <span className="lp-eyebrow-pulse" />
                INTELLIGENCE FOR A COMPLEX MARKET
              </div>

              <h1>
                See the market.
                <br />
                Understand the <span>signals.</span>
              </h1>

              <p className="lp-hero-description">
                Bring business data, market research and intelligent analytics
                together. Ask better questions, investigate the signals and
                turn information into meaningful insight.
              </p>

              <div className="lp-hero-actions">
                <Link to="/signup" className="lp-button lp-button-primary lp-button-large">
                  Explore your workspace <ArrowUpRight size={18} />
                </Link>
                <a href="#capabilities" className="lp-text-link">
                  Discover the platform <ArrowRight size={17} />
                </a>
              </div>

              <div className="lp-hero-assurances">
                <span><ShieldCheck size={15} /> Evidence-aware</span>
                <span><Database size={15} /> Data-grounded</span>
                <span><Workflow size={15} /> Agentic research</span>
              </div>
            </div>

            <div className="lp-hero-product">
              <WorkspacePreview />
            </div>
          </div>

          <div className="lp-hero-bottom">
            <span>RESEARCH</span>
            <i />
            <span>ANALYTICS</span>
            <i />
            <span>INTELLIGENCE</span>
            <i />
            <span>DECISION SUPPORT</span>
          </div>
        </section>

        <section className="lp-intro-strip" aria-label="Platform positioning">
          <div className="lp-intro-strip-inner">
            <div>
              <span className="lp-strip-kicker">ONE CONNECTED PLATFORM</span>
              <strong>From scattered information to structured understanding.</strong>
            </div>
            <p>
              An integrated environment for research, quantitative analysis
              and market intelligence.
            </p>
          </div>
        </section>

        <section className="lp-capabilities lp-section" id="capabilities">
          <div className="lp-section-heading">
            <div>
              <span className="lp-eyebrow lp-eyebrow-dark">THE PLATFORM</span>
              <h2>
                More context.
                <br />
                <span>More meaningful insight.</span>
              </h2>
            </div>
            <p>
              Explore business performance, customer signals and market
              context through research workflows designed to connect the
              pieces that matter.
            </p>
          </div>

          <div className="lp-capability-grid">
            {capabilities.map((capability) => {
              const Icon = capability.icon;

              return (
                <article className="lp-capability-card" key={capability.number}>
                  <div className="lp-capability-card-top">
                    <span className="lp-capability-icon"><Icon size={21} /></span>
                    <span className="lp-capability-number">{capability.number}</span>
                  </div>

                  <h3>{capability.title}</h3>
                  <p>{capability.description}</p>

                  <div className="lp-capability-card-footer">
                    <span>{capability.tag}</span>
                    <ChevronRight size={16} />
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section className="lp-feature-story">
          <div className="lp-feature-story-inner">
            <div className="lp-feature-story-image">
              <img
                src="/images/retail-behavior.jpg"
                alt="Retail environment representing customer and market activity"
                loading="lazy"
              />
              <div className="lp-image-label">
                <span><Activity size={15} /></span>
                CONNECT THE SIGNALS
              </div>
            </div>

            <div className="lp-feature-story-copy">
              <span className="lp-eyebrow">BEYOND INDIVIDUAL DATA POINTS</span>
              <h2>
                The bigger picture
                <br />
                <span>is in the connections.</span>
              </h2>
              <p>
                Business performance does not exist in isolation. Product
                movements, customer feedback and changing market conditions
                can each add context to the same question.
              </p>

              <div className="lp-story-points">
                <div>
                  <span><Check size={14} /></span>
                  <p><strong>Connect information</strong> across internal data and external research.</p>
                </div>
                <div>
                  <span><Check size={14} /></span>
                  <p><strong>Investigate patterns</strong> with analytics and coordinated workflows.</p>
                </div>
                <div>
                  <span><Check size={14} /></span>
                  <p><strong>Understand the evidence</strong> behind the findings and limitations.</p>
                </div>
              </div>

              <Link to="/signup" className="lp-inline-link">
                Start exploring <ArrowUpRight size={17} />
              </Link>
            </div>
          </div>
        </section>

        <section className="lp-workflow lp-section" id="workflow">
          <div className="lp-section-heading lp-workflow-heading">
            <div>
              <span className="lp-eyebrow lp-eyebrow-dark">A COORDINATED PROCESS</span>
              <h2>
                One question.
                <br />
                <span>A complete research journey.</span>
              </h2>
            </div>
            <p>
              Follow the journey from the initial question to a structured
              report, with visibility into the work taking place along the way.
            </p>
          </div>

          <div className="lp-workflow-grid">
            {researchStages.map((stage) => {
              const Icon = stage.icon;

              return (
                <article className="lp-workflow-step" key={stage.number}>
                  <div className="lp-workflow-step-top">
                    <span>{stage.number}</span>
                    <Icon size={21} />
                  </div>
                  <h3>{stage.title}</h3>
                  <p>{stage.description}</p>
                </article>
              );
            })}
          </div>

          <div className="lp-workflow-caption">
            <span className="lp-caption-line" />
            <span>RESEARCH WITH VISIBILITY. ANALYSIS WITH CONTEXT.</span>
            <span className="lp-caption-line" />
          </div>
        </section>

        <section className="lp-evidence">
          <div className="lp-evidence-inner">
            <div className="lp-evidence-copy">
              <span className="lp-eyebrow">BUILT AROUND TRUST</span>
              <h2>
                Intelligent research.
                <br />
                <span>Grounded conclusions.</span>
              </h2>
              <p>
                AI can help coordinate research and interpret information.
                Quantitative findings still need to be calculated, validated
                and presented with their context.
              </p>
              <Link to="/signup" className="lp-button lp-button-light">
                Explore ASYNC <ArrowUpRight size={17} />
              </Link>
            </div>

            <div className="lp-evidence-visual">
              <div className="lp-evidence-orbit lp-orbit-one" />
              <div className="lp-evidence-orbit lp-orbit-two" />
              <div className="lp-evidence-core">
                <ShieldCheck size={34} />
                <span>Evidence</span>
                <small>BEFORE CONCLUSIONS</small>
              </div>
              <span className="lp-evidence-node lp-node-one"><Database size={17} /></span>
              <span className="lp-evidence-node lp-node-two"><Workflow size={17} /></span>
              <span className="lp-evidence-node lp-node-three"><BarChart3 size={17} /></span>
            </div>
          </div>
        </section>

        <section className="lp-about lp-section" id="about">
          <div className="lp-about-top">
            <div>
              <span className="lp-eyebrow lp-eyebrow-dark">ASYNC MARKET INTELLIGENCE</span>
              <h2>
                Make the next
                <br />
                question count.
              </h2>
            </div>
            <div className="lp-about-copy">
              <p>
                A research and analytics environment for people who want to
                go beyond surface-level answers and understand what the data
                and evidence are really saying.
              </p>
              <Link to="/signup" className="lp-button lp-button-primary lp-button-large">
                Get started <ArrowUpRight size={18} />
              </Link>
            </div>
          </div>

          <div className="lp-about-image-grid">
            <div className="lp-about-image lp-about-image-wide">
              <img
                src="/images/market-analytics.jpg"
                alt="Business analytics and market research"
                loading="lazy"
              />
              <span>BUSINESS ANALYTICS</span>
            </div>
            <div className="lp-about-image">
              <img
                src="/images/warehouse-operations.jpg"
                alt="Warehouse and operations environment"
                loading="lazy"
              />
              <span>OPERATIONAL CONTEXT</span>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-footer-main">
          <Brand />
          <p>Research. Analyze. Understand.</p>
          <Link to="/login" className="lp-footer-login">
            Sign in to your workspace <ArrowUpRight size={15} />
          </Link>
        </div>
        <div className="lp-footer-bottom">
          <span>© {CURRENT_YEAR} ASYNC Market Intelligence</span>
          <span>Intelligence for a complex market.</span>
          <a href="#top">Back to top ↑</a>
        </div>
      </footer>
    </div>
  );
}
