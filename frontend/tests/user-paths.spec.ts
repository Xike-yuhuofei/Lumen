import { test, expect, Page } from '@playwright/test'

/* ============================================================================
 * USER_PATHS.md → 可运行 E2E
 * 解耦说明（与 task 约束一致，依据 USER_PATHS.md「范围与边界」）：
 *  - 主线/边缘里「无真实后端、仅 UI 存在」的交互（插件安装/更新本地态、账户菜单占位项、
 *    #/files、#/design-system 占位页）只做「存在性/可交互」断言。
 *  - 异常分支 X1/X3/X4/X5/X6/X7/X8：其前置条件是「后端不可用 / 返回失败 / 超时无响应」。
 *    在共享真实后端的前提下不破坏其余用例，故用 Playwright route 拦截可控地注入失败前置，
 *    断言前端对这些异常的真实错误处理路径。（触发真实后端宕机会中断整套回归，故为模拟前置。）
 *  - 其余主线/边缘（导入、学习空间、对话、设置持久化、会话管理）全部走真实后端，不 mock。
 * ============================================================================ */

const NAV = {
  newTask: { cls: '.navItem-r4wswG', text: '新建对话' },
  spaces: { cls: '.navItem-r4wswG', text: '学习空间' },
  marketplace: { cls: '.navItem-r4wswG', text: '插件市场' },
  library: { cls: '.navItem-r4wswG', text: '资料库' },
}

test.describe.configure({ mode: 'serial' })
test.setTimeout(180000)

async function appInitScript(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('trae:sidebarOpen', '1')
    localStorage.setItem('trae:statusOpen', '0')
    localStorage.removeItem('lumen:sessions')
    localStorage.removeItem('lumen:selectedSession')
    localStorage.removeItem('askora:sessions')
    // 仅初次导航时播种默认主题；reload 时不再覆盖，保证持久化断言有效。
    if (!sessionStorage.getItem('trae:e2e-init')) {
      localStorage.setItem('trae:theme', 'dark')
      sessionStorage.setItem('trae:e2e-init', '1')
    }
  })
}

async function openApp(page: Page, route = '/') {
  await appInitScript(page)
  await page.goto(route)
  await page.waitForSelector('.app-root')
}

async function clickNav(page: Page, nav: { cls: string; text: string }) {
  await page.locator(nav.cls).filter({ hasText: nav.text }).first().click()
}

/** 等待 #agent-chat-view 里出现非空 assistant 内容（markdown 文本 或 ask_user 提问卡片）。
 *  真实 Gitee LLM 教学 turn 偶发 130~240s 延迟，超时给足冗余。 */
async function assistantHasContent(page: Page, timeout = 240000) {
  await expect
    .poll(async () => {
      const md = await page
        .locator('#agent-chat-view .markdown-renderer')
        .last()
        .innerText()
        .catch(() => '')
      const quiz = await page.locator('#agent-chat-view .quiz-card').count().catch(() => 0)
      return md.trim().length > 0 ? 1 : quiz
    }, { timeout, intervals: [1000] })
    .toBeGreaterThan(0)
}

async function sendInComposer(page: Page, text: string) {
  const box = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-wrapper')
  await expect(box).toBeVisible()
  await box.click()
  const editable = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-editable')
  await editable.pressSequentially(text)
  await page.locator('.chat-input-v2-send-button').click()
}

const unique = (prefix: string) => `${prefix}-${Date.now()}`

/* ---------------- J3 · 普通对话问答（选作首测，顺带验证真实后端 LLM 链路） ---------------- */
test('J3 普通对话问答：真实 LLM 流式返回内容', async ({ page }) => {
  test.setTimeout(300000)
  await openApp(page)
  await clickNav(page, NAV.newTask)
  await sendInComposer(page, '用一句话介绍你自己。')
  await expect(page.locator('#agent-chat-view')).toBeVisible({ timeout: 15000 })
  await expect(page.locator('#agent-chat-view .user-message-query-text').first()).toBeVisible({ timeout: 15000 })
  await assistantHasContent(page)
  // 侧栏出现新会话
  await expect(page.locator('.taskItem .taskText').first()).not.toHaveText('新对话', { timeout: 30000 })
})

/* ---------------- J1 · 学习一份新资料（真实导入→轮询→加入空间→预览） ---------------- */
test('J1 导入资料→解析→加入学习空间→预览（真实后端）', async ({ page }) => {
  test.setTimeout(240000)
  await openApp(page)
  await clickNav(page, NAV.library)
  const title = page.locator('.title-yQrHui').first()
  await expect(title).toHaveText('资料库')
  await expect(page.locator('.headerActions-TKXare').getByRole('button', { name: '刷新' })).toBeVisible()
  await expect(page.locator('.headerActions-TKXare').getByRole('button', { name: '导入资料' })).toBeVisible()

  const fileName = unique('e2e-双宫纱')
  const md = '# 双宫纱工艺要点\n\n双宫纱由桑蚕丝经两道工序织成，表面有天然疙瘩。'
  await page.locator('input[type="file"]').setInputFiles({
    name: `${fileName}.md`,
    mimeType: 'text/markdown',
    buffer: Buffer.from(md),
  })

  // 导入 Modal
  await expect(page.locator('.detailPanel-NZOW7g .detailTitle-X7zIZu').filter({ hasText: '导入资料' })).toBeVisible()
  // 等待 modal 的异步 listKnowledgeBases 解析完（确认提示反映 targetExists 后再提交，
  // 避免 targetExists 仍为初始 false 而误走 createKnowledgeBase → “already exists”）
  await expect(page.locator('.detailPanel-NZOW7g').getByText(/已存在|首次导入/)).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '开始导入' }).click()
  // 轮询直到 ready（真实索引，给足时间）
  await expect(page.locator('.detailPanel-NZOW7g').getByText('导入完成')).toBeVisible({ timeout: 150000 })
  await page.getByRole('button', { name: '完成' }).click()

  // 列表刷新出卡片，状态已解析
  const card = page.locator('.pluginCard-cq4jH5').filter({ hasText: fileName })
  await expect(card.first()).toBeVisible({ timeout: 30000 })
  await expect(card.first()).toContainText('已解析')

  // 预览正文
  await card.first().getByRole('button', { name: '打开' }).click()
  await expect(page.locator('.detailPanel-NZOW7g pre')).toContainText('双宫纱')
  await page.getByRole('button', { name: '关闭' }).click()
  await expect(page.locator('.detailPanel-NZOW7g pre')).toHaveCount(0)

  // 加入学习空间（真实 createLearningGoal）
  await card.first().getByRole('button', { name: '添加到学习空间' }).click()
  await expect(page.locator('.libraryToast')).toContainText('已加入学习空间', { timeout: 20000 })
  await expect(card.first().getByRole('button', { name: '已加入学习空间' })).toBeVisible({ timeout: 15000 })
})

/* ---------------- E1 + X9 · 删除资料（含取消分支） ---------------- */
test('E1+X9 删除资料：取消保留、确认删除（真实后端）', async ({ page }) => {
  await openApp(page)
  await clickNav(page, NAV.library)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('资料库')
  // 挑选一个可删除条目（取第一个普通条目，避免刚创建/处理中的歧义；用文件 input 造一个即可）
  await page.locator('input[type="file"]').setInputFiles({
    name: `${unique('e2e-del')}.md`,
    mimeType: 'text/markdown',
    buffer: Buffer.from('# delete me\n\n\n内容'),
  })
  // 等待 targetExists 解析完成再提交，避免误走 create 分支
  await expect(page.locator('.detailPanel-NZOW7g').getByText(/已存在|首次导入/)).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect(page.locator('.detailPanel-NZOW7g').getByText('导入完成')).toBeVisible({ timeout: 150000 })
  await page.getByRole('button', { name: '完成' }).click()

  const delName = page.locator('.pluginCard-cq4jH5').filter({ hasText: 'e2e-del' }).first()
  await expect(delName).toBeVisible({ timeout: 30000 })
  await delName.getByRole('button', { name: '删除' }).click()
  await expect(page.locator('.detailPanel-NZOW7g .detailTitle-X7zIZu').filter({ hasText: '删除资料' })).toBeVisible()

  // 取消分支：不删除
  await page.getByRole('button', { name: '取消' }).click()
  await expect(page.locator('.pluginCard-cq4jH5').filter({ hasText: 'e2e-del' })).toBeVisible()
  // Esc 取消也是 E1 的分支
  await delName.getByRole('button', { name: '删除' }).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('.pluginCard-cq4jH5').filter({ hasText: 'e2e-del' })).toBeVisible()

  // 确认删除
  await delName.getByRole('button', { name: '删除' }).click()
  await page.getByRole('button', { name: '删除', exact: true }).last().click()
  await expect(page.locator('.libraryToast')).toContainText('已删除', { timeout: 15000 })
  await expect(page.locator('.pluginCard-cq4jH5').filter({ hasText: 'e2e-del' })).toHaveCount(0)
})

/* ---------------- E4 · 重命名 / 删除学习空间（真实后端） ---------------- */
test('E4 学习空间：重命名与删除（真实后端）', async ({ page }) => {
  const goalName = unique('e2e-space')
  // 用真实后端 API 直接创建目标（不走 LLM、稳定、快）
  const resp = await page.request.post('/api/v1/learning/goals', {
    data: { title: goalName, description: 'E2E 重命名/删除', kb_name: '' },
  })
  expect(resp.ok()).toBeTruthy()
  const created = (await resp.json()) as { book_id?: string }
  expect(created.book_id).toBeTruthy()

  await openApp(page)
  await clickNav(page, NAV.spaces)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('学习空间')

  const target = page.locator('.spaceCard').filter({ hasText: goalName }).first()
  await expect(target).toBeVisible({ timeout: 20000 })
  await target.getByRole('button', { name: '更多操作' }).click()
  await page.locator('.spaceCardMenu').getByRole('menuitem', { name: '重命名' }).click()
  await expect(page.locator('#goal-rename-input')).toBeVisible()
  const newName = `${goalName}-renamed`
  await page.locator('#goal-rename-input').fill(newName)
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.spaceCard').filter({ hasText: newName }).first()).toBeVisible({ timeout: 20000 })

  // 删除重命名后的空间
  await page.locator('.spaceCard').filter({ hasText: newName }).first().getByRole('button', { name: '更多操作' }).click()
  await page.locator('.spaceCardMenu').getByRole('menuitem', { name: '删除' }).click()
  await expect(page.locator('.spaceCard').filter({ hasText: newName })).toHaveCount(0, { timeout: 20000 })
})

/* ---------------- J2 · 直接开启学习目标（真实创建 + 自动 Learn turn） ---------------- */
test('J2 新建学习空间并自动进入引导学习（真实后端 LLM）', async ({ page }) => {
  test.setTimeout(320000)
  const goalTitle = unique('掌握线性代数第三章')
  await openApp(page)
  await clickNav(page, NAV.spaces)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('学习空间')

  await page.getByRole('button', { name: '新建空间' }).click()
  await expect(page.locator('.detailPanel-NZOW7g .detailTitle-X7zIZu').filter({ hasText: '新建空间' })).toBeVisible()
  // 空名称禁用
  await expect(page.getByRole('button', { name: '创建空间' })).toBeDisabled()
  await page.locator('#goal-name-input').fill(goalTitle)
  await page.locator('#goal-desc-input').fill('围绕教材第三章，重点掌握行列式与特征值')
  await expect(page.getByRole('button', { name: '创建空间' })).toBeEnabled()
  await page.getByRole('button', { name: '创建空间' }).click()

  // 自动发起 Learn turn 并进入 #/chat
  await expect(page.locator('#agent-chat-view')).toBeVisible({ timeout: 15000 })
  await expect(page.locator('#agent-chat-view .user-message-query-text').first()).toBeVisible({ timeout: 15000 })
  await expect(page.locator('#agent-chat-view')).toContainText(goalTitle, { timeout: 20000 })
  await assistantHasContent(page)
})

/* ---------------- J4 · 继续已有学习 + 进度详情（真实后端） ---------------- */
test('J4 继续学习与进度详情（真实后端）', async ({ page }) => {
  test.setTimeout(320000)
  await openApp(page)
  await clickNav(page, NAV.spaces)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('学习空间')

  // 取卡片列表第一个，点击卡片主体打开进度详情
  const firstCard = page.locator('.spaceCard').first()
  await expect(firstCard).toBeVisible({ timeout: 20000 })
  await firstCard.click()
  // 进度详情弹窗（整体进度 或 计划未生成）
  await expect(page.locator('.detailInfoSection-c234JE').first()).toBeVisible({ timeout: 20000 })
  const panelText = await page.locator('.detailPanel-NZOW7g').innerText().catch(() => '')
  expect(panelText).toMatch(/学习空间|空间整体进度|学习计划尚未生成/)

  // 弹窗底部「继续学习」触发 mastery turn
  await page.locator('.detailActionBar-BhqrLr').getByRole('button', { name: '继续学习' }).click()
  await expect(page.locator('#agent-chat-view')).toBeVisible({ timeout: 15000 })
  await assistantHasContent(page)
})

/* ---------------- E5 · 重命名 / 置顶 / 删除会话（真实后端） ---------------- */
test('E5 会话管理：置顶、重命名、删除（真实后端）', async ({ page }) => {
  await openApp(page)
  await clickNav(page, NAV.newTask)
  await sendInComposer(page, '创建一个用于会话管理的占位会话。')
  await expect(page.locator('#agent-chat-view')).toBeVisible({ timeout: 15000 })
  const item = page.locator('.taskItem .taskText').first()
  await expect(item).not.toHaveText('新对话', { timeout: 30000 })
  const label = await item.innerText()

  const sidebar = page.locator('.taskItem').filter({ hasText: label }).first()
  // 置顶 / 取消置顶
  await sidebar.hover()
  await sidebar.getByRole('button', { name: '置顶' }).click()
  await expect(page.locator('.pinnedSectionList .taskItem').first()).toBeVisible({ timeout: 15000 })
  await page.locator('.pinnedSectionList .taskItem').first().hover()
  await page.locator('.pinnedSectionList .taskItem').first().getByRole('button', { name: '更多' }).click()
  await page.locator('.taskMenu').getByRole('menuitem', { name: '取消置顶' }).click()
  await page.keyboard.press('Escape')

  // 重命名
  const renamed = page.locator('.taskItem').filter({ hasText: label }).first()
  await renamed.hover()
  await renamed.getByRole('button', { name: '更多' }).click()
  await page.locator('.taskMenu').getByRole('menuitem', { name: '重命名' }).click()
  const newLabel = `${label}-renamed`
  await page.locator('.renameInput-q2DQZg').fill(newLabel)
  await page.getByRole('button', { name: '确认' }).click()
  await expect(page.locator('.taskItem .taskText').filter({ hasText: newLabel })).toHaveCount(1, { timeout: 15000 })

  // 删除（本地 + 后端）
  const final = page.locator('.taskItem').filter({ hasText: newLabel }).first()
  await final.hover()
  await final.getByRole('button', { name: '更多' }).click()
  await page.locator('.taskMenu').getByRole('menuitem', { name: '删除任务' }).click()
  await expect(page.locator('.taskItem .taskText').filter({ hasText: newLabel })).toHaveCount(0, { timeout: 15000 })
})

