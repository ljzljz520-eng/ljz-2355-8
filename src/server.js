import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { GuideService } from './guide-service.js';
import { errorBody } from './errors.js';

const root = join(fileURLToPath(new URL('..', import.meta.url)));
const publicDir = join(root, 'public');
const port = Number(process.env.PORT ?? 3000);

const service = new GuideService();
service.createOnlinePackage('online');
service.installPackage('whole', service.createWholeManifest('2.0.0'));
service.installPackage('route-old', service.createRouteManifest(1));
service.installPackage('route', service.createRouteManifest(2));

function sendJson(res, value, status = 200) {
  const body = JSON.stringify(value, null, 2);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) reject(new Error('body too large'));
    });
    req.on('end', () => resolve(body ? JSON.parse(body) : {}));
    req.on('error', reject);
  });
}

function call(res, fn) {
  try {
    sendJson(res, fn());
  } catch (error) {
    const status = error.code?.startsWith?.('MISSING_') ? 404 : 400;
    sendJson(res, errorBody(error), error.code ? status : 500);
  }
}

async function requestHandler(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const params = url.searchParams;
  const at = params.get('at') ?? '2026-10-01T10:00:00Z';
  const pkg = params.get('package') ?? 'online';

  try {
    if (url.pathname === '/api/health') return sendJson(res, { ok: true });
    if (url.pathname === '/api/map' && req.method === 'GET') {
      return sendJson(res, service.getMap(pkg, at));
    }
    if (url.pathname === '/api/documents' && req.method === 'GET') {
      return sendJson(res, service.browseDocuments(pkg, {
        at,
        language: params.get('language') ?? 'zh',
        mode: params.get('mode'),
        floorId: params.get('floorId'),
        zoneId: params.get('zoneId'),
        maxMinutes: params.get('maxMinutes')
      }));
    }
    if (url.pathname.startsWith('/api/exhibits/') && req.method === 'GET') {
      const exhibitId = decodeURIComponent(url.pathname.split('/').pop());
      return sendJson(res, service.resolveExhibit(pkg, exhibitId, at));
    }
    if (url.pathname === '/api/route' && req.method === 'GET') {
      return sendJson(res, service.findRoute(
        pkg,
        params.get('from') ?? 'f1-lobby',
        params.get('to') ?? 'e-bronze',
        at
      ));
    }
    if (url.pathname === '/api/document' && req.method === 'GET') {
      return sendJson(res, service.getDocument(pkg, params.get('exhibitId'), {
        at,
        language: params.get('language') ?? 'zh',
        mode: params.get('mode') ?? 'short'
      }));
    }
    if (url.pathname === '/api/packages' && req.method === 'GET') {
      return sendJson(res, {
        packages: ['online', 'whole', 'route', 'route-old'].map((id) => service.packageStatus(id)),
        targetRouteManifest: service.createRouteManifest(2)
      });
    }
    if (url.pathname === '/api/update/session' && req.method === 'POST') {
      const body = await readBody(req);
      return sendJson(res, service.startUpdate(body.packageId ?? 'route-old', service.createRouteManifest(2), {
        missingBlockKeys: body.missingBlockKeys ?? []
      }), 201);
    }
    if (url.pathname === '/api/update/chunk' && req.method === 'POST') {
      const body = await readBody(req);
      return sendJson(res, service.downloadChunk(body.sessionId, body.key, Number(body.index)));
    }
    if (url.pathname === '/api/update/activate' && req.method === 'POST') {
      const body = await readBody(req);
      return sendJson(res, service.activateUpdate(body.sessionId));
    }
    if (url.pathname === '/api/update/rollback' && req.method === 'POST') {
      const body = await readBody(req);
      return sendJson(res, service.rollbackPackage(body.packageId ?? 'route-old'));
    }

    const requestedPath = url.pathname === '/' ? '/index.html' : url.pathname;
    const filePath = join(publicDir, requestedPath);
    if (!filePath.startsWith(publicDir)) {
      return sendJson(res, errorBody({ message: 'forbidden' }), 403);
    }
    const content = await readFile(filePath);
    const type = {
      '.html': 'text/html; charset=utf-8',
      '.js': 'text/javascript; charset=utf-8',
      '.css': 'text/css; charset=utf-8',
      '.json': 'application/json; charset=utf-8'
    }[extname(filePath)] ?? 'application/octet-stream';
    res.writeHead(200, { 'content-type': type });
    return res.end(content);
  } catch (error) {
    const status = error.code === 'ENOENT' ? 404 : (error.code?.startsWith?.('MISSING_') ? 404 : 400);
    return sendJson(res, errorBody(error), error.code ? status : 500);
  }
}

const server = http.createServer((req, res) => {
  requestHandler(req, res).catch((error) => sendJson(res, errorBody(error), 500));
});

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  server.listen(port, () => {
    console.log(`展馆导览资料站 listening on http://localhost:${port}`);
  });
}

export { server, service };
