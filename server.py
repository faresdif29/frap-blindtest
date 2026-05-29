#!/usr/bin/env python3
import os, json, time, threading, random, string, queue, re
import urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

PORT = int(os.environ.get('PORT', 8080))

# ── ARTISTS POOL (server-side, pour le multijoueur) ──────────────────────────
ARTISTS = [
    {'name':'Jul','id':1191615},{'name':'GIMS','id':4429712},{'name':'Ninho','id':5542343},
    {'name':'Gazo','id':8873540},{'name':'Naps','id':4842061},{'name':'Werenoi','id':121672292},
    {'name':'PLK','id':1479842},{'name':'Koba LaD','id':14621667},{'name':'Soprano','id':13011},
    {'name':'Niska','id':5288900},{'name':'SDM','id':604107},{'name':'Tiakola','id':13918545},
    {'name':'Hamza','id':171998},{'name':'Leto','id':455796},{'name':'L2B','id':13790723},
    {'name':'Franglish','id':10695573},{'name':'KeBlack','id':7459268},{'name':'Naza','id':7459270},
    {'name':'Tayc','id':12526056},{'name':'Guy2Bezbar','id':11026886},{'name':'Niaks','id':52937632},
    {'name':'ZKR','id':14240131},{'name':'Gambi','id':65303292},{'name':'Hatik','id':12422192},
    {'name':'PNL','id':1519461},{'name':'Damso','id':9197980},{'name':'Booba','id':390},
    {'name':'Nekfeu','id':1412564},{'name':'SCH','id':162665},{'name':'Kaaris','id':388973},
    {'name':'Orelsan','id':259467},{'name':'Freeze Corleone','id':13755123},
    {'name':'Laylow','id':4510044},{'name':'Soolking','id':10189104},
    {'name':'Heuss L\'Enfoiré','id':13645509},{'name':'Zola','id':13962203},
    {'name':'Rohff','id':750},{'name':'Gradur','id':5876247},{'name':'Vald','id':5175734},
    {'name':'Dinos','id':292949},{'name':'Lomepal','id':5111084},{'name':'Josman','id':7365500},
    {'name':'Timal','id':74463},{'name':'Rsko','id':9976422},{'name':'Landy','id':14447309},
    {'name':'Kekra','id':8352118},{'name':'Da Uzi','id':11884111},{'name':'Ven1','id':243505001},
    {'name':'Morad','id':111130212},{'name':'Dosseh','id':158083},{'name':'Siboy','id':6311908},
    {'name':'IAM','id':48},{'name':'Sefyu','id':12984},{'name':'Kery James','id':5025},
    {'name':'Lino','id':6568},{'name':'Médine','id':14289},{'name':'Oxmo Puccino','id':7983},
]

CURATED = [
    3314018771,3102004051,2659306652,3045111081,1759430967,3000573421,
    3282889891,2872998762,3728009502,4002471911,3411610351,3484456821,
    3713170282,2635800932,991623302,653159322,882365842,354918041,
    414838122,133165774,135203382,602971012,463794542,84310967,
]

# ── ROOM STATE ───────────────────────────────────────────────────────────────
rooms_lock = threading.Lock()
rooms = {}  # code -> room dict

def gen_code():
    return ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=4))

def gen_id():
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))

def normalize(s):
    return re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()

def matches(g, a):
    ng, na = normalize(g), normalize(a)
    return len(ng) >= 2 and (na in ng or ng in na)

def parse_feats(title):
    m = re.search(r'\((?:feat|ft|avec|with)\.?\s+([^)]+)\)', title, re.I)
    if not m: return []
    return [f.strip() for f in re.split(r'[,&]', m.group(1)) if f.strip()]

def clean_title(title):
    return re.sub(r'\s*\((?:feat|ft|avec|with)\.?[^)]*\)', '', title, flags=re.I).strip()

def broadcast(code, data):
    msg = f"data: {json.dumps(data)}\n\n".encode()
    with rooms_lock:
        room = rooms.get(code)
        if not room: return
        dead = []
        for pid, q in room['queues'].items():
            try: q.put_nowait(msg)
            except: dead.append(pid)
        for pid in dead:
            room['queues'].pop(pid, None)

