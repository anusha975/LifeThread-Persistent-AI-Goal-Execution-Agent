import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Compass, Home } from 'lucide-react';
import { Button } from '../components/ui/Button';

export const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
      <div className="max-w-md w-full rounded-2xl bg-slate-900 border border-slate-800 p-8 text-center space-y-5 shadow-2xl">
        <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center mx-auto text-emerald-400">
          <Compass className="w-8 h-8" />
        </div>
        <div>
          <h1 className="text-4xl font-extrabold text-white font-mono">404</h1>
          <h2 className="text-lg font-semibold text-slate-200 mt-1">Page Not Found</h2>
          <p className="text-xs text-slate-400 mt-2 leading-relaxed">
            The requested resource or route does not exist within the LifeThread agent platform.
          </p>
        </div>
        <div className="pt-2">
          <Button
            onClick={() => navigate('/dashboard')}
            leftIcon={<Home className="w-4 h-4" />}
          >
            Return to Dashboard
          </Button>
        </div>
      </div>
    </div>
  );
};
