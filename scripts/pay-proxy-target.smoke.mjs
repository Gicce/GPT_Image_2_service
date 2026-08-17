#!/usr/bin/env node
/**
 * Smoke test: admin vite proxy target resolution
 *
 * Verifies that the /api proxy target resolves to the backend's real port
 * (8000, per backend/Dockerfile + docker-compose.yml + nginx upstream),
 * and that API_PROXY_TARGET env var overrides it.
 *
 * Pure static audit — no dev server, no backend required.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const configPath = join(root, 'frontend', 'vite.config.js');
const source = readFileSync(configPath, 'utf8');

let failures = 0;
function check(name, cond) {
  if (cond) {
    console.log(`  PASS  ${name}`);
  } else {
    console.error(`  FAIL  ${name}`);
    failures++;
  }
}

console.log(`[pay-proxy-target] auditing ${configPath}`);

// Extract the default target expression
const defaultMatch = source.match(/process\.env\.API_PROXY_TARGET\s*\|\|\s*['"]([^'"]+)['"]/);
check('reads API_PROXY_TARGET env with fallback default', !!defaultMatch);
check('default target is backend port 8000 (matches Dockerfile/docker-compose/nginx)',
  !!defaultMatch && defaultMatch[1].includes(':8000'));

// The old ghost port must be gone — no service ever listened on 5001
check('ghost port 5001 no longer referenced', !source.includes('5001'));

// Proxy rule still routes /api through the resolved target
const proxyMatch = source.match(/['"]\/api['"]\s*:\s*\{\s*[\s\S]*?target:\s*proxyTarget/);
check('/api proxy rule uses resolved proxyTarget', !!proxyMatch);

// Simulate env override resolution
function resolveTarget(env) {
  const m = source.match(/process\.env\.API_PROXY_TARGET\s*\|\|\s*['"]([^'"]+)['"]/);
  return env.API_PROXY_TARGET || (m ? m[1] : undefined);
}
check('env defined → uses env value',
  resolveTarget({ API_PROXY_TARGET: 'http://localhost:9000' }) === 'http://localhost:9000');
check('env undefined → uses default 8000',
  resolveTarget({}) === 'http://127.0.0.1:8000');

if (failures > 0) {
  console.error(`[pay-proxy-target] FAILED (${failures} check(s))`);
  process.exit(1);
}
console.log('[pay-proxy-target] ALL CHECKS PASSED');
