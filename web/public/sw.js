/* Service Worker:接收 Web Push 并展示系统通知(照 agu 先例,iOS PWA 需 HTTPS+加入主屏幕) */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (_) { data = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(data.title || '研判雷达', {
    body: data.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: data.tag || undefined,            // 同 tag 的通知合并替换(同一只票不叠一屏)
    renotify: !!data.tag,                  // 合并替换时仍再次提醒
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil((async () => {
    const list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    if (list.length) {
      const c = list[0];
      // iOS Safari/PWA 不支持 client.navigate,聚焦后发消息由页面自己跳(agu 实测可靠)
      try { await c.focus(); } catch (_) {}
      c.postMessage({ type: 'notif-navigate', url });
      return;
    }
    if (self.clients.openWindow) return self.clients.openWindow(url);
  })());
});
