import { h } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, NButton } from 'naive-ui'

/**
 * 流程接力提示：某阶段完成后，用 success message 提示"完成信息 + 前往按钮"。
 * 按钮点击后跳转下一步路由并关闭该 message。
 *
 * 用法：
 *   const { notifyNext } = useNextStep()
 *   notifyNext('摄入完成：3 个新文献', { label: '前往解析', to: '/pipeline' })
 */
export function useNextStep() {
  const message = useMessage()
  const router = useRouter()

  /**
   * @param {string} content - 完成信息（支持 \n 换行）
   * @param {{ label: string, to?: string }} [next] - 下一步；
   *   省略或不带 to 时只显示纯完成提示（用于下一步就在当前页操作的场景）
   */
  function notifyNext(content, next) {
    if (!next?.to) {
      return message.success(content, { duration: 6000 })
    }
    // naive-ui 2.44 的 message.success(content, options)：content 接受函数作为自定义渲染。
    // （此前误用的 { render } options 形态在该版本不生效，会渲染空白 toast。）
    const msg = message.success(
      () => h('div', { style: 'display:flex;align-items:center;gap:10px' }, [
        h('span', { style: 'white-space:pre-line' }, content),
        h(NButton, {
          size: 'tiny',
          tertiary: true,
          type: 'success',
          onClick: () => {
            router.push(next.to)
            msg.destroy()
          },
        }, { default: () => `${next.label} →` }),
      ]),
      { duration: 6000 },
    )
    return msg
  }

  return { notifyNext }
}
