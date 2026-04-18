"""Blender operators for Battlespire import."""
import bpy
from bpy.props import StringProperty
from bpy.types import Operator
import os, time
from .core import parse_3d, parse_bs6_scene, parse_bs6_lights, parse_bs6_watr, parse_bs6_flats, CREATURE_TABLE
from .builder import (RM, build_mesh_object, build_level, build_lights, build_world_light, build_sky,
    build_water, build_spawn_markers, build_effect_spawns, build_npc_spawns, build_monster_spawns,
    build_effect_sprites, build_creature_sprites, build_npc_sprites, build_object_animations,
    export_animated_bsis, get_animated_tex_path, apply_animated_textures,
    OVERSIZE_RADIUS)

class BS_OT_LoadData(Operator):
    bl_idname = "battlespire.load_data"
    bl_label = "Load Game Data"
    def execute(self, context):
        gd=context.preferences.addons[__package__].preferences.gamedata_path
        if not gd or not os.path.isdir(gd): self.report({'ERROR'},"GAMEDATA path not set."); return {'CANCELLED'}
        t0=time.time(); ok=RM.load(gd)
        if ok: self.report({'INFO'},f"{len(RM.get_model_names())} models, {len(RM.get_scene_names())} scenes ({time.time()-t0:.1f}s)")
        else: self.report({'ERROR'},"Failed to load 3D.BSA")
        return {'FINISHED'}

class BS_OT_ImportLevel(Operator):
    bl_idname = "battlespire.import_level"
    bl_label = "Import Level"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        props=context.scene.bs_props; level=props.level_enum
        RM.use_animated_tex=props.use_animated_tex
        if not level or level=='NONE': self.report({'ERROR'},"No level selected"); return {'CANCELLED'}
        t0=time.time(); sd=RM.get_scene_data(level)
        if not sd: self.report({'ERROR'},f"Cannot read {level}"); return {'CANCELLED'}
        objects=parse_bs6_scene(sd)
        if not objects: self.report({'WARNING'},f"{level}: no objects"); return {'CANCELLED'}
        mc={}
        for m in set(o['mesh'].upper() for o in objects):
            raw=RM.get_mesh_raw(m); mc[m]=parse_3d(raw,RM.tex_sizes) if raw else None
        valid=[o for o in objects if mc.get(o['mesh'].upper())]
        stem=os.path.splitext(level)[0]
        col=bpy.data.collections.new(stem); bpy.context.scene.collection.children.link(col)
        built=build_level(level,valid,mc,col)
        lc=sc=ec=nc=0; ms=mm=0
        # Parse flats once (shared between spawns, effects, NPCs, monsters)
        need_flats=props.import_spawns or props.import_effects or props.import_npcs or props.import_monsters
        flats=parse_bs6_flats(sd) if need_flats else None
        if props.import_lights:
            lights=parse_bs6_lights(sd)
            if lights: lc=build_lights(lights,valid,col)
        if props.import_water:
            watr=parse_bs6_watr(sd)
            if watr is not None: build_water(watr,valid,col)
        if props.import_spawns and flats:
            sc=build_spawn_markers(flats,valid,col)
        if props.import_effects and flats:
            ec=build_effect_spawns(flats,valid,col)
        if props.import_npcs and flats:
            nc=build_npc_spawns(flats,valid,col)
        if props.import_monsters and flats:
            ms,mm=build_monster_spawns(flats,valid,col)
        parts=[f"{built} objects"]
        if lc: parts.append(f"{lc} lights")
        if sc: parts.append(f"{sc} spawns")
        if ec: parts.append(f"{ec} effects")
        if nc: parts.append(f"{nc} NPCs")
        if ms or mm: parts.append(f"{ms} monsters ({mm} unknown)")
        self.report({'INFO'},f"{stem}: {', '.join(parts)} ({time.time()-t0:.1f}s)")
        return {'FINISHED'}

