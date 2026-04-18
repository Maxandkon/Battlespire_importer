"""Blender builders. Never caches bpy refs — lookup by name."""
import bpy, os, math, glob
from collections import defaultdict
from .core import (
    BSAArchive, bsi_get_size, bsi_get_frames, bsi_decode_image, bsi_decode_all_frames, parse_3d,
    parse_bs6_scene, parse_bs6_lights, parse_bs6_watr, parse_bs6_flats,
    parse_levels_txt, rotate_point, SCENE_SCALE,
    CREATURE_TABLE, CREATURE_FILTERS, NPC_TABLE, EFFECT_BSIS,
    FLAT_TYPES_MONSTER, FLAT_TYPES_EFFECT, FLAT_TYPES_SPAWN,
    FLAT_TYPES_NPC, FLAT_TYPES_STUFF, GHOST_ALPHA_PREFIXES,
    MONSTER_CODE_TO_PREFIX, CREATURE_INDEX_TO_PREFIX,
)

OVERSIZE_RADIUS = 5.0
ALPHA_DISABLED = {'wind3', 'wind1', 'wind2'}

# Sprite heights for level placement (Blender units, calibrated to door height ~4.0)
NPC_SPAWN_HEIGHT = 2.5
NPC_HEIGHT_OVERRIDES = {
    'dagon': 5.0,
    'xiivilai': 3.5,
    'imago': 2.0,
    'rishaal': 1.3,
}

# Creature collision radius from GAME.EXE (dword[0] >> 16, used for future monster scale)
CREATURE_SPRITE_SCALE = {
    'smp':  2, 'ver':  2, 'dre':  3, 'spd':  5, 'skl':  5,
    'ght':  8, 'wth':  6, 'mr':   6, 'fda':  6, 'icd':  6,
    'mas':  6, 'cln':  5, 'sdc':  3, 'dsr':  7, 'dld': 10,
}

# Creature sprite heights for level placement (Blender units)
MONSTER_SPAWN_HEIGHT = {
    'smp': 1.6, 'ver': 1.8, 'dre': 2.5, 'spd': 2.5, 'skl': 2.5,
    'ght': 2.8, 'wth': 2.8, 'mr':  2.5, 'fda': 2.8, 'icd': 2.8,
    'mas': 2.8, 'cln': 2.2, 'sdc': 2.5, 'dsr': 2.8, 'dld': 3.5,
    'mld': 3.0,
}
MONSTER_DEFAULT_HEIGHT = 2.5

