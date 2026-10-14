import { afterEach, expect, it } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { NRadioButton, NRadioGroup } from 'naive-ui'
import { parse, compileStyle } from '@vue/compiler-sfc'
import worksSource from '../src/views/Works.vue?raw'

let app
let stylesheet
afterEach(() => {
  app?.unmount()
  stylesheet?.remove()
  document.body.replaceChildren()
})

it('keeps export captions styled without breaking either radio-button group', async () => {
  const scopeId = 'data-v-export-regression'
  const groups = [
    ['Format', ['bibtex', 'ris', 'matrix.csv']],
    ['Scope', ['filtered', 'all']],
  ]
  const host = document.createElement('div')
  document.body.append(host)
  app = createApp({
    __scopeId: scopeId,
    render: () => h('section', groups.map(([caption, values]) =>
      h('div', { class: 'export-group' }, [
        h('label', caption),
        h(NRadioGroup, { value: values[0] }, {
          default: () => values.map(value => h(NRadioButton, { value }, { default: () => value })),
        }),
      ]),
    )),
  })
  app.mount(host)
  await nextTick()

  const { descriptor } = parse(worksSource)
  const compiled = compileStyle({ source: descriptor.styles[0].content, id: scopeId, scoped: true })
  expect(compiled.errors).toEqual([])
  stylesheet = document.createElement('style')
  stylesheet.textContent = compiled.code
  document.head.append(stylesheet)

  for (const caption of host.querySelectorAll('.export-group > label')) {
    expect(getComputedStyle(caption).display).toBe('block')
    expect(getComputedStyle(caption).marginBottom).toBe('6px')
  }
  const buttons = [...host.querySelectorAll('.n-radio-button')]
  expect(buttons).toHaveLength(5)
  for (const button of buttons) {
    expect(getComputedStyle(button).display).toBe('inline-block')
    expect(getComputedStyle(button).marginBottom).not.toBe('6px')
  }
})
