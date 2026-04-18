"""
Battlespire data parsers: BSA archives, BSI textures, .3D models, BS6 scenes.
Pure Python + optional numpy. No Blender dependency.
"""
import os, math
from array import array
from io import BytesIO
from struct import unpack_from, iter_unpack, calcsize, unpack

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

SCENE_SCALE = 0.0256
_B40 = "0123456789abcdefghijklmnopqrstuvwxyz~_#%"

def decode_texture_name(tex_raw, u2_first2):
    if tex_raw >= 0xFFFE: return None
    combined = (u2_first2 << 16) | tex_raw
    if combined == 0: return None
    chars = []; val = combined
    for _ in range(6): chars.append(_B40[val % 40]); val //= 40
    return ''.join(reversed(chars)).lstrip('0').rstrip('%') or None

def _lzss(fd):
    window = array('B', b' ' * 4078 + b'\x00' * 18)
    pos = 4078; out = BytesIO()
    def emit(b):
        nonlocal pos
        window[pos] = b; pos = (pos + 1) & 0xFFF; out.write(bytes([b]))
    try:
        while True:
            b = fd.read(1)
            if not b: break
            flags = b[0]
            for bit in range(8):
                if flags & (1 << bit):
                    nxt = fd.read(1)
                    if not nxt: raise IndexError
                    emit(nxt[0])
                else:
                    code = fd.read(2)
                    if len(code) < 2: raise IndexError
                    off = code[0] | (code[1] & 0xF0) << 4
                    ln = (code[1] & 0xF) + 3
                    for x in range(off, off + ln): emit(window[x & 0xFFF])
    except IndexError: pass
    return out.getvalue()

class BSAArchive:
    def __init__(self, path):
        with open(path, 'rb') as f: self._data = f.read()
        count, _ = unpack_from('<2H', self._data, 0)
        fmt = '<12sHI'; sz = calcsize(fmt)
        footer = self._data[len(self._data) - count * sz:]
        self._toc = {}; offset = 4
        for name_raw, compressed, size in iter_unpack(fmt, footer):
            name = bytes(name_raw).decode(errors='replace').rstrip('\x00')
            self._toc[name] = (offset, size, bool(compressed)); offset += size
        self._cache = {}
    def names(self, ext=None):
        if ext:
            e = ext.upper(); return [n for n in self._toc if n.upper().endswith(e)]
        return list(self._toc.keys())
    def has(self, name): return name in self._toc
    def get(self, name):
        if name in self._cache: return self._cache[name]
        if name not in self._toc: return None
        o, s, c = self._toc[name]; raw = self._data[o:o+s]
        if c:
            try: raw = _lzss(BytesIO(raw))
            except: pass
        self._cache[name] = raw; return raw

# ═══════════════════════════════════════════════════════════════════════════
#  BSI
# ═══════════════════════════════════════════════════════════════════════════
def _bsi_chunks(data):
    chunks = {}
    pos = 8 if (len(data) >= 4 and data[0:4] == b'BSIF') else 0
    while pos + 8 <= len(data):
        tag = data[pos:pos+4].decode('ascii', errors='replace')
        length = unpack_from('>I', data, pos + 4)[0]
        if tag == 'END ': break
        if tag == 'BSIF': pos += 8; continue
        if tag not in chunks: chunks[tag] = data[pos+8:pos+8+length]
        pos += 8 + length
    return chunks

def bsi_get_size(bsi_data):
    chunks = _bsi_chunks(bsi_data); bhdr = chunks.get('BHDR')
    if not bhdr or len(bhdr) < 26: return None
    w, h = unpack_from('<2h', bhdr, 4)
    return (w, h) if w > 0 and h > 0 else None

