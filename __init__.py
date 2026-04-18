bl_info = {
    "name": "Battlespire 3D Importer",
    "author": "Maxandkon",
    "version": (2, 0, 'a'),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Battlespire, File > Import",
    "description": "Import 3D models and levels from An Elder Scrolls Legend: Battlespire",
    "category": "Import-Export",
}
import bpy
from bpy.props import StringProperty, EnumProperty, PointerProperty, BoolProperty
from bpy.types import AddonPreferences, Panel, PropertyGroup
import os
from .builder import RM
from .core import CREATURE_TABLE
from .operators import op_classes

@bpy.app.handlers.persistent
def _on_load_post(*args): RM.reset()

translations_dict = {
    "uk_UA": {
        ("*","Battlespire"): "Battlespire",
        ("*","Import Level"): "Імпорт локації",
        ("*","Import"): "Імпортувати",
        ("*","Point Lights"): "Точкове світло",
        ("*","Water"): "Вода",
        ("*","Spawn Points"): "Точки спавну",
        ("*","Effects"): "Ефекти",
        ("*","NPCs"): "НПС",
        ("*","Monsters"): "Монстри",
        ("*","Data Files"): "Файли даних",
        ("*","Load Game Data"): "Завантажити дані",
        ("*","This may take a moment"): "Це може зайняти час",
        ("*","Experimental"): "Експериментальне",
        ("*","Import Sky + World"): "Імпорт неба + World",
        ("*","Entities"): "Сутності",
        ("*","Import Entity Sprites"): "Імпорт спрайтів сутностей",
        ("*","Import Effect Sprites"): "Імпорт спрайтів ефектів",
        ("*","Import (with animations)"): "Імпорт (з анімаціями)",
        ("*","Animated Textures"): "Анімовані текстури",
        ("*","Textures exported"): "Текстури експортовано",
        ("*","Not exported yet"): "Ще не експортовано",
        ("*","Export Animated Textures"): "Експорт анімованих текстур",
        ("*","Others (unused)"): "Інші (невикористані)",
        ("*","Import Models"): "Імпорт моделей",
    },
}

class BS_AddonPreferences(AddonPreferences):
    bl_idname = __package__
    gamedata_path: StringProperty(name="GAMEDATA Folder", subtype='DIR_PATH', default="")
    def draw(self, context):
        layout = self.layout
        layout.label(text="Path to GAMEDATA folder:")
        col = layout.column(align=True)
        col.label(text="...\\An Elder Scrolls Legend")
        col.label(text="Battlespire\\GAMEDATA", icon='INFO')
        layout.prop(self, "gamedata_path")
        gd = self.gamedata_path
        if gd and os.path.isdir(gd):
            found = [f for f in ["3D.BSA","BSI.BSA","BS6.BSA","3D.BS6","LEVELS.TXT"]
                     if os.path.isfile(os.path.join(gd, f))]
            layout.label(text=f"Found: {', '.join(found)}", icon='CHECKMARK')
        elif gd: layout.label(text="Folder not found!", icon='ERROR')

def _get_level_items(self, context):
    items = []
    if RM.is_loaded:
        for sn in RM.get_scene_names():
            items.append((sn, os.path.splitext(sn)[0], f"Level {os.path.splitext(sn)[0]}"))
    if not items: items.append(('NONE','(not loaded)',''))
    return items

def _get_creature_items(self, context):
    items = []
    # All NPCs as a single entry
    items.append(('all_npc', 'All NPCs', 'Import all NPC sprites'))
    # Then creatures + PvP
    for prefix, name in sorted(CREATURE_TABLE.items(), key=lambda x: x[1]):
        if RM.is_loaded:
            c = RM.get_creature_bsi_count(prefix)
            items.append((prefix, f"{name} ({c})", f"{name} sprites"))
        else: items.append((prefix, name, f"{name} sprites"))
    if not items: items.append(('NONE','(none)',''))
    return items

class BS_SceneProperties(PropertyGroup):
    level_enum: EnumProperty(name="Level", items=_get_level_items)
    model_name: StringProperty(name="Model Name", default="")
    import_lights: BoolProperty(name="Point Lights", default=False)
    import_water: BoolProperty(name="Water", default=False)
    import_spawns: BoolProperty(name="Spawn Points", default=False)
    import_effects: BoolProperty(name="Effects", default=False)
    import_npcs: BoolProperty(name="NPCs", default=False)
    import_monsters: BoolProperty(name="Monsters", default=False)
    use_animated_tex: BoolProperty(name="Animated Textures", default=False)
    creature_type: EnumProperty(name="Creature", items=_get_creature_items)

