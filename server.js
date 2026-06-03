// ============================================================
// FenixTV — Backend Railway con Firebase
// Reemplaza tu server.js actual con este archivo
// npm install express firebase-admin cors
// ============================================================

const express = require('express');
const cors = require('cors');
const { initializeApp, cert } = require('firebase-admin/app');
const { getDatabase } = require('firebase-admin/database');
const path = require('path');
const fs = require('fs');

const app = express();
app.use(express.json());
app.use(cors());

// ─── Firebase Admin Init ───────────────────────────────────
// OPCIÓN A: Con service account JSON (recomendado para Railway)
// Pon tus credenciales en variable de entorno FIREBASE_SERVICE_ACCOUNT
let firebaseApp;
try {
  const serviceAccount = process.env.FIREBASE_SERVICE_ACCOUNT
    ? JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT)
    : require('./serviceAccountKey.json'); // fallback local

  firebaseApp = initializeApp({
    credential: cert(serviceAccount),
    databaseURL: "https://helio-santino-rp-default-rtdb.firebaseio.com"
  });
} catch(e) {
  console.error('Firebase init error:', e.message);
  console.log('Asegúrate de tener FIREBASE_SERVICE_ACCOUNT en variables de entorno de Railway');
}

const db = getDatabase(firebaseApp);

// ─── Servir el panel ───────────────────────────────────────
app.get('/mac-panel', (req, res) => {
  const panelPath = path.join(__dirname, 'public', 'mac-panel.html');
  if (fs.existsSync(panelPath)) {
    res.sendFile(panelPath);
  } else {
    res.status(404).send('Panel no encontrado. Coloca mac-panel.html en /public/');
  }
});

// ─── API: Buscar MAC en Firebase ──────────────────────────
// La app FenixTV llama a este endpoint con la MAC del dispositivo
app.get('/api/mac/:mac', async (req, res) => {
  const macParam = decodeURIComponent(req.params.mac).toUpperCase();
  const macKey = macParam.replace(/:/g, '-');

  console.log(`[MAC LOOKUP] ${macParam}`);

  try {
    // Buscar en todos los usuarios (cualquier admin puede registrar MACs)
    const allUsers = await db.ref('users').get();
    if (!allUsers.exists()) {
      return res.json({ found: false, message: 'Sin MACs registradas' });
    }

    const usersData = allUsers.val();
    let found = null;

    // Buscar por MAC normalizada (reemplazando : por -)
    outer:
    for (const uid of Object.keys(usersData)) {
      const macs = usersData[uid].macs || {};
      for (const key of Object.keys(macs)) {
        const entry = macs[key];
        const entryMac = (entry.mac || key.replace(/-/g, ':')).toUpperCase();
        if (entryMac === macParam || key === macKey) {
          found = entry;
          break outer;
        }
      }
    }

    if (!found || !found.list) {
      return res.json({ found: false, message: 'MAC no registrada o sin lista asignada' });
    }

    console.log(`[MAC FOUND] ${macParam} → ${found.listType} | ${found.name || 'Sin nombre'}`);

    return res.json({
      found: true,
      mac: macParam,
      name: found.name || 'Fenix TV',
      url: found.url || found.list,
      listType: found.listType || 'm3u',
      // Para Xtream, también devuelve las credenciales por si la app las necesita
      ...(found.listType === 'xtream' ? {
        xtreamServer: found.xtreamServer,
        xtreamUser: found.xtreamUser,
        xtreamPass: found.xtreamPass,
      } : {})
    });

  } catch(err) {
    console.error('[MAC ERROR]', err);
    res.status(500).json({ found: false, error: 'Error interno del servidor' });
  }
});

// ─── API: Registrar MAC desde la app (auto-registro) ──────
// Opcional: la app puede registrar su propia MAC automáticamente
app.post('/api/mac/register', async (req, res) => {
  const { mac, deviceName } = req.body;
  if (!mac) return res.status(400).json({ ok: false, error: 'MAC requerida' });

  const macKey = mac.toUpperCase().replace(/:/g, '-');

  // Guardar en un nodo "pendientes" para que el admin la asigne desde el panel
  await db.ref(`pending_macs/${macKey}`).set({
    mac: mac.toUpperCase(),
    deviceName: deviceName || 'Desconocido',
    registeredAt: Date.now()
  });

  res.json({ ok: true, message: 'MAC registrada como pendiente' });
});

// ─── API: MACs pendientes de asignar ──────────────────────
app.get('/api/pending-macs', async (req, res) => {
  try {
    const snap = await db.ref('pending_macs').get();
    res.json(snap.val() || {});
  } catch(e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── Health check ─────────────────────────────────────────
app.get('/health', (req, res) => res.json({ ok: true, time: new Date().toISOString() }));
app.get('/', (req, res) => res.redirect('/mac-panel'));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`FenixTV Panel corriendo en puerto ${PORT}`));

module.exports = app;