class BS_OT_ImportLevelAnimated(Operator):
    bl_idname = "battlespire.import_level_animated"
    bl_label = "Import (with animations)"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        props=context.scene.bs_props; level=props.level_enum
        RM.use_animated_tex=props.use_animated_tex
        if not level or level=='NONE': self.report({'ERROR'},"No level selected"); return {'CANCELLED'}
        t0=time.time(); sd=RM.get_scene_data(level)
        if not sd: self.report({'ERROR'},f"Cannot read {level}"); return {'CANCELLED'}
        objects=parse_bs6_scene(sd)
        if not objects: self.report({'WARNING'},f"{level}: no objects"); return {'CANCELLED'}
        mc={}
        for m in set(o['mesh'].upper() for o in objects):
            raw=RM.get_mesh_raw(m); mc[m]=parse_3d(raw,RM.tex_sizes) if raw else None
        valid=[o for o in objects if mc.get(o['mesh'].upper())]
        stem=os.path.splitext(level)[0]
        col=bpy.data.collections.new(stem); bpy.context.scene.collection.children.link(col)
        built=build_level(level,valid,mc,col)
        # Object movement animations
        ac=build_object_animations(valid,col)
        lc=sc=ec=nc=0; ms=mm=0
        need_flats=props.import_spawns or props.import_effects or props.import_npcs or props.import_monsters
        flats=parse_bs6_flats(sd) if need_flats else None
        if props.import_lights:
            lights=parse_bs6_lights(sd)
            if lights: lc=build_lights(lights,valid,col)
        if props.import_water:
            watr=parse_bs6_watr(sd)
            if watr is not None: build_water(watr,valid,col)
        if props.import_spawns and flats:
            sc=build_spawn_markers(flats,valid,col)
        if props.import_effects and flats:
            ec=build_effect_spawns(flats,valid,col)
        if props.import_npcs and flats:
            nc=build_npc_spawns(flats,valid,col)
        if props.import_monsters and flats:
            ms,mm=build_monster_spawns(flats,valid,col)
        parts=[f"{built} objects"]
        if ac: parts.append(f"{ac} animated")
        if lc: parts.append(f"{lc} lights")
        if sc: parts.append(f"{sc} spawns")
        if ec: parts.append(f"{ec} effects")
        if nc: parts.append(f"{nc} NPCs")
        if ms or mm: parts.append(f"{ms} monsters ({mm} unknown)")
        self.report({'INFO'},f"{stem}: {', '.join(parts)} ({time.time()-t0:.1f}s)")
        return {'FINISHED'}

class BS_OT_ExportTextures(Operator):
    bl_idname = "battlespire.export_textures"
    bl_label = "Export Animated Textures"
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        t0=time.time()
        count=export_animated_bsis()
        self.report({'INFO'},f"Exported {count} animated textures ({time.time()-t0:.1f}s)")
        return {'FINISHED'}

class BS_OT_ToggleAnimatedTex(Operator):
    bl_idname = "battlespire.toggle_animated_tex"
    bl_label = "Apply Animated Textures"
    def execute(self, context):
        props=context.scene.bs_props
        count=apply_animated_textures()
        props.use_animated_tex=True; RM.use_animated_tex=True
        self.report({'INFO'},f"Applied animated textures to {count} materials")
        return {'FINISHED'}

class BS_OT_ImportSkyWorld(Operator):
    bl_idname = "battlespire.import_sky_world"
    bl_label = "Import Sky + World"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        level=context.scene.bs_props.level_enum
        if not level or level=='NONE': self.report({'ERROR'},"No level selected"); return {'CANCELLED'}
        li=RM.get_level_info(level); sd=RM.get_scene_data(level)
        if not sd: self.report({'ERROR'},f"Cannot read {level}"); return {'CANCELLED'}
        objects=parse_bs6_scene(sd)
        if not objects: self.report({'WARNING'},"No objects"); return {'CANCELLED'}
        stem=os.path.splitext(level)[0]
        col=bpy.data.collections.get(stem)
        if not col: col=bpy.data.collections.new(f"{stem}_Sky"); bpy.context.scene.collection.children.link(col)
        build_world_light(li); build_sky(li,objects,col)
        self.report({'INFO'},f"Sky: {li.get('sky_bsi','-') if li else '-'}")
        return {'FINISHED'}

class BS_OT_ImportEffectSprites(Operator):
    bl_idname = "battlespire.import_effect_sprites"
    bl_label = "Import Effect Sprites"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        RM.use_animated_tex=context.scene.bs_props.use_animated_tex
        col=bpy.data.collections.new("Effect_Sprites"); bpy.context.scene.collection.children.link(col)
        built=build_effect_sprites(col)
        self.report({'INFO'},f"{built} effect sprites"); return {'FINISHED'}

class BS_OT_ImportCreatureSprites(Operator):
    bl_idname = "battlespire.import_creature_sprites"
    bl_label = "Import Entity Sprites"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        RM.use_animated_tex=context.scene.bs_props.use_animated_tex
        prefix=context.scene.bs_props.creature_type
        if not prefix: self.report({'ERROR'},"Select entity"); return {'CANCELLED'}
        if prefix == 'all_npc':
            col=bpy.data.collections.new("NPC_All"); bpy.context.scene.collection.children.link(col)
            built=build_npc_sprites(col)
            self.report({'INFO'},f"{built} NPC sprites"); return {'FINISHED'}
        name=CREATURE_TABLE.get(prefix,prefix)
        col=bpy.data.collections.new(f"Entity_{name}"); bpy.context.scene.collection.children.link(col)
        built=build_creature_sprites(prefix,name,col)
        self.report({'INFO'},f"{built} sprites for {name}"); return {'FINISHED'}

class BS_OT_ImportNPCSprites(Operator):
    bl_idname = "battlespire.import_npc_sprites"
    bl_label = "Import NPC Sprites"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        RM.use_animated_tex=context.scene.bs_props.use_animated_tex
        col=bpy.data.collections.new("NPC_Sprites"); bpy.context.scene.collection.children.link(col)
        built=build_npc_sprites(col)
        self.report({'INFO'},f"{built} NPC sprites"); return {'FINISHED'}