class ResourceManager:
    def __init__(self): self.reset()
    def reset(self):
        self._gamedata=""; self._loaded=False
        self._model_bsa=self._model_bs6=self._bsi_bsa=self._bs6_bsa=None
        self.tex_sizes={}; self._bsi_name_index={}; self._failed_images=set(); self.levels_info={}
        self._creature_bsi_cache={}; self.use_animated_tex=False
    @property
    def is_loaded(self): return self._loaded
    def load(self, gamedata_path):
        if self._loaded and self._gamedata==gamedata_path: return True
        self.reset(); self._gamedata=gamedata_path
        for f,a in [("3D.BSA","_model_bsa"),("3D.BS6","_model_bs6"),("BSI.BSA","_bsi_bsa"),("BS6.BSA","_bs6_bsa")]:
            p=os.path.join(gamedata_path,f)
            if os.path.isfile(p): setattr(self,a,BSAArchive(p))
        if self._bsi_bsa:
            for fn in self._bsi_bsa.names('.BSI'):
                stem=os.path.splitext(fn)[0].lower()
                raw=self._bsi_bsa.get(fn)
                if raw:
                    sz=bsi_get_size(raw)
                    if sz: self.tex_sizes[stem]=sz
                self._bsi_name_index[stem]=fn
        self.levels_info=parse_levels_txt(gamedata_path)
        self._loaded=self._model_bsa is not None
        # Pre-cache creature BSI counts for fast dropdown rendering
        if self._loaded:
            for prefix in CREATURE_FILTERS:
                self._creature_bsi_cache[prefix]=len(self.get_creature_bsi_names(prefix))
        return self._loaded
    def get_mesh_raw(self, name):
        key=name.upper()
        if not key.endswith('.3D'): key+='.3D'
        for arc in [self._model_bsa,self._model_bs6]:
            if arc:
                d=arc.get(key)
                if d: return d
        if self._gamedata:
            loose=os.path.join(self._gamedata,key)
            if os.path.isfile(loose):
                with open(loose,'rb') as f: return f.read()
        return None
    def get_model_names(self):
        n=set()
        for a in [self._model_bsa,self._model_bs6]:
            if a: n.update(a.names('.3D'))
        return sorted(n)
    def get_scene_names(self):
        s=[]
        if self._bs6_bsa: s.extend(self._bs6_bsa.names('.BS6'))
        if self._gamedata:
            for p in glob.glob(os.path.join(self._gamedata,'*.BS6')):
                fn=os.path.basename(p)
                if fn not in s and fn.upper()!='3D.BS6': s.append(fn)
        return sorted(s)
    def get_scene_data(self, name):
        if self._bs6_bsa:
            d=self._bs6_bsa.get(name)
            if d: return d
        if self._gamedata:
            loose=os.path.join(self._gamedata,name)
            if os.path.isfile(loose):
                with open(loose,'rb') as f: return f.read()
        return None
    def get_level_info(self, sn): return self.levels_info.get(sn.lower())
    def level_has_sky(self, sn):
        i=self.get_level_info(sn); return i is not None and i.get('sky_bsi') is not None
    def resolve_bsi(self, tex_name):
        if not self._bsi_bsa: return None
        exact=tex_name.upper()+'.BSI'
        if self._bsi_bsa.has(exact): return exact
        if tex_name in self._bsi_name_index: return self._bsi_name_index[tex_name]
        m=sorted([v for k,v in self._bsi_name_index.items() if k.startswith(tex_name)])
        return m[0] if len(m)==1 else None
    def get_bsi_raw(self, tex_name):
        fn=self.resolve_bsi(tex_name)
        return self._bsi_bsa.get(fn) if fn and self._bsi_bsa else None
    def get_image(self, tex_name):
        existing=bpy.data.images.get(tex_name)
        if existing: return existing
        # Try animated texture folder first
        if self.use_animated_tex:
            img=self._load_animated_image(tex_name)
            if img: return img
        if tex_name in self._failed_images: return None
        bsi_data=self.get_bsi_raw(tex_name)
        if not bsi_data: self._failed_images.add(tex_name); return None
        result=bsi_decode_image(bsi_data)
        if not result: self._failed_images.add(tex_name); return None
        w,h,pixels=result
        img=bpy.data.images.new(tex_name,w,h,alpha=True)
        img.pixels=pixels; img.pack(); return img
    def _load_animated_image(self, tex_name):
        """Load texture as Image Sequence from BS_TEXTURES folder."""
        tex_path=get_animated_tex_path(self._gamedata)
        if not tex_path: return None
        tex_dir=os.path.join(tex_path,tex_name)
        if not os.path.isdir(tex_dir): return None
        frames=sorted(f for f in os.listdir(tex_dir) if f.endswith('.png'))
        if len(frames)<2: return None
        first=os.path.join(tex_dir,frames[0])
        img=bpy.data.images.load(first)
        img.name=tex_name; img.source='SEQUENCE'
        return img
    def get_creature_bsi_names(self, prefix):
        if prefix not in CREATURE_FILTERS: return []
        filt = CREATURE_FILTERS[prefix]
        inc = filt['include']
        exc = filt.get('exclude', [])
        max_len = filt.get('max_len', 999)
        result = []
        for k in sorted(self._bsi_name_index):
            if len(k) > max_len: continue
            if any(k.startswith(e) for e in exc): continue
            if any(k.startswith(p) for p in inc): result.append(k)
        return result
    def get_creature_bsi_count(self, prefix):
        """Fast cached count for UI dropdown (avoids iterating all BSI names)."""
        return self._creature_bsi_cache.get(prefix, 0)
    @staticmethod
    def _mat_name(tex_name, color):
        if tex_name: return tex_name
        r,g,b=round(color[0],3),round(color[1],3),round(color[2],3)
        return f"solid_{r}_{g}_{b}"
    def get_material(self, tex_name, color):
        mat_name=self._mat_name(tex_name,color)
        existing=bpy.data.materials.get(mat_name)
        if existing: return existing
        mat=bpy.data.materials.new(name=mat_name); mat.use_nodes=True
        nodes=mat.node_tree.nodes; links=mat.node_tree.links; nodes.clear()
        bsdf=nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location=(0,0)
        bsdf.inputs['Metallic'].default_value=0.0; bsdf.inputs['Roughness'].default_value=1.0
        for n in ['IOR','IOR Level']:
            if n in bsdf.inputs: bsdf.inputs[n].default_value=1.0; break
        for n in ['Specular IOR Level','Specular']:
            if n in bsdf.inputs: bsdf.inputs[n].default_value=0.0; break
        out=nodes.new('ShaderNodeOutputMaterial'); out.location=(300,0)
        links.new(bsdf.outputs['BSDF'],out.inputs['Surface'])
        if tex_name and tex_name.startswith('1_'):
            bsdf.inputs['Alpha'].default_value=0.0; _set_alpha_blend(mat)
        elif tex_name:
            img=self.get_image(tex_name)
            if img:
                tx=nodes.new('ShaderNodeTexImage'); tx.location=(-400,0)
                tx.image=img; tx.interpolation='Closest'; tx.extension='REPEAT'
                _setup_image_sequence(tx, tex_name)
                links.new(tx.outputs['Color'],bsdf.inputs['Base Color'])
                if tex_name not in ALPHA_DISABLED:
                    links.new(tx.outputs['Alpha'],bsdf.inputs['Alpha']); _set_alpha_clip(mat)
            else: bsdf.inputs['Base Color'].default_value=(*color,1.0)
        else: bsdf.inputs['Base Color'].default_value=(*color,1.0)
        mat.use_backface_culling=False; return mat

def _setup_image_sequence(tex_node, tex_name):
    """Configure texture node for Image Sequence if the image is animated."""
    img=tex_node.image
    if not img or img.source!='SEQUENCE': return
    nframes=_get_animated_frame_count(tex_name)
    if nframes<2: return
    iu=tex_node.image_user
    iu.frame_duration=nframes; iu.frame_offset=-1
    iu.use_cyclic=True; iu.use_auto_refresh=True

def _set_alpha_clip(m):
    try: m.blend_method='CLIP'; m.alpha_threshold=0.5
    except: pass
def _set_alpha_blend(m):
    try: m.blend_method='BLEND'
    except: pass

RM = ResourceManager()

# ═══════════════════════════════════════════════════════════════════════════
def _scene_offsets(objects):
    px=[o['pos'][0]*SCENE_SCALE for o in objects]
    py=[o['pos'][1]*SCENE_SCALE for o in objects]
    pz=[o['pos'][2]*SCENE_SCALE for o in objects]
    return (sum(px)/len(px) if px else 0, max(py) if py else 0, sum(pz)/len(pz) if pz else 0)