def fetch_track_deezer(path):
    url = f"https://api.deezer.com/{path}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def pick_track():
    """Pick a random track from CURATED or random artist."""
    for _ in range(5):
        try:
            if random.random() < 0.4:
                tid = random.choice(CURATED)
                t = fetch_track_deezer(f"track/{tid}")
                if t.get('preview'):
                    artist_name = t.get('artist', {}).get('name', '?')
                    match = next((a for a in ARTISTS if matches(a['name'], artist_name)), None)
                    return t, match or {'name': artist_name, 'id': t.get('artist', {}).get('id')}
            else:
                a = random.choice(ARTISTS)
                data = fetch_track_deezer(f"artist/{a['id']}/top?limit=50")
                tracks = [t for t in data.get('data', []) if t.get('preview')]
                if tracks:
                    return random.choice(tracks), a
        except: pass
    return None, None

def start_round(code):
    track, artist = pick_track()
    if not track:
        broadcast(code, {'type': 'error', 'msg': 'Impossible de charger un son'})
        return
    feats = parse_feats(track.get('title', ''))
    with rooms_lock:
        room = rooms.get(code)
        if not room: return
        room['phase'] = 'playing'
        room['track'] = track
        room['artist'] = artist
        room['feats'] = feats
        room['answers'] = {}
        room['round'] = room.get('round', 0) + 1
        round_num = room['round']
        for p in room['players'].values():
            p['answered'] = False
        room['timer_end'] = time.time() + 35
    broadcast(code, {
        'type': 'round_start',
        'round': round_num,
        'preview': track['preview'],
        'cover_blur': track.get('album', {}).get('cover_medium', ''),
        'feat_count': len(feats),
    })
    def auto_end():
        time.sleep(36)
        with rooms_lock:
            r = rooms.get(code)
            if r and r['phase'] == 'playing' and r.get('round') == round_num:
                pass
            else: return
        reveal_round(code)
    threading.Thread(target=auto_end, daemon=True).start()

def reveal_round(code):
    with rooms_lock:
        room = rooms.get(code)
        if not room or room['phase'] != 'playing': return
        room['phase'] = 'result'
        track = room['track']
        artist = room['artist']
        feats = room['feats']
        answers = dict(room['answers'])
        players_snap = [
            {'id': pid, 'name': p['name'], 'score': p['score'], 'streak': p['streak']}
            for pid, p in room['players'].items()
        ]
        players_snap.sort(key=lambda x: -x['score'])
    broadcast(code, {
        'type': 'round_result',
        'title': clean_title(track.get('title', '')),
        'artist': artist['name'],
        'feats': feats,
        'cover': track.get('album', {}).get('cover_medium', ''),
        'album': track.get('album', {}).get('title', ''),
        'answers': answers,
        'leaderboard': players_snap,
    })

def room_snapshot(code):
    room = rooms.get(code)
    if not room: return {}
    return {
        'code': code,
        'phase': room['phase'],
        'host': room['host'],
        'round': room.get('round', 0),
        'players': [
            {'id': pid, 'name': p['name'], 'score': p['score'],
             'streak': p['streak'], 'answered': p['answered']}
            for pid, p in room['players'].items()
        ],
    }

