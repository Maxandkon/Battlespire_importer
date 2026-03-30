"""
Blender mesh/material builders and resource manager.
Key principle: NEVER cache bpy.types references — they become invalid on undo/load.
Instead, cache only names and use bpy.data.*.get(name) every time.
"""

import bpy
import os
from collections import defaultdict
from .core import (
    BSAArchive, bsi_get_size, bsi_decode_image, parse_3d,
    parse_bs6_scene, rotate_point, SCENE_SCALE,
)

OVERSIZE_RADIUS = 5.0


class ResourceManager:

    def __init__(self):
        self.reset()

    def reset(self):
        self._gamedata = ""
        self._loaded = False
        self._model_bsa = None
        self._model_bs6 = None
        self._bsi_bsa = None
        self._bs6_bsa = None
        self.tex_sizes = {}
        self._bsi_name_index = {}
        self._failed_images = set()

    @property
    def is_loaded(self):
        return self._loaded

    def load(self, gamedata_path):
        if self._loaded and self._gamedata == gamedata_path:
            return True
        self.reset()
        self._gamedata = gamedata_path

        for fname, attr in [("3D.BSA", "_model_bsa"), ("3D.BS6", "_model_bs6"),
                            ("BSI.BSA", "_bsi_bsa"), ("BS6.BSA", "_bs6_bsa")]:
            p = os.path.join(gamedata_path, fname)
            if os.path.isfile(p):
                setattr(self, attr, BSAArchive(p))

        if self._bsi_bsa:
            for fn in self._bsi_bsa.names('.BSI'):
                stem = os.path.splitext(fn)[0].lower()
                raw = self._bsi_bsa.get(fn)
                if raw:
                    sz = bsi_get_size(raw)
                    if sz: self.tex_sizes[stem] = sz
                self._bsi_name_index[stem] = fn

        self._loaded = self._model_bsa is not None
        return self._loaded

    def get_mesh_raw(self, name):
        key = name.upper()
        if not key.endswith('.3D'): key += '.3D'
        for arc in [self._model_bsa, self._model_bs6]:
            if arc:
                data = arc.get(key)
                if data: return data
        return None

    def get_model_names(self):
        names = set()
        for arc in [self._model_bsa, self._model_bs6]:
            if arc: names.update(arc.names('.3D'))
        return sorted(names)

    def get_scene_names(self):
        if not self._bs6_bsa: return []
        return sorted(self._bs6_bsa.names('.BS6'))

    def get_scene_data(self, name):
        return self._bs6_bsa.get(name) if self._bs6_bsa else None

    def resolve_bsi(self, tex_name):
        if not self._bsi_bsa: return None
        exact = tex_name.upper() + '.BSI'
        if self._bsi_bsa.has(exact): return exact
        if tex_name in self._bsi_name_index: return self._bsi_name_index[tex_name]
        matches = sorted([v for k, v in self._bsi_name_index.items() if k.startswith(tex_name)])
        return matches[0] if len(matches) == 1 else None

    # ── Blender image — always lookup by name, decode on miss ─────────

    @staticmethod
    def _img_bl_name(tex_name):
        return f"bs_{tex_name}"

    def get_image(self, tex_name):
        bl_name = self._img_bl_name(tex_name)
        existing = bpy.data.images.get(bl_name)
        if existing:
            return existing
        if bl_name in self._failed_images:
            return None

        bsi_fname = self.resolve_bsi(tex_name)
        bsi_data = self._bsi_bsa.get(bsi_fname) if bsi_fname and self._bsi_bsa else None
        if not bsi_data:
            self._failed_images.add(bl_name)
            return None
        result = bsi_decode_image(bsi_data)
        if not result:
            self._failed_images.add(bl_name)
            return None
        w, h, pixels = result
        img = bpy.data.images.new(bl_name, w, h, alpha=True)
        img.pixels = pixels
        img.pack()
        return img

    # ── Blender material — always lookup by name, create on miss ──────

    @staticmethod
    def _mat_bl_name(tex_name, color):
        if tex_name:
            return f"bs_{tex_name}"
        r, g, b = round(color[0], 3), round(color[1], 3), round(color[2], 3)
        return f"bs_solid_{r}_{g}_{b}"

    def get_material(self, tex_name, color):
        mat_name = self._mat_bl_name(tex_name, color)
        existing = bpy.data.materials.get(mat_name)
        if existing:
            return existing

        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.location = (0, 0)
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Roughness'].default_value = 1.0

        for ior_name in ['IOR', 'IOR Level']:
            if ior_name in bsdf.inputs:
                bsdf.inputs[ior_name].default_value = 1.0
                break
        for spec_name in ['Specular IOR Level', 'Specular']:
            if spec_name in bsdf.inputs:
                bsdf.inputs[spec_name].default_value = 0.0
                break

        out = nodes.new('ShaderNodeOutputMaterial')
        out.location = (300, 0)
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

        if tex_name and tex_name.startswith('1_'):
            bsdf.inputs['Alpha'].default_value = 0.0
            self._set_alpha_clip(mat)
        elif tex_name:
            img = self.get_image(tex_name)
            if img:
                tx = nodes.new('ShaderNodeTexImage')
                tx.location = (-400, 0)
                tx.image = img
                tx.interpolation = 'Closest'
                tx.extension = 'REPEAT'
                links.new(tx.outputs['Color'], bsdf.inputs['Base Color'])
            else:
                bsdf.inputs['Base Color'].default_value = (*color, 1.0)
        else:
            bsdf.inputs['Base Color'].default_value = (*color, 1.0)

        mat.use_backface_culling = False
        return mat

    @staticmethod
    def _set_alpha_clip(mat):
        try:
            mat.blend_method = 'CLIP'
            mat.alpha_threshold = 0.5
        except (AttributeError, TypeError):
            pass


