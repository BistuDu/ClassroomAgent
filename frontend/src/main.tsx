import { createRoot } from 'react-dom/client';
import { App } from './App';
import { Preview } from './Preview';
import 'katex/dist/katex.min.css';
import 'streamdown/styles.css';
import './style.css';
import './workbench.css';
import './classroom.css';
createRoot(document.getElementById('root')!).render(location.pathname==='/preview'?<Preview/>:<App/>);
