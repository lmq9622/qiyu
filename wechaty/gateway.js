/* Qiyu Wechaty gateway: Python backend bridges via HTTP */
const http = require('http')
const PORT = parseInt(process.env.QIYU_GATEWAY_PORT || '18765', 10)
const HOST = process.env.QIYU_GATEWAY_HOST || '127.0.0.1'
const CALLBACK_URL = process.env.QIYU_CALLBACK_URL || ''
const CALLBACK_SECRET = process.env.QIYU_CALLBACK_SECRET || ''
const PUPPET = process.env.WECHATY_PUPPET || 'wechaty-puppet-wechat4u'
const TOKEN = process.env.WECHATY_PUPPET_SERVICE_TOKEN || ''
const state = { state: 'idle', qr: '', qrStatus: 0, user: '', userAvatar: '', message: '', startedAt: 0, msgCount: 0 }
let botStarted = false
function setState(partial) {
  Object.assign(state, partial)
  console.log('[gateway] state=' + state.state + ' qrStatus=' + state.qrStatus + ' user=' + state.user)
}
function json(res, code, obj) {
  const body = JSON.stringify(obj)
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(body) })
  res.end(body)
}
function readBody(req) {
  return new Promise((resolve) => {
    let data = ''
    req.on('data', (c) => { data += c; if (data.length > 20 * 1024 * 1024) req.destroy() })
    req.on('end', () => { try { resolve(data ? JSON.parse(data) : {}) } catch (e) { resolve({}) } })
    req.on('error', () => resolve({}))
  })
}
function pushInbound(payload) {
  if (!CALLBACK_URL) return
  try {
    const body = JSON.stringify(payload)
    const u = new URL(CALLBACK_URL)
    const headers = {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body),
      'X-Qiyu-Secret': CALLBACK_SECRET,
    }
    const req = http.request({ hostname: u.hostname, port: u.port || 80, path: u.pathname + u.search, method: 'POST', headers }, (r) => { r.resume() })
    req.on('error', (e) => console.error('[gateway] callback error:', e.message))
    req.write(body)
    req.end()
  } catch (e) {
    console.error('[gateway] callback error:', e.message)
  }
}
let bot = null
let fileBox = null
try {
  const { WechatyBuilder } = require('wechaty')
  fileBox = require('file-box')
  const options = { name: 'qiyu-wechaty', puppet: PUPPET }
  if (PUPPET === 'wechaty-puppet-service') {
    if (!TOKEN) {
      setState({ state: 'error', message: 'service puppet needs WECHATY_PUPPET_SERVICE_TOKEN' })
    } else {
      process.env.WECHATY_PUPPET_SERVICE_TOKEN = TOKEN
    }
  }
  bot = WechatyBuilder.build(options)
  bot.on('scan', (qrcode, status) => {
    const scanned = status === 3
    setState({ state: scanned ? 'scanned' : 'waiting', qr: qrcode || '', qrStatus: status || 0,
      message: scanned ? 'scanned, confirm on phone' : 'scan qr with wechat' })
  })
  bot.on('login', (user) => {
    setState({ state: 'loggedin', qr: '', user: user.name() || user.id(), message: 'login ok', startedAt: Date.now() })
    pushInbound({ type: 'login', from: state.user, ts: Date.now() })
  })
  bot.on('logout', (user, reason) => {
    setState({ state: 'logout', qr: '', user: '', message: 'logged out: ' + (reason || '') })
  })
  bot.on('error', (e) => {
    console.error('[gateway] wechaty error:', e && e.message)
    setState({ state: 'error', message: 'wechaty error: ' + (e && e.message || e) })
  })
bot.on('message', async (msg) => {
    try {
      if (msg.self()) return
      const room = msg.room()
      if (room) {
        const mentionSelf = await msg.mentionSelf()
        if (!mentionSelf) return
      }
      const talker = msg.talker()
      const from = talker.id()
      const fromName = talker.name()
      const text = msg.text() || ''
      const payload = { type: 'message', from: from, fromName: fromName, text: text, room: room ? room.id : '', ts: Date.now(), msgId: msg.id || '' }
      try {
        const fb = await msg.toFileBox()
        if (fb) {
          const buf = await fb.toBuffer()
          if (buf && buf.length > 0 && buf.length < 8 * 1024 * 1024) {
            payload.image = 'data:' + (fb.mimeType || 'application/octet-stream') + ';base64,' + buf.toString('base64')
            payload.fileName = fb.name || ''
          }
        }
      } catch (e) { /* no attachment */ }
      state.msgCount += 1
      pushInbound(payload)
    } catch (e) {
      console.error('[gateway] message handler error:', e && e.message)
    }
  })
} catch (e) {
  console.error('[gateway] wechaty load error:', e && e.message)
  process.exit(2)
}
async function sendText(to, text) {
  if (!bot || !bot.currentUser) return { ok: false, message: 'not logged in' }
  const contact = await bot.Contact.find({ id: to })
  if (!contact) return { ok: false, message: 'contact not found' }
  await contact.say(text)
  return { ok: true }
}
async function sendImage(to, image, fileName) {
  if (!bot || !bot.currentUser) return { ok: false, message: 'not logged in' }
  const contact = await bot.Contact.find({ id: to })
  if (!contact) return { ok: false, message: 'contact not found' }
  let b64 = image
  if (image.startsWith('data:')) {
    b64 = image.replace(/^data:[^,]+,/, '')
  }
  const buf = Buffer.from(b64, 'base64')
  const fb = fileBox.FileBox.fromBuffer(buf, fileName || ('image_' + Date.now() + '.png'))
  await contact.say(fb)
  return { ok: true }
}
async function logoutAndExit() {
  try {
    if (bot) { await bot.logout(); await bot.stop() }
  } catch (e) { /* ignore */ }
  setTimeout(() => process.exit(0), 500)
}
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://' + HOST + ':' + PORT)
  try {
    if (req.method === 'GET' && u.pathname === '/status') {
      return json(res, 200, Object.assign({ ok: true }, state))
    }
    if (req.method === 'POST' && u.pathname === '/start') {
      if (bot == null) return json(res, 400, { ok: false, message: 'wechaty not loaded' })
      if (botStarted) return json(res, 200, { ok: true, message: 'already started' })
      botStarted = true
      try {
        await bot.start()
        return json(res, 200, { ok: true, message: 'started' })
      } catch (e) {
        botStarted = false
        setState({ state: 'error', message: 'start failed: ' + (e && e.message || e) })
        return json(res, 500, { ok: false, message: e && e.message || String(e) })
      }
    }
    if (req.method === 'POST' && u.pathname === '/send') {
      const b = await readBody(req)
      if (b.image) return json(res, 200, await sendImage(b.to, b.image, b.fileName))
      if (b.text) return json(res, 200, await sendText(b.to, b.text))
      return json(res, 400, { ok: false, message: 'missing to/text/image' })
    }
    if (req.method === 'POST' && u.pathname === '/stop') {
      json(res, 200, { ok: true })
      logoutAndExit()
      return
    }
    if (req.method === 'GET' && u.pathname === '/ping') {
      return json(res, 200, { ok: true, pid: process.pid })
    }
    json(res, 404, { ok: false, message: 'not found' })
  } catch (e) {
    json(res, 500, { ok: false, message: e && e.message || String(e) })
  }
})
server.on('error', (e) => {
  if (e && e.code === 'EADDRINUSE') {
    console.error('[gateway] port ' + PORT + ' already in use by another gateway, exiting (3)')
  } else {
    console.error('[gateway] http server error:', e && e.message)
  }
  process.exit(3)
})
server.listen(PORT, HOST, () => {
  console.log('[gateway] Qiyu Wechaty gateway on ' + HOST + ':' + PORT + ' puppet=' + PUPPET)
  setState({ state: 'idle', message: 'gateway ready' })
})
process.on('SIGTERM', logoutAndExit)
process.on('SIGINT', logoutAndExit)