def _make_sprite_material(tex_name):
    mn=f"sprite_{tex_name}"; existing=bpy.data.materials.get(mn)
    if existing: return existing
    img=RM.get_image(tex_name)
    if not img: return None
    mat=bpy.data.materials.new(name=mn); mat.use_nodes=True
    nd=mat.node_tree.nodes; lk=mat.node_tree.links; nd.clear()
    emit=nd.new('ShaderNodeEmission'); emit.location=(0,0); emit.inputs['Strength'].default_value=1.5
    tx=nd.new('ShaderNodeTexImage'); tx.location=(-400,0)
    tx.image=img; tx.interpolation='Closest'; tx.extension='REPEAT'
    _setup_image_sequence(tx, tex_name)
    lk.new(tx.outputs['Color'],emit.inputs['Color'])
    transp=nd.new('ShaderNodeBsdfTransparent'); transp.location=(0,-200)
    mix=nd.new('ShaderNodeMixShader'); mix.location=(200,0)
    # Ghost/Wraith: alpha from color brightness × texture alpha
    is_ghost = any(tex_name.startswith(p) for p in GHOST_ALPHA_PREFIXES)
    if is_ghost:
        bw=nd.new('ShaderNodeRGBToBW'); bw.location=(-200,200)
        lk.new(tx.outputs['Color'],bw.inputs['Color'])
        mul=nd.new('ShaderNodeMath'); mul.location=(-50,200); mul.operation='MULTIPLY'
        lk.new(tx.outputs['Alpha'],mul.inputs[0])
        lk.new(bw.outputs['Val'],mul.inputs[1])
        lk.new(mul.outputs['Value'],mix.inputs['Fac'])
    else:
        lk.new(tx.outputs['Alpha'],mix.inputs['Fac'])
    lk.new(transp.outputs['BSDF'],mix.inputs[1])
    lk.new(emit.outputs['Emission'],mix.inputs[2])
    out=nd.new('ShaderNodeOutputMaterial'); out.location=(400,0)
    lk.new(mix.outputs['Shader'],out.inputs['Surface'])
    _set_alpha_blend(mat); return mat

def _create_sprite_plane(name, tex_name, w, h, collection, target_height=None):
    if target_height and h > 0:
        # Fixed world-space height, maintain aspect ratio
        aspect=w/h; hh=target_height*0.5; hw=hh*aspect
    else:
        # Pixel-based scale (gallery/preview mode)
        aspect=h/w if w>0 else 1.0; scale=max(w,h)/128.0
        hw=0.5*scale; hh=hw*aspect
    verts=[(-hw,0,-hh),(hw,0,-hh),(hw,0,hh),(-hw,0,hh)]; faces=[(0,1,2,3)]
    mesh=bpy.data.meshes.new(name); mesh.from_pydata(verts,[],faces)
    uv=mesh.uv_layers.new(name='UVMap')
    for li,loop in enumerate(mesh.loops): uv.data[li].uv=[(0,0),(1,0),(1,1),(0,1)][loop.vertex_index]
    mesh.update()
    mat=_make_sprite_material(tex_name)
    if mat: mesh.materials.append(mat)
    obj=bpy.data.objects.new(name,mesh); collection.objects.link(obj); return obj

# ═══════════════════════════════════════════════════════════════════════════
#  MESH BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def build_mesh_object(model, name, collection):
    stem=os.path.splitext(name)[0]
    mg=defaultdict(list)
    for p in model['planes']:
        if len(p['vertices'])<3: continue
        tn=p['texture_name']
        mk=('t',tn) if tn else ('c',round(p['color'][0],3),round(p['color'][1],3),round(p['color'][2],3))
        mg[mk].append(p)
    if not mg: return None
    mk_list=list(mg.keys()); mk2i={mk:i for i,mk in enumerate(mk_list)}
    verts=[]; faces=[]; uvs=[]; mat_ids=[]; vi=0
    for mk,plist in mg.items():
        mi=mk2i[mk]
        for pl in plist:
            vs=pl['vertices']
            for i in range(1,len(vs)-1):
                for j in (0,i,i+1):
                    vx,vy,vz,u,v=vs[j]; verts.append((vx,vy,vz)); uvs.append((u,v))
                faces.append((vi,vi+1,vi+2)); mat_ids.append(mi); vi+=3
    mesh=bpy.data.meshes.new(stem); mesh.from_pydata(verts,[],faces)
    for mk in mk_list:
        rep=mg[mk][0]; mesh.materials.append(RM.get_material(rep['texture_name'],rep['color']))
    for fi,mi in enumerate(mat_ids): mesh.polygons[fi].material_index=mi
    ul=mesh.uv_layers.new(name='UVMap')
    for li,loop in enumerate(mesh.loops): ul.data[li].uv=uvs[loop.vertex_index]
    mesh.update()
    obj=bpy.data.objects.new(stem,mesh); collection.objects.link(obj)
    for poly in mesh.polygons: poly.use_smooth=False
    return obj

