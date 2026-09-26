import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  LogOut,
  Target,
  User as UserIcon,
  Sparkles,
  Activity,
  Brain,
  Bot,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { cn } from "../../utils/cn";

export const AppShell: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const navItems = [
    {
      to: "/dashboard",
      label: "Dashboard",
      icon: <LayoutDashboard className="w-4 h-4" />,
    },
    { to: "/goals", label: "Goals", icon: <Target className="w-4 h-4" /> },
    {
      to: "/assistant",
      label: "Agent Chat",
      icon: <Bot className="w-4 h-4" />,
    },
    {
      to: "/activity",
      label: "Agent Activity",
      icon: <Activity className="w-4 h-4" />,
    },
    {
      to: "/memories",
      label: "Memory & Context",
      icon: <Brain className="w-4 h-4" />,
    },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-emerald-500/30 selection:text-emerald-300">
      {/* Top Navigation Bar */}
      <header className="border-b border-slate-800 bg-slate-900/75 backdrop-blur-md sticky top-0 z-40 transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          {/* Logo & Navigation */}
          <div className="flex items-center space-x-8">
            <div
              className="flex items-center space-x-3 cursor-pointer"
              onClick={() => navigate("/dashboard")}
            >
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 p-0.5 shadow-lg shadow-emerald-500/20">
                <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
                  <Sparkles className="w-5 h-5 text-emerald-400" />
                </div>
              </div>
              <div className="flex items-baseline space-x-1.5">
                <span className="font-bold text-lg tracking-tight text-white">
                  LifeThread
                </span>
                <span className="text-[10px] font-mono tracking-wider uppercase text-emerald-400 font-semibold bg-emerald-950/80 px-1.5 py-0.5 rounded border border-emerald-800/60">
                  AI Agent
                </span>
              </div>
            </div>

            {/* Desktop Navigation Links */}
            <nav className="hidden md:flex items-center space-x-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center space-x-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-all duration-150",
                      isActive
                        ? "bg-slate-800 text-emerald-400 shadow-sm border border-slate-700/60"
                        : "text-slate-400 hover:text-slate-200 hover:bg-slate-850 hover:bg-slate-800/40",
                    )
                  }
                >
                  {item.icon}
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Right Action Bar */}
          <div className="flex items-center space-x-4">
            {/* User Profile Badge */}
            <div className="flex items-center space-x-2.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs">
              <div className="w-6 h-6 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                <UserIcon className="w-3.5 h-3.5" />
              </div>
              <div className="hidden sm:block text-left">
                <div className="font-medium text-slate-200 truncate max-w-[140px]">
                  {user?.display_name || user?.email || "User"}
                </div>
              </div>
            </div>

            {/* Logout Button */}
            <button
              onClick={handleLogout}
              className="p-2 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 transition-all duration-150"
              title="Sign Out"
              aria-label="Sign Out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Mobile Navigation Bar */}
        <div className="md:hidden border-t border-slate-800/80 px-4 py-2 flex items-center space-x-2 bg-slate-900/90">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "flex-1 flex items-center justify-center space-x-2 py-2 rounded-lg text-xs font-medium transition-colors",
                  isActive
                    ? "bg-slate-800 text-emerald-400 border border-slate-700/60"
                    : "text-slate-400 hover:text-slate-200",
                )
              }
            >
              {item.icon}
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>
      </header>

      {/* Main Content Viewport */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>

      {/* Floating Agent Chat Launcher (hidden on chat page itself) */}
      {!window.location.pathname.includes("/assistant") && (
        <div className="fixed bottom-6 right-6 z-50">
          <button
            onClick={() => navigate("/assistant")}
            className="flex items-center space-x-2 px-4 py-2.5 rounded-full bg-gradient-to-r from-emerald-600 to-teal-500 hover:from-emerald-500 hover:to-teal-400 text-white font-semibold text-xs shadow-xl shadow-emerald-500/25 border border-emerald-400/40 hover:scale-105 active:scale-95 transition-all"
            title="Open Conversational Agent Chat"
          >
            <Bot className="w-4 h-4" />
            <span>Ask Agent</span>
          </button>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500 font-mono">
        LifeThread Autonomous AI Agent Platform • Production Enterprise UX
      </footer>
    </div>
  );
};
