# mini_meet_render.py
import asyncio, json, os, random, string
from aiohttp import web

# Rooms storage: room_id -> set of WebSockets
rooms = {}

def random_room_id(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

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
body {{ font-family: Arial; margin:10px; }}
#controls button {{ margin:5px; padding:5px 10px; }}
#videos {{ display:grid; grid-template-columns:repeat(auto-fill,200px); gap:10px; }}
.video-container {{ display:flex; flex-direction:column; align-items:center; }}
video {{ width:200px; border:1px solid #ccc; border-radius:4px; }}
.name-label {{ margin-top:2px; font-size:14px; color:#333; }}
#chat {{ margin-top:10px; border:1px solid #ccc; padding:5px; width:400px; height:150px; overflow-y:auto; }}
#chatInput {{ width:400px; }}
</style>
</head>
<body>
<h2>Mini Meet - Room {room_id}</h2>
<div id="controls">
<button id="copyLink">Copy Meeting Link</button>
<button id="muteBtn">Mute</button>
<button id="camBtn">Camera</button>
<button id="screenBtn">Share Screen</button>
</div>
<div id="videos"></div>
<div id="chat"></div>
<input id="chatInput" placeholder="Type a message...">
<button id="sendBtn">Send</button>

<script>
const roomId = "{room_id}";
const ws = new WebSocket(`wss://${{location.host}}/ws/${{roomId}}`);
let localStream;
const userName = prompt("Enter your name") || "Me";

// Peer connections and containers
const pcs = {{}};
const clients = {{}};

// Chat box
const chatBox = document.getElementById('chat');
function addChat(msg){{ const p=document.createElement('div'); p.textContent=msg; chatBox.appendChild(p); chatBox.scrollTop=chatBox.scrollHeight; }}

// Buttons
document.getElementById('sendBtn').onclick=()=>{{
    const val=document.getElementById('chatInput').value;
    if(val){{ ws.send(JSON.stringify({{type:'chat',from:userName,msg:val}})); document.getElementById('chatInput').value=''; }}
}};
document.getElementById('chatInput').addEventListener('keypress', e=>{{ if(e.key==='Enter') document.getElementById('sendBtn').click(); }});

document.getElementById('copyLink').onclick=()=>navigator.clipboard.writeText(window.location.href).then(()=>alert('Link copied'));
document.getElementById('muteBtn').onclick=()=>localStream.getAudioTracks().forEach(t=>t.enabled=!t.enabled);
document.getElementById('camBtn').onclick=()=>localStream.getVideoTracks().forEach(t=>t.enabled=!t.enabled);
document.getElementById('screenBtn').onclick=async()=>{{
    try {{
        const screenStream = await navigator.mediaDevices.getDisplayMedia({{video:true}});
        const track = screenStream.getVideoTracks()[0];
        Object.values(pcs).forEach(pc=>pc.getSenders().find(s=>s.track.kind==='video').replaceTrack(track));
        track.onended=()=>{{ const camTrack=localStream.getVideoTracks()[0]; Object.values(pcs).forEach(pc=>pc.getSenders().find(s=>s.track.kind==='video').replaceTrack(camTrack)); }};
    }}catch(e){{console.error(e);}}
}};

// Get camera/mic
async function initLocalStream() {{
    localStream = await navigator.mediaDevices.getUserMedia({{video:true,audio:true}});
    // Optional: hide local video
    // const localVideo = document.createElement('video');
    // localVideo.autoplay=true; localVideo.muted=true; localVideo.srcObject=localStream;
    // document.getElementById('videos').appendChild(localVideo);

    ws.onopen=()=>ws.send(JSON.stringify({{type:'join',name:userName}}));
}}
initLocalStream();

// Create a peer connection for new user
async function createPC(peerId) {{
    const pc = new RTCPeerConnection();
    pcs[peerId]=pc;
    localStream.getTracks().forEach(track=>pc.addTrack(track,localStream));

    pc.ontrack=e=>{{
        if(!clients[peerId]) {{
            const container=document.createElement('div');
            container.className='video-container';
            const v=document.createElement('video');
            v.autoplay=true; v.srcObject=e.streams[0];
            const label=document.createElement('div');
            label.className='name-label'; label.textContent=peerId;
            container.appendChild(v); container.appendChild(label);
            document.getElementById('videos').appendChild(container);
            clients[peerId]=container;
        }}
    }};

    pc.onicecandidate=e=>{{ if(e.candidate) ws.send(JSON.stringify({{type:'candidate',to:peerId,candidate:e.candidate,from:userName}})); }};
    return pc;
}}

// Signaling
ws.onmessage=async msg=>{{
    const data=JSON.parse(msg.data);
    if(data.type==='join' && data.id!==userName){{
        const pc=await createPC(data.id);
        const offer=await pc.createOffer();
        await pc.setLocalDescription(offer);
        ws.send(JSON.stringify({{type:'offer',to:data.id,from:userName,sdp:pc.localDescription}}));
    }}
    else if(data.type==='offer' && data.to===userName){{
        const pc=await createPC(data.from);
        await pcs[data.from].setRemoteDescription(data.sdp);
        const answer=await pcs[data.from].createAnswer();
        await pcs[data.from].setLocalDescription(answer);
        ws.send(JSON.stringify({{type:'answer',to:data.from,from:userName,sdp:pcs[data.from].localDescription}}));
    }}
    else if(data.type==='answer' && data.to===userName){{
        await pcs[data.from].setRemoteDescription(data.sdp);
    }}
    else if(data.type==='candidate' && data.to===userName){{
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
    room_id=request.match_info.get('room_id')
    if room_id not in rooms: rooms[room_id]=set()
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    rooms[room_id].add(ws)

    async def broadcast(msg, exclude=None):
        for peer in rooms[room_id]:
            if peer!=exclude:
                await peer.send_str(msg)

    try:
        async for msg in ws:
            if msg.type==web.WSMsgType.TEXT:
                data=json.loads(msg.data)
                if data.get('type')=='join':
                    await broadcast(json.dumps({'type':'join','id':data.get('name')}), exclude=ws)
                else:
                    await broadcast(msg.data, exclude=ws)
    finally:
        rooms[room_id].remove(ws)
        if len(rooms[room_id])==0: del rooms[room_id]
    return ws

# App
app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/room/{room_id}", index)
app.router.add_get("/ws/{room_id}", websocket_handler)

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    print(f"Server running at http://localhost:{port}")
    web.run_app(app,port=port)