def build_level(scene_name, objects, mesh_cache, collection):
    ox,oy,oz=_scene_offsets(objects); ic={}; built=0
    for od in objects:
        key=od['mesh'].upper(); model=mesh_cache.get(key)
        if not model or not model['planes']: continue
        ic[key]=ic.get(key,0)+1; label=f"{od['mesh']}_{ic[key]:03d}"
        px0=od['pos'][0]*SCENE_SCALE-ox; py0=-(od['pos'][1]*SCENE_SCALE-oy); pz0=od['pos'][2]*SCENE_SCALE-oz
        rx,ry,rz=od['rot']
        mg=defaultdict(list)
        for p in model['planes']:
            if len(p['vertices'])<3: continue
            tn=p['texture_name']
            mk=('t',tn) if tn else ('c',round(p['color'][0],3),round(p['color'][1],3),round(p['color'][2],3))
            mg[mk].append(p)
        if not mg: continue
        mk_list=list(mg.keys()); mk2i={mk:i for i,mk in enumerate(mk_list)}
        verts=[]; faces=[]; uvs=[]; mat_ids=[]; vi=0
        for mk,plist in mg.items():
            mi=mk2i[mk]
            for pl in plist:
                vs=pl['vertices']
                for i in range(1,len(vs)-1):
                    for j in (0,i,i+1):
                        vx,vy,vz,u,v=vs[j]
                        wx,wy,wz=rotate_point(vx,vy,vz,rx,ry,rz)
                        verts.append((-wx-px0,-wz-pz0,-wy+py0)); uvs.append((u,v))
                    faces.append((vi,vi+1,vi+2)); mat_ids.append(mi); vi+=3
        mesh=bpy.data.meshes.new(label); mesh.from_pydata(verts,[],faces)
        for mk in mk_list:
            rep=mg[mk][0]; mesh.materials.append(RM.get_material(rep['texture_name'],rep['color']))
        for fi,mi in enumerate(mat_ids): mesh.polygons[fi].material_index=mi
        ul=mesh.uv_layers.new(name='UVMap')
        for li,loop in enumerate(mesh.loops): ul.data[li].uv=uvs[loop.vertex_index]
        mesh.update()
        bl_obj=bpy.data.objects.new(label,mesh); collection.objects.link(bl_obj)
        for poly in mesh.polygons: poly.use_smooth=False
        if verts:
            ox_o=-px0; oy_o=-pz0; oz_o=py0
            for v in mesh.vertices: v.co.x-=ox_o; v.co.y-=oy_o; v.co.z-=oz_o
            bl_obj.location=(ox_o,oy_o,oz_o); mesh.update()
        # Store CTRL data for later animation
        cm=od.get('ctrl_move')
        if cm:
            bl_obj['ctrl_dx']=cm['dx']; bl_obj['ctrl_dy']=cm['dy']; bl_obj['ctrl_dz']=cm['dz']
            bl_obj['ctrl_dur']=cm['duration']; bl_obj['ctrl_flags']=cm['flags']
        cr=od.get('ctrl_rot')
        if cr:
            bl_obj['ctrl_drx']=cr['drx']; bl_obj['ctrl_dry']=cr['dry']; bl_obj['ctrl_drz']=cr['drz']
            bl_obj['ctrl_rdur']=cr['duration']; bl_obj['ctrl_rflags']=cr['flags']
        built+=1
    return built

# ═══════════════════════════════════════════════════════════════════════════
def build_lights(lights, objects, collection):
    if not lights or not objects: return 0
    ox,oy,oz=_scene_offsets(objects); built=0
    for i,lit in enumerate(lights):
        px=lit['pos'][0]*SCENE_SCALE-ox; py=-(lit['pos'][1]*SCENE_SCALE-oy); pz=lit['pos'][2]*SCENE_SCALE-oz
        radius=lit['radius']*SCENE_SCALE; energy=lit['brightness']/128.0*10.0
        ld=bpy.data.lights.new(name=f"Light_{i:03d}",type='POINT')
        ld.energy=energy*5000.0; ld.color=(1.0,0.9,0.75); ld.use_shadow=False
        try: ld.use_custom_distance=True; ld.cutoff_distance=radius
        except: ld.shadow_soft_size=radius
        lo=bpy.data.objects.new(f"Light_{i:03d}",ld); lo.location=(-px,-pz,py)
        collection.objects.link(lo); built+=1
    return built

def build_world_light(level_info):
    if not level_info: return
    world=bpy.context.scene.world
    if not world: world=bpy.data.worlds.new("BS_World"); bpy.context.scene.world=world
    world.use_nodes=True; nd=world.node_tree.nodes; lk=world.node_tree.links; nd.clear()
    bg=nd.new('ShaderNodeBackground'); bg.location=(0,0)
    out=nd.new('ShaderNodeOutputWorld'); out.location=(300,0)
    lk.new(bg.outputs['Background'],out.inputs['Surface'])
    fr,fg,fb=level_info['fog_rgb']
    bg.inputs['Color'].default_value=(fr,fg,fb,1.0)
    bg.inputs['Strength'].default_value=1.0

def build_sky(level_info, objects, collection):
    if not level_info or not level_info.get('sky_bsi'): return
    sky_name=level_info['sky_bsi'].replace('.bsi','').replace('.BSI','')
    img=RM.get_image(sky_name)
    if not img: return
    ox,oy,oz=_scene_offsets(objects)
    bzs=[-(o['pos'][1]*SCENE_SCALE-oy) for o in objects]
    sky_z=max(bzs)+50.0 if bzs else 100.0
    apx=[o['pos'][0]*SCENE_SCALE for o in objects]; apz=[o['pos'][2]*SCENE_SCALE for o in objects]
    ss=max((max(apx)-min(apx))*0.6+10 if apx else 50, (max(apz)-min(apz))*0.6+10 if apz else 50)
    verts=[(-ss,-ss,sky_z),(ss,-ss,sky_z),(ss,ss,sky_z),(-ss,ss,sky_z)]
    mesh=bpy.data.meshes.new("Sky"); mesh.from_pydata(verts,[],[(0,1,2,3)])
    uv=mesh.uv_layers.new(name='UVMap')
    for li,loop in enumerate(mesh.loops): uv.data[li].uv=[(0,0),(1,0),(1,1),(0,1)][loop.vertex_index]
    mesh.update()
    mn=f"sky_{sky_name}"; mat=bpy.data.materials.get(mn)
    if not mat:
        mat=bpy.data.materials.new(name=mn); mat.use_nodes=True
        nd=mat.node_tree.nodes; lk=mat.node_tree.links; nd.clear()
        emit=nd.new('ShaderNodeEmission'); emit.location=(0,0); emit.inputs['Strength'].default_value=1.0
        tx=nd.new('ShaderNodeTexImage'); tx.location=(-400,0)
        tx.image=img; tx.interpolation='Closest'; tx.extension='EXTEND'
        lk.new(tx.outputs['Color'],emit.inputs['Color'])
        out=nd.new('ShaderNodeOutputMaterial'); out.location=(300,0)
        lk.new(emit.outputs['Emission'],out.inputs['Surface'])
    mesh.materials.append(mat)
    collection.objects.link(bpy.data.objects.new("Sky",mesh))

