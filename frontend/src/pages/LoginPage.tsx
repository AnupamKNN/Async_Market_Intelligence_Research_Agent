import { useState, type FormEvent } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  Eye,
  EyeOff,
  ShieldCheck,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { useNavigate } from "react-router-dom";

import { useAuth } from "../context/useAuth";

function LoginPage() {
  const { pathname } = useLocation();
  const isSignup = pathname === "/signup";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const { login, register } = useAuth();
  const navigate = useNavigate();
  
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
  event.preventDefault();

  setError("");
  setNotice("");

  if (isSignup && password !== confirmPassword) {
    setError("Your passwords do not match.");
    return;
  }

  if (password.length < 8) {
    setError("Password must contain at least 8 characters.");
    return;
  }

  setIsSubmitting(true);

  try {
    if (isSignup) {
      await register(email.trim(), password);
    } else {
      await login(email.trim(), password);
    }

    navigate("/workspace", { replace: true });
  } catch (error) {
    setError(
      error instanceof Error
        ? error.message
        : "Authentication failed. Please try again.",
    );
  } finally {
    setIsSubmitting(false);
  }
}

  function handleGoogleAuth() {
    setError("");
    setNotice(
      "Google authentication will be enabled after backend OAuth integration."
    );
  }

  return (
    <main className="login-shell">
      <section className="login-left">
        <Link to="/" className="login-brand">
          <span className="brand-mark">
            <Activity size={19} />
          </span>

          <span className="brand-name">
            ASYNC
            <small>MARKET INTELLIGENCE</small>
          </span>
        </Link>

        <div className="login-content">
          <Link to="/" className="back-link">
            <ArrowLeft size={15} />
            Back to home
          </Link>

          <span className="eyebrow">
            {isSignup ? "CREATE YOUR WORKSPACE" : "YOUR RESEARCH WORKSPACE"}
          </span>

          <h1>
            {isSignup ? (
              <>
                Create your
                <br />
                <span>account.</span>
              </>
            ) : (
              <>
                Welcome
                <br />
                <span>back.</span>
              </>
            )}
          </h1>

          <p className="login-description">
            {isSignup
              ? "Create your account to connect business data, coordinate intelligent research and discover actionable market insights."
              : "Sign in to continue your market research, explore business intelligence and access your previous conversations."}
          </p>

          <button
            type="button"
            className="google-login-button"
            onClick={handleGoogleAuth}
          >
            <span className="google-g">G</span>
            {isSignup ? "Sign up with Google" : "Continue with Google"}
            <ArrowUpRight size={16} />
          </button>

          <div className="auth-divider">
            <span />
            <small>OR CONTINUE WITH EMAIL</small>
            <span />
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-field">
              <label htmlFor="email">Email address</label>
              <input
                id="email"
                name="email"
                type="email"
                placeholder="you@example.com"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>

            <div className="auth-field">
              <label htmlFor="password">Password</label>

              <div className="password-input-wrapper">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter your password"
                  autoComplete={
                    isSignup ? "new-password" : "current-password"
                  }
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  minLength={8}
                  required
                />

                <button
                  type="button"
                  className="password-toggle"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((value) => !value)}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </div>

            {isSignup && (
              <div className="auth-field">
                <label htmlFor="confirmPassword">Confirm password</label>

                <div className="password-input-wrapper">
                  <input
                    id="confirmPassword"
                    name="confirmPassword"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder="Re-enter your password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) =>
                      setConfirmPassword(event.target.value)
                    }
                    minLength={8}
                    required
                  />

                  <button
                    type="button"
                    className="password-toggle"
                    aria-label={
                      showConfirmPassword
                        ? "Hide confirm password"
                        : "Show confirm password"
                    }
                    onClick={() =>
                      setShowConfirmPassword((value) => !value)
                    }
                  >
                    {showConfirmPassword ? (
                      <EyeOff size={17} />
                    ) : (
                      <Eye size={17} />
                    )}
                  </button>
                </div>
              </div>
            )}

            {isSignup && (
              <p className="password-hint">
                Use at least 8 characters for your password.
              </p>
            )}

            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}

            {notice && (
              <p className="login-notice" role="status">
                {notice}
              </p>
            )}

            <button
                type="submit"
                className="auth-submit-button"
                disabled={isSubmitting}
                >
                {isSubmitting
                    ? "Please wait..."
                    : isSignup
                    ? "Create account"
                    : "Sign in"}

                {!isSubmitting && <ArrowUpRight size={16} />}
                </button>
          </form>

          <p className="auth-switch">
            {isSignup
              ? "Already have an account?"
              : "New to Async Market Intelligence?"}

            {" "}

            <Link to={isSignup ? "/login" : "/signup"}>
              {isSignup ? "Sign in" : "Create an account"}
            </Link>
          </p>

          <div className="login-security">
            <ShieldCheck size={16} />
            <span>Your research workspace is private and secure.</span>
          </div>
        </div>

        <footer className="login-footer">
          © 2026 Async Market Intelligence
        </footer>
      </section>

      <section className="login-right">
        <div className="login-image" />

        <div className="login-image-content">
          <span className="eyebrow">
            INTELLIGENCE. WITHOUT THE NOISE.
          </span>

          <h2>
            Better questions.
            <br />
            <span>Better decisions.</span>
          </h2>

          <p>
            Connect your data, coordinate intelligent research
            and uncover insights with evidence you can examine.
          </p>

          <div className="login-image-caption">
            <span className="status-dot" />
            Agentic research and analytics workspace
          </div>
        </div>
      </section>
    </main>
  );
}

export default LoginPage;