/* ---------------- J5 + E2 · 插件市场（仅 UI 存在性/交互断言） ---------------- */
test('J5+E2 插件市场：浏览/搜索/安装/详情/更新（UI）', async ({ page }) => {
  await openApp(page)
  await clickNav(page, NAV.marketplace)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('插件市场')

  // 分类 tab 存在（选中项用 Active 类，其余用常规类）
  for (const cat of ['推荐', '教学与学习', '资料处理', '搜索与研究', '工具与自动化', '集成']) {
    await expect(
      page.locator('.categoryNavItemActive-k6zapU, .categoryNavItem-HXakRf').filter({ hasText: cat }),
    ).toBeVisible()
  }
  // 搜索过滤
  await page.locator('[name="marketplace-search"]').fill('Flashcards')
  await expect(page.locator('.pluginCard-cq4jH5').filter({ hasText: 'Flashcards' })).toBeVisible()
  await expect(page.locator('.pluginCard-cq4jH5').filter({ hasText: 'Zotero' })).toHaveCount(0)
  await page.locator('[name="marketplace-search"]').fill('')

  // 安装一个未安装插件 → 按钮变「打开」
  const flashcards = page.locator('.pluginCard-cq4jH5').filter({ hasText: 'Flashcards' }).first()
  const installBtn = flashcards.getByRole('button').filter({ hasText: '安装' })
  await installBtn.click()
  await expect(flashcards.getByRole('button').filter({ hasText: '打开' })).toBeVisible()

  // 插件详情弹窗
  await flashcards.click()
  await expect(page.locator('.detailPanel-NZOW7g .detailTitle-X7zIZu').filter({ hasText: 'Flashcards' })).toBeVisible()
  await expect(page.locator('.detailPanel-NZOW7g').getByText('可用技能')).toBeVisible()
  await expect(page.locator('.detailBtnPrimary-NtBx72').filter({ hasText: '+ 安装技能' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('.detailPanel-NZOW7g')).toHaveCount(0)

  // E2 · 辅助筛选「可更新」→ 出现带「更新」按钮的已安装插件；更新后刷新本地态
  await page.locator('.categoryNavItem-HXakRf').filter({ hasText: '可更新' }).click()
  const updatable = page.locator('.pluginCard-cq4jH5').filter({ hasText: 'Deep Research' }).first()
  await expect(updatable.getByRole('button').filter({ hasText: '更新' })).toBeVisible({ timeout: 15000 })
  await updatable.getByRole('button').filter({ hasText: '更新' }).click()
  // 更新后不再视为「可更新」→ 该插件从「可更新」筛选下消失
  await expect(page.locator('.pluginCard-cq4jH5').filter({ hasText: 'Deep Research' })).toHaveCount(0, { timeout: 10000 })
  // 回到「全部」：仍已安装，按钮为「打开」
  await page.locator('.categoryNavItem-HXakRf').filter({ hasText: '全部' }).click()
  const dr = page.locator('.pluginCard-cq4jH5').filter({ hasText: 'Deep Research' }).first()
  await expect(dr.getByRole('button').filter({ hasText: '打开' })).toBeVisible({ timeout: 10000 })
  // 「打开」应打开详情，而非卸载
  await dr.getByRole('button').filter({ hasText: '打开' }).click()
  await expect(page.locator('.detailPanel-NZOW7g .detailTitle-X7zIZu').filter({ hasText: 'Deep Research' })).toBeVisible({ timeout: 10000 })
  await page.keyboard.press('Escape')
})

/* ---------------- J6 · 配置个人环境（真实后端持久化主题） ---------------- */
test('J6 设置：主题修改并持久化（真实后端）', async ({ page }) => {
  await openApp(page)
  await page.locator('.accountTrigger-y5IeNi').click()
  await page.locator('.accountMenuItem-NXEKcd').filter({ hasText: '设置' }).click()
  await expect(page.locator('.dtSettings[role="dialog"]')).toBeVisible()
  await expect(page.locator('#dt-settings-title')).toHaveText('通用')

  await page.getByRole('button', { name: '主题' }).click()
  await page.getByRole('option', { name: '亮色' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  // 对话与工具页可见
  await page.locator('.dtSettingsNavItem').filter({ hasText: '对话与工具' }).click()
  await expect(page.locator('#dt-settings-title')).toHaveText('对话与工具')
  await expect(page.getByRole('switch', { name: '头脑风暴' })).toBeVisible()
  await page.locator('.dtSettingsClose').click()

  // 刷新后主题仍为 light（localStorage + 后端）
  await page.reload()
  await page.waitForSelector('.app-root')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  // 还原为暗色，避免影响其他测试
  await page.locator('.accountTrigger-y5IeNi').click()
  await page.locator('.accountMenuItem-NXEKcd').filter({ hasText: '设置' }).click()
  await page.getByRole('button', { name: '主题' }).click()
  await page.getByRole('option', { name: '暗色' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

/* ---------------- E3 · 退出登录（占位按钮，UI 存在性） ---------------- */
test('E3 退出登录为占位项（仅 UI 存在）', async ({ page }) => {
  await openApp(page)
  await page.locator('.accountTrigger-y5IeNi').click()
  // 退出登录为占位按钮（无真实登录态与跳转），仅断言其存在。
  await expect(page.locator('.accountLogoutButton-MqoPgT').filter({ hasText: '退出登录' })).toBeVisible()
})

/* ---------------- E7 · 占位页访问（#/files、#/design-system） ---------------- */
test('E7 占位页：我的文件 / 设计系统可见', async ({ page }) => {
  await openApp(page)
  // Work 模式 → 我的文件
  await page.getByRole('tab', { name: 'Work' }).click()
  await page.locator('.navItem-r4wswG').filter({ hasText: '我的文件' }).click()
  await expect(page.locator('.titleText-H3MNV2').filter({ hasText: '我的文件' })).toBeVisible({ timeout: 15000 })

  // Design 模式 → 设计系统
  await page.getByRole('tab', { name: 'Design' }).click()
  await page.locator('.navItem-r4wswG').filter({ hasText: '设计系统' }).click()
  await expect(page.locator('.titleText-H3MNV2').filter({ hasText: '设计系统' })).toBeVisible({ timeout: 15000 })
})

/* ================= 异常 / 分支（模拟失败前置注入） ================= */

/* X3 · 资料库加载失败 → 重试 */
test('X3 资料库加载失败显示错误并可重试', async ({ page }) => {
  await page.route('**/api/v1/knowledge/list', (r) => r.abort())
  await openApp(page)
  await clickNav(page, NAV.library)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('资料库')
  // 加载失败文案 + 重试按钮
  await expect(page.getByText(/加载知识库失败|请求失败|Failed/)).toBeVisible({ timeout: 20000 })
  const retry = page.getByRole('button', { name: '重试' })
  await expect(retry).toBeVisible()
  // 恢复后重试可正常加载
  await page.unroute('**/api/v1/knowledge/list')
  await retry.click()
  await expect(page.locator('.pluginsContentInner-amtMMJ .pluginCard-cq4jH5').first().or(page.getByText('这里空空如也'))).toBeVisible({ timeout: 20000 })
})

/* X5 · 学习空间加载失败 */
test('X5 学习空间加载失败显示错误文案', async ({ page }) => {
  await page.route('**/api/v1/learning/progress', (r) => { if (r.request().method() === 'GET') r.abort(); else r.continue() })
  await openApp(page)
  await clickNav(page, NAV.spaces)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('学习空间')
  await expect(page.getByText('无法加载学习空间，请确认后端已启动')).toBeVisible({ timeout: 20000 })
})

/* X7 · 创建学习空间失败 */
test('X7 创建学习空间失败提示', async ({ page }) => {
  await page.route('**/api/v1/learning/goals', (r) => {
    if (r.request().method() === 'POST') r.abort()
    else r.continue()
  })
  await openApp(page)
  await clickNav(page, NAV.spaces)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('学习空间')
  await page.getByRole('button', { name: '新建空间' }).click()
  await page.locator('#goal-name-input').fill(unique('x7-fail'))
  await page.getByRole('button', { name: '创建空间' }).click()
  await expect(page.getByText('创建空间失败，请重试')).toBeVisible({ timeout: 20000 })
})

/* X4 · 导入解析/上传失败 */
test('X4 导入失败阶段显示错误并可重试/关闭', async ({ page }) => {
  await page.route('**/api/v1/knowledge/*/upload', (r) => r.abort())
  await page.route('**/api/v1/knowledge/create', (r) => r.abort())
  await openApp(page)
  await clickNav(page, NAV.library)
  await expect(page.locator('.title-yQrHui').first()).toHaveText('资料库')
  await page.locator('input[type="file"]').setInputFiles({
    name: `${unique('x4')}.md`,
    mimeType: 'text/markdown',
    buffer: Buffer.from('# x\n\n\n'),
  })
  await page.getByRole('button', { name: '开始导入' }).click()
  await expect(page.locator('.detailPanel-NZOW7g').getByText('导入失败')).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  await expect(page.getByRole('button', { name: '关闭' })).toBeVisible()
})

/* X2 · 资料解析失败 → 重新解析 */
test('X2 解析失败条目显示「重新解析」并触发重试', async ({ page }) => {
  await page.route('**/api/v1/knowledge/list', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 'kb-x2', name: '资料库', is_default: true, status: 'error', statistics: { raw_documents: 1, images: 0, content_lists: 0, rag_initialized: false, rag_provider: 'llamaindex', needs_reindex: false }, metadata: { last_error: '解析失败（模拟）' }, progress: { error: '解析失败（模拟）' } },
      ]),
    }))
  await page.route('**/api/v1/knowledge/*/files', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [{ name: 'broken.md', type: 'file', size: 12, modified: Math.floor(Date.now() / 1000) }] }) }))
  await openApp(page)
  await clickNav(page, NAV.library)
  const card = page.locator('.pluginCard-cq4jH5').filter({ hasText: 'broken.md' })
  await expect(card.first()).toBeVisible({ timeout: 20000 })
  await expect(card.first()).toContainText('解析失败')
  await expect(card.first().getByRole('button', { name: '重新解析' })).toBeVisible()
  // 触发重新解析（POST retry，真实后端接受；若后端不可用则仅验证按钮可点，不强制成功）
  await card.first().getByRole('button', { name: '重新解析' }).click()
  await expect(page.locator('.libraryToast')).toHaveCount(1, { timeout: 15000 })
})