def build_water(watr_height, objects, collection):
    if watr_height is None: return
    ox,oy,oz=_scene_offsets(objects); wz=-(watr_height*SCENE_SCALE-oy)
    apx=[o['pos'][0]*SCENE_SCALE for o in objects]; apz=[o['pos'][2]*SCENE_SCALE for o in objects]
    ws=max((max(apx)-min(apx))*0.6+5 if apx else 50, (max(apz)-min(apz))*0.6+5 if apz else 50)
    wg=ws*1.5  # geometry size (1.5x larger than texture calc)
    verts=[(-wg,-wg,wz),(wg,-wg,wz),(wg,wg,wz),(-wg,wg,wz)]
    mesh=bpy.data.meshes.new("Water"); mesh.from_pydata(verts,[],[(0,1,2,3)])
    uv=mesh.uv_layers.new(name='UVMap')
    uvs=wg/2  # UV scale matches expanded geometry for same texture density
    for li,loop in enumerate(mesh.loops): uv.data[li].uv=[(0,0),(uvs,0),(uvs,uvs),(0,uvs)][loop.vertex_index]
    mesh.update()
    mn="bs_water"; mat=bpy.data.materials.get(mn)
    if not mat:
        mat=bpy.data.materials.new(name=mn); mat.use_nodes=True
        nd=mat.node_tree.nodes; lk=mat.node_tree.links; nd.clear()
        bsdf=nd.new('ShaderNodeBsdfPrincipled'); bsdf.location=(0,0)
        bsdf.inputs['Alpha'].default_value=0.9; bsdf.inputs['Roughness'].default_value=0.2
        for n in ['IOR','IOR Level']:
            if n in bsdf.inputs: bsdf.inputs[n].default_value=1.33; break
        img=RM.get_image('water2')
        if img:
            tx=nd.new('ShaderNodeTexImage'); tx.location=(-400,0)
            tx.image=img; tx.interpolation='Closest'; tx.extension='REPEAT'
            lk.new(tx.outputs['Color'],bsdf.inputs['Base Color'])
        else: bsdf.inputs['Base Color'].default_value=(0.02,0.05,0.12,1.0)
        out=nd.new('ShaderNodeOutputMaterial'); out.location=(300,0)
        lk.new(bsdf.outputs['BSDF'],out.inputs['Surface']); _set_alpha_blend(mat)
    mesh.materials.append(mat)
    collection.objects.link(bpy.data.objects.new("Water",mesh))

def build_spawn_markers(flats, objects, collection):
    if not flats or not objects: return 0
    ox,oy,oz=_scene_offsets(objects); built=0
    for i,flat in enumerate(flats):
        ft=flat['type']
        if ft in FLAT_TYPES_MONSTER: continue  # handled by build_monster_spawns
        if ft in FLAT_TYPES_NPC: continue  # handled by build_npc_spawns
        if ft in FLAT_TYPES_EFFECT: continue  # handled by build_effect_spawns
        px=flat['pos'][0]*SCENE_SCALE-ox; py=-(flat['pos'][1]*SCENE_SCALE-oy); pz=flat['pos'][2]*SCENE_SCALE-oz
        if ft in FLAT_TYPES_STUFF: display='SPHERE'; sz=0.2
        elif ft in FLAT_TYPES_SPAWN: display='CONE'; sz=0.4
        else: display='PLAIN_AXES'; sz=0.15
        e=bpy.data.objects.new(f"spawn_{ft}_{i:03d}",None)
        e.empty_display_type=display; e.empty_display_size=sz; e.location=(-px,-pz,py)
        collection.objects.link(e); built+=1
    return built

def build_effect_spawns(flats, objects, collection):
    """Place effect sprites at their FLAS positions on the level."""
    if not flats or not objects: return 0
    ox,oy,oz=_scene_offsets(objects); built=0
    for i,flat in enumerate(flats):
        ft=flat['type']
        bsi_name=FLAT_TYPES_EFFECT.get(ft)
        if not bsi_name: continue
        sz=RM.tex_sizes.get(bsi_name)
        if not sz: continue
        w,h=sz
        px=flat['pos'][0]*SCENE_SCALE-ox; py=-(flat['pos'][1]*SCENE_SCALE-oy); pz=flat['pos'][2]*SCENE_SCALE-oz
        obj=_create_sprite_plane(f"fx_{ft}_{i:03d}",bsi_name,w,h,collection)
        if obj: obj.location=(-px,-pz,py); built+=1
    return built

