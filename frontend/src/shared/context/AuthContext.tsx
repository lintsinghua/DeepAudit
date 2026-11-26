import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { apiClient } from '../api/serverClient';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_superuser: boolean;
  avatar_url?: string;
}

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (token: string, rememberMe?: boolean) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
      // Check both localStorage (remember me) and sessionStorage (session only)
      const token = localStorage.getItem('access_token') || sessionStorage.getItem('access_token');
      if (token) {
        try {
          const response = await apiClient.get('/users/me');
          setUser(response.data);
          setIsAuthenticated(true);
        } catch (error) {
          console.error('Auth check failed', error);
          logout();
        }
      }
      setIsLoading(false);
    };

    checkAuth();
  }, []);

  const login = async (token: string, rememberMe: boolean = false) => {
    // Clear any existing tokens first
    localStorage.removeItem('access_token');
    sessionStorage.removeItem('access_token');

    // Store token based on rememberMe preference
    if (rememberMe) {
      localStorage.setItem('access_token', token);
    } else {
      sessionStorage.setItem('access_token', token);
    }

    try {
        const response = await apiClient.get('/users/me');
        setUser(response.data);
        setIsAuthenticated(true);
    } catch (e) {
        console.error("Login fetch user failed", e);
    }
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    sessionStorage.removeItem('access_token');
    setUser(null);
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ user, isAuthenticated, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

