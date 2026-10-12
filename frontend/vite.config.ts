import { defineConfig, loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
const projectRoot = fileURLToPath(new URL('../', import.meta.url));

export default defineConfig(({ mode }) => {
 const env = loadEnv(mode, projectRoot, 'OPENMAIC_');
 const backendOrigin = env.OPENMAIC_ORIGIN || `http://127.0.0.1:${env.OPENMAIC_PORT || '8000'}`;
 return {
  root:fileURLToPath(new URL('.',import.meta.url)),
  envDir:projectRoot,
  esbuild:{jsx:'automatic'},
  server:{host:'127.0.0.1',proxy:{'/api':backendOrigin}},
  build:{outDir:'dist',emptyOutDir:true,rollupOptions:{output:{manualChunks:{react:['react','react-dom'],math:['katex']}}}},
 };
});