def build_npc_spawns(flats, objects, collection):
    """Place NPC sprites at their FLAS positions on the level."""
    if not flats or not objects: return 0
    ox,oy,oz=_scene_offsets(objects); built=0
    for i,flat in enumerate(flats):
        ft=flat['type']
        if ft not in FLAT_TYPES_NPC: continue
        bsi_name=ft  # NPC flat type == BSI texture name
        sz=RM.tex_sizes.get(bsi_name)
        if not sz: continue
        w,h=sz
        th=NPC_HEIGHT_OVERRIDES.get(bsi_name, NPC_SPAWN_HEIGHT)
        px=flat['pos'][0]*SCENE_SCALE-ox; py=-(flat['pos'][1]*SCENE_SCALE-oy); pz=flat['pos'][2]*SCENE_SCALE-oz
        obj=_create_sprite_plane(f"npc_{ft}_{i:03d}",bsi_name,w,h,collection,target_height=th)
        if obj: obj.location=(-px,-pz,py); built+=1
    return built

def build_monster_spawns(flats, objects, collection):
    """Place monster sprites at FLAS positions using STRU creature data.
    Uses text creature code (IDNB=0x6C) or binary creature index (IDNB=0x6A).
    Monsters without either get cube markers."""
    if not flats or not objects: return (0, 0)
    ox,oy,oz=_scene_offsets(objects); sprites=0; markers=0
    for i,flat in enumerate(flats):
        ft=flat['type']
        if ft not in FLAT_TYPES_MONSTER: continue
        px=flat['pos'][0]*SCENE_SCALE-ox; py=-(flat['pos'][1]*SCENE_SCALE-oy); pz=flat['pos'][2]*SCENE_SCALE-oz
        # Resolve creature prefix: try text code first, then binary index
        prefix=None
        cc=flat.get('creature_code')
        if cc and len(cc)>=2:
            code2=cc[:2].lower()
            prefix=MONSTER_CODE_TO_PREFIX.get(code2)
        if not prefix:
            ci=flat.get('creature_index')
            if ci is not None and 1<=ci<len(CREATURE_INDEX_TO_PREFIX):
                prefix=CREATURE_INDEX_TO_PREFIX[ci]
        if prefix:
            bsi_name=f"{prefix}w00"
            sz=RM.tex_sizes.get(bsi_name)
            if sz:
                w,h=sz; th=MONSTER_SPAWN_HEIGHT.get(prefix, MONSTER_DEFAULT_HEIGHT)
                obj=_create_sprite_plane(f"mon_{prefix}_{i:03d}",bsi_name,w,h,collection,target_height=th)
                if obj: obj.location=(-px,-pz,py); sprites+=1; continue
        # Fallback: cube marker for unknown/unresolved monsters
        e=bpy.data.objects.new(f"spawn_{ft}_{i:03d}",None)
        e.empty_display_type='CUBE'; e.empty_display_size=0.3; e.location=(-px,-pz,py)
        collection.objects.link(e); markers+=1
    return (sprites, markers)

# ═══════════════════════════════════════════════════════════════════════════
def build_effect_sprites(collection):
    built=0; x=0.0
    for tn in EFFECT_BSIS:
        sz=RM.tex_sizes.get(tn)
        if not sz: continue
        w,h=sz; obj=_create_sprite_plane(f"fx_{tn}",tn,w,h,collection)
        if obj: obj.location.x=x; x+=max(w,h)/128.0+0.3; built+=1
    return built

def build_creature_sprites(prefix, creature_name, collection):
    names=RM.get_creature_bsi_names(prefix)
    if not names: return 0
    built=0; x=0.0
    for tn in names:
        sz=RM.tex_sizes.get(tn)
        if not sz: continue
        w,h=sz; obj=_create_sprite_plane(tn,tn,w,h,collection)
        if obj: obj.location.x=x; x+=max(w,h)/128.0+0.2; built+=1
    return built

def build_npc_sprites(collection):
    built=0; x=0.0
    for tn in NPC_TABLE:
        sz=RM.tex_sizes.get(tn)
        if not sz: continue
        w,h=sz; obj=_create_sprite_plane(f"npc_{tn}",tn,w,h,collection)
        if obj: obj.location.x=x; x+=max(w,h)/128.0+0.3; built+=1
    return built

# ═══════════════════════════════════════════════════════════════════════════
#  OBJECT ANIMATIONS (CTRL IDNB=0x105 + auto-rotating objects)
# ═══════════════════════════════════════════════════════════════════════════
ANIM_FPS = 24

# ═══════════════════════════════════════════════════════════════════════════
#  Hardcoded object animations — objects whose movement is defined by name
#  in GAME.EXE, not in BS6 data files.
#
#  EXE handler at virtual 0x24080, checks mesh name with strncmp:
#   ┌─────────────┬───────────────────────────────────────────────────────┐
#   │ Mesh name   │ Behavior in game                                    │
#   ├─────────────┼───────────────────────────────────────────────────────┤
#   │ sigil*      │ Z-rotation + vertical bob. EXE refs: 0x5B456 setup, │
#   │             │ 0x5B4B7 update. Params: edx=27728, ecx=256, +30 bob │
#   │ boat        │ Water bobbing                                       │
#   │ boat2       │ Water bobbing                                       │
#   │ l8balon1    │ Balloon sway/bob (L8 level)                         │
#   │ rflag       │ PvP red flag waving                                 │
#   │ bflag       │ PvP blue flag waving                                │
#   │ rbase       │ PvP red base marker                                 │
#   │ bbase       │ PvP blue base marker                                │
#   └─────────────┴───────────────────────────────────────────────────────┘
#
#  CTRL types found in BS6 data (NOT hardcoded):
#   ┌──────────────┬──────────────────────────────────────────────────────┐
#   │ IDNB         │ Behavior                                           │
#   ├──────────────┼──────────────────────────────────────────────────────┤
#   │ 0x105        │ Linear movement [dx,dy,dz, duration_ms, flags,0,0,0]│
#   │              │   flags=0x72: ping-pong (lifts, platforms)          │
#   │              │   flags=0, dur>0: one-shot (doors, buttons)         │
#   │              │   flags=0, dur=0: instant (shown as Constant kf)    │
#   │ 0x200        │ Rotation [drx,dry,drz, dur_ms, flags, 0,0,0]       │
#   │              │   Values in angle units (2048 = 360°)               │
#   │              │   flags=0x72: ping-pong (doors, levers, traps)      │
#   │              │   flags=0x63: continuous loop (wheels, gears)        │
#   │              │   flags=0x6372: ping-pong swing (bells)             │
#   │              │   flags=0, dur>0: one-shot (triggered)              │
#   │              │   flags=0, dur=0: instant                           │
#   │ 0x95         │ Physics/trigger speed param (NOT standalone anim)   │
#   │ 0x10         │ Interactive trigger (doors, chests, panels)         │
#   │ 0x5          │ Static marker (floating platforms, stalactites)     │
#   └──────────────┴──────────────────────────────────────────────────────┘
# ═══════════════════════════════════════════════════════════════════════════

