import socket
import threading
import json
import time
import math
import random

# Bind to your specified IP and port
SERVER_IP = "10.50.25.236"
SERVER_PORT = 7777

# Game constants
TICK_RATE = 60
MAP_WIDTH = 2000
MAP_HEIGHT = 2000

# Game state
players = {}
bullets = []
lock = threading.Lock()
bullet_id = 0

def gen_id():
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))

def broadcast(msg, exclude=None):
    data = json.dumps(msg).encode() + b'\n'
    with lock:
        dead = []
        for pid, p in players.items():
            if pid == exclude:
                continue
            try:
                p['sock'].send(data)
            except:
                dead.append(pid)
        for pid in dead:
            if pid in players:
                del players[pid]

def broadcast_all(msg):
    broadcast(msg, None)

def handle_client(sock, addr):
    global bullet_id
    player_id = gen_id()
    
    with lock:
        players[player_id] = {
            'id': player_id,
            'sock': sock,
            'addr': addr,
            'x': random.randint(100, MAP_WIDTH - 100),
            'y': random.randint(100, MAP_HEIGHT - 100),
            'angle': 0,
            'health': 100,
            'maxHealth': 100,
            'speed': 5,
            'radius': 20,
            'color': f'hsl({random.randint(0, 360)}, 70%, 50%)',
            'name': f'Player {player_id[:4]}',
            'score': 0,
            'lastShot': 0,
            'keys': {'w': False, 'a': False, 's': False, 'd': False}
        }
    
    # Send init
    try:
        init_msg = json.dumps({
            'type': 'init',
            'playerId': player_id,
            'players': {k: {key: v[key] for key in v if key not in ['sock']} for k, v in players.items()},
            'map': {'width': MAP_WIDTH, 'height': MAP_HEIGHT}
        }).encode() + b'\n'
        sock.send(init_msg)
    except:
        with lock:
            if player_id in players:
                del players[player_id]
        return
    
    broadcast({'type': 'playerJoined', 'player': {k: v for k, v in players[player_id].items() if k != 'sock'}}, player_id)
    print(f"[+] {player_id} connected from {addr} | Total: {len(players)}")
    
    # Receive loop
    buffer = b''
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    data = json.loads(line.decode())
                except:
                    continue
                
                with lock:
                    if player_id not in players:
                        break
                    p = players[player_id]
                    
                    if data.get('type') == 'input':
                        if 'keys' in data:
                            p['keys'] = data['keys']
                        if 'angle' in data:
                            p['angle'] = data['angle']
                    
                    elif data.get('type') == 'shoot':
                        now = time.time() * 1000
                        if now - p['lastShot'] < 150:
                            continue
                        p['lastShot'] = now
                        
                        b = {
                            'id': bullet_id,
                            'ownerId': player_id,
                            'x': p['x'] + math.cos(p['angle']) * 30,
                            'y': p['y'] + math.sin(p['angle']) * 30,
                            'vx': math.cos(p['angle']) * 15,
                            'vy': math.sin(p['angle']) * 15,
                            'damage': 25,
                            'life': 100
                        }
                        bullet_id += 1
                        bullets.append(b)
                    
                    elif data.get('type') == 'name':
                        name = data.get('name', '')[:16]
                        if name:
                            p['name'] = name
                            broadcast_all({'type': 'playerUpdate', 'player': {k: v for k, v in p.items() if k != 'sock'}})
                        
        except Exception as e:
            print(f"[!] Error with {player_id}: {e}")
            break
    
    # Disconnect
    with lock:
        if player_id in players:
            del players[player_id]
    broadcast_all({'type': 'playerLeft', 'playerId': player_id})
    print(f"[-] {player_id} disconnected | Total: {len(players)}")
    try:
        sock.close()
    except:
        pass

def game_loop():
    while True:
        start = time.time()
        
        with lock:
            # Update player positions
            for pid, p in players.items():
                dx, dy = 0, 0
                if p['keys'].get('w'): dy -= 1
                if p['keys'].get('s'): dy += 1
                if p['keys'].get('a'): dx -= 1
                if p['keys'].get('d'): dx += 1
                
                if dx != 0 and dy != 0:
                    dx *= 0.707
                    dy *= 0.707
                
                p['x'] += dx * p['speed']
                p['y'] += dy * p['speed']
                p['x'] = max(p['radius'], min(MAP_WIDTH - p['radius'], p['x']))
                p['y'] = max(p['radius'], min(MAP_HEIGHT - p['radius'], p['y']))
            
            # Update bullets
            i = len(bullets) - 1
            while i >= 0:
                b = bullets[i]
                b['x'] += b['vx']
                b['y'] += b['vy']
                b['life'] -= 1
                
                if b['x'] < 0 or b['x'] > MAP_WIDTH or b['y'] < 0 or b['y'] > MAP_HEIGHT:
                    b['life'] = 0
                
                # Collision check
                for pid, p in players.items():
                    if pid == b['ownerId']:
                        continue
                    dist = math.hypot(b['x'] - p['x'], b['y'] - p['y'])
                    if dist < p['radius'] + 5:
                        p['health'] -= b['damage']
                        b['life'] = 0
                        
                        if p['health'] <= 0:
                            if b['ownerId'] in players:
                                players[b['ownerId']]['score'] += 1
                            p['health'] = p['maxHealth']
                            p['x'] = random.randint(100, MAP_WIDTH - 100)
                            p['y'] = random.randint(100, MAP_HEIGHT - 100)
                            
                            broadcast_all({
                                'type': 'kill',
                                'killer': players[b['ownerId']]['name'] if b['ownerId'] in players else 'Unknown',
                                'victim': p['name']
                            })
                        break
                
                if b['life'] <= 0:
                    bullets.pop(i)
                i -= 1
            
            # Build state
            state = {
                'type': 'state',
                'players': {k: {key: v[key] for key in v if key not in ['sock']} for k, v in players.items()},
                'bullets': bullets,
                'timestamp': time.time()
            }
        
        broadcast_all(state)
        
        elapsed = time.time() - start
        sleep_time = max(0, (1.0 / TICK_RATE) - elapsed)
        time.sleep(sleep_time)

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((SERVER_IP, SERVER_PORT))
    server.listen(10)
    
    print(f"[*] Server bound to {SERVER_IP}:{SERVER_PORT}")
    print(f"[*] Waiting for connections...")
    
    # Start game loop
    threading.Thread(target=game_loop, daemon=True).start()
    
    while True:
        sock, addr = server.accept()
        sock.settimeout(30)
        threading.Thread(target=handle_client, args=(sock, addr), daemon=True).start()

if __name__ == '__main__':
    main()