/* X1 · 后端未启动（连接失败） */
test('X1 后端不可用时提示无法连接', async ({ page }) => {
  // 模拟后端不可达：拦截并立即关闭 WS 升级请求
  await page.routeWebSocket('**/api/v1/ws', (ws) => { ws.close() })
  await openApp(page)
  await clickNav(page, NAV.newTask)
  await sendInComposer(page, 'hello x1')
  await expect(page.getByText('无法连接 Lumen 后端，请确认本地 API 已启动')).toBeVisible({ timeout: 30000 })
})

/* X8 · 发送时无活跃连接（归入连接失败路径） */
test('X8 发送时无活跃连接不静默失败', async ({ page }) => {
  await page.routeWebSocket('**/api/v1/ws', (ws) => { ws.close() })
  await openApp(page)
  await clickNav(page, NAV.newTask)
  await sendInComposer(page, 'hello x8')
  // 连接失败必须呈现给用户（错误文字或恢复按钮），不得静默无反馈
  await expect(page.locator('.chat-input-v2-container').first()).toBeVisible({ timeout: 10000 })
  const anyError = page.getByText(/无法连接 Lumen 后端|等待回复超时|回复失败/)
  await expect(anyError.first()).toBeVisible({ timeout: 30000 })
})

/* X6 · 对话等待超时（把超时拉到最小 30s + 无响应） */
test('X6 等待回复超时提示', async ({ page }) => {
  // loadRuntimeUiSettings 先读 GET /api/v1/settings（含 ui），操纵 chat_response_timeout=30
  await page.route('**/api/v1/settings/ui', (r) => {
    if (r.request().method() === 'GET') {
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ response_language: 'zh', chat_response_timeout: 30 }) })
    } else r.continue()
  })
  await page.route('**/api/v1/settings', (r) => {
    if (r.request().method() === 'GET') {
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ui: { response_language: 'zh', chat_response_timeout: 30 } }) })
    } else r.continue()
  })
  // WS 可建立但无任何 turn 事件返回 → 走 idle 等待超时（30s）
  await page.routeWebSocket('**/api/v1/ws', (ws) => { /* 不返回任何事件 */ })
  await openApp(page)
  await clickNav(page, NAV.newTask)
  await sendInComposer(page, 'hello x6')
  await expect(page.getByText('等待回复超时，请稍后重试或在设置中延长等待时间。')).toBeVisible({ timeout: 60000 })
})