HARDCODED_ANIMS = {
    'sigil':    {'rot_period': 3.0, 'bob_amp': 0.38, 'bob_period': 1.5},
    'boat':     {'bob_amp': 0.25, 'bob_period': 4.0},
    'boat2':    {'bob_amp': 0.25, 'bob_period': 4.0},
    'l8balon1': {'bob_amp': 0.5, 'bob_period': 6.0},
}

_ANG_TO_RAD = math.tau / 2048.0

def build_object_animations(objects, collection):
    """Apply keyframe animations to objects in the collection.
    Handles: CTRL 0x105 (movement), CTRL 0x200 (rotation), hardcoded anims."""
    animated = 0
    for obj in collection.objects:
        if obj.type != 'MESH': continue
        did_anim = False; use_cycle = False; is_hardcoded = False
        mesh_name = obj.name.rsplit('_', 1)[0].lower()

        # ── CTRL 0x105: linear movement ──
        if 'ctrl_dx' in obj:
            dx=obj['ctrl_dx']; dy=obj['ctrl_dy']; dz=obj['ctrl_dz']
            dur_ms=obj['ctrl_dur']; flags=obj.get('ctrl_flags', 0)
            bl_dx = -dx * SCENE_SCALE
            bl_dy = -dz * SCENE_SCALE
            bl_dz = -dy * SCENE_SCALE
            rest = obj.location.copy()
            if dur_ms <= 0:
                obj.location = rest
                obj.keyframe_insert(data_path='location', frame=1)
                obj.location = (rest.x + bl_dx, rest.y + bl_dy, rest.z + bl_dz)
                obj.keyframe_insert(data_path='location', frame=2)
                if obj.animation_data and obj.animation_data.action:
                    for fc in obj.animation_data.action.fcurves:
                        if fc.data_path == 'location':
                            for kp in fc.keyframe_points: kp.interpolation = 'CONSTANT'
            else:
                dur_frames = max(int(dur_ms / 1000.0 * ANIM_FPS), 2)
                obj.location = rest
                obj.keyframe_insert(data_path='location', frame=1)
                obj.location = (rest.x + bl_dx, rest.y + bl_dy, rest.z + bl_dz)
                obj.keyframe_insert(data_path='location', frame=1 + dur_frames)
                if flags == 0x72:
                    obj.location = rest
                    obj.keyframe_insert(data_path='location', frame=1 + dur_frames * 2)
                    use_cycle = True
            did_anim = True

        # ── CTRL 0x200: rotation ──
        if 'ctrl_drx' in obj:
            drx=obj['ctrl_drx']; dry=obj['ctrl_dry']; drz=obj['ctrl_drz']
            dur_ms=obj['ctrl_rdur']; flags=obj.get('ctrl_rflags', 0)
            # Game rotation axes → Blender Euler:
            #   game drX → Blender rot X (negated, same as position X→-X)
            #   game drZ → Blender rot Y (negated, same as position Z→-Y)
            #   game drY → Blender rot Z (game uses -ry internally, so positive here)
            bl_rx = -drx * _ANG_TO_RAD
            bl_ry = -drz * _ANG_TO_RAD
            bl_rz = dry * _ANG_TO_RAD
            rest_rot = tuple(obj.rotation_euler)
            if dur_ms <= 0:
                obj.rotation_euler = rest_rot
                obj.keyframe_insert(data_path='rotation_euler', frame=1)
                obj.rotation_euler = (rest_rot[0]+bl_rx, rest_rot[1]+bl_ry, rest_rot[2]+bl_rz)
                obj.keyframe_insert(data_path='rotation_euler', frame=2)
                if obj.animation_data and obj.animation_data.action:
                    for fc in obj.animation_data.action.fcurves:
                        if fc.data_path == 'rotation_euler':
                            for kp in fc.keyframe_points: kp.interpolation = 'CONSTANT'
            else:
                dur_frames = max(int(dur_ms / 1000.0 * ANIM_FPS), 2)
                obj.rotation_euler = rest_rot
                obj.keyframe_insert(data_path='rotation_euler', frame=1)
                obj.rotation_euler = (rest_rot[0]+bl_rx, rest_rot[1]+bl_ry, rest_rot[2]+bl_rz)
                obj.keyframe_insert(data_path='rotation_euler', frame=1 + dur_frames)
                low_flags = flags & 0xFF
                if low_flags == 0x72:
                    obj.rotation_euler = rest_rot
                    obj.keyframe_insert(data_path='rotation_euler', frame=1 + dur_frames * 2)
                    use_cycle = True
                elif low_flags == 0x63:
                    use_cycle = True
            did_anim = True

        # ── Hardcoded animations (sigil, boat, l8balon1) ──
        anim = None
        for prefix, params in HARDCODED_ANIMS.items():
            if mesh_name.startswith(prefix):
                anim = params; break
        if anim:
            is_hardcoded = True
            if 'rot_period' in anim:
                rot_f = int(anim['rot_period'] * ANIM_FPS)
                obj.rotation_euler = (0, 0, 0)
                obj.keyframe_insert(data_path='rotation_euler', frame=1)
                obj.rotation_euler = (0, 0, math.pi * 2)
                obj.keyframe_insert(data_path='rotation_euler', frame=1 + rot_f)
            if 'bob_amp' in anim:
                bob_f = int(anim['bob_period'] * ANIM_FPS)
                rest = obj.location.copy()
                obj.location = rest
                obj.keyframe_insert(data_path='location', frame=1)
                obj.location = (rest.x, rest.y, rest.z + anim['bob_amp'])
                obj.keyframe_insert(data_path='location', frame=1 + bob_f // 2)
                obj.location = rest
                obj.keyframe_insert(data_path='location', frame=1 + bob_f)
            use_cycle = True; did_anim = True

        # ── Apply interpolation + cyclic ──
        if did_anim and obj.animation_data and obj.animation_data.action:
            interp = 'BEZIER' if is_hardcoded else 'LINEAR'
            for fc in obj.animation_data.action.fcurves:
                has_constant = any(kp.interpolation == 'CONSTANT' for kp in fc.keyframe_points)
                if not has_constant:
                    for kp in fc.keyframe_points: kp.interpolation = interp
                if use_cycle:
                    mod = fc.modifiers.new(type='CYCLES')
                    mod.mode_before = 'REPEAT'; mod.mode_after = 'REPEAT'
            animated += 1
    return animated

# ═══════════════════════════════════════════════════════════════════════════
#  TEXTURE ANIMATION (multi-frame BSI export)
# ═══════════════════════════════════════════════════════════════════════════
ANIMATED_TEX_DIR = 'BS_TEXTURES'

def get_animated_tex_path(gamedata_path=None):
    """Return path to animated textures folder (sibling of GAMEDATA, not inside it)."""
    gd = gamedata_path or RM._gamedata
    if not gd: return None
    parent = os.path.dirname(gd.rstrip('/\\'))
    p = os.path.join(parent, ANIMATED_TEX_DIR)
    return p if os.path.isdir(p) else None

def export_animated_bsis(gamedata_path=None):
    """Export all multi-frame BSIs as PNG sequences into BS_TEXTURES/ (next to GAMEDATA)."""
    gd = gamedata_path or RM._gamedata
    if not gd or not RM._bsi_bsa: return 0
    parent = os.path.dirname(gd.rstrip('/\\'))
    out_dir = os.path.join(parent, ANIMATED_TEX_DIR)
    os.makedirs(out_dir, exist_ok=True)
    exported = 0
    for fn in RM._bsi_bsa.names('.BSI'):
        stem = os.path.splitext(fn)[0].lower()
        raw = RM._bsi_bsa.get(fn)
        if not raw: continue
        info = bsi_get_frames(raw)
        if not info or info[2] <= 1: continue
        w, h, nframes = info
        frames = bsi_decode_all_frames(raw)
        if not frames: continue
        tex_dir = os.path.join(out_dir, stem)
        os.makedirs(tex_dir, exist_ok=True)
        for fi, (fw, fh, pixels) in enumerate(frames):
            _save_png(os.path.join(tex_dir, f"{stem}_{fi:04d}.png"), fw, fh, pixels)
        exported += 1
    return exported

def _save_png(path, w, h, pixels):
    """Save RGBA pixel data as PNG using Blender's image API."""
    img = bpy.data.images.new('_tmp_export', w, h, alpha=True)
    img.pixels = pixels
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)

