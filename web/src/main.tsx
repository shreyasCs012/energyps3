import React from 'react';
import { createRoot } from 'react-dom/client';

function App() {
  return <main><h1>EnergySense Twin</h1><p>Phase 0 scaffold</p><strong>SYNTHETIC DATA — simulation-based projections</strong></main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);