# ── HTTP SERVER ──────────────────────────────────────────────────────────────
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors(); self.end_headers()

    def do_GET(self):
        p = self.path.split('?')[0]
        if p in ('/', '/index.html'):
            self._serve_html()
        elif p.startswith('/api/deezer/'):
            self._proxy_deezer()
        elif p == '/api/room/events':
            self._sse()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(n) or b'{}')
        p = self.path.split('?')[0]
        routes = {
            '/api/room/create': self._create,
            '/api/room/join':   self._join,
            '/api/room/start':  self._start,
            '/api/room/answer': self._answer,
            '/api/room/next':   self._next,
        }
        fn = routes.get(p)
        if fn: fn(body)
        else: self.send_response(404); self.end_headers()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, data, status=200):
        b = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.send_header('Content-Length', len(b))
        self.end_headers()
        self.wfile.write(b)

    def _serve_html(self):
        try:
            with open('index.html', 'rb') as f: data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        except: self.send_response(404); self.end_headers()

    def _proxy_deezer(self):
        dpath = self.path[len('/api/deezer/'):]
        try:
            req = urllib.request.Request(f"https://api.deezer.com/{dpath}",
                                          headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self._cors()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._json({'error': str(e)}, 500)

    def _sse(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = qs.get('room', [''])[0].upper()
        pid  = qs.get('player', [''])[0]
        with rooms_lock:
            room = rooms.get(code)
            if not room or pid not in room['players']:
                self.send_response(404); self.end_headers(); return
            q = queue.Queue(maxsize=50)
            room['queues'][pid] = q
            snap = room_snapshot(code)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(f"data: {json.dumps({'type':'init','room':snap})}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=25)
                    self.wfile.write(msg)
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except:
            pass
        finally:
            with rooms_lock:
                r = rooms.get(code)
                if r: r['queues'].pop(pid, None)

    def _create(self, body):
        name = (body.get('name') or 'Player')[:20]
        pid = gen_id()
        with rooms_lock:
            code = gen_code()
            while code in rooms: code = gen_code()
            rooms[code] = {
                'players': {pid: {'name': name, 'score': 0, 'streak': 0, 'answered': False}},
                'host': pid, 'phase': 'waiting',
                'track': None, 'artist': None, 'feats': [],
                'answers': {}, 'queues': {}, 'round': 0,
            }
        self._json({'code': code, 'player_id': pid})

    def _join(self, body):
        code = (body.get('code') or '').upper().strip()
        name = (body.get('name') or 'Player')[:20]
        with rooms_lock:
            room = rooms.get(code)
            if not room:
                self._json({'error': 'Salon introuvable'}, 404); return
            if room['phase'] != 'waiting':
                self._json({'error': 'Partie déjà commencée'}, 400); return
            pid = gen_id()
            room['players'][pid] = {'name': name, 'score': 0, 'streak': 0, 'answered': False}
            snap = room_snapshot(code)
        broadcast(code, {'type': 'player_joined', 'room': snap})
        self._json({'code': code, 'player_id': pid})

    def _start(self, body):
        code = (body.get('code') or '').upper()
        pid  = body.get('player_id', '')
        with rooms_lock:
            room = rooms.get(code)
            if not room or room['host'] != pid:
                self._json({'error': 'Pas le host'}, 403); return
        threading.Thread(target=start_round, args=(code,), daemon=True).start()
        self._json({'ok': True})

    def _answer(self, body):
        code  = (body.get('code') or '').upper()
        pid   = body.get('player_id', '')
        g_art = (body.get('artist') or '').strip()
        g_ttl = (body.get('title')  or '').strip()
        g_fts = body.get('feats', [])

        with rooms_lock:
            room = rooms.get(code)
            if not room or room['phase'] != 'playing':
                self._json({'error': 'Pas en jeu'}, 400); return
            if pid not in room['players']:
                self._json({'error': 'Joueur inconnu'}, 404); return
            if room['players'][pid]['answered']:
                self._json({'error': 'Déjà répondu'}, 400); return

            track  = room['track']
            artist = room['artist']
            feats  = room['feats']
            clean_t = clean_title(track.get('title', ''))

            art_ok  = bool(g_art) and matches(g_art, artist['name'])
            ttl_ok  = bool(g_ttl) and matches(g_ttl, clean_t)
            m_feats = [f for f in feats if any(matches(g, f) for g in g_fts)]
            gained  = (1 if art_ok else 0) + (1 if ttl_ok else 0) + len(m_feats)

            p = room['players'][pid]
            p['score']    += gained
            p['streak']    = p['streak'] + 1 if gained else 0
            p['answered']  = True

            room['answers'][pid] = {
                'artist': g_art, 'title': g_ttl, 'feats': g_fts,
                'artist_ok': art_ok, 'title_ok': ttl_ok,
                'matched_feats': m_feats, 'gained': gained,
            }
            all_done = all(pl['answered'] for pl in room['players'].values())
            snap_players = [
                {'id': i, 'name': pl['name'], 'score': pl['score'],
                 'streak': pl['streak'], 'answered': pl['answered']}
                for i, pl in room['players'].items()
            ]

        broadcast(code, {'type': 'player_answered', 'players': snap_players})
        if all_done:
            threading.Thread(target=reveal_round, args=(code,), daemon=True).start()
        self._json({'ok': True, 'gained': gained})

    def _next(self, body):
        code = (body.get('code') or '').upper()
        pid  = body.get('player_id', '')
        with rooms_lock:
            room = rooms.get(code)
            if not room or room['host'] != pid:
                self._json({'error': 'Pas le host'}, 403); return
            if room['phase'] != 'result':
                self._json({'error': 'Pas en résultat'}, 400); return
        threading.Thread(target=start_round, args=(code,), daemon=True).start()
        self._json({'ok': True})

    def log_message(self, *a): pass

if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"FRAP → http://localhost:{PORT}")
    with ThreadedHTTPServer(('0.0.0.0', PORT), Handler) as s:
        s.serve_forever()
