self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: "window" }).then(clientList => {
      if (clientList.length > 0) {
        // Focus on first open tab
        return clientList[0].focus();
      }
      // If no open tabs, open homepage
      return clients.openWindow('/');
    })
  );
});

// Optional: handle push messages from server (Web Push)
self.addEventListener('push', function(event) {
  let payload = {};
  try {
    payload = event.data.json();
  } catch (e) {
    payload = { title: 'Notification', body: event.data ? event.data.text() : '' };
  }
  const title = payload.title || 'Notification';
  const options = { body: payload.body || '', tag: payload.tag || undefined, renotify: true };
  event.waitUntil(self.registration.showNotification(title, options));
});
