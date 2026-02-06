# mini_meet_full_render.py
import asyncio, json, os, random, string
from aiohttp import web

# Storage for rooms
rooms = {}  # room_id -> set of websockets

# Generate random room ID
def random_room_id(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# Serve main HTML
async def index(request):
    room_id = request.match_info.get('room_id')
    if not room_id:
        raise web.HTTPFound(f"/room/{random_room_id()}")
    
    return web.Response(
        content_type="text/html",
        text=f"""
<!DOCTYPE html>
<html>
<head>
<title>Mini Meet - Room {room_id}</title>
<style>
body {{ font-family: Arial; margin:10px; text-align:center; }}
#controls button {{ margin:5px; padding:5px 10px; }}
#videos {{ display:grid; grid-template-columns:repeat(auto-fill,200px); gap:10px; justify-content:center; }}
.video-container {{ display:flex; flex-direction:column; align-items:center; border:1px solid #ccc; padding:5px; border-radius:5px; }}
video {{ width:200px; border-radius:4px; }}
.name-label {{ margin-top:2px; font-size:14px; color:#333; }}
#chat {{ margin-top:10px; border:1px solid #ccc; padding:5px; width:400px; height:150px; overflow-y:auto; margin:auto; text-align:left; }}
#chatInput {{ width:300px; }}
</style>
</head>
<body>
<h2>Mini Meet - Room {room_id}</h2>
<div id="controls">
<button id="copyLink">Copy Link</button>
<button id="muteBtn">Mute/Unmute</button>
<button id="camBtn">Camera On/Off</button>
<button id="screenBtn">Share Screen</button>
</div>

<div id="videos"></div>

<div id="chat"></div>
<input id="chatInput" placeholder="Type a message...">
<button id="sendBtn">Send</button>

<script>
const roomId = "{room_id}";
const ws = new WebSocket(`wss://${{location.host}}/ws/${{roomId}}`);
let localStream, screenStream;
const userId = Math.random().toString(36).substring(2,8);
const pcs = {{}};
const videoElems = {{}};

// Chat
const chatBox = document.getElementById('chat');
function addChat(msg) {{
    const p = document.createElement('div'); p.textContent = msg;
    chatBox.appendChild(p);
    chatBox.scrollTop = chatBox.scrollHeight;
}}

// Buttons
document.getElementById('sendBtn').onclick = ()=> {{
    const val = document.getElementById('chatInput').value;
    if(val) {{
        ws.send(JSON.stringify({{type:'chat',from:userId,msg:val}}));
        addChat('Me: '+val);
        document.getElementById('chatInput').value='';
    }}
}};
document.getElementById('chatInput').addEventListener('keypress', e=>{{ if(e.key==='Enter') document.getElementById('sendBtn').click(); }});
document.getElementById('copyLink').onclick = ()=>navigator.clipboard.writeText(window.location.href).then(()=>alert('Link copied'));
document.getElementById('muteBtn').onclick = ()=>localStream.getAudioTracks().forEach(t=>t.enabled=!t.enabled);
document.getElementById('camBtn').onclick = ()=>localStream.getVideoTracks().forEach(t=>t.enabled=!t.enabled);

// Local Stream
async function initLocalStream() {{
    localStream = await navigator.mediaDevices.getUserMedia({{video:true,audio:true}});
    addLocalVideo('Me', localStream);
    ws.onopen = ()=>ws.send(JSON.stringify({{type:'join',id:userId}}));
}}
initLocalStream();

function addLocalVideo(name, stream) {{
    const container = document.createElement('div'); container.className='video-container';
    const v = document.createElement('video'); v.autoplay=true; v.srcObject=stream;
    const label = document.createElement('div'); label.className='name-label'; label.textContent=name;
    container.appendChild(v); container.appendChild(label);
    document.getElementById('videos').appendChild(container);
    videoElems[name] = container;
}}

// Create Peer Connection
async function createPC(peerId) {{
    if(pcs[peerId]) return pcs[peerId];
    const pc = new RTCPeerConnection();
    pcs[peerId] = pc;

    // Add local camera tracks
    localStream.getTracks().forEach(track => pc.addTrack(track, localStream));

    pc.ontrack = e => {{
        const remoteName = peerId;
        if(!videoElems[remoteName]) {{
            addLocalVideo(remoteName, e.streams[0]);
        }}
    }};

    pc.onicecandidate = e => {{
        if(e.candidate) ws.send(JSON.stringify({{type:'candidate',to:peerId,from:userId,candidate:e.candidate}}));
    }};
    return pc;
}}

// Screen Sharing
document.getElementById('screenBtn').onclick = async ()=> {{
    try {{
        screenStream = await navigator.mediaDevices.getDisplayMedia({{video:true}});
        const track = screenStream.getVideoTracks()[0];
        Object.values(pcs).forEach(pc => pc.addTrack(track, screenStream));
        addLocalVideo('Screen', screenStream);

        track.onended = ()=> {{
            Object.values(pcs).forEach(pc => {{
                const senders = pc.getSenders().filter(s=>s.track.kind==='video' && s.track.label===track.label);
                senders.forEach(s=>pc.removeTrack(s));
            }});
            videoElems['Screen'].remove();
            delete videoElems['Screen'];
        }};
    }} catch(e){{console.error(e);}}
}};

// Signaling
ws.onmessage = async msg => {{
    const data = JSON.parse(msg.data);
    if(data.type==='join' && data.id!==userId){{
        const pc = await createPC(data.id);
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        ws.send(JSON.stringify({{type:'offer',to:data.id,from:userId,sdp:pc.localDescription}}));
    }}
    else if(data.type==='offer' && data.to===userId){{
        const pc = await createPC(data.from);
        await pcs[data.from].setRemoteDescription(data.sdp);
        const answer = await pcs[data.from].createAnswer();
        await pcs[data.from].setLocalDescription(answer);
        ws.send(JSON.stringify({{type:'answer',to:data.from,from:userId,sdp:pcs[data.from].localDescription}}));
    }}
    else if(data.type==='answer' && data.to===userId){{
        await pcs[data.from].setRemoteDescription(data.sdp);
    }}
    else if(data.type==='candidate' && data.to===userId){{
        await pcs[data.from].addIceCandidate(data.candidate);
    }}
    else if(data.type==='chat'){{
        addChat(data.from+': '+data.msg);
    }}
}};

</script>
</body>
</html>
"""
    )

# WebSocket handler
async def websocket_handler(request):
    room_id = request.match_info.get('room_id')
    if room_id not in rooms: rooms[room_id] = set()
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    rooms[room_id].add(ws)

    async def broadcast(msg, exclude=None):
        for peer in rooms[room_id]:
            if peer != exclude:
                await peer.send_str(msg)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get('type') == 'join':
                    await broadcast(json.dumps({'type':'join','id':data.get('id')}), exclude=ws)
                else:
                    await broadcast(msg.data, exclude=ws)
    finally:
        rooms[room_id].remove(ws)
        if len(rooms[room_id])==0: del rooms[room_id]
    return ws

# Main app
app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/room/{room_id}", index)
app.router.add_get("/ws/{room_id}", websocket_handler)

if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Server running at http://localhost:{port}")
    web.run_app(app, port=port)
