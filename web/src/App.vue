<script setup>
import AppLayout from './components/AppLayout.vue'
import { NConfigProvider, NMessageProvider, NDialogProvider } from 'naive-ui'

const themeOverrides = {
  common: {
    primaryColor: '#1f6feb',
    successColor: '#16833a',
    warningColor: '#9a6700',
    errorColor: '#c32f27',
    fontFamily: '"Segoe UI", "Microsoft YaHei", Arial, sans-serif',
  }
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
