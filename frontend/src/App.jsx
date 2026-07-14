import CIAPDashboard from "./CIAP_Dashboard.jsx";
import LoginScreen from "./LoginScreen.jsx";
import { AuthProvider, useAuth } from "./lib/AuthContext.jsx";

function Gate() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="w-full min-h-screen bg-[#0B0F14] flex items-center justify-center">
        <div className="text-slate-500 text-sm font-mono">initializing…</div>
      </div>
    );
  }

  return user ? <CIAPDashboard /> : <LoginScreen />;
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