class BS_OT_ImportUnused(Operator):
    bl_idname = "battlespire.import_unused"
    bl_label = "Import Unused Assets"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        RM.use_animated_tex=context.scene.bs_props.use_animated_tex
        t0=time.time(); used=set()
        for sn in RM.get_scene_names():
            sd=RM.get_scene_data(sn)
            if sd:
                for o in parse_bs6_scene(sd): used.add(o['mesh'].upper()+'.3D')
        unused=sorted(set(RM.get_model_names())-used)
        cn_col=bpy.data.collections.new("Others_Unused"); bpy.context.scene.collection.children.link(cn_col)
        cl_col=bpy.data.collections.new("Others_Oversized"); bpy.context.scene.collection.children.link(cl_col)
        for vl in bpy.context.scene.view_layers:
            lc=vl.layer_collection.children.get("Others_Oversized")
            if lc: lc.exclude=True
        x=0.0; cn=cl=0
        for name in unused:
            raw=RM.get_mesh_raw(name)
            if not raw: continue
            m=parse_3d(raw,RM.tex_sizes)
            if not m or not m['planes']: continue
            big=m['radius']>OVERSIZE_RADIUS
            obj=build_mesh_object(m,name,cl_col if big else cn_col)
            if obj and not big: obj.location.x=x; x+=m['radius']*2+0.5; cn+=1
            elif obj: cl+=1
        self.report({'INFO'},f"{cn} + {cl} oversized ({time.time()-t0:.1f}s)"); return {'FINISHED'}

class BS_OT_ImportModelByName(Operator):
    bl_idname = "battlespire.import_model_by_name"
    bl_label = "Import Model"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        if not RM.is_loaded: self.report({'ERROR'},"Load game data first."); return {'CANCELLED'}
        RM.use_animated_tex=context.scene.bs_props.use_animated_tex
        name=context.scene.bs_props.model_name.strip().upper()
        if not name: self.report({'ERROR'},"Enter name"); return {'CANCELLED'}
        if not name.endswith('.3D'): name+='.3D'
        raw=RM.get_mesh_raw(name)
        if not raw: self.report({'ERROR'},f"{name} not found"); return {'CANCELLED'}
        m=parse_3d(raw,RM.tex_sizes)
        if not m: self.report({'ERROR'},"Parse failed"); return {'CANCELLED'}
        col=bpy.data.collections.get("BS_Models")
        if not col: col=bpy.data.collections.new("BS_Models"); bpy.context.scene.collection.children.link(col)
        build_mesh_object(m,name,col); self.report({'INFO'},f"Imported {name}"); return {'FINISHED'}

class BS_OT_ImportFile(Operator):
    bl_idname = "battlespire.import_file"
    bl_label = "Import .3D File"
    bl_options = {'REGISTER','UNDO'}
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.3D;*.3d", options={'HIDDEN'})
    def invoke(self, context, event): context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}
    def execute(self, context):
        if not os.path.isfile(self.filepath): self.report({'ERROR'},"Not found"); return {'CANCELLED'}
        with open(self.filepath,'rb') as f: d=f.read()
        m=parse_3d(d,RM.tex_sizes if RM.is_loaded else {})
        if not m: self.report({'ERROR'},"Parse failed"); return {'CANCELLED'}
        col=bpy.data.collections.get("BS_Models")
        if not col: col=bpy.data.collections.new("BS_Models"); bpy.context.scene.collection.children.link(col)
        build_mesh_object(m,os.path.basename(self.filepath),col)
        self.report({'INFO'},f"Imported {os.path.basename(self.filepath)}"); return {'FINISHED'}

class BS_OT_ImportFolder(Operator):
    bl_idname = "battlespire.import_folder"
    bl_label = "Import .3D Folder"
    bl_options = {'REGISTER','UNDO'}
    directory: StringProperty(subtype='DIR_PATH')
    def invoke(self, context, event): context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}
    def execute(self, context):
        files=[f for f in os.listdir(self.directory) if f.upper().endswith('.3D')]
        if not files: self.report({'WARNING'},"No .3D files"); return {'CANCELLED'}
        col=bpy.data.collections.new(os.path.basename(self.directory.rstrip('/\\'))); bpy.context.scene.collection.children.link(col)
        n=0; ts=RM.tex_sizes if RM.is_loaded else {}
        for fn in sorted(files):
            with open(os.path.join(self.directory,fn),'rb') as f: d=f.read()
            m=parse_3d(d,ts)
            if m: build_mesh_object(m,fn,col); n+=1
        self.report({'INFO'},f"Imported {n} models"); return {'FINISHED'}

op_classes = (BS_OT_LoadData, BS_OT_ImportLevel, BS_OT_ImportLevelAnimated,
    BS_OT_ImportSkyWorld, BS_OT_ExportTextures, BS_OT_ToggleAnimatedTex,
    BS_OT_ImportNPCSprites, BS_OT_ImportEffectSprites, BS_OT_ImportCreatureSprites,
    BS_OT_ImportUnused, BS_OT_ImportModelByName, BS_OT_ImportFile, BS_OT_ImportFolder)
