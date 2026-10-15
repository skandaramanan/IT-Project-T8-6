// The locally served reviewer UI; data and attribution belong to the backend.
import { createRoot } from 'react-dom/client';
import '@fontsource/source-sans-3/400.css';
import '@fontsource/source-sans-3/600.css';
import '@fontsource/source-sans-3/700.css';
import App from './App';
import './style.css';

createRoot(document.getElementById('root')!).render(<App />);
