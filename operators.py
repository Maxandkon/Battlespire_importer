"""
Blender operators for Battlespire import.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
import os, time

from .core import parse_3d, parse_bs6_scene
from .builder import RM, build_mesh_object, build_level, OVERSIZE_RADIUS


def _ensure_loaded(context):
    """Check if RM is loaded. Returns True/False."""
    return RM.is_loaded


def _get_gamedata(context):
    prefs = context.preferences.addons[__package__].preferences
    return prefs.gamedata_path


class BS_OT_LoadData(Operator):
    bl_idname = "battlespire.load_data"
    bl_label = "Load Game Data"
    bl_description = "Load Battlespire archives (may take a moment)"

    def execute(self, context):
        gd = _get_gamedata(context)
        if not gd or not os.path.isdir(gd):
            self.report({'ERROR'}, "GAMEDATA path not set. Open addon preferences.")
            return {'CANCELLED'}
        t0 = time.time()
        ok = RM.load(gd)
        dt = time.time() - t0
        if ok:
            n_models = len(RM.get_model_names())
            n_scenes = len(RM.get_scene_names())
            n_tex = len(RM.tex_sizes)
            self.report({'INFO'}, f"Loaded: {n_models} models, {n_scenes} scenes, {n_tex} textures ({dt:.1f}s)")
        else:
            self.report({'ERROR'}, "Failed to load 3D.BSA")
        return {'FINISHED'}


class BS_OT_ImportLevel(Operator):
    bl_idname = "battlespire.import_level"
    bl_label = "Import Level"
    bl_description = "Import a Battlespire level"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not _ensure_loaded(context):
            self.report({'ERROR'}, "Load game data first."); return {'CANCELLED'}
        level = context.scene.bs_props.level_enum
        if not level or level == 'NONE':
            self.report({'ERROR'}, "No level selected"); return {'CANCELLED'}

        t0 = time.time()
        scene_data = RM.get_scene_data(level)
        if not scene_data:
            self.report({'ERROR'}, f"Cannot read {level}"); return {'CANCELLED'}
        objects = parse_bs6_scene(scene_data)
        if not objects:
            self.report({'WARNING'}, f"{level}: no objects"); return {'CANCELLED'}

        mesh_cache = {}
        needed = set(o['mesh'].upper() for o in objects)
        for m in needed:
            raw = RM.get_mesh_raw(m)
            mesh_cache[m] = parse_3d(raw, RM.tex_sizes) if raw else None
        valid = [o for o in objects if mesh_cache.get(o['mesh'].upper())]

        stem = os.path.splitext(level)[0]
        col = bpy.data.collections.new(stem)
        bpy.context.scene.collection.children.link(col)
        built = build_level(level, valid, mesh_cache, col)

        self.report({'INFO'}, f"{stem}: {built} objects ({time.time()-t0:.1f}s)")
        return {'FINISHED'}


class BS_OT_ImportUnused(Operator):
    bl_idname = "battlespire.import_unused"
    bl_label = "Import Unused Assets"
    bl_description = "Import all 3D models not used in any level"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not _ensure_loaded(context):
            self.report({'ERROR'}, "Load game data first."); return {'CANCELLED'}

        t0 = time.time()
        used = set()
        for sn in RM.get_scene_names():
            sd = RM.get_scene_data(sn)
            if sd:
                for obj in parse_bs6_scene(sd):
                    used.add(obj['mesh'].upper() + '.3D')

        all_models = set(RM.get_model_names())
        unused = sorted(all_models - used)

        col_normal = bpy.data.collections.new("Others_Unused")
        bpy.context.scene.collection.children.link(col_normal)
        col_large = bpy.data.collections.new("Others_Oversized")
        bpy.context.scene.collection.children.link(col_large)
        # Hide oversized collection by default in viewport
        for vl in bpy.context.scene.view_layers:
            lc = vl.layer_collection.children.get("Others_Oversized")
            if lc: lc.exclude = True

        x_offset = 0.0
        count_normal = 0; count_large = 0
        for name in unused:
            raw = RM.get_mesh_raw(name)
            if not raw: continue
            model = parse_3d(raw, RM.tex_sizes)
            if not model or not model['planes']: continue

            is_large = model['radius'] > OVERSIZE_RADIUS
            target_col = col_large if is_large else col_normal
            obj = build_mesh_object(model, name, target_col)
            if obj and not is_large:
                obj.location.x = x_offset
                x_offset += model['radius'] * 2.0 + 0.5
                count_normal += 1
            elif obj:
                count_large += 1

        self.report({'INFO'},
            f"{count_normal} assets + {count_large} oversized (hidden) in {time.time()-t0:.1f}s")
        return {'FINISHED'}


class BS_OT_ImportModelByName(Operator):
    bl_idname = "battlespire.import_model_by_name"
    bl_label = "Import Model"
    bl_description = "Import a model from 3D.BSA by name"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not _ensure_loaded(context):
            self.report({'ERROR'}, "Load game data first."); return {'CANCELLED'}
        name = context.scene.bs_props.model_name.strip().upper()
        if not name:
            self.report({'ERROR'}, "Enter a model name"); return {'CANCELLED'}
        if not name.endswith('.3D'): name += '.3D'
        raw = RM.get_mesh_raw(name)
        if not raw:
            self.report({'ERROR'}, f"{name} not found"); return {'CANCELLED'}
        model = parse_3d(raw, RM.tex_sizes)
        if not model:
            self.report({'ERROR'}, f"Failed to parse {name}"); return {'CANCELLED'}

        col = bpy.data.collections.get("BS_Models")
        if not col:
            col = bpy.data.collections.new("BS_Models")
            bpy.context.scene.collection.children.link(col)
        build_mesh_object(model, name, col)
        self.report({'INFO'}, f"Imported {name}: {len(model['planes'])} faces")
        return {'FINISHED'}


class BS_OT_ImportFile(Operator):
    bl_idname = "battlespire.import_file"
    bl_label = "Import .3D File"
    bl_description = "Import a Battlespire .3D file from disk"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.3D;*.3d", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            self.report({'ERROR'}, f"Not found: {self.filepath}"); return {'CANCELLED'}
        with open(self.filepath, 'rb') as f: data = f.read()
        model = parse_3d(data, RM.tex_sizes if RM.is_loaded else {})
        if not model:
            self.report({'ERROR'}, "Parse failed"); return {'CANCELLED'}
        col = bpy.data.collections.get("BS_Models")
        if not col:
            col = bpy.data.collections.new("BS_Models")
            bpy.context.scene.collection.children.link(col)
        build_mesh_object(model, os.path.basename(self.filepath), col)
        self.report({'INFO'}, f"Imported {os.path.basename(self.filepath)}")
        return {'FINISHED'}


class BS_OT_ImportFolder(Operator):
    bl_idname = "battlespire.import_folder"
    bl_label = "Import .3D Folder"
    bl_description = "Import all .3D files from a folder"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}

    def execute(self, context):
        files = [f for f in os.listdir(self.directory) if f.upper().endswith('.3D')]
        if not files:
            self.report({'WARNING'}, "No .3D files found"); return {'CANCELLED'}
        col = bpy.data.collections.new(os.path.basename(self.directory.rstrip('/\\')))
        bpy.context.scene.collection.children.link(col)
        imported = 0
        ts = RM.tex_sizes if RM.is_loaded else {}
        for fname in sorted(files):
            with open(os.path.join(self.directory, fname), 'rb') as f: data = f.read()
            model = parse_3d(data, ts)
            if model:
                build_mesh_object(model, fname, col); imported += 1
        self.report({'INFO'}, f"Imported {imported} models")
        return {'FINISHED'}


op_classes = (
    BS_OT_LoadData,
    BS_OT_ImportLevel,
    BS_OT_ImportUnused,
    BS_OT_ImportModelByName,
    BS_OT_ImportFile,
    BS_OT_ImportFolder,
)
