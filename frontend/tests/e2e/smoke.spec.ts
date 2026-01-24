import { test, expect } from '@playwright/test'

test('email generator loads', async ({ page }) => {
  await page.goto('/email')
  await expect(page.getByText('Email Generator', { exact: false })).toBeVisible()
  await expect(page.getByText('Choose Product & Audience', { exact: false })).toBeVisible()
})

test('saved research loads', async ({ page }) => {
  await page.goto('/saved-runs')
  await expect(page.getByText('Saved Research', { exact: false })).toBeVisible()
})

test('selected hook appears in generated email', async ({ page }) => {
  test.setTimeout(240_000)
  await page.goto('/email')

  await page.getByText('CARE Coaching', { exact: true }).click()
  await page.getByPlaceholder('Search states...').fill('Georgia')
  await page.getByText('Georgia', { exact: true }).click()

  await page.getByRole('button', { name: /Continue/i }).click()

  const monitoringHook = page
    .locator('[data-testid="cached-state-hook"]')
    .filter({ hasText: 'Monitoring' })
    .first()
  await expect(monitoringHook).toBeVisible({ timeout: 20_000 })
  await monitoringHook.locator('input[type="checkbox"]').check()

  await page.getByRole('button', { name: /Generate Email/i }).click()
  await expect(page.getByText('Review and Improve Email', { exact: false })).toBeVisible({ timeout: 180_000 })

  const triggerExcerpt = (await page.locator('[data-testid="selected-trigger-excerpt"]').first().textContent()) || ''
  const emailBody = ((await page.locator('[data-testid="email-body"]').textContent()) || '').toLowerCase()

  const stopwords = new Set([
    'that', 'this', 'with', 'from', 'have', 'will', 'must', 'your', 'their', 'they', 'them', 'these',
    'those', 'into', 'over', 'under', 'state', 'district', 'districts', 'school', 'schools', 'program',
    'funds', 'funding', 'eligible', 'requires', 'requirement', 'requirements',
  ])
  const tokens = Array.from(new Set(
    (triggerExcerpt.match(/[A-Za-z]{4,}/g) || [])
      .map((word) => word.toLowerCase())
      .filter((word) => !stopwords.has(word))
  ))
  const prioritizedTokens = tokens.includes('monitoring') ? ['monitoring', ...tokens] : tokens

  expect(prioritizedTokens.length).toBeGreaterThan(0)
  expect(prioritizedTokens.some((token) => emailBody.includes(token))).toBeTruthy()
})
