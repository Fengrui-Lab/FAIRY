import React from 'react';
import ReactDOM from 'react-dom/client';
const App = React.lazy(() => window.location.pathname.replace(/\/$/, '') === '/showcase'
  ? import('./showcase/Showcase')
  : import('./Workbench'));

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><React.Suspense fallback={<div style={{ padding: 32 }}>Loading FAIRY…</div>}><App /></React.Suspense></React.StrictMode>);
