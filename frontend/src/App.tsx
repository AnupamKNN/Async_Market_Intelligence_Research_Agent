
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import { AuthProvider } from "./context/AuthProvider";
import { useAuth } from "./context/useAuth";
import { lazy, Suspense, type ReactNode } from "react";

const LandingPage = lazy(() => import("./pages/LandingPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const WorkspacePage = lazy(() => import("./pages/WorkspacePage"));

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading, authError } = useAuth();

  if (loading) {
    return (
      <div className="container py-5">
        Restoring your session...
      </div>
    );
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
    return (
      <div className="container py-5">
        Loading...
      </div>
    );
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
        <Suspense
          fallback={
            <div className="app-loading" role="status">
              Loading ASYNC...
            </div>
          }
        >
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

            <Route
              path="*"
              element={<Navigate to="/" replace />}
            />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