class BS_PT_MainPanel(Panel):
    bl_label = "Battlespire"
    bl_idname = "BS_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Battlespire"

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences
        gd = prefs.gamedata_path

        box = layout.box()
        box.label(text="Data Files", icon='FILE_FOLDER')
        if gd and os.path.isdir(gd):
            box.label(text=os.path.basename(gd.rstrip('/\\')), icon='CHECKMARK')
        else:
            box.label(text="Set GAMEDATA path", icon='ERROR')
            box.operator("preferences.addon_show", text="Preferences",
                         icon='PREFERENCES').module = __package__
            return
        if not RM.is_loaded:
            layout.separator(); box = layout.box()
            box.label(text="This may take a moment", icon='TIME')
            box.operator("battlespire.load_data", icon='IMPORT'); return

        props = context.scene.bs_props

        # Level
        layout.separator(); box = layout.box()
        box.label(text="Import Level", icon='WORLD_DATA')
        box.prop(props, "level_enum", text="")
        row = box.row(align=True)
        row.prop(props, "import_lights", toggle=True)
        row.prop(props, "import_water", toggle=True)
        row.prop(props, "import_spawns", toggle=True)
        row = box.row(align=True)
        row.prop(props, "import_effects", toggle=True)
        row.prop(props, "import_npcs", toggle=True)
        row.prop(props, "import_monsters", toggle=True)
        box.operator("battlespire.import_level", text="Import", icon='IMPORT')
        box.operator("battlespire.import_level_animated", text="Import (with animations)", icon='ANIM')

        # Sky + World (experimental)
        layout.separator(); box = layout.box()
        box.label(text="Experimental", icon='MODIFIER')
        level = props.level_enum
        has_sky = RM.level_has_sky(level) if level and level != 'NONE' else False
        sub = box.row(); sub.enabled = has_sky
        sub.operator("battlespire.import_sky_world", icon='LIGHT_SUN')

        # Animated Textures
        from .builder import get_animated_tex_path
        tex_path = get_animated_tex_path()
        layout.separator(); box = layout.box()
        box.label(text="Animated Textures", icon='RENDER_ANIMATION')
        if tex_path:
            box.label(text="Textures exported", icon='CHECKMARK')
            if props.use_animated_tex:
                box.label(text="Applied to scene", icon='FILE_REFRESH')
            else:
                box.operator("battlespire.toggle_animated_tex",
                             text="Apply to existing materials", icon='PLAY')
        else:
            box.label(text="Not exported yet", icon='INFO')
            box.operator("battlespire.export_textures", icon='EXPORT')

        # Entities (All NPCs + Creatures + PvP)
        layout.separator(); box = layout.box()
        box.label(text="Entities", icon='COMMUNITY')
        box.prop(props, "creature_type", text="")
        box.operator("battlespire.import_creature_sprites", icon='IMPORT')

        # Effects
        layout.separator(); box = layout.box()
        box.label(text="Effects", icon='PARTICLES')
        box.operator("battlespire.import_effect_sprites", icon='IMPORT')

        # Others
        layout.separator(); box = layout.box()
        box.label(text="Others (unused)", icon='OUTLINER_OB_MESH')
        box.operator("battlespire.import_unused", icon='IMPORT')

        # Model by name
        layout.separator(); box = layout.box()
        box.label(text="Import Models", icon='MESH_DATA')
        box.prop(props, "model_name", text="", icon='VIEWZOOM')
        box.operator("battlespire.import_model_by_name", text="Import", icon='IMPORT')

def menu_func_import(self, context):
    self.layout.operator("battlespire.import_file", text="Battlespire .3D (.3D)")
    self.layout.operator("battlespire.import_folder", text="Battlespire .3D Folder")

classes = (BS_AddonPreferences, BS_SceneProperties, *op_classes, BS_PT_MainPanel)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.bs_props = PointerProperty(type=BS_SceneProperties)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.app.handlers.load_post.append(_on_load_post)
    try: bpy.app.translations.register(__package__, translations_dict)
    except: pass

def unregister():
    try: bpy.app.translations.unregister(__package__)
    except: pass
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    del bpy.types.Scene.bs_props
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    RM.reset()
