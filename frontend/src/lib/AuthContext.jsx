import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { login as apiLogin, whoami, getToken, setToken, UnauthorizedError } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // { user_id, role, full_name, permissions }
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadUser = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await whoami();
      setUser(me);
    } catch (err) {
      if (err instanceof UnauthorizedError) setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const login = useCallback(async (badgeNumber, password) => {
    setError(null);
    try {
      const data = await apiLogin(badgeNumber, password);
      setToken(data.access_token);
      const me = await whoami();
      setUser(me);
      return true;
    } catch (err) {
      setError(err.message || "Login failed");
      return false;
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, error, login, logout, reload: loadUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
