<script setup>
import AppLayout from './components/AppLayout.vue'
import { NConfigProvider, NMessageProvider, NDialogProvider } from 'naive-ui'

const themeOverrides = {
  common: {
    primaryColor: '#0d9373',
    primaryColorHover: '#087e63',
    primaryColorPressed: '#076a55',
    primaryColorSuppl: '#15a985',
    successColor: '#16865e',
    warningColor: '#b66a18',
    errorColor: '#c4473a',
    borderRadius: '10px',
    borderColor: '#e7e7e3',
    dividerColor: '#ecece8',
    textColorBase: '#20201f',
    fontFamily: 'Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif',
  },
  Button: {
    borderRadiusMedium: '10px',
    fontWeight: '520',
    heightMedium: '38px',
  },
  Input: {
    borderRadius: '10px',
    heightMedium: '40px',
    boxShadowFocus: '0 0 0 3px rgba(13, 147, 115, 0.10)',
  },
  Select: {
    peers: {
      InternalSelection: {
        borderRadius: '10px',
        heightMedium: '40px',
      },
    },
  },
  Card: {
    borderRadius: '16px',
  },
}
</script>

<template>
  <NConfigProvider :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <AppLayout>
          <router-view />
        </AppLayout>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
