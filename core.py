"""
Battlespire data parsers: BSA archives, BSI textures, .3D models, BS6 scenes.
No Blender dependency — pure Python + optional numpy.
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


def bsi_decode_image(bsi_data):
    chunks = _bsi_chunks(bsi_data); bhdr = chunks.get('BHDR')
    if not bhdr or len(bhdr) < 26: return None
    w, h = unpack_from('<2h', bhdr, 4)
    frames = unpack_from('<h', bhdr, 14)[0]; flags = unpack_from('<h', bhdr, 24)[0]
    if w <= 0 or h <= 0: return None
    img_data = chunks.get('DATA')
    if not img_data: return None
    if flags != 0: pixel_data = _bsi_decompress(img_data, w, h*frames)
    else: pixel_data = img_data[:w*h*frames]
    hicl = chunks.get('HICL')
    if not hicl: return None
    pal = [(0.0,0.0,0.0,1.0)]*256
    for i in range(min(128, len(hicl)//2)):
        c = unpack_from('<H', hicl, i*2)[0]
        pal[i<<1] = (((c>>11)&0x1F)/31.0, ((c>>6)&0x1F)/31.0, ((c>>1)&0x1F)/31.0, 1.0)
    pal[0] = (0.0, 0.0, 0.0, 0.0)
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


# ═══════════════════════════════════════════════════════════════════════════
#  BS6 SCENE + LIGHTS
# ═══════════════════════════════════════════════════════════════════════════

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
                        name = name_raw.decode(errors='replace').rstrip('\x00')
                        mesh_names.append(name if name else '')
                elif tag3 == 'OBJD':
                    idfi = pos = rot = None
                    for tag4, chunk4 in bs6_blocks(chunk3):
                        if   tag4 == 'IDFI': idfi = unpack_from('<I', chunk4)[0]
                        elif tag4 == 'POSI': pos  = unpack_from('<3i', chunk4)
                        elif tag4 == 'ANGS': rot  = unpack_from('<3i', chunk4)
                    if idfi is not None:
                        mesh = mesh_names[idfi] if idfi < len(mesh_names) else ''
                        if mesh:
                            objects.append({'mesh': mesh, 'pos': pos or (0,0,0), 'rot': rot or (0,0,0)})
    return objects


def parse_bs6_lights(data):
    lights = []
    for tag, chunk in bs6_blocks(data):
        if tag != 'GNRL': continue
        for tag2, chunk2 in bs6_blocks(chunk):
            if tag2 != 'LITS': continue
            for tag3, chunk3 in bs6_blocks(chunk2):
                if tag3 != 'LITD': continue
                pos = (0, 0, 0); radius = 512; brightness = 32
                for tag4, chunk4 in bs6_blocks(chunk3):
                    if   tag4 == 'POSI': pos = unpack_from('<3i', chunk4)
                    elif tag4 == 'RADI': radius = unpack_from('<I', chunk4)[0]
                    elif tag4 == 'BRIT': brightness = unpack_from('<I', chunk4)[0]
                lights.append({'pos': pos, 'radius': radius, 'brightness': brightness})
    return lights


# ═══════════════════════════════════════════════════════════════════════════
#  ROTATION
# ═══════════════════════════════════════════════════════════════════════════

def _fixed_to_rad(v): return v * math.tau / 2048.0

def rotate_point(x, y, z, rx, ry, rz):
    ay = _fixed_to_rad(-ry)
    x2 = x*math.cos(ay)+z*math.sin(ay); z2 = -x*math.sin(ay)+z*math.cos(ay); x,z=x2,z2
    ax = _fixed_to_rad(rx)
    y2 = y*math.cos(ax)-z*math.sin(ax); z2 = y*math.sin(ax)+z*math.cos(ax); y,z=y2,z2
    az = _fixed_to_rad(rz)
    x2 = x*math.cos(az)-y*math.sin(az); y2 = x*math.sin(az)+y*math.cos(az); x,y=x2,y2
    return x, y, z