RM = ResourceManager()


# ═══════════════════════════════════════════════════════════════════════════
#  MESH BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def build_mesh_object(model, name, collection):
    stem = os.path.splitext(name)[0]
    mat_groups = defaultdict(list)
    for plane in model['planes']:
        if len(plane['vertices']) < 3: continue
        tn = plane['texture_name']
        if tn: mk = ('t', tn)
        else: c = plane['color']; mk = ('c', round(c[0],3), round(c[1],3), round(c[2],3))
        mat_groups[mk].append(plane)
    if not mat_groups: return None

    mat_keys = list(mat_groups.keys())
    mk2i = {mk: i for i, mk in enumerate(mat_keys)}
    verts = []; faces = []; uvs = []; mat_ids = []; vi = 0
    for mk, plist in mat_groups.items():
        mi = mk2i[mk]
        for plane in plist:
            vs = plane['vertices']
            for i in range(1, len(vs)-1):
                for j in (0, i, i+1):
                    vx,vy,vz,u,v = vs[j]
                    verts.append((vx,vy,vz)); uvs.append((u,v))
                faces.append((vi,vi+1,vi+2)); mat_ids.append(mi); vi += 3

    mesh = bpy.data.meshes.new(stem)
    mesh.from_pydata(verts, [], faces)
    for mk in mat_keys:
        rep = mat_groups[mk][0]
        mesh.materials.append(RM.get_material(rep['texture_name'], rep['color']))
    for fi, mi in enumerate(mat_ids):
        mesh.polygons[fi].material_index = mi
    uv_layer = mesh.uv_layers.new(name='UVMap')
    for li, loop in enumerate(mesh.loops):
        uv_layer.data[li].uv = uvs[loop.vertex_index]
    mesh.update()
    obj = bpy.data.objects.new(stem, mesh)
    collection.objects.link(obj)
    for poly in mesh.polygons:
        poly.use_smooth = False
    return obj


def build_level(scene_name, objects, mesh_cache, collection):
    all_px = [o['pos'][0]*SCENE_SCALE for o in objects]
    all_py = [o['pos'][1]*SCENE_SCALE for o in objects]
    all_pz = [o['pos'][2]*SCENE_SCALE for o in objects]
    ox = sum(all_px)/len(all_px) if all_px else 0
    oy = max(all_py) if all_py else 0
    oz = sum(all_pz)/len(all_pz) if all_pz else 0

    instance_count = {}; built = 0
    for obj_data in objects:
        key = obj_data['mesh'].upper()
        model = mesh_cache.get(key)
        if not model or not model['planes']: continue
        instance_count[key] = instance_count.get(key, 0) + 1
        label = f"{obj_data['mesh']}_{instance_count[key]:03d}"
        px0 = obj_data['pos'][0]*SCENE_SCALE - ox
        py0 = -(obj_data['pos'][1]*SCENE_SCALE - oy)
        pz0 = obj_data['pos'][2]*SCENE_SCALE - oz
        rx, ry, rz = obj_data['rot']

        mat_groups = defaultdict(list)
        for plane in model['planes']:
            if len(plane['vertices']) < 3: continue
            tn = plane['texture_name']
            if tn: mk = ('t', tn)
            else: c = plane['color']; mk = ('c', round(c[0],3), round(c[1],3), round(c[2],3))
            mat_groups[mk].append(plane)
        if not mat_groups: continue

        mat_keys = list(mat_groups.keys())
        mk2i = {mk: i for i, mk in enumerate(mat_keys)}
        verts = []; faces = []; uvs = []; mat_ids = []; vi = 0
        for mk, plist in mat_groups.items():
            mi = mk2i[mk]
            for plane in plist:
                vs = plane['vertices']
                for i in range(1, len(vs)-1):
                    for j in (0, i, i+1):
                        vx,vy,vz,u,v = vs[j]
                        wx,wy,wz = rotate_point(vx,vy,vz,rx,ry,rz)
                        wx = -wx - px0; wy = -wy + py0; wz = wz + pz0
                        verts.append((wx, -wz, wy)); uvs.append((u,v))
                    faces.append((vi,vi+1,vi+2)); mat_ids.append(mi); vi += 3

        mesh = bpy.data.meshes.new(label)
        mesh.from_pydata(verts, [], faces)
        for mk in mat_keys:
            rep = mat_groups[mk][0]
            mesh.materials.append(RM.get_material(rep['texture_name'], rep['color']))
        for fi, mi in enumerate(mat_ids):
            mesh.polygons[fi].material_index = mi
        uv_layer = mesh.uv_layers.new(name='UVMap')
        for li, loop in enumerate(mesh.loops):
            uv_layer.data[li].uv = uvs[loop.vertex_index]
        mesh.update()
        bl_obj = bpy.data.objects.new(label, mesh)
        collection.objects.link(bl_obj)
        for poly in mesh.polygons:
            poly.use_smooth = False
        built += 1
    return built