def _get_animated_frame_count(tex_name):
    """Return frame count for animated texture, or 0."""
    tex_path = get_animated_tex_path()
    if not tex_path: return 0
    tex_dir = os.path.join(tex_path, tex_name)
    if not os.path.isdir(tex_dir): return 0
    return len([f for f in os.listdir(tex_dir) if f.endswith('.png')])

def apply_animated_textures():
    """Switch all applicable materials from packed to Image Sequence."""
    tex_path = get_animated_tex_path()
    if not tex_path: return 0
    count = 0
    for mat in bpy.data.materials:
        if not mat.use_nodes: continue
        for nd in mat.node_tree.nodes:
            if nd.type != 'TEX_IMAGE' or not nd.image: continue
            tex_name = nd.image.name
            if nd.image.source == 'SEQUENCE': continue
            nframes = _get_animated_frame_count(tex_name)
            if nframes < 2: continue
            tex_dir = os.path.join(tex_path, tex_name)
            first = sorted(f for f in os.listdir(tex_dir) if f.endswith('.png'))[0]
            old_img = nd.image
            new_img = bpy.data.images.load(os.path.join(tex_dir, first))
            new_img.name = tex_name; new_img.source = 'SEQUENCE'
            nd.image = new_img
            nd.image_user.frame_duration = nframes
            nd.image_user.frame_offset = -1
            nd.image_user.use_cyclic = True
            nd.image_user.use_auto_refresh = True
            if old_img.users == 0: bpy.data.images.remove(old_img)
            count += 1
    return count
