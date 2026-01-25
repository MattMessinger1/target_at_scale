import { test, expect } from '@playwright/test'

test('email generator loads', async ({ page }) => {
  await page.goto('/email')
  await expect(page.getByRole('heading', { name: 'Email Generator' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Choose Product & Audience' })).toBeVisible()
})

test('saved research loads', async ({ page }) => {
  await page.goto('/saved-runs')
  await expect(page.getByRole('heading', { name: 'Saved Research' })).toBeVisible()
})

test('selected hook appears in generated email and saves feedback', async ({ page }) => {
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
  const hookText = (await monitoringHook.textContent()) || ''
  await monitoringHook.locator('input[type="checkbox"]').check()

  await page.getByRole('button', { name: /Generate Email/i }).click()
  await expect(page.getByText('Review and Improve Email', { exact: false })).toBeVisible({ timeout: 180_000 })

  const emailBody = ((await page.locator('[data-testid="email-body"]').textContent()) || '').toLowerCase()

  const stopwords = new Set([
    'that', 'this', 'with', 'from', 'have', 'will', 'must', 'your', 'their', 'they', 'them', 'these',
    'those', 'into', 'over', 'under', 'state', 'district', 'districts', 'school', 'schools', 'program',
    'funds', 'funding', 'eligible', 'requires', 'requirement', 'requirements',
  ])
  const tokens = Array.from(new Set(
    (hookText.match(/[A-Za-z]{4,}/g) || [])
      .map((word) => word.toLowerCase())
      .filter((word) => !stopwords.has(word))
  ))
  const prioritizedTokens = tokens.includes('monitoring') ? ['monitoring', ...tokens] : tokens

  expect(prioritizedTokens.length).toBeGreaterThan(0)
  expect(prioritizedTokens.some((token) => emailBody.includes(token))).toBeTruthy()

  const marker = `PW-${Date.now()}`
  await page.getByTestId('edited-subject').fill(`CARE Coaching ${marker}`)
  await page.getByTestId('edited-email').fill(`${emailBody}\n\nEdited for review ${marker}.`)
  await page.getByTestId('save-email').click()
  await expect(page.getByText('Email saved', { exact: false })).toBeVisible({ timeout: 30_000 })

  let found = false
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const reviewResponse = await page.request.get(
      '/feedback/email-reviews?product=CARE%20Coaching&state_code=GA&limit=10'
    )
    if (reviewResponse.ok()) {
      const reviewData = await reviewResponse.json()
      found = (reviewData.items || []).some((item: { subject_preview?: string }) =>
        (item.subject_preview || '').includes(marker)
      )
    }
    if (found) break
    await page.waitForTimeout(3000)
  }
  expect(found).toBeTruthy()

  await page.goto('/training')
  await page.getByRole('button', { name: /^Reviews/ }).click()
  await expect(
    page.getByTestId('review-subject').filter({ hasText: marker }).first()
  ).toBeVisible({ timeout: 30_000 })
})
