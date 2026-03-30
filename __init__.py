bl_info = {
    "name": "Battlespire 3D Importer",
    "author": "Maxandkon",
    "version": (1, 0, 1),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Battlespire, File > Import",
    "description": "Import 3D models and levels from An Elder Scrolls Legend: Battlespire",
    "category": "Import-Export",
}

import bpy
from bpy.props import StringProperty, EnumProperty, PointerProperty
from bpy.types import AddonPreferences, Panel, PropertyGroup
import os

from .builder import RM
from .operators import op_classes

# ═══════════════════════════════════════════════════════════════════════════
#  LOAD HANDLER — reset RM when .blend changes so data is re-loaded
# ═══════════════════════════════════════════════════════════════════════════

@bpy.app.handlers.persistent
def _on_load_post(*args):
    RM.reset()

# ═══════════════════════════════════════════════════════════════════════════
#  TRANSLATION
# ═══════════════════════════════════════════════════════════════════════════

translations_dict = {
    "uk_UA": {
        ("*", "Battlespire 3D Importer"): "Battlespire 3D Імпортер",
        ("*", "GAMEDATA Folder"): "Тека GAMEDATA",
        ("*", "Battlespire"): "Battlespire",
        ("*", "Import Level"): "Імпорт локації",
        ("*", "Import"): "Імпортувати",
        ("*", "Import Unused Assets"): "Імпорт невикористаних",
        ("*", "Model Name"): "Назва моделі",
        ("*", "Import Model"): "Імпорт моделі",
        ("*", "Import .3D File"): "Імпорт .3D файлу",
        ("*", "Import .3D Folder"): "Імпорт теки .3D",
        ("*", "Others (unused)"): "Інші (невикористані)",
        ("*", "Import Models"): "Імпорт моделей",
        ("*", "Data Files"): "Файли даних",
        ("*", "Load Game Data"): "Завантажити дані",
        ("*", "Level"): "Локація",
        ("*", "Not loaded"): "Не завантажено",
        ("*", "This may take a moment"): "Це може зайняти час",
    },
}

# ═══════════════════════════════════════════════════════════════════════════
#  PREFERENCES
# ═══════════════════════════════════════════════════════════════════════════

class BS_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    gamedata_path: StringProperty(
        name="GAMEDATA Folder",
        subtype='DIR_PATH',
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Path to GAMEDATA folder:")
        col = layout.column(align=True)
        col.label(text="...\\An Elder Scrolls Legend")
        col.label(text="Battlespire\\GAMEDATA", icon='INFO')
        layout.prop(self, "gamedata_path")
        gd = self.gamedata_path
        if gd and os.path.isdir(gd):
            found = [f for f in ["3D.BSA", "BSI.BSA", "BS6.BSA", "3D.BS6"]
                     if os.path.isfile(os.path.join(gd, f))]
            layout.label(text=f"Found: {', '.join(found)}", icon='CHECKMARK')
        elif gd:
            layout.label(text="Folder not found!", icon='ERROR')

# ═══════════════════════════════════════════════════════════════════════════
#  SCENE PROPERTIES
# ═══════════════════════════════════════════════════════════════════════════

def _get_level_items(self, context):
    items = []
    if RM.is_loaded:
        for sn in RM.get_scene_names():
            stem = os.path.splitext(sn)[0]
            items.append((sn, stem, f"Level {stem}"))
    if not items:
        items.append(('NONE', '(not loaded)', ''))
    return items

class BS_SceneProperties(PropertyGroup):
    level_enum: EnumProperty(
        name="Level",
        items=_get_level_items,
    )
    model_name: StringProperty(
        name="Model Name",
        default="",
    )

# ═══════════════════════════════════════════════════════════════════════════
#  PANEL
# ═══════════════════════════════════════════════════════════════════════════

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
            box.operator("preferences.addon_show",
                         text="Preferences", icon='PREFERENCES').module = __package__
            return

        if not RM.is_loaded:
            layout.separator()
            box = layout.box()
            box.label(text="This may take a moment", icon='TIME')
            box.operator("battlespire.load_data", icon='IMPORT')
            return

        props = context.scene.bs_props

        layout.separator()
        box = layout.box()
        box.label(text="Import Level", icon='WORLD_DATA')
        box.prop(props, "level_enum", text="")
        box.operator("battlespire.import_level",
                      text="Import", icon='IMPORT')

        layout.separator()
        box = layout.box()
        box.label(text="Others (unused)", icon='OUTLINER_OB_MESH')
        box.operator("battlespire.import_unused", icon='IMPORT')

        layout.separator()
        box = layout.box()
        box.label(text="Import Models", icon='MESH_DATA')
        box.prop(props, "model_name", text="", icon='VIEWZOOM')
        box.operator("battlespire.import_model_by_name",
                      text="Import", icon='IMPORT')

# ═══════════════════════════════════════════════════════════════════════════
#  FILE MENU
# ═══════════════════════════════════════════════════════════════════════════

def menu_func_import(self, context):
    self.layout.operator("battlespire.import_file",
                          text="Battlespire .3D (.3D)")
    self.layout.operator("battlespire.import_folder",
                          text="Battlespire .3D Folder")

# ═══════════════════════════════════════════════════════════════════════════
#  REGISTER
# ═══════════════════════════════════════════════════════════════════════════

classes = (
    BS_AddonPreferences,
    BS_SceneProperties,
    *op_classes,
    BS_PT_MainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bs_props = PointerProperty(type=BS_SceneProperties)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.app.handlers.load_post.append(_on_load_post)
    try:
        bpy.app.translations.register(__package__, translations_dict)
    except Exception:
        pass

def unregister():
    try:
        bpy.app.translations.unregister(__package__)
    except Exception:
        pass
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    del bpy.types.Scene.bs_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    RM.reset()
