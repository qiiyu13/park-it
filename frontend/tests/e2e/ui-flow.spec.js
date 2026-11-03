import { execFileSync } from 'node:child_process'
import fs from 'node:fs'

import { expect, test } from '@playwright/test'

const ADMIN_USER = process.env.UI_ADMIN_USER || 'ui-admin'
const ADMIN_PASSWORD = process.env.UI_ADMIN_PASSWORD || 'ui-test-password'

test.describe.configure({ mode: 'serial' })

async function gotoApp(page, path) {
  await page.goto(path)
  await page.waitForLoadState('networkidle')
  // Without hydration a click hits the native form and reloads the page.
  await page.waitForFunction(
    () => Boolean(document.querySelector('#__nuxt')?.__vue_app__),
  )
}

async function login(page) {
  await gotoApp(page, '/login')
  await page.getByPlaceholder('Masukkan username').fill(ADMIN_USER)
  await page.getByPlaceholder('Masukkan password').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/$/)
}

test('login rejects invalid credentials', async ({ page }) => {
  await gotoApp(page, '/login')
  await expect(page.getByRole('heading', { name: 'E-Parking v2' })).toBeVisible()

  await page.getByPlaceholder('Masukkan username').fill('not-a-user')
  await page.getByPlaceholder('Masukkan password').fill('wrong-password')
  await page.getByRole('button', { name: 'Masuk' }).click()

  await expect(page.getByText('Username atau password salah')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

test('admin logs in and sees the dashboard', async ({ page }) => {
  await login(page)

  // Login response carries username/role only; the full name arrives on /me.
  await expect(page.getByText(ADMIN_USER).first()).toBeVisible()
  await expect(page.getByText('Ringkasan operasional')).toBeVisible()
  await expect(page.getByText('Operasional').first()).toBeVisible()
})

test('direct navigation keeps the session (SSR cookie forwarding)', async ({ page }) => {
  // Login client-side first.
  await login(page)

  // Each of these is a full document request — without forwarded cookies the
  // SSR auth middleware bounces back to /login.
  for (const [path, title] of [
    ['/transaksi', 'Transaksi'],
    ['/device', 'Perangkat'],
    ['/setting', 'Pengaturan'],
    ['/report', 'Laporan'],
  ]) {
    await gotoApp(page, path)
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect(page.getByText(title, { exact: true }).first()).toBeVisible()
  }
})

test('POS kiosk renders and blocks on worker check-in', async ({ page }) => {
  await login(page)

  await gotoApp(page, '/pos')
  await expect(page).toHaveURL(/\/pos$/)
  await expect(page.getByText('Belum ada petugas')).toBeVisible()
  await expect(
    page.getByRole('button', { name: /MASUK SHIFT/ }),
  ).toBeVisible()
  // Guard the worker-dialog surface styling.
  const dialog = page.locator('.pos-modal').first()
  await expect(dialog).toBeVisible()
  const background = await dialog.evaluate(
    (el) => getComputedStyle(el).backgroundColor,
  )
  expect(background).not.toBe('rgba(0, 0, 0, 0)')
})

test('anonymous /pos redirects to login', async ({ page, context }) => {
  await context.clearCookies()
  await gotoApp(page, '/pos')
  await expect(page).toHaveURL(/\/login$/)
})

test('unregistered POS blocks instead of guessing a lane', async ({ page }) => {
  const container = process.env.UI_PG_CONTAINER
  const user = process.env.UI_DB_USER || 'parking'
  const db = process.env.UI_DB_NAME || 'parking'
  expect(container, 'UI_PG_CONTAINER must be set').toBeTruthy()

  execFileSync(
    'docker',
    [
      'exec',
      container,
      'psql',
      '-U',
      user,
      '-d',
      db,
      '-c',
      "INSERT INTO gates (name, code, direction, protocol, is_active, hardware_config) VALUES ('Extra Out', 'GOUT-99', 'OUT', 'compass', true, '{}') ON CONFLICT (code) DO NOTHING",
    ],
    { stdio: 'pipe' },
  )

  await login(page)
  await gotoApp(page, '/pos')
  await expect(page.getByText('POS Tidak Terdaftar')).toBeVisible()
  await expect(page.getByText('Komputer ini belum terhubung ke booth')).toBeVisible()

  execFileSync(
    'docker',
    [
      'exec',
      container,
      'psql',
      '-U',
      user,
      '-d',
      db,
      '-c',
      "DELETE FROM gates WHERE code = 'GOUT-99'",
    ],
    { stdio: 'pipe' },
  )
})

test('anonymous /setup redirects to login once setup is complete', async ({
  page,
  context,
}) => {
  await context.clearCookies()
  await gotoApp(page, '/setup')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('button', { name: 'Masuk' })).toBeVisible()
})

test('fresh-install setup token is reachable without a JWT', async ({
  page,
  context,
}) => {
  // Re-open the wizard the way a real installer would: reset setup_complete
  // and mint a fresh one-time token. This is the regression guard for the
  // /setup ↔ /login redirect loop.
  const container = process.env.UI_PG_CONTAINER
  const user = process.env.UI_DB_USER || 'parking'
  const db = process.env.UI_DB_NAME || 'parking'
  const tokenPath = process.env.UI_SETUP_TOKEN_PATH

  expect(container, 'UI_PG_CONTAINER must be set').toBeTruthy()
  expect(tokenPath, 'UI_SETUP_TOKEN_PATH must be set').toBeTruthy()

  execFileSync(
    'docker',
    [
      'exec',
      container,
      'psql',
      '-U',
      user,
      '-d',
      db,
      '-c',
      "UPDATE settings SET value='false' WHERE key='setup_complete'",
    ],
    { stdio: 'pipe' },
  )
  fs.writeFileSync(tokenPath, 'ui-setup-token')

  await context.clearCookies()
  await gotoApp(page, '/setup?token=ui-setup-token')

  await expect(page).toHaveURL(/\/setup/)
  await expect(page.getByRole('heading', { name: 'Buat akun administrator' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Masuk' })).toHaveCount(0)
})