def bsi_get_frames(bsi_data):
    chunks = _bsi_chunks(bsi_data); bhdr = chunks.get('BHDR')
    if not bhdr or len(bhdr) < 26: return None
    w, h = unpack_from('<2h', bhdr, 4)
    frames = unpack_from('<h', bhdr, 14)[0]
    if w <= 0 or h <= 0 or frames <= 0: return None
    return (w, h, frames)

def _bsi_decompress(data, width, th):
    out = bytearray()
    for line in range(th):
        if line*4+4 > len(data): out.extend(b'\x00'*width); continue
        idx = unpack_from('<I', data, line*4)[0]
        is_rle = bool(idx & 0x80000000); off = idx & 0x7FFFFFFF
        if not is_rle: out.extend(data[off:off+width])
        else:
            f = BytesIO(data[off:]); w = 0
            while w < width:
                c = f.read(1)
                if not c: out.extend(b'\x00'*(width-w)); break
                c = c[0]
                if c & 0x80:
                    n=c&0x7F; p=f.read(1)
                    if not p: out.extend(b'\x00'*(width-w)); break
                    out.extend(p*n); w+=n
                else:
                    blk=f.read(c); out.extend(blk); w+=len(blk)
                    if len(blk)<c: out.extend(b'\x00'*(c-len(blk)))
    return bytes(out)

