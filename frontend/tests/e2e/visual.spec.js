import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { expect, test } from '@playwright/test'

const ADMIN_USER = process.env.UI_ADMIN_USER || 'ui-admin'
const ADMIN_PASSWORD = process.env.UI_ADMIN_PASSWORD || 'ui-test-password'
const OUT_DIR = process.env.UI_SCREENSHOT_DIR || 'test-results/screens'

async function gotoApp(page, url) {
  await page.goto(url)
  await page.waitForLoadState('networkidle')
  await page.waitForFunction(() => Boolean(document.querySelector('#__nuxt')?.__vue_app__))
}

async function login(page) {
  await gotoApp(page, '/login')
  await page.getByPlaceholder('Masukkan username').fill(ADMIN_USER)
  await page.getByPlaceholder('Masukkan password').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/$/)
}

test('capture redesigned surfaces', async ({ page }) => {
  test.skip(process.env.UI_SCREENSHOTS !== '1', 'screenshots disabled')

  const container = process.env.UI_PG_CONTAINER
  if (container) {
    execFileSync(
      'docker',
      [
        'exec',
        container,
        'psql',
        '-U',
        process.env.UI_DB_USER || 'parking',
        '-d',
        process.env.UI_DB_NAME || 'parking',
        '-c',
        "UPDATE settings SET value='true' WHERE key='setup_complete'",
      ],
      { stdio: 'pipe' },
    )
  }

  fs.mkdirSync(OUT_DIR, { recursive: true })
  await page.setViewportSize({ width: 1440, height: 900 })

  await gotoApp(page, '/login')
  await page.screenshot({ path: path.join(OUT_DIR, '01-login.png'), fullPage: true })

  await login(page)
  await expect(page.getByText('Ringkasan operasional')).toBeVisible()
  await page.screenshot({ path: path.join(OUT_DIR, '02-dashboard.png'), fullPage: true })

  await gotoApp(page, '/transaksi')
  await page.screenshot({ path: path.join(OUT_DIR, '03-transaksi.png'), fullPage: true })

  await gotoApp(page, '/setting')
  await page.screenshot({ path: path.join(OUT_DIR, '04-setting.png'), fullPage: true })

  await gotoApp(page, '/device')
  await page.screenshot({ path: path.join(OUT_DIR, '05-device.png'), fullPage: true })

  if (container) {
    execFileSync(
      'docker',
      [
        'exec',
        container,
        'psql',
        '-U',
        process.env.UI_DB_USER || 'parking',
        '-d',
        process.env.UI_DB_NAME || 'parking',
        '-c',
        "DELETE FROM gates WHERE code = 'GOUT-99'",
      ],
      { stdio: 'pipe' },
    )
  }

  await page.setViewportSize({ width: 1366, height: 768 })
  await gotoApp(page, '/pos')
  await expect(page.getByText('Belum ada petugas')).toBeVisible()
  await page.screenshot({ path: path.join(OUT_DIR, '06-pos-worker-checkin.png'), fullPage: true })
})
