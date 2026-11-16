
import { BrowserRouter, Routes, Route, Navigate, Link } from "react-router-dom";
import LoginPage from "./pages/LoginPage";

import { AuthProvider } from "./context/AuthProvider";
import { useAuth } from "./context/useAuth";

import {
  Activity,
  ArrowUpRight,
  Database,
  Search,
  ShieldCheck,
  Workflow,
} from "lucide-react";

import { type ReactNode } from "react";

import WorkspacePage from "./pages/WorkspacePage";

const features = [
  {
    icon: Workflow,
    title: "Agentic research workflows",
    description:
      "Coordinate research tasks, retrieval, evidence assessment and analytical reasoning through intelligent workflows.",
  },
  {
    icon: Database,
    title: "Deterministic analytics",
    description:
      "Perform validated calculations on actual datasets instead of relying on unverified model-generated numbers.",
  },
  {
    icon: ShieldCheck,
    title: "Evidence-aware research",
    description:
      "Keep research traceable with source references, evidence assessment and transparent limitations.",
  },
];

function LandingPage() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top">
          <span className="brand-mark">
            <Activity size={19} />
          </span>

          <span className="brand-name">
            ASYNC
            <small>MARKET INTELLIGENCE</small>
          </span>
        </a>

        <nav className="top-navigation">
          <a href="#capabilities">Capabilities</a>
          <a href="#workflow">How it works</a>
          <a href="#about">About</a>
        </nav>

        <Link to="/signup" className="primary-button">
          Get started <ArrowUpRight size={17} />
        </Link>
      </header>

      <main id="top">
        <section className="hero-section">
          <div className="hero-content">
            <div className="eyebrow">
              <span className="status-dot" />
              AI-POWERED MARKET INTELLIGENCE
            </div>

            <h1>
              Research deeper.
              <br />
              <span>Decide with clarity.</span>
            </h1>

            <p className="hero-description">
              An intelligent research platform that connects internal
              business data, external market information and deterministic
              analytics to transform complex questions into actionable
              insights.
            </p>

            <div className="hero-actions">
              <a href="#capabilities" className="primary-button">
                Explore capabilities <ArrowUpRight size={17} />
              </a>

              <a href="#workflow" className="secondary-button">
                Discover the workflow
              </a>
            </div>

            <div className="hero-footnote">
              <span><ShieldCheck size={15} /> Evidence-aware</span>
              <span><Database size={15} /> Data-grounded</span>
              <span><Workflow size={15} /> Agentic workflows</span>
            </div>
          </div>

          <div className="hero-visual">
            <div className="visual-glow" />

            <div className="preview-card">
              <div className="preview-header">
                <div>
                  <span className="preview-label">WORKSPACE PREVIEW</span>
                  <h2>Online Retail Intelligence</h2>
                </div>

                <span className="ready-badge">DATA READY</span>
              </div>

              <div className="metric-grid">
                <div className="metric-card">
                  <span>Transaction lines</span>
                  <strong>1.04M</strong>
                  <small>Retail records</small>
                </div>

                <div className="metric-card">
                  <span>Unique products</span>
                  <strong>5,304</strong>
                  <small>Product catalog</small>
                </div>

                <div className="metric-card">
                  <span>Customers</span>
                  <strong>5,942</strong>
                  <small>Unique customers</small>
                </div>

                <div className="metric-card">
                  <span>Countries</span>
                  <strong>43</strong>
                  <small>Market coverage</small>
                </div>
              </div>

              <div className="preview-workflow">
                <div className="workflow-heading">
                  <span>Research pipeline</span>
                  <span className="live-indicator">● READY</span>
                </div>

                {[
                  "Research planning",
                  "Evidence retrieval",
                  "Quantitative analysis",
                  "Findings and interpretation",
                ].map((stage, index) => (
                  <div className="workflow-step" key={stage}>
                    <span className="workflow-number">
                      0{index + 1}
                    </span>
                    <span>{stage}</span>
                    <ShieldCheck size={15} />
                  </div>
                ))}
              </div>

              <div className="preview-footer">
                Example workspace · Online Retail dataset
              </div>
            </div>
          </div>
        </section>

        <section className="industry-section">
          <div className="section-heading">
            <div>
              <span className="eyebrow">REAL-WORLD INTELLIGENCE</span>
              <h2>Insights beyond the spreadsheet.</h2>
            </div>

            <p>
              Understand the business activity behind the numbers:
              customers, products, inventory and markets.
            </p>
          </div>

          <div className="industry-grid">
            <article className="industry-card">
              <img
                src="/images/market-analytics.jpg"
                alt="Business professional reviewing a data chart on a tablet"
                loading="lazy"
              />
              <div className="industry-overlay">
                <span>01 / ANALYTICS</span>
                <h3>Understand the numbers.</h3>
                <p>Transform business data into meaningful findings.</p>
              </div>
            </article>

            <article className="industry-card">
              <img
                src="/images/retail-behavior.jpg"
                alt="Family shopping in a supermarket"
                loading="lazy"
              />
              <div className="industry-overlay">
                <span>02 / RETAIL</span>
                <h3>Understand customer markets.</h3>
                <p>Explore retail activity and consumer behavior.</p>
              </div>
            </article>

            <article className="industry-card">
              <img
                src="/images/warehouse-operations.jpg"
                alt="Warehouse workers managing inventory"
                loading="lazy"
              />
              <div className="industry-overlay">
                <span>03 / OPERATIONS</span>
                <h3>Understand operations.</h3>
                <p>Explore inventory, products and supply chains.</p>
              </div>
            </article>
          </div>
        </section>

        <section className="capabilities-section" id="capabilities">
          <div className="section-heading">
            <div>
              <span className="eyebrow">PLATFORM CAPABILITIES</span>
              <h2>More than a chatbot.</h2>
            </div>

            <p>
              A connected research and analytics environment designed
              to move from questions to defensible conclusions.
            </p>
          </div>

          <div className="feature-grid">
            {features.map((feature) => {
              const Icon = feature.icon;

              return (
                <article className="feature-card" key={feature.title}>
                  <div className="feature-icon">
                    <Icon size={22} />
                  </div>

                  <h3>{feature.title}</h3>
                  <p>{feature.description}</p>

                  <ArrowUpRight className="feature-arrow" size={18} />
                </article>
              );
            })}
          </div>
        </section>

        <section className="workflow-section" id="workflow">
          <div className="workflow-copy">
            <span className="eyebrow">HOW IT WORKS</span>
            <h2>One question. A coordinated research process.</h2>
            <p>
              Submit a research question, follow execution in real time
              and explore the generated report when the agents finish.
            </p>
          </div>

          <div className="workflow-callout">
            <Search size={25} />
            <div>
              <strong>Research workspace</strong>
              <span>
                The next milestone is connecting this interface
                to your working FastAPI backend.
              </span>
            </div>
          </div>
        </section>
        <section className="final-cta">
          <div>
            <span className="eyebrow">READY TO BEGIN?</span>
            <h2>
              Your next research question
              <br />
              deserves a better answer.
            </h2>
            <p>
              Bring together data, research and intelligent analysis
              in one connected workspace.
            </p>
          </div>

          <Link to="/login" className="primary-button">
            Get started <ArrowUpRight size={17} />
          </Link>
        </section>
      </main>

      <footer className="site-footer" id="about">
        <span>ASYNC MARKET INTELLIGENCE</span>
        <span>Research. Analyze. Understand.</span>
      </footer>
    </div>
  );
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading, authError } = useAuth();

  if (loading) {
    return <div className="container py-5">Restoring your session...</div>;
  }

  if (authError) {
    return (
      <div className="container py-5" role="alert">
        Unable to verify your session: {authError}
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

function GuestRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="container py-5">Loading...</div>;
  }

  if (user) {
    return <Navigate to="/workspace" replace />;
  }

  return children;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />

          <Route
            path="/login"
            element={
              <GuestRoute>
                <LoginPage />
              </GuestRoute>
            }
          />

          <Route
            path="/signup"
            element={
              <GuestRoute>
                <LoginPage />
              </GuestRoute>
            }
          />

          <Route
            path="/workspace"
            element={
              <ProtectedRoute>
                <WorkspacePage />
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;