bl_info = {
    "name": "Battlespire 3D Importer",
    "author": "Maxandkon",
    "version": (1, 0, 0),
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
#  TRANSLATION
# ═══════════════════════════════════════════════════════════════════════════

translations_dict = {
    "uk_UA": {
        ("*", "Battlespire 3D Importer"): "Battlespire 3D Імпортер",
        ("*", "GAMEDATA Folder"): "Тека GAMEDATA",
        ("*", "Battlespire"): "Battlespire",
        ("*", "Import Level"): "Імпорт локації",
        ("*", "Import"): "Імпортувати",
        ("*", "Import Unused Assets"): "Імпорт невикористаних об'єктів",
        ("*", "Model Name"): "Назва моделі",
        ("*", "Import Model"): "Імпорт моделі",
        ("*", "Import .3D File"): "Імпорт .3D файлу",
        ("*", "Import .3D Folder"): "Імпорт теки .3D",
        ("*", "Others (unused assets)"): "Інші (невикористані)",
        ("*", "Import Models"): "Імпорт моделей",
        ("*", "Data Files"): "Файли даних",
        ("*", "Load Game Data"): "Завантажити дані гри",
        ("*", "Level"): "Локація",
        ("*", "Select level to import"): "Оберіть локацію для імпорту",
        ("*", "Others (unused)"): "Інші (невикористані)",
        ("*", "Not loaded"): "Не завантажено",
        ("*", "May take some time"): "Займає деякий час",
        ("*", "Enter model name from 3D.BSA (e.g. TOILET)"): "Введіть назву моделі з 3D.BSA (напр. TOILET)",
    },
}

# ═══════════════════════════════════════════════════════════════════════════
#  PREFERENCES
# ═══════════════════════════════════════════════════════════════════════════

class BS_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    gamedata_path: StringProperty(
        name="GAMEDATA Folder",
        description="Path to the GAMEDATA folder inside your Battlespire installation",
        subtype='DIR_PATH',
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Set path to the GAMEDATA folder:")
        layout.label(text="...\\An Elder Scrolls Legend Battlespire\\GAMEDATA", icon='INFO')
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
            items.append((sn, stem, f"Import level {stem}"))
    if not items:
        items.append(('NONE', '(not loaded)', ''))
    return items


class BS_SceneProperties(PropertyGroup):
    level_enum: EnumProperty(
        name="Level",
        description="Select level to import",
        items=_get_level_items,
    )
    model_name: StringProperty(
        name="Model Name",
        description="Enter model name from 3D.BSA (e.g. TOILET)",
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

        # Path status
        box = layout.box()
        box.label(text="Data Files", icon='FILE_FOLDER')
        if gd and os.path.isdir(gd):
            box.label(text=os.path.basename(gd.rstrip('/\\')), icon='CHECKMARK')
        else:
            box.label(text="GAMEDATA path not set!", icon='ERROR')
            box.operator("preferences.addon_show",
                         text="Open Preferences", icon='PREFERENCES').module = __package__
            return

        # Load button or loaded status
        if not RM.is_loaded:
            layout.separator()
            box = layout.box()
            box.label(text="Loading archives may take some time", icon='TIME')
            box.operator("battlespire.load_data", text="Load Game Data", icon='IMPORT')
            return

        props = context.scene.bs_props

        layout.separator()

        # Level import
        box = layout.box()
        box.label(text="Import Level", icon='WORLD_DATA')
        box.prop(props, "level_enum", text="")
        box.operator("battlespire.import_level", text="Import", icon='IMPORT')

        layout.separator()

        # Unused assets
        box = layout.box()
        box.label(text="Others (unused)", icon='OUTLINER_OB_MESH')
        box.operator("battlespire.import_unused", text="Import Unused Assets", icon='IMPORT')

        layout.separator()

        # Model by name
        box = layout.box()
        box.label(text="Import Models", icon='MESH_DATA')
        box.prop(props, "model_name", text="", icon='VIEWZOOM')
        box.operator("battlespire.import_model_by_name", text="Import Model", icon='IMPORT')

# ═══════════════════════════════════════════════════════════════════════════
#  FILE MENU
# ═══════════════════════════════════════════════════════════════════════════

def menu_func_import(self, context):
    self.layout.operator("battlespire.import_file", text="Battlespire .3D Model (.3D)")
    self.layout.operator("battlespire.import_folder", text="Battlespire .3D Folder")

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
    try:
        bpy.app.translations.register(__package__, translations_dict)
    except Exception:
        pass

def unregister():
    try:
        bpy.app.translations.unregister(__package__)
    except Exception:
        pass
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    del bpy.types.Scene.bs_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    RM.reset()
