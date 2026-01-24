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
