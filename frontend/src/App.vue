<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { darkTheme } from 'naive-ui'

const themeOverrides = {
  common: {
    primaryColor: '#00d4aa',
    primaryColorHover: '#00e8bb',
    primaryColorPressed: '#00b892',
    primaryColorSuppl: '#00d4aa',
    fontFamily: '"DM Sans", sans-serif',
    fontFamilyMono: '"Space Mono", monospace',
    borderRadius: '8px',
    borderRadiusSmall: '6px',
  },
  Card: {
    borderRadius: '10px',
    color: '#1e1e2e',
    borderColor: '#2a2a3e',
  },
  Button: {
    borderRadiusMedium: '8px',
    borderRadiusSmall: '6px',
  },
  Input: {
    borderRadius: '8px',
    color: '#1e1e2e',
    borderColor: '#2a2a3e',
    borderHover: '#00d4aa',
    borderFocus: '#00d4aa',
  },
  DataTable: {
    borderRadius: '10px',
    thColor: '#1a1a2a',
    tdColor: '#1e1e2e',
    borderColor: '#2a2a3e',
  },
  Menu: {
    borderRadius: '8px',
    itemColorActive: '#00d4aa1a',
    itemColorActiveHover: '#00d4aa2a',
    itemTextColorActive: '#00d4aa',
    itemTextColorActiveHover: '#00d4aa',
    itemIconColorActive: '#00d4aa',
    itemIconColorActiveHover: '#00d4aa',
  },
  Tag: {
    borderRadius: '6px',
  },
}
</script>

<style>
:root {
  --cy-bg: #16161e;
  --cy-bg-elevated: #1e1e2e;
  --cy-bg-surface: #262636;
  --cy-border: #2a2a3e;
  --cy-border-light: #363650;
  --cy-accent: #00d4aa;
  --cy-accent-glow: #00d4aa33;
  --cy-accent-soft: #00d4aa1a;
  --cy-text: #e4e4ef;
  --cy-text-muted: #8888a0;
  --cy-text-dim: #5c5c72;
  --cy-danger: #ff4466;
  --cy-warning: #ffaa33;
  --cy-success: #00d4aa;
  --cy-font: 'DM Sans', sans-serif;
  --cy-font-mono: 'Space Mono', monospace;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: var(--cy-font);
  background: var(--cy-bg);
  color: var(--cy-text);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Page header pattern */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--cy-border);
}
.page-header-title {
  font-family: var(--cy-font);
  font-size: 22px;
  font-weight: 700;
  color: var(--cy-text);
  letter-spacing: -0.02em;
}
.page-header-title::before {
  content: '';
  display: inline-block;
  width: 4px;
  height: 22px;
  background: var(--cy-accent);
  border-radius: 2px;
  margin-right: 12px;
  vertical-align: middle;
}
.page-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Filter bar pattern */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

/* Stat card pattern */
.stat-card {
  background: var(--cy-bg-elevated);
  border: 1px solid var(--cy-border);
  border-radius: 10px;
  padding: 20px 24px;
  position: relative;
  overflow: hidden;
  transition: border-color 0.3s, box-shadow 0.3s;
}
.stat-card:hover {
  border-color: var(--cy-border-light);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}
.stat-card-accent {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 3px;
  border-radius: 10px 10px 0 0;
}
.stat-card-label {
  font-size: 13px;
  color: var(--cy-text-muted);
  font-weight: 500;
  margin-bottom: 8px;
  letter-spacing: 0.02em;
}
.stat-card-value {
  font-family: var(--cy-font-mono);
  font-size: 28px;
  font-weight: 700;
  color: var(--cy-text);
  letter-spacing: -0.02em;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--cy-border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--cy-border-light); }
</style>