def _bsi_build_palette(hicl):
    pal = [(0.0,0.0,0.0,1.0)]*256
    for i in range(min(128, len(hicl)//2)):
        c = unpack_from('<H', hicl, i*2)[0]
        pal[i<<1] = (((c>>11)&0x1F)/31.0,((c>>6)&0x1F)/31.0,((c>>1)&0x1F)/31.0,1.0)
    pal[0] = (0.0, 0.0, 0.0, 0.0)
    return pal

def bsi_decode_image(bsi_data):
    chunks = _bsi_chunks(bsi_data); bhdr = chunks.get('BHDR')
    if not bhdr or len(bhdr) < 26: return None
    w, h = unpack_from('<2h', bhdr, 4)
    frames = unpack_from('<h', bhdr, 14)[0]; flags = unpack_from('<h', bhdr, 24)[0]
    if w <= 0 or h <= 0: return None
    img_data = chunks.get('DATA'); hicl = chunks.get('HICL')
    if not img_data or not hicl: return None
    total_h = h * max(frames, 1)
    if flags != 0: pixel_data = _bsi_decompress(img_data, w, total_h)
    else: pixel_data = img_data[:w*total_h]
    pal = _bsi_build_palette(hicl)
    frame = pixel_data[:w*h]
    if HAS_NP:
        pal_np = np.array(pal, dtype=np.float32)
        pix = np.frombuffer(frame, dtype=np.uint8).copy()
        if len(pix)<w*h: pix=np.pad(pix,(0,w*h-len(pix)))
        rgba = pal_np[pix].reshape(h,w,4)[::-1].flatten()
        return (w, h, rgba.tolist())
    else:
        pixels=[0.0]*(w*h*4)
        for row in range(h):
            dr=h-1-row
            for col in range(w):
                si=row*w+col; di=(dr*w+col)*4; idx=frame[si] if si<len(frame) else 0
                r,g,b,a=pal[idx]; pixels[di]=r; pixels[di+1]=g; pixels[di+2]=b; pixels[di+3]=a
        return (w, h, pixels)

def bsi_decode_all_frames(bsi_data):
    """Decode ALL frames from a multi-frame BSI. Returns list of (w, h, pixels) or None."""
    chunks = _bsi_chunks(bsi_data); bhdr = chunks.get('BHDR')
    if not bhdr or len(bhdr) < 26: return None
    w, h = unpack_from('<2h', bhdr, 4)
    frames = max(unpack_from('<h', bhdr, 14)[0], 1); flags = unpack_from('<h', bhdr, 24)[0]
    if w <= 0 or h <= 0 or frames <= 1: return None
    img_data = chunks.get('DATA'); hicl = chunks.get('HICL')
    if not img_data or not hicl: return None
    total_h = h * frames
    if flags != 0: pixel_data = _bsi_decompress(img_data, w, total_h)
    else: pixel_data = img_data[:w*total_h]
    pal = _bsi_build_palette(hicl)
    result = []
    for fi in range(frames):
        frame = pixel_data[fi*w*h:(fi+1)*w*h]
        if HAS_NP:
            pal_np = np.array(pal, dtype=np.float32)
            pix = np.frombuffer(frame, dtype=np.uint8).copy()
            if len(pix)<w*h: pix=np.pad(pix,(0,w*h-len(pix)))
            rgba = pal_np[pix].reshape(h,w,4)[::-1].flatten()
            result.append((w, h, rgba.tolist()))
        else:
            pixels=[0.0]*(w*h*4)
            for row in range(h):
                dr=h-1-row
                for col in range(w):
                    si=row*w+col; di=(dr*w+col)*4; idx=frame[si] if si<len(frame) else 0
                    r,g,b,a=pal[idx]; pixels[di]=r; pixels[di+1]=g; pixels[di+2]=b; pixels[di+3]=a
            result.append((w, h, pixels))
    return result

# ═══════════════════════════════════════════════════════════════════════════
#  UV / .3D / BS6 / LEVELS.TXT
# ═══════════════════════════════════════════════════════════════════════════

def _uv_from_xyz(pts, uvs, tp):
    if len(pts)<3 or len(uvs)<3: return uvs[-1] if uvs else (0.0,0.0)
    try:
        p0,p1,p2=pts[0],pts[1],pts[2]; u0,v0=uvs[0]; u1,v1=uvs[1]; u2,v2=uvs[2]
        e1=(p1[0]-p0[0],p1[1]-p0[1],p1[2]-p0[2]); e2=(p2[0]-p0[0],p2[1]-p0[1],p2[2]-p0[2])
        eu1=(u1-u0,v1-v0); eu2=(u2-u0,v2-v0); et=(tp[0]-p0[0],tp[1]-p0[1],tp[2]-p0[2])
        d11=sum(a*b for a,b in zip(e1,e1)); d12=sum(a*b for a,b in zip(e1,e2))
        d22=sum(a*b for a,b in zip(e2,e2)); d1t=sum(a*b for a,b in zip(e1,et))
        d2t=sum(a*b for a,b in zip(e2,et)); dn=d11*d22-d12*d12
        if abs(dn)<1e-10: return uvs[-1]
        s=(d22*d1t-d12*d2t)/dn; t=(d11*d2t-d12*d1t)/dn
        return(u0+s*eu1[0]+t*eu2[0], v0+s*eu1[1]+t*eu2[1])
    except: return uvs[-1] if uvs else (0.0,0.0)

def parse_3d(data, tex_sizes):
    if len(data) < 64: return None
    try:
        keys = ['pointCount','planeCount','radius','u1','u2','planeDataOffset','objectListOffset',
                'objectCount','u3','u4','u5','pointListOffset','normalListOffset','u6','planeListOffset']
        hdr = dict(zip(keys, unpack_from('<15I', data, 4)))
    except: return None
    pd = data[hdr['pointListOffset']:hdr['pointListOffset']+hdr['pointCount']*12]
    points = [(x*0.0001,y*0.0001,z*0.0001) for x,y,z in iter_unpack('<3i', pd)]
    nd = data[hdr['normalListOffset']:hdr['normalListOffset']+hdr['planeCount']*12]
    normals = list(iter_unpack('<3i', nd))
    planes=[]; texture_names=set(); fio = BytesIO(data[hdr['planeListOffset']:])
    for pi in range(hdr['planeCount']):
        h10=fio.read(10)
        if len(h10)<10: break
        pt_count,u1b,tex_raw,u2_6=unpack('<2BH6s',h10); u2f2=unpack('<H',u2_6[:2])[0]
        tex_name=decode_texture_name(tex_raw,u2f2)
        if tex_name: texture_names.add(tex_name)
        sz=tex_sizes.get(tex_name) if tex_name else None
        tw=float(sz[0]) if sz else 128.0; th=float(sz[1]) if sz else 128.0
        if tex_raw>=0xFFFE: color=(0.55,0.55,0.55)
        else: color=((tex_raw&0x1F)/31.0,((tex_raw>>5)&0x1F)/31.0,((tex_raw>>10)&0x1F)/31.0)
        raw_uv=[]; raw_pts=[]
        for vi in range(pt_count):
            pr=fio.read(8)
            if len(pr)<8: break
            pidx_r,ur,vr=unpack('<IHH',pr); pidx=pidx_r//12
            px,py,pz=points[pidx] if pidx<len(points) else (0,0,0)
            raw_uv.append((ur,vr)); raw_pts.append((px,py,pz))
        texel_uv=[]
        for vi,(ur,vr) in enumerate(raw_uv):
            us=ur-65536 if ur>=32768 else ur; vs=vr-65536 if vr>=32768 else vr
            ut=us/16.0; vt=vs/16.0
            if vi==0: cu,cv=ut,vt
            elif vi<=2: cu+=ut; cv+=vt
            else:
                if len(texel_uv)>=3: cu,cv=_uv_from_xyz(raw_pts,texel_uv,raw_pts[vi])
            texel_uv.append((cu,cv))
        verts=[]
        for vi,(px,py,pz) in enumerate(raw_pts):
            if vi<len(texel_uv): u=texel_uv[vi][0]/tw; v=-texel_uv[vi][1]/th
            else: u,v=0.0,0.0
            verts.append((px,py,pz,u,v))
        nrm=normals[pi] if pi<len(normals) else (0,0,1)
        nx,ny,nz=nrm; L=math.sqrt(nx*nx+ny*ny+nz*nz) or 1.0
        planes.append({'color':color,'vertices':verts,'normal':(nx/L,ny/L,nz/L),'texture_name':tex_name})
    return {'points':points,'planes':planes,'radius':hdr['radius']*0.0001,'texture_names':sorted(texture_names)}

def bs6_blocks(data):
    pos = 0
    while pos + 8 <= len(data):
        name = data[pos:pos+4].decode('ascii', errors='replace')
        length = unpack_from('<I', data, pos+4)[0]
        yield name, data[pos+8:pos+8+length]; pos += 8 + length

def parse_bs6_scene(data):
    objects = []
    for tag, chunk in bs6_blocks(data):
        if tag != 'GNRL': continue
        for tag2, chunk2 in bs6_blocks(chunk):
            if tag2 != 'OBJS': continue
            mesh_names = []
            for tag3, chunk3 in bs6_blocks(chunk2):
                if tag3 == 'LFIL':
                    for name_raw, in iter_unpack('260s', chunk3):
                        n = name_raw.decode(errors='replace').rstrip('\x00')
                        mesh_names.append(n if n else '')
                elif tag3 == 'OBJD':
                    idfi=pos=rot=None; ctrl_move=None; ctrl_rot=None
                    for tag4, chunk4 in bs6_blocks(chunk3):
                        if tag4=='IDFI': idfi=unpack_from('<I',chunk4)[0]
                        elif tag4=='POSI': pos=unpack_from('<3i',chunk4)
                        elif tag4=='ANGS': rot=unpack_from('<3i',chunk4)
                        elif tag4=='CTRL':
                            idnb=0
                            for st, sc in bs6_blocks(chunk4):
                                if st=='IDNB' and len(sc)==4: idnb=unpack_from('<I',sc)[0]
                                elif st=='RAWD':
                                    if idnb==0x105 and len(sc)>=16:
                                        vals=list(iter_unpack('<i',sc))
                                        dx,dy,dz=vals[0][0],vals[1][0],vals[2][0]
                                        dur=vals[3][0]; flags=vals[4][0] if len(vals)>4 else 0
                                        if dx or dy or dz:
                                            ctrl_move={'dx':dx,'dy':dy,'dz':dz,'duration':dur,'flags':flags}
                                    elif idnb==0x200 and len(sc)>=16:
                                        vals=list(iter_unpack('<i',sc))
                                        drx,dry,drz=vals[0][0],vals[1][0],vals[2][0]
                                        dur=vals[3][0]; flags=vals[4][0] if len(vals)>4 else 0
                                        if drx or dry or drz:
                                            ctrl_rot={'drx':drx,'dry':dry,'drz':drz,'duration':dur,'flags':flags}
                    if idfi is not None:
                        mesh = mesh_names[idfi] if idfi < len(mesh_names) else ''
                        if mesh: objects.append({'mesh':mesh,'pos':pos or (0,0,0),'rot':rot or (0,0,0),
                                                 'ctrl_move':ctrl_move,'ctrl_rot':ctrl_rot})
    return objects

def parse_bs6_lights(data):
    lights = []
    for tag, chunk in bs6_blocks(data):
        if tag != 'GNRL': continue
        for tag2, chunk2 in bs6_blocks(chunk):
            if tag2 != 'LITS': continue
            for tag3, chunk3 in bs6_blocks(chunk2):
                if tag3 != 'LITD': continue
                pos=(0,0,0); radius=512; brightness=32
                for tag4, chunk4 in bs6_blocks(chunk3):
                    if tag4=='POSI': pos=unpack_from('<3i',chunk4)
                    elif tag4=='RADI': radius=unpack_from('<I',chunk4)[0]
                    elif tag4=='BRIT': brightness=unpack_from('<I',chunk4)[0]
                lights.append({'pos':pos,'radius':radius,'brightness':brightness})
    return lights

def parse_bs6_watr(data):
    for tag, chunk in bs6_blocks(data):
        if tag != 'GNRL': continue
        for tag2, chunk2 in bs6_blocks(chunk):
            if tag2 == 'WATR' and len(chunk2) >= 4:
                val = unpack_from('<i', chunk2)[0]
                return val if val != 0 else None
    return None

def parse_bs6_flats(data):
    flats = []
    for tag, chunk in bs6_blocks(data):
        if tag != 'GNRL': continue
        for tag2, chunk2 in bs6_blocks(chunk):
            if tag2 != 'FLAS': continue
            for tag3, chunk3 in bs6_blocks(chunk2):
                if tag3 != 'FLAD': continue
                filn=None; pos=(0,0,0); scal=0; ambi=0
                creature_code=None; creature_index=None
                for tag4, chunk4 in bs6_blocks(chunk3):
                    if tag4=='FILN': filn=chunk4.decode('ascii',errors='replace').rstrip('\x00')
                    elif tag4=='POSI': pos=unpack_from('<3i',chunk4)
                    elif tag4=='SCAL': scal=unpack_from('<i',chunk4)[0]
                    elif tag4=='AMBI': ambi=unpack_from('<i',chunk4)[0]
                    elif tag4=='STRU':
                        idnb=0
                        for st, sc in bs6_blocks(chunk4):
                            if st=='IDNB' and len(sc)==4:
                                idnb=unpack_from('<I',sc)[0]
                            elif st=='RAWD':
                                if idnb==0x6C and 2<=len(sc)<=8:
                                    txt=sc.decode('ascii',errors='replace').rstrip('\x00')
                                    if txt and len(txt)>=2 and all(c.isalnum() for c in txt):
                                        creature_code=txt
                                elif idnb==0x6A and len(sc)>=4:
                                    val=unpack_from('<I',sc)[0]
                                    if 1<=val<=15:
                                        creature_index=val
                if filn: flats.append({'type':filn,'pos':pos,'scale':scal,'ambi':ambi,
                                       'creature_code':creature_code,'creature_index':creature_index})
    return flats

def parse_levels_txt(gamedata_path):
    path = os.path.join(gamedata_path, 'LEVELS.TXT')
    if not os.path.isfile(path): return {}
    levels = {}
    try:
        with open(path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 11: continue
                bs6=parts[0].lower(); flags=parts[3]
                sky=parts[4] if parts[4].lower()!='xxxx' else None
                rgb_str=parts[5]; brit=int(parts[10]); name=' '.join(parts[11:])
                r=int(rgb_str[0])/9.0; g=int(rgb_str[1])/9.0; b=int(rgb_str[2])/9.0
                levels[bs6] = {'brightness':brit,'sky_bsi':sky,'fog_rgb':(r,g,b),'flags':flags,'name':name}
    except: pass
    return levels

# ═══════════════════════════════════════════════════════════════════════════
#  CREATURE TABLE — all 16 from GAME.EXE + BSI analysis
# ═══════════════════════════════════════════════════════════════════════════

CREATURE_TABLE = {
    # Creatures (BSI prefixes from GAME.EXE BSI table)
    'smp': 'Scamp',
    'ver': 'Vermai',
    'dre': 'Dremora',
    'spd': 'Spider Daedra',
    'skl': 'Skeleton',
    'ght': 'Ghost',
    'wth': 'Wraith',
    'mr':  'Morphoid Daedra',
    'fda': 'Fire Daedra',
    'icd': 'Frost Daedra',
    'mas': 'Herne (Mastema)',
    'cln': 'Clannfear',
    'sdc': 'Seducer',
    'dsr': 'Dark Seducer',
    'dld': 'Daedra Lord',
    'mld': 'Morphoid Lord',
    # PvP teams
    'bfe': 'Female Blue Team',
    'rfe': 'Female Red Team',
    'bma': 'Male Blue Team',
    'rma': 'Male Red Team',
    # Special
    'skel': 'Skeleton (Extra)',
}

CREATURE_FILTERS = {
    'smp':  {'include': ['smp']},
    'ver':  {'include': ['ver']},
    'dre':  {'include': ['dre']},
    'spd':  {'include': ['spd']},
    'skl':  {'include': ['skl']},
    'ght':  {'include': ['ght']},
    'wth':  {'include': ['wth']},
    'mr':   {'include': ['mr'], 'max_len': 6, 'exclude': ['mrev', 'mrhr']},
    'fda':  {'include': ['fda'], 'exclude': ['fdag']},
    'icd':  {'include': ['icd']},
    'mas':  {'include': ['mas']},
    'cln':  {'include': ['cln']},
    'sdc':  {'include': ['sdc']},
    'dsr':  {'include': ['dsr']},
    'dld':  {'include': ['dld']},
    'mld':  {'include': ['mld']},
    'bfe':  {'include': ['bfe']},
    'rfe':  {'include': ['rfe']},
    'bma':  {'include': ['bma']},
    'rma':  {'include': ['rma']},
    'skel': {'include': ['skel']},
}

NPC_TABLE = [
    'chimere', 'clarentv', 'deyanira', 'jaciel', 'josian',
    'vatasha', 'faydra', 'rishaal', 'sumeer', 'zenaida',
    'wonsh00', 'imago', 'sirran', 'xiivilai', 'dagon',
    'vatchild', 'childfay', 'childjac', 'childdey',
]

# Billboard effect sprites (all known BSI effect names)
EFFECT_BSIS = ['flam00', 'flam01', 'flmw00', 'flmw01', 'glow', 'glow00', 'twinkle']

# ── FLAS flat type classification ──
FLAT_TYPES_MONSTER = {'monster1', 'monster2'}
FLAT_TYPES_SPAWN = {'start', 'bstart', 'rstart', 'restart', 'user'}

# NPC flat types → BSI texture name (flat_type == bsi_name in all known cases)
FLAT_TYPES_NPC = {
    'chimere', 'clarentv', 'deyanira', 'jaciel', 'josian',
    'vatasha', 'faydra', 'rishaal', 'sumeer', 'zenaida',
    'wonsh00', 'imago', 'sirran', 'xiivilai', 'dagon',
}

# Effect flat types → BSI texture name
FLAT_TYPES_EFFECT = {
    'flam00': 'flam00',
    'flam01': 'flam01',
    'flmw00': 'flmw00',
    'flmw01': 'flmw01',
}

# Legacy grouping for spawn markers
FLAT_TYPES_STUFF = {'stuff', 'trigger'}

# Monster STRU 2-letter code → creature BSI prefix (from GAME.EXE + TXT.BSA dialogue codes)
MONSTER_CODE_TO_PREFIX = {
    # Creature type codes (generic monsters)
    'sk': 'smp',    # Scamp
    'vm': 'ver',    # Vermai
    'dr': 'dre',    # Dremora
    'sd': 'spd',    # Spider Daedra (Perthan)
    'wr': 'wth',    # Wraith
    'gh': 'ght',    # Ghost
    'fr': 'fda',    # Fire Daedra
    'ft': 'icd',    # Frost Daedra
    'ma': 'mas',    # Herne (Mastema)
    'cf': 'cln',    # Clannfear
    'sr': 'sdc',    # Seducer
    'ds': 'dsr',    # Dark Seducer
    'ml': 'dld',    # Daedra Lord
    'dl': 'dld',    # Daedra Lord (alt code)
    # Named NPC codes that appear in monster STRU (use parent creature sprite)
    'dm': 'dre',    # Dremora Methats (NPC)
    'dn': 'dre',    # Dremora Rathine (NPC)
    'dt': 'dre',    # Dremora Tanchelm (NPC)
    'dg': 'dre',    # Dremora Gatanas (NPC)
    'ka': 'wth',    # Wraith of Kirel Aman (NPC)
    'pb': 'wth',    # Wraith of Paxti Bittor (NPC)
    'sv': 'spd',    # Spider Vorn (NPC)
}

# Binary creature index from STRU IDNB=0x6A → BSI prefix (1-based index from GAME.EXE)
CREATURE_INDEX_TO_PREFIX = [
    None,   # 0 = unused
    'smp',  # 1 = Scamp
    'ver',  # 2 = Vermai
    'dre',  # 3 = Dremora
    'spd',  # 4 = Spider Daedra
    'skl',  # 5 = Skeleton
    'ght',  # 6 = Ghost
    'wth',  # 7 = Wraith
    'mr',   # 8 = Morphoid Daedra
    'fda',  # 9 = Fire Daedra
    'icd',  # 10 = Frost Daedra
    'mas',  # 11 = Herne (Mastema)
    'cln',  # 12 = Clannfear
    'sdc',  # 13 = Seducer
    'dsr',  # 14 = Dark Seducer
    'dld',  # 15 = Daedra Lord
]

# Creature prefixes that use color-based alpha (semi-transparent entities)
GHOST_ALPHA_PREFIXES = {'ght', 'wth'}

def _fixed_to_rad(v): return v * math.tau / 2048.0
def rotate_point(x, y, z, rx, ry, rz):
    ay=_fixed_to_rad(-ry)
    x2=x*math.cos(ay)+z*math.sin(ay); z2=-x*math.sin(ay)+z*math.cos(ay); x,z=x2,z2
    ax=_fixed_to_rad(rx)
    y2=y*math.cos(ax)-z*math.sin(ax); z2=y*math.sin(ax)+z*math.cos(ax); y,z=y2,z2
    az=_fixed_to_rad(rz)
    x2=x*math.cos(az)-y*math.sin(az); y2=x*math.sin(az)+y*math.cos(az); x,y=x2,y2
    return x, y, z
