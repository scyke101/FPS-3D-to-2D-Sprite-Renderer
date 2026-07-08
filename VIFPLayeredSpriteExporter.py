bl_info = {
    "name": "FP Layer Exporter",
    "author": "Vi",
    "version": (1, 7, 1),
    "blender": (4, 4, 6),
    "location": "View3D > Sidebar > FP Export",
    "description": "Exports layered first-person sprite sequences from panel-assigned object categories, dynamically splits weapon top/bottom, and optionally renders armor depth-clipped by the body using holdout masking with seam expansion, with optional matching normal-map exports",
    "category": "Render",
}

import bpy
import os
import tempfile
import glob
import shutil


RENDERABLE_OBJECT_TYPES = {
    "MESH",
    "CURVE",
    "SURFACE",
    "META",
    "FONT",
    "VOLUME",
    "HAIR",
    "POINTCLOUD",
    "GREASEPENCIL",
}


# -----------------------------------------------------------------------------
# Category item storage
# -----------------------------------------------------------------------------

class FPLayerObjectItem(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(
        name="Object",
        type=bpy.types.Object
    )


class FPLayerExportSettings(bpy.types.PropertyGroup):
    output_folder: bpy.props.StringProperty(
        name="Output Folder",
        subtype="DIR_PATH",
        default="//fp_layer_renders"
    )

    use_name_subfolders: bpy.props.BoolProperty(
        name="Use Name Subfolders",
        default=True,
        description="Put each exported layer inside a subfolder named after the hand, weapon, or armor name"
    )

    animation_name: bpy.props.StringProperty(
        name="Animation Name",
        default="1H_Block"
    )

    hand_name: bpy.props.StringProperty(
        name="Hand Name",
        default="Human"
    )

    weapon_name: bpy.props.StringProperty(
        name="Weapon Name",
        default="IronDagger"
    )

    armor_name: bpy.props.StringProperty(
        name="Armor Name",
        default="LeatherGlove"
    )

    weapon_objects: bpy.props.CollectionProperty(type=FPLayerObjectItem)
    body_objects: bpy.props.CollectionProperty(type=FPLayerObjectItem)
    armor_objects: bpy.props.CollectionProperty(type=FPLayerObjectItem)

    export_mode: bpy.props.EnumProperty(
        name="Export Mode",
        description="Choose which frames to export",
        items=(
            ("CURRENT", "Current Frame", "Export only the current frame"),
            ("TIMELINE", "Timeline Frames", "Export frames from Start Frame to End Frame using Frame Interval"),
            ("KEYED", "Keyed Category Frames", "Export frames keyed on objects assigned to Weapon, Body, and Armor"),
        ),
        default="CURRENT"
    )

    frame_interval: bpy.props.IntProperty(
        name="Frame Interval",
        default=5,
        min=1
    )

    start_frame: bpy.props.IntProperty(
        name="Start Frame",
        default=0,
        min=0
    )

    end_frame: bpy.props.IntProperty(
        name="End Frame",
        default=100,
        min=0
    )

    frame_padding: bpy.props.IntProperty(
        name="Frame Padding",
        default=0,
        min=0,
        max=6
    )

    export_weapon_bottom: bpy.props.BoolProperty(
        name="Export Weapon Bottom",
        default=True,
        description="Generate WeaponBottom from WeaponFull minus the depth-tested visible weapon pass"
    )

    export_body: bpy.props.BoolProperty(
        name="Export Body / Hands",
        default=True,
        description="Export the Body objects normally. Body alpha is also used as the hand/arm mask"
    )

    export_armor: bpy.props.BoolProperty(
        name="Export Armor",
        default=True
    )

    armor_body_holdout: bpy.props.BoolProperty(
        name="Body Holdout for Armor",
        default=True,
        description="Render armor with Body objects as holdouts so body-hidden interior armor pixels are removed by real 3D depth"
    )

    expand_armor: bpy.props.BoolProperty(
        name="Expand Armor",
        default=True,
        description="Restore a small overlap from ArmorFull to hide tiny seams where the body holdout over-cuts the armor"
    )

    armor_expand_pixels: bpy.props.IntProperty(
        name="Armor Expand Pixels",
        description="Restore this many pixels from ArmorFull around the depth-tested ArmorVisible edge to prevent seams",
        default=1,
        min=0,
        max=4
    )

    export_weapon_top: bpy.props.BoolProperty(
        name="Export Weapon Top",
        default=True,
        description="Generate WeaponTop from the depth-tested visible weapon pass"
    )

    transparent_background: bpy.props.BoolProperty(
        name="Transparent Background",
        default=True
    )

    render_normal_maps: bpy.props.BoolProperty(
        name="Render Normal Maps",
        description="Also render matching camera-space normal-map layers into Normal subfolders using a temporary material override",
        default=False
    )

    normal_maps_use_smooth_normals: bpy.props.BoolProperty(
        name="Smooth Normal Maps",
        description="Use smoothed/interpolated normals instead of blocky face normals",
        default=True
    )

    pack_specular_emissive_alpha: bpy.props.BoolProperty(
        name="Pack Roughness/Emissive Alpha",
        description="Encode shininess from roughness or emissive strength into the normal-map alpha channel",
        default=False
    )

    keep_temp_sources: bpy.props.BoolProperty(
        name="Keep Source Renders",
        description="Also save WeaponFull, WeaponVisible, and Body source renders for debugging",
        default=False
    )

    expand_weapon_top: bpy.props.BoolProperty(
        name="Expand Weapon Top",
        description="Restore a small overlap from WeaponFull to hide seams",
        default=True
    )

    weapon_top_expand_pixels: bpy.props.IntProperty(
        name="Weapon Top Expand Pixels",
        description="Dilate the generated WeaponTop alpha by this many pixels to prevent tiny seams where the body holdout over-cuts the weapon",
        default=1,
        min=0,
        max=4
    )


# -----------------------------------------------------------------------------
# Category panel operators
# -----------------------------------------------------------------------------

def get_category_collection(settings, category):
    if category == "WEAPON":
        return settings.weapon_objects
    if category == "BODY":
        return settings.body_objects
    if category == "ARMOR":
        return settings.armor_objects
    return None


def item_collection_contains(collection, obj):
    if not obj:
        return False
    for item in collection:
        if item.obj == obj:
            return True
    return False


def add_object_to_item_collection(collection, obj):
    if not obj or item_collection_contains(collection, obj):
        return False
    item = collection.add()
    item.obj = obj
    return True


class FP_OT_add_selected_to_category(bpy.types.Operator):
    bl_idname = "fp_layers.add_selected_to_category"
    bl_label = "Add Selected"
    bl_description = "Add selected renderable objects to this category"

    category: bpy.props.EnumProperty(
        items=(
            ("WEAPON", "Weapon", "Add to Weapon objects"),
            ("BODY", "Body", "Add to Body objects"),
            ("ARMOR", "Armor", "Add to Armor objects"),
        )
    )

    def execute(self, context):
        settings = context.scene.fp_layer_export_settings
        collection = get_category_collection(settings, self.category)

        if collection is None:
            self.report({"ERROR"}, "Unknown category.")
            return {"CANCELLED"}

        added = 0
        skipped = 0

        for obj in context.selected_objects:
            if obj.type not in RENDERABLE_OBJECT_TYPES:
                skipped += 1
                continue
            if add_object_to_item_collection(collection, obj):
                added += 1

        self.report({"INFO"}, f"Added {added} object(s). Skipped {skipped} non-renderable object(s).")
        return {"FINISHED"}


class FP_OT_add_active_to_category(bpy.types.Operator):
    bl_idname = "fp_layers.add_active_to_category"
    bl_label = "Add Active"
    bl_description = "Add the active object to this category"

    category: bpy.props.EnumProperty(
        items=(
            ("WEAPON", "Weapon", "Add to Weapon objects"),
            ("BODY", "Body", "Add to Body objects"),
            ("ARMOR", "Armor", "Add to Armor objects"),
        )
    )

    def execute(self, context):
        settings = context.scene.fp_layer_export_settings
        collection = get_category_collection(settings, self.category)
        obj = context.object

        if not obj:
            self.report({"WARNING"}, "No active object.")
            return {"CANCELLED"}

        if obj.type not in RENDERABLE_OBJECT_TYPES:
            self.report({"WARNING"}, f"Active object is not a renderable type: {obj.type}")
            return {"CANCELLED"}

        if add_object_to_item_collection(collection, obj):
            self.report({"INFO"}, f"Added {obj.name}.")
        else:
            self.report({"INFO"}, f"{obj.name} is already assigned.")

        return {"FINISHED"}


class FP_OT_remove_category_item(bpy.types.Operator):
    bl_idname = "fp_layers.remove_category_item"
    bl_label = "Remove"
    bl_description = "Remove this object slot from the category"

    category: bpy.props.EnumProperty(
        items=(
            ("WEAPON", "Weapon", "Remove from Weapon objects"),
            ("BODY", "Body", "Remove from Body objects"),
            ("ARMOR", "Armor", "Remove from Armor objects"),
        )
    )

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        settings = context.scene.fp_layer_export_settings
        collection = get_category_collection(settings, self.category)

        if collection is None or self.index < 0 or self.index >= len(collection):
            self.report({"WARNING"}, "Invalid object slot.")
            return {"CANCELLED"}

        collection.remove(self.index)
        return {"FINISHED"}


class FP_OT_clear_category(bpy.types.Operator):
    bl_idname = "fp_layers.clear_category"
    bl_label = "Clear"
    bl_description = "Clear all object slots from this category"

    category: bpy.props.EnumProperty(
        items=(
            ("WEAPON", "Weapon", "Clear Weapon objects"),
            ("BODY", "Body", "Clear Body objects"),
            ("ARMOR", "Armor", "Clear Armor objects"),
        )
    )

    def execute(self, context):
        settings = context.scene.fp_layer_export_settings
        collection = get_category_collection(settings, self.category)
        if collection is None:
            return {"CANCELLED"}

        collection.clear()
        return {"FINISHED"}



# -----------------------------------------------------------------------------
# Normal material helpers
# -----------------------------------------------------------------------------

def get_or_create_normal_output_material(use_smooth_normals=True):
    material_name = "M_NormalOutput"
    old_material = bpy.data.materials.get(material_name)

    if old_material is not None:
        bpy.data.materials.remove(old_material, do_unlink=True)

    material = bpy.data.materials.new(material_name)
    material.use_nodes = True

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    geometry_node = nodes.new(type="ShaderNodeNewGeometry")
    geometry_node.location = (-1100, 0)

    transform_node = nodes.new(type="ShaderNodeVectorTransform")
    transform_node.location = (-850, 0)
    transform_node.vector_type = 'NORMAL'
    transform_node.convert_from = 'WORLD'
    transform_node.convert_to = 'CAMERA'

    axis_fix_node = nodes.new(type="ShaderNodeVectorMath")
    axis_fix_node.operation = 'MULTIPLY'
    axis_fix_node.inputs[1].default_value = (1.0, -1.0, -1.0)
    axis_fix_node.location = (-600, 0)

    multiply_node = nodes.new(type="ShaderNodeVectorMath")
    multiply_node.operation = 'MULTIPLY'
    multiply_node.inputs[1].default_value = (0.5, 0.5, 0.5)
    multiply_node.location = (-350, 0)

    add_node = nodes.new(type="ShaderNodeVectorMath")
    add_node.operation = 'ADD'
    add_node.inputs[1].default_value = (0.5, 0.5, 0.5)
    add_node.location = (-100, 0)

    emission_node = nodes.new(type="ShaderNodeEmission")
    emission_node.location = (150, 0)
    emission_node.inputs["Strength"].default_value = 1.0

    output_node = nodes.new(type="ShaderNodeOutputMaterial")
    output_node.location = (400, 0)

    normal_output = "Normal" if use_smooth_normals else "True Normal"
    links.new(geometry_node.outputs[normal_output], transform_node.inputs["Vector"])
    links.new(transform_node.outputs["Vector"], axis_fix_node.inputs[0])
    links.new(axis_fix_node.outputs["Vector"], multiply_node.inputs[0])
    links.new(multiply_node.outputs["Vector"], add_node.inputs[0])
    links.new(add_node.outputs["Vector"], emission_node.inputs["Color"])
    links.new(emission_node.outputs["Emission"], output_node.inputs["Surface"])

    return material


def capture_material_slots_by_object(objects):
    """
    Capture the actual object material slots, including slot link mode.

    This is safer than only storing obj.data.materials because Blender material
    slots can be OBJECT-linked instead of DATA-linked, and multiple objects can
    share the same mesh datablock. Restoring through obj.material_slots preserves
    what the object actually had assigned before temporary render overrides.
    """
    captured = {}

    for obj in objects:
        slots = getattr(obj, "material_slots", None)
        if slots is None:
            continue

        captured[obj.name] = [(slot.material, slot.link) for slot in slots]

    return captured


def apply_material_override_to_objects(objects, material):
    for obj in objects:
        slots = getattr(obj, "material_slots", None)
        if slots is None:
            continue

        data = getattr(obj, "data", None)
        data_materials = getattr(data, "materials", None)
        if data_materials is None:
            continue

        if len(slots) == 0:
            data_materials.append(material)
        else:
            for slot in slots:
                slot.material = material


def restore_material_slots_by_object(captured_materials):
    for obj_name, saved_slots in captured_materials.items():
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            continue

        data = getattr(obj, "data", None)
        data_materials = getattr(data, "materials", None)
        if data_materials is None:
            continue

        # Match the original slot count first. Extra temporary slots are removed;
        # missing slots are recreated as empty slots before restoring assignments.
        while len(obj.material_slots) > len(saved_slots):
            data_materials.pop(index=len(obj.material_slots) - 1)

        while len(obj.material_slots) < len(saved_slots):
            data_materials.append(None)

        for index, (material, link) in enumerate(saved_slots):
            try:
                obj.material_slots[index].link = link
            except Exception:
                pass

            obj.material_slots[index].material = material


def make_normal_folder(folder):
    return os.path.join("Normals", folder)


def make_normal_filename(filename):
    name, ext = os.path.splitext(filename)
    return f"{name}_n{ext}"


def clamp01(value):
    return max(0.0, min(1.0, float(value)))


def socket_default_float(socket, fallback=0.0):
    if socket is None:
        return fallback

    value = getattr(socket, "default_value", fallback)

    if isinstance(value, (int, float)):
        return float(value)

    return fallback


def socket_default_color_strength(socket):
    if socket is None:
        return 0.0

    value = getattr(socket, "default_value", None)

    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    try:
        return max(float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return 0.0


def get_linked_socket_source(socket):
    if socket is None or not socket.is_linked:
        return None

    return socket.links[0].from_socket


def get_socket_value_or_linked_default(socket, fallback=0.0):
    source_socket = get_linked_socket_source(socket)

    if source_socket is not None:
        return socket_default_float(source_socket, fallback)

    return socket_default_float(socket, fallback)


def get_socket_color_strength_or_linked_default(socket):
    source_socket = get_linked_socket_source(socket)

    if source_socket is not None:
        return socket_default_color_strength(source_socket)

    return socket_default_color_strength(socket)


def find_principled_bsdf(material):
    if material is None or not material.use_nodes or material.node_tree is None:
        return None

    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            return node

    return None


def get_node_input(node, names):
    if node is None:
        return None

    for name in names:
        socket = node.inputs.get(name)

        if socket is not None:
            return socket

    return None


def get_material_roughness_emissive_data(material):
    if material is None:
        return 0.5, 0.0

    roughness_value = 0.5
    emissive_value = 0.0
    emissive_threshold = 0.01

    principled = find_principled_bsdf(material)

    if principled is not None:
        roughness_socket = get_node_input(principled, ["Roughness"])
        emission_strength_socket = get_node_input(principled, ["Emission Strength", "EmissionStrength"])
        emission_color_socket = get_node_input(principled, ["Emission Color", "Emission"])

        roughness_value = get_socket_value_or_linked_default(
            roughness_socket,
            roughness_value
        )

        emission_strength = get_socket_value_or_linked_default(
            emission_strength_socket,
            0.0
        )

        emission_color_strength = get_socket_color_strength_or_linked_default(
            emission_color_socket
        )

        raw_emissive = emission_strength * emission_color_strength

        if raw_emissive > emissive_threshold:
            emissive_value = raw_emissive

    return clamp01(roughness_value), clamp01(emissive_value)


def encode_roughness_emissive_alpha(roughness_value=0.5, emissive_value=0.0):
    roughness_value = clamp01(roughness_value)
    emissive_value = clamp01(emissive_value)

    if emissive_value > 0.0:
        return (128.0 + (emissive_value * 127.0)) / 255.0

    shininess_value = 1.0 - roughness_value
    return (shininess_value * 127.0) / 255.0


def get_or_create_scalar_output_material(material_name, scalar_value):
    safe_name = material_name if material_name else "None"
    output_name = f"M_FP_SpriteData_{safe_name}_{int(scalar_value * 255.0):03d}"
    old_material = bpy.data.materials.get(output_name)

    if old_material is not None:
        bpy.data.materials.remove(old_material, do_unlink=True)

    material = bpy.data.materials.new(output_name)
    material.use_nodes = True

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    emission_node = nodes.new(type="ShaderNodeEmission")
    emission_node.location = (0, 0)
    emission_node.inputs["Color"].default_value = (
        scalar_value,
        scalar_value,
        scalar_value,
        1.0
    )
    emission_node.inputs["Strength"].default_value = 1.0

    output_node = nodes.new(type="ShaderNodeOutputMaterial")
    output_node.location = (250, 0)
    links.new(emission_node.outputs["Emission"], output_node.inputs["Surface"])

    return material


def apply_sprite_data_materials_to_objects(objects):
    for obj in objects:
        data = getattr(obj, "data", None)
        materials = getattr(data, "materials", None)
        if materials is None:
            continue

        original_materials = [slot for slot in materials]

        if not original_materials:
            roughness_value, emissive_value = get_material_roughness_emissive_data(None)
            scalar_value = encode_roughness_emissive_alpha(roughness_value, emissive_value)
            materials.append(get_or_create_scalar_output_material("None", scalar_value))
            continue

        data_materials = []

        for original_material in original_materials:
            roughness_value, emissive_value = get_material_roughness_emissive_data(original_material)
            scalar_value = encode_roughness_emissive_alpha(roughness_value, emissive_value)
            material_name = original_material.name if original_material else "None"
            data_materials.append(get_or_create_scalar_output_material(material_name, scalar_value))

        materials.clear()
        for material in data_materials:
            materials.append(material)


def combine_normal_alpha_with_sprite_data(normal_path, data_path):
    if not normal_path or not data_path:
        return

    if not os.path.exists(normal_path) or not os.path.exists(data_path):
        return

    normal_image = bpy.data.images.load(normal_path, check_existing=False)
    data_image = bpy.data.images.load(data_path, check_existing=False)

    try:
        try:
            data_image.colorspace_settings.name = "Non-Color"
        except Exception:
            pass

        normal_pixels = list(normal_image.pixels)
        data_pixels = list(data_image.pixels)
        pixel_count = min(len(normal_pixels), len(data_pixels)) // 4

        for index in range(pixel_count):
            alpha_index = (index * 4) + 3
            red_index = index * 4

            if normal_pixels[alpha_index] > 0.0:
                normal_pixels[alpha_index] = data_pixels[red_index]

        normal_image.pixels.foreach_set(normal_pixels)
        normal_image.save_render(normal_path)

    finally:
        bpy.data.images.remove(normal_image)
        bpy.data.images.remove(data_image)


# -----------------------------------------------------------------------------
# Object / render helpers
# -----------------------------------------------------------------------------

def objects_from_item_collection(item_collection):
    objects = set()
    for item in item_collection:
        if item.obj and item.obj.name in bpy.data.objects:
            objects.add(item.obj)
    return objects


def get_category_objects(settings):
    return {
        "WEAPON": objects_from_item_collection(settings.weapon_objects),
        "BODY": objects_from_item_collection(settings.body_objects),
        "ARMOR": objects_from_item_collection(settings.armor_objects),
    }


def get_render_managed_objects(scene):
    managed = []
    for obj in scene.objects:
        if obj.type in RENDERABLE_OBJECT_TYPES:
            managed.append(obj)
    return managed


def set_visible_render_category(scene, category_objects):
    category_objects = set(category_objects)

    for obj in get_render_managed_objects(scene):
        obj.hide_render = obj not in category_objects


def save_original_hide_render(scene):
    return {obj.name: obj.hide_render for obj in scene.objects}


def restore_original_hide_render(original_hide_render):
    for obj_name, hide_render in original_hide_render.items():
        obj = bpy.data.objects.get(obj_name)
        if obj:
            obj.hide_render = hide_render


def make_temp_holdout_material():
    material = bpy.data.materials.new("FP_TEMP_DEPTH_HOLDOUT")
    material.use_nodes = True

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    holdout = nodes.new("ShaderNodeHoldout")
    links.new(holdout.outputs[0], output.inputs[0])

    return material


def save_object_material_slots(objects):
    return capture_material_slots_by_object(objects)


def assign_holdout_material(objects, holdout_material):
    apply_material_override_to_objects(objects, holdout_material)


def restore_object_material_slots(saved_materials):
    restore_material_slots_by_object(saved_materials)


def render_visible_depth_pass(scene, foreground_objects, holdout_objects, filepath):
    """
    Render foreground pixels that survive real 3D depth against holdout objects.

    Foreground objects render normally. Holdout objects render with a Holdout
    shader, meaning they write alpha/depth occlusion without contributing color.
    If the foreground is in front of the holdout geometry, it remains visible.
    If it is behind the holdout geometry, the holdout cuts it out.
    """
    visible_objects = set(foreground_objects) | set(holdout_objects)
    holdout_material = None
    saved_holdout_materials = save_object_material_slots(holdout_objects)

    try:
        holdout_material = make_temp_holdout_material()
        assign_holdout_material(holdout_objects, holdout_material)
        set_visible_render_category(scene, visible_objects)
        render_current_scene_to_file(scene, filepath)
    finally:
        restore_object_material_slots(saved_holdout_materials)
        if holdout_material and holdout_material.name in bpy.data.materials:
            bpy.data.materials.remove(holdout_material)


def render_weapon_visible_depth_pass(scene, weapon_objects, body_objects, filepath):
    """
    Render weapon pixels that survive real 3D depth against the body.

    Weapon objects render normally. Body objects render with a Holdout shader,
    meaning they write an alpha hole/depth occlusion without contributing body
    color. If the weapon is in front of the body, it remains visible. If it is
    behind the body, the body cuts it out.
    """
    render_visible_depth_pass(scene, weapon_objects, body_objects, filepath)


def render_armor_visible_depth_pass(scene, armor_objects, body_objects, filepath):
    """
    Render armor pixels that survive real 3D depth against the body.

    Armor objects render normally. Body objects render with a Holdout shader,
    so body-hidden interior armor faces are cut out before the PNG is saved.
    """
    render_visible_depth_pass(scene, armor_objects, body_objects, filepath)


# -----------------------------------------------------------------------------
# Frame helpers
# -----------------------------------------------------------------------------

def collect_keyed_frames_from_objects(objects):
    frames = set()

    for obj in objects:
        anim_data = obj.animation_data
        if anim_data and anim_data.action:
            for fcurve in anim_data.action.fcurves:
                for key in fcurve.keyframe_points:
                    frames.add(int(round(key.co.x)))

        data = getattr(obj, "data", None)
        shape_keys = getattr(data, "shape_keys", None)
        if shape_keys and shape_keys.animation_data and shape_keys.animation_data.action:
            for fcurve in shape_keys.animation_data.action.fcurves:
                for key in fcurve.keyframe_points:
                    frames.add(int(round(key.co.x)))

    return sorted(frames)


def get_export_frames(scene, settings, category_objects):
    if settings.export_mode == "TIMELINE":
        if settings.end_frame < settings.start_frame:
            raise ValueError("End Frame must be greater than or equal to Start Frame.")

        return list(range(settings.start_frame, settings.end_frame + 1, settings.frame_interval))

    if settings.export_mode == "KEYED":
        keyed_source_objects = set()
        keyed_source_objects.update(category_objects["WEAPON"])
        keyed_source_objects.update(category_objects["BODY"])
        keyed_source_objects.update(category_objects["ARMOR"])
        return collect_keyed_frames_from_objects(keyed_source_objects)

    return [scene.frame_current]


# -----------------------------------------------------------------------------
# File/path helpers
# -----------------------------------------------------------------------------

def make_output_path(base_output_path, folder, subfolder, use_name_subfolders):
    if use_name_subfolders:
        path = os.path.join(base_output_path, folder, subfolder)
    else:
        path = os.path.join(base_output_path, folder)

    os.makedirs(path, exist_ok=True)
    return path


def layer_output_file(base_output_path, folder, subfolder, use_name_subfolders, filename):
    layer_path = make_output_path(base_output_path, folder, subfolder, use_name_subfolders)
    return os.path.join(layer_path, filename)


# -----------------------------------------------------------------------------
# Render / image helpers
# -----------------------------------------------------------------------------

def render_current_scene_to_file(scene, filepath):
    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)


def newest_matching_file(pattern):
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def move_compositor_output(temp_dir, slot_prefix, final_path):
    if not final_path:
        return

    rendered_path = newest_matching_file(os.path.join(temp_dir, f"{slot_prefix}*.png"))

    if not rendered_path:
        raise RuntimeError(f"Compositor did not create output for {slot_prefix}.")

    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    if os.path.exists(final_path):
        os.remove(final_path)

    shutil.move(rendered_path, final_path)


def safe_node_input(node, preferred_name, fallback_index):
    if preferred_name in node.inputs:
        return node.inputs[preferred_name]
    return node.inputs[fallback_index]


def safe_node_output(node, preferred_name, fallback_index):
    if preferred_name in node.outputs:
        return node.outputs[preferred_name]
    return node.outputs[fallback_index]


def processed_mask_socket(nodes, links, body_alpha_socket, expand_pixels, soften_pixels):
    current_socket = body_alpha_socket

    if expand_pixels > 0:
        try:
            dilate = nodes.new("CompositorNodeDilateErode")
            try:
                dilate.mode = "DISTANCE"
            except Exception:
                pass
            try:
                dilate.distance = expand_pixels
            except Exception:
                pass
            links.new(current_socket, safe_node_input(dilate, "Mask", 0))
            current_socket = safe_node_output(dilate, "Mask", 0)
        except Exception:
            pass

    if soften_pixels > 0.0:
        try:
            blur = nodes.new("CompositorNodeBlur")
            blur.use_relative = False
            blur.size_x = int(round(soften_pixels))
            blur.size_y = int(round(soften_pixels))
            links.new(current_socket, safe_node_input(blur, "Image", 0))
            current_socket = safe_node_output(blur, "Image", 0)
        except Exception:
            pass

    return current_socket


def add_file_output_node(nodes, output_dir, slot_prefixes):
    file_node = nodes.new("CompositorNodeOutputFile")
    file_node.base_path = output_dir
    file_node.format.file_format = "PNG"
    file_node.format.color_mode = "RGBA"

    # Blender's file_slots.new(...) returns the new INPUT SOCKET in some versions,
    # not the slot settings object. The socket has no .path attribute, which caused:
    # 'NodeSocketColor' object has no attribute 'path'.
    # So: create the input, then set the path through file_node.file_slots by index.
    file_node.file_slots[0].path = slot_prefixes[0]

    for slot_prefix in slot_prefixes[1:]:
        file_node.file_slots.new(slot_prefix)
        file_node.file_slots[len(file_node.file_slots) - 1].path = slot_prefix

    return file_node


def save_pixels_to_png(width, height, pixels, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    image = bpy.data.images.new(
        name="FP_Layer_Pixel_Output",
        width=width,
        height=height,
        alpha=True,
        float_buffer=False
    )

    try:
        image.pixels.foreach_set(pixels)
        image.filepath_raw = filepath
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)


def copy_png_file(source_path, destination_path):
    if not destination_path:
        return

    os.makedirs(os.path.dirname(destination_path), exist_ok=True)

    if os.path.exists(destination_path):
        os.remove(destination_path)

    shutil.copyfile(source_path, destination_path)



def dilate_rgba_alpha_pixels(width, height, source_pixels, expand_pixels):
    """
    Expand non-transparent RGBA pixels outward by expand_pixels.

    New pixels copy color from the nearest source pixel. Existing pixels are
    preserved. This creates a tiny visual overlap for layered sprites and helps
    hide depth/alpha seams between WeaponTop and Body.
    """
    expand_pixels = int(max(0, expand_pixels))

    if expand_pixels <= 0:
        return list(source_pixels)

    output_pixels = list(source_pixels)
    pixel_count = width * height

    source_alpha = [0.0] * pixel_count
    for pixel_index in range(pixel_count):
        source_alpha[pixel_index] = source_pixels[(pixel_index * 4) + 3]

    for y in range(height):
        for x in range(width):
            pixel_index = (y * width) + x
            base = pixel_index * 4

            if source_alpha[pixel_index] > 0.0:
                continue

            best_source_index = -1
            best_distance_sq = None
            best_alpha = 0.0

            y_min = max(0, y - expand_pixels)
            y_max = min(height - 1, y + expand_pixels)
            x_min = max(0, x - expand_pixels)
            x_max = min(width - 1, x + expand_pixels)

            for sample_y in range(y_min, y_max + 1):
                for sample_x in range(x_min, x_max + 1):
                    dx = sample_x - x
                    dy = sample_y - y
                    distance_sq = (dx * dx) + (dy * dy)

                    if distance_sq == 0 or distance_sq > (expand_pixels * expand_pixels):
                        continue

                    sample_index = (sample_y * width) + sample_x
                    sample_alpha = source_alpha[sample_index]

                    if sample_alpha <= 0.0:
                        continue

                    if (
                        best_source_index < 0
                        or distance_sq < best_distance_sq
                        or (distance_sq == best_distance_sq and sample_alpha > best_alpha)
                    ):
                        best_source_index = sample_index
                        best_distance_sq = distance_sq
                        best_alpha = sample_alpha

            if best_source_index < 0:
                continue

            source_base = best_source_index * 4
            output_pixels[base + 0] = source_pixels[source_base + 0]
            output_pixels[base + 1] = source_pixels[source_base + 1]
            output_pixels[base + 2] = source_pixels[source_base + 2]
            output_pixels[base + 3] = best_alpha

    return output_pixels


def save_expanded_weapon_top(weapon_full_path, weapon_visible_path, destination_path, expand_pixels):
    """
    Save WeaponTop from WeaponVisible, but restore a small rim from WeaponFull
    wherever the depth-tested visible pass appears to have over-cut the weapon.

    This is intentionally different from simple dilation. Simple dilation only
    grows fully transparent pixels. Many Blender edge pixels are already barely
    non-transparent due to antialiasing, so a naive dilate can appear to do
    nothing. This version compares WeaponVisible against WeaponFull and can
    replace weak/over-cut visible alpha with the real full weapon pixel when it
    is close to a visible weapon pixel.
    """
    if not weapon_visible_path or not destination_path:
        return

    expand_pixels = int(max(0, expand_pixels))

    if expand_pixels <= 0 or not weapon_full_path:
        copy_png_file(weapon_visible_path, destination_path)
        return

    full_image = None
    visible_image = None

    try:
        full_image = bpy.data.images.load(weapon_full_path, check_existing=False)
        visible_image = bpy.data.images.load(weapon_visible_path, check_existing=False)

        full_width, full_height = full_image.size
        visible_width, visible_height = visible_image.size

        if full_width != visible_width or full_height != visible_height:
            copy_png_file(weapon_visible_path, destination_path)
            return

        width = full_width
        height = full_height
        pixel_count = width * height

        full_pixels = [0.0] * (pixel_count * 4)
        visible_pixels = [0.0] * (pixel_count * 4)
        output_pixels = [0.0] * (pixel_count * 4)

        full_image.pixels.foreach_get(full_pixels)
        visible_image.pixels.foreach_get(visible_pixels)

        output_pixels[:] = visible_pixels[:]

        visible_alpha = [0.0] * pixel_count
        full_alpha = [0.0] * pixel_count

        for pixel_index in range(pixel_count):
            base = pixel_index * 4
            visible_alpha[pixel_index] = visible_pixels[base + 3]
            full_alpha[pixel_index] = full_pixels[base + 3]

        radius_sq = expand_pixels * expand_pixels
        visible_threshold = 0.01
        improvement_threshold = 0.001

        for y in range(height):
            for x in range(width):
                pixel_index = (y * width) + x
                base = pixel_index * 4

                # Only fill pixels that are actually part of the full weapon and
                # where the visible/depth pass has less alpha than the full pass.
                if full_alpha[pixel_index] <= visible_alpha[pixel_index] + improvement_threshold:
                    continue

                near_visible_weapon = False
                y_min = max(0, y - expand_pixels)
                y_max = min(height - 1, y + expand_pixels)
                x_min = max(0, x - expand_pixels)
                x_max = min(width - 1, x + expand_pixels)

                for sample_y in range(y_min, y_max + 1):
                    if near_visible_weapon:
                        break
                    for sample_x in range(x_min, x_max + 1):
                        dx = sample_x - x
                        dy = sample_y - y
                        distance_sq = (dx * dx) + (dy * dy)

                        if distance_sq > radius_sq:
                            continue

                        sample_index = (sample_y * width) + sample_x
                        if visible_alpha[sample_index] > visible_threshold:
                            near_visible_weapon = True
                            break

                if not near_visible_weapon:
                    continue

                # Restore the actual full-weapon pixel, not a smeared neighbor.
                # This prevents growing color outside the real weapon silhouette.
                output_pixels[base + 0] = full_pixels[base + 0]
                output_pixels[base + 1] = full_pixels[base + 1]
                output_pixels[base + 2] = full_pixels[base + 2]
                output_pixels[base + 3] = full_pixels[base + 3]

        save_pixels_to_png(width, height, output_pixels, destination_path)

    finally:
        if full_image:
            bpy.data.images.remove(full_image)
        if visible_image:
            bpy.data.images.remove(visible_image)



def save_expanded_holdout_layer(full_path, visible_path, destination_path, expand_pixels):
    """
    Save a depth-tested foreground layer, optionally restoring a small rim from
    the full foreground render. Used by both WeaponTop and Armor.
    """
    save_expanded_weapon_top(
        full_path,
        visible_path,
        destination_path,
        expand_pixels
    )


def render_holdout_layer_with_optional_expansion(
    scene,
    foreground_objects,
    holdout_objects,
    full_path,
    visible_path,
    final_path,
    expand_pixels
):
    """
    Render a layer as Full + Visible-against-holdout, then save the visible
    result with an optional restored rim from the full render.

    This mirrors the WeaponTop seam-hiding flow for any foreground layer.
    """
    set_visible_render_category(scene, foreground_objects)
    render_current_scene_to_file(scene, full_path)

    render_visible_depth_pass(
        scene,
        foreground_objects,
        holdout_objects,
        visible_path
    )

    save_expanded_holdout_layer(
        full_path,
        visible_path,
        final_path,
        expand_pixels
    )

def split_weapon_with_depth_visible_compositor(
    source_scene,
    weapon_full_path,
    weapon_visible_path,
    weapon_bottom_path,
    weapon_top_path,
    weapon_top_expand_pixels=0
):
    """
    Split WeaponFull into WeaponBottom and WeaponTop using already-rendered PNGs.

    This intentionally does not use Blender compositor nodes. The previous version
    built a temporary compositor scene and failed in some Blender 4.4+ contexts with:
    'Scene' object has no attribute 'node_tree'. Pixel processing is simpler here:

        WeaponTop    = WeaponVisible
        WeaponBottom = WeaponFull color with alpha = FullAlpha - VisibleAlpha
    """
    if not os.path.exists(weapon_full_path):
        raise FileNotFoundError(f"Missing WeaponFull render: {weapon_full_path}")

    if not os.path.exists(weapon_visible_path):
        raise FileNotFoundError(f"Missing WeaponVisible render: {weapon_visible_path}")

    if not weapon_bottom_path and not weapon_top_path:
        return

    # WeaponTop is the depth-tested visible weapon render, optionally expanded
    # by a few pixels to create a tiny overlap under the Body layer. This helps
    # hide subpixel/depth-cut seams in layered first-person sprites.
    if weapon_top_path:
        save_expanded_weapon_top(
            weapon_full_path,
            weapon_visible_path,
            weapon_top_path,
            weapon_top_expand_pixels
        )

    # WeaponBottom is only needed when requested.
    if not weapon_bottom_path:
        return

    weapon_full_image = None
    weapon_visible_image = None

    try:
        weapon_full_image = bpy.data.images.load(weapon_full_path, check_existing=False)
        weapon_visible_image = bpy.data.images.load(weapon_visible_path, check_existing=False)

        full_width, full_height = weapon_full_image.size
        visible_width, visible_height = weapon_visible_image.size

        if full_width != visible_width or full_height != visible_height:
            raise RuntimeError(
                "WeaponFull and WeaponVisible renders have different dimensions."
            )

        full_pixels = [0.0] * (full_width * full_height * 4)
        visible_pixels = [0.0] * (visible_width * visible_height * 4)
        bottom_pixels = [0.0] * (full_width * full_height * 4)

        weapon_full_image.pixels.foreach_get(full_pixels)
        weapon_visible_image.pixels.foreach_get(visible_pixels)

        pixel_count = full_width * full_height

        for pixel_index in range(pixel_count):
            base = pixel_index * 4

            full_alpha = full_pixels[base + 3]
            visible_alpha = visible_pixels[base + 3]
            bottom_alpha = max(0.0, min(1.0, full_alpha - visible_alpha))

            bottom_pixels[base + 0] = full_pixels[base + 0]
            bottom_pixels[base + 1] = full_pixels[base + 1]
            bottom_pixels[base + 2] = full_pixels[base + 2]
            bottom_pixels[base + 3] = bottom_alpha

        save_pixels_to_png(full_width, full_height, bottom_pixels, weapon_bottom_path)

    finally:
        if weapon_full_image:
            bpy.data.images.remove(weapon_full_image)
        if weapon_visible_image:
            bpy.data.images.remove(weapon_visible_image)

# -----------------------------------------------------------------------------
# Main exporter
# -----------------------------------------------------------------------------

class FP_OT_export_layers(bpy.types.Operator):
    bl_idname = "fp_layers.export"
    bl_label = "Export FP Layers"
    bl_description = "Render first-person object categories as layered PNG sequences"

    def execute(self, context):
        scene = context.scene
        settings = scene.fp_layer_export_settings

        base_output_path = bpy.path.abspath(settings.output_folder)
        os.makedirs(base_output_path, exist_ok=True)

        category_objects = get_category_objects(settings)
        needs_weapon_split = settings.export_weapon_bottom or settings.export_weapon_top

        if needs_weapon_split and not category_objects["WEAPON"]:
            self.report({"ERROR"}, "Weapon object list is empty.")
            return {"CANCELLED"}

        armor_needs_body_holdout = settings.export_armor and settings.armor_body_holdout

        if (needs_weapon_split or settings.export_body or armor_needs_body_holdout) and not category_objects["BODY"]:
            self.report({"ERROR"}, "Body object list is empty. Body is required as the visible layer and/or holdout mask.")
            return {"CANCELLED"}

        if settings.export_armor and not category_objects["ARMOR"]:
            self.report({"WARNING"}, "Armor object list is empty. Armor layer will be skipped.")

        if not (settings.export_weapon_bottom or settings.export_body or settings.export_armor or settings.export_weapon_top):
            self.report({"WARNING"}, "No layers selected for export.")
            return {"CANCELLED"}

        try:
            frames = get_export_frames(scene, settings, category_objects)
        except ValueError as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}

        if not frames:
            self.report({"WARNING"}, "No frames found to export.")
            return {"CANCELLED"}

        original_frame = scene.frame_current
        original_filepath = scene.render.filepath
        original_film_transparent = scene.render.film_transparent
        original_file_format = scene.render.image_settings.file_format
        original_color_mode = scene.render.image_settings.color_mode
        original_use_overwrite = scene.render.use_overwrite
        original_use_file_extension = scene.render.use_file_extension
        original_hide_render = save_original_hide_render(scene)

        original_view_transform = scene.view_settings.view_transform
        original_look = scene.view_settings.look
        original_exposure = scene.view_settings.exposure
        original_gamma = scene.view_settings.gamma

        scene.render.film_transparent = settings.transparent_background
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.use_overwrite = True
        scene.render.use_file_extension = True

        animation_name = settings.animation_name.strip()
        hand_name = settings.hand_name.strip()
        weapon_name = settings.weapon_name.strip()
        armor_name = settings.armor_name.strip()

        total_renders = 0
        total_generated = 0

        normal_material = None
        normal_override_objects = set()
        captured_normal_materials = None

        if settings.render_normal_maps:
            normal_material = get_or_create_normal_output_material(
                settings.normal_maps_use_smooth_normals
            )
            normal_override_objects.update(category_objects["WEAPON"])
            normal_override_objects.update(category_objects["BODY"])
            normal_override_objects.update(category_objects["ARMOR"])
            captured_normal_materials = capture_material_slots_by_object(normal_override_objects)

        try:
            with tempfile.TemporaryDirectory(prefix="fp_layer_export_") as temp_dir:
                for export_index, frame in enumerate(frames):
                    scene.frame_set(frame)
                    frame_number = str(export_index).zfill(settings.frame_padding)

                    weapon_source_path = os.path.join(temp_dir, f"WeaponFull_{frame_number}.png")
                    weapon_visible_path = os.path.join(temp_dir, f"WeaponVisible_{frame_number}.png")
                    body_source_path = os.path.join(temp_dir, f"Body_{frame_number}.png")

                    if needs_weapon_split:
                        set_visible_render_category(scene, category_objects["WEAPON"])
                        render_current_scene_to_file(scene, weapon_source_path)
                        total_renders += 1

                        render_weapon_visible_depth_pass(
                            scene,
                            category_objects["WEAPON"],
                            category_objects["BODY"],
                            weapon_visible_path
                        )
                        total_renders += 1

                    if settings.export_body or needs_weapon_split:
                        body_filename = f"{hand_name}_{animation_name}_{frame_number}.png"
                        body_final_path = layer_output_file(
                            base_output_path,
                            "Body",
                            hand_name,
                            settings.use_name_subfolders,
                            body_filename
                        )

                        body_render_path = body_final_path if settings.export_body else body_source_path

                        set_visible_render_category(scene, category_objects["BODY"])
                        render_current_scene_to_file(scene, body_render_path)
                        total_renders += 1

                        if settings.export_body:
                            body_source_path = body_final_path

                    if settings.export_armor and category_objects["ARMOR"]:
                        armor_filename = f"{armor_name}_{animation_name}_{frame_number}.png"
                        armor_final_path = layer_output_file(
                            base_output_path,
                            "Armor",
                            armor_name,
                            settings.use_name_subfolders,
                            armor_filename
                        )

                        if settings.armor_body_holdout:
                            armor_full_path = os.path.join(temp_dir, f"ArmorFull_{frame_number}.png")
                            armor_visible_path = os.path.join(temp_dir, f"ArmorVisible_{frame_number}.png")
                            armor_expand_pixels = settings.armor_expand_pixels if settings.expand_armor else 0

                            render_holdout_layer_with_optional_expansion(
                                scene,
                                category_objects["ARMOR"],
                                category_objects["BODY"],
                                armor_full_path,
                                armor_visible_path,
                                armor_final_path,
                                armor_expand_pixels
                            )
                            total_renders += 2
                            total_generated += 1
                        else:
                            set_visible_render_category(scene, category_objects["ARMOR"])
                            render_current_scene_to_file(scene, armor_final_path)
                            total_renders += 1

                    if needs_weapon_split:
                        weapon_bottom_path = None
                        weapon_top_path = None

                        if settings.export_weapon_bottom:
                            weapon_bottom_path = layer_output_file(
                                base_output_path,
                                "WeaponBottom",
                                weapon_name,
                                settings.use_name_subfolders,
                                f"{weapon_name}_{animation_name}_Bottom_{frame_number}.png"
                            )

                        if settings.export_weapon_top:
                            weapon_top_path = layer_output_file(
                                base_output_path,
                                "WeaponTop",
                                weapon_name,
                                settings.use_name_subfolders,
                                f"{weapon_name}_{animation_name}_Top_{frame_number}.png"
                            )

                        try:
                            split_weapon_with_depth_visible_compositor(
                                scene,
                                weapon_source_path,
                                weapon_visible_path,
                                weapon_bottom_path,
                                weapon_top_path,
                                settings.weapon_top_expand_pixels if settings.expand_weapon_top else 0
                            )
                        except Exception as err:
                            self.report({"ERROR"}, f"Weapon split failed: {err}")
                            return {"CANCELLED"}

                        total_generated += int(bool(weapon_bottom_path)) + int(bool(weapon_top_path))

                    if settings.render_normal_maps:
                        normal_body_final_path = None
                        normal_armor_final_path = None
                        normal_weapon_bottom_path = None
                        normal_weapon_top_path = None

                        data_body_path = None
                        data_armor_path = None
                        data_weapon_bottom_path = None
                        data_weapon_top_path = None

                        apply_material_override_to_objects(normal_override_objects, normal_material)
                        context.view_layer.update()

                        scene.view_settings.view_transform = "Standard"
                        scene.view_settings.look = "None"
                        scene.view_settings.exposure = 0.0
                        scene.view_settings.gamma = 1.0

                        if needs_weapon_split:
                            normal_weapon_source_path = os.path.join(temp_dir, f"WeaponFull_N_{frame_number}.png")
                            normal_weapon_visible_path = os.path.join(temp_dir, f"WeaponVisible_N_{frame_number}.png")

                            set_visible_render_category(scene, category_objects["WEAPON"])
                            render_current_scene_to_file(scene, normal_weapon_source_path)
                            total_renders += 1

                            render_weapon_visible_depth_pass(
                                scene,
                                category_objects["WEAPON"],
                                category_objects["BODY"],
                                normal_weapon_visible_path
                            )
                            total_renders += 1

                        if settings.export_body:
                            normal_body_filename = make_normal_filename(f"{hand_name}_{animation_name}_{frame_number}.png")
                            normal_body_final_path = layer_output_file(
                                base_output_path,
                                make_normal_folder("Body"),
                                hand_name,
                                settings.use_name_subfolders,
                                normal_body_filename
                            )

                            set_visible_render_category(scene, category_objects["BODY"])
                            render_current_scene_to_file(scene, normal_body_final_path)
                            total_renders += 1

                        if settings.export_armor and category_objects["ARMOR"]:
                            normal_armor_filename = make_normal_filename(f"{armor_name}_{animation_name}_{frame_number}.png")
                            normal_armor_final_path = layer_output_file(
                                base_output_path,
                                make_normal_folder("Armor"),
                                armor_name,
                                settings.use_name_subfolders,
                                normal_armor_filename
                            )

                            if settings.armor_body_holdout:
                                normal_armor_full_path = os.path.join(temp_dir, f"ArmorFull_N_{frame_number}.png")
                                normal_armor_visible_path = os.path.join(temp_dir, f"ArmorVisible_N_{frame_number}.png")
                                armor_expand_pixels = settings.armor_expand_pixels if settings.expand_armor else 0

                                render_holdout_layer_with_optional_expansion(
                                    scene,
                                    category_objects["ARMOR"],
                                    category_objects["BODY"],
                                    normal_armor_full_path,
                                    normal_armor_visible_path,
                                    normal_armor_final_path,
                                    armor_expand_pixels
                                )
                                total_renders += 2
                                total_generated += 1
                            else:
                                set_visible_render_category(scene, category_objects["ARMOR"])
                                render_current_scene_to_file(scene, normal_armor_final_path)
                                total_renders += 1

                        if needs_weapon_split:
                            if settings.export_weapon_bottom:
                                normal_weapon_bottom_path = layer_output_file(
                                    base_output_path,
                                    make_normal_folder("WeaponBottom"),
                                    weapon_name,
                                    settings.use_name_subfolders,
                                    make_normal_filename(f"{weapon_name}_{animation_name}_Bottom_{frame_number}.png")
                                )

                            if settings.export_weapon_top:
                                normal_weapon_top_path = layer_output_file(
                                    base_output_path,
                                    make_normal_folder("WeaponTop"),
                                    weapon_name,
                                    settings.use_name_subfolders,
                                    make_normal_filename(f"{weapon_name}_{animation_name}_Top_{frame_number}.png")
                                )

                            try:
                                split_weapon_with_depth_visible_compositor(
                                    scene,
                                    normal_weapon_source_path,
                                    normal_weapon_visible_path,
                                    normal_weapon_bottom_path,
                                    normal_weapon_top_path,
                                    settings.weapon_top_expand_pixels
                                )
                            except Exception as err:
                                self.report({"ERROR"}, f"Normal weapon split failed: {err}")
                                return {"CANCELLED"}

                            total_generated += int(bool(normal_weapon_bottom_path)) + int(bool(normal_weapon_top_path))

                        restore_material_slots_by_object(captured_normal_materials)
                        context.view_layer.update()

                        if settings.pack_specular_emissive_alpha:
                            apply_sprite_data_materials_to_objects(normal_override_objects)
                            context.view_layer.update()

                            scene.view_settings.view_transform = "Raw"
                            scene.view_settings.look = "None"
                            scene.view_settings.exposure = 0.0
                            scene.view_settings.gamma = 1.0

                            if needs_weapon_split:
                                data_weapon_source_path = os.path.join(temp_dir, f"WeaponFull_Data_{frame_number}.png")
                                data_weapon_visible_path = os.path.join(temp_dir, f"WeaponVisible_Data_{frame_number}.png")

                                set_visible_render_category(scene, category_objects["WEAPON"])
                                render_current_scene_to_file(scene, data_weapon_source_path)
                                total_renders += 1

                                render_weapon_visible_depth_pass(
                                    scene,
                                    category_objects["WEAPON"],
                                    category_objects["BODY"],
                                    data_weapon_visible_path
                                )
                                total_renders += 1

                            if settings.export_body and normal_body_final_path:
                                data_body_path = os.path.join(temp_dir, f"Body_Data_{frame_number}.png")
                                set_visible_render_category(scene, category_objects["BODY"])
                                render_current_scene_to_file(scene, data_body_path)
                                total_renders += 1

                            if settings.export_armor and category_objects["ARMOR"] and normal_armor_final_path:
                                data_armor_path = os.path.join(temp_dir, f"Armor_Data_{frame_number}.png")
                                if settings.armor_body_holdout:
                                    data_armor_full_path = os.path.join(temp_dir, f"ArmorFull_Data_{frame_number}.png")
                                    data_armor_visible_path = os.path.join(temp_dir, f"ArmorVisible_Data_{frame_number}.png")
                                    armor_expand_pixels = settings.armor_expand_pixels if settings.expand_armor else 0

                                    render_holdout_layer_with_optional_expansion(
                                        scene,
                                        category_objects["ARMOR"],
                                        category_objects["BODY"],
                                        data_armor_full_path,
                                        data_armor_visible_path,
                                        data_armor_path,
                                        armor_expand_pixels
                                    )
                                    total_renders += 2
                                    total_generated += 1
                                else:
                                    set_visible_render_category(scene, category_objects["ARMOR"])
                                    render_current_scene_to_file(scene, data_armor_path)
                                    total_renders += 1

                            if needs_weapon_split:
                                if normal_weapon_bottom_path:
                                    data_weapon_bottom_path = os.path.join(temp_dir, f"WeaponBottom_Data_{frame_number}.png")

                                if normal_weapon_top_path:
                                    data_weapon_top_path = os.path.join(temp_dir, f"WeaponTop_Data_{frame_number}.png")

                                try:
                                    split_weapon_with_depth_visible_compositor(
                                        scene,
                                        data_weapon_source_path,
                                        data_weapon_visible_path,
                                        data_weapon_bottom_path,
                                        data_weapon_top_path,
                                        settings.weapon_top_expand_pixels
                                    )
                                except Exception as err:
                                    self.report({"ERROR"}, f"Sprite-data weapon split failed: {err}")
                                    return {"CANCELLED"}

                                total_generated += int(bool(data_weapon_bottom_path)) + int(bool(data_weapon_top_path))

                            combine_normal_alpha_with_sprite_data(normal_body_final_path, data_body_path)
                            combine_normal_alpha_with_sprite_data(normal_armor_final_path, data_armor_path)
                            combine_normal_alpha_with_sprite_data(normal_weapon_bottom_path, data_weapon_bottom_path)
                            combine_normal_alpha_with_sprite_data(normal_weapon_top_path, data_weapon_top_path)

                            restore_material_slots_by_object(captured_normal_materials)
                            context.view_layer.update()

                        scene.view_settings.view_transform = original_view_transform
                        scene.view_settings.look = original_look
                        scene.view_settings.exposure = original_exposure
                        scene.view_settings.gamma = original_gamma

                    if needs_weapon_split and settings.keep_temp_sources:
                        source_weapon_path = make_output_path(
                            base_output_path,
                            "Source_WeaponFull",
                            weapon_name,
                            settings.use_name_subfolders
                        )
                        source_visible_path = make_output_path(
                            base_output_path,
                            "Source_WeaponVisible",
                            weapon_name,
                            settings.use_name_subfolders
                        )
                        source_body_path = make_output_path(
                            base_output_path,
                            "Source_Body",
                            hand_name,
                            settings.use_name_subfolders
                        )

                        shutil.copyfile(weapon_source_path, os.path.join(
                            source_weapon_path,
                            f"{weapon_name}_{animation_name}_WeaponFull_{frame_number}.png"
                        ))
                        shutil.copyfile(weapon_visible_path, os.path.join(
                            source_visible_path,
                            f"{weapon_name}_{animation_name}_WeaponVisible_{frame_number}.png"
                        ))
                        shutil.copyfile(body_source_path, os.path.join(
                            source_body_path,
                            f"{hand_name}_{animation_name}_Body_{frame_number}.png"
                        ))

        finally:
            if captured_normal_materials is not None:
                restore_material_slots_by_object(captured_normal_materials)

            scene.frame_set(original_frame)
            scene.render.filepath = original_filepath
            scene.render.film_transparent = original_film_transparent
            scene.render.image_settings.file_format = original_file_format
            scene.render.image_settings.color_mode = original_color_mode
            scene.render.use_overwrite = original_use_overwrite
            scene.render.use_file_extension = original_use_file_extension

            scene.view_settings.view_transform = original_view_transform
            scene.view_settings.look = original_look
            scene.view_settings.exposure = original_exposure
            scene.view_settings.gamma = original_gamma

            restore_original_hide_render(original_hide_render)

        self.report(
            {"INFO"},
            f"Rendered {total_renders} source image(s). Generated {total_generated} weapon split image(s)."
        )

        return {"FINISHED"}


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

def draw_object_category_box(layout, settings, title, category, item_collection):
    box = layout.box()
    header = box.row(align=True)
    header.label(text=f"{title} ({len(item_collection)})")

    clear_op = header.operator("fp_layers.clear_category", text="Clear", icon="TRASH")
    clear_op.category = category

    if len(item_collection) == 0:
        box.label(text="No objects assigned.")
    else:
        for index, item in enumerate(item_collection):
            row = box.row(align=True)
            row.prop(item, "obj", text="")
            remove_op = row.operator("fp_layers.remove_category_item", text="", icon="X")
            remove_op.category = category
            remove_op.index = index

    add_row = box.row(align=True)
    active_op = add_row.operator("fp_layers.add_active_to_category", text="Add Active")
    active_op.category = category
    selected_op = add_row.operator("fp_layers.add_selected_to_category", text="Add Selected")
    selected_op.category = category


class FP_PT_layer_export_panel(bpy.types.Panel):
    bl_label = "FP Layer Exporter"
    bl_idname = "FP_PT_layer_export_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "FP Export"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fp_layer_export_settings

        version = ".".join(map(str, bl_info["version"]))

        box = layout.box()
        box.label(text=f"FP Layer Exporter v{version}")

        box.prop(settings, "output_folder")
        box.prop(settings, "use_name_subfolders")
        box.prop(settings, "transparent_background")
        box.prop(settings, "render_normal_maps")

        if settings.render_normal_maps:
            box.prop(settings, "normal_maps_use_smooth_normals")
            box.prop(settings, "pack_specular_emissive_alpha")

            if settings.pack_specular_emissive_alpha:
                data_box = box.box()
                data_box.label(text="Normal Alpha Packing")
                data_box.label(text="0-127: shininess from roughness")
                data_box.label(text="128-255: emissive strength")

        box.separator()

        box.prop(settings, "animation_name")
        box.prop(settings, "hand_name")
        box.prop(settings, "weapon_name")
        box.prop(settings, "armor_name")

        layout.separator()

        draw_object_category_box(layout, settings, "Weapon Objects", "WEAPON", settings.weapon_objects)
        draw_object_category_box(layout, settings, "Body Objects", "BODY", settings.body_objects)
        draw_object_category_box(layout, settings, "Armor Objects", "ARMOR", settings.armor_objects)

        layout.separator()

        box = layout.box()
        box.label(text="Layers to Export:")
        box.prop(settings, "export_weapon_bottom")
        box.prop(settings, "export_body")
        box.prop(settings, "export_armor")
        if settings.export_armor:
            box.prop(settings, "armor_body_holdout")
            if settings.armor_body_holdout:
                box.prop(settings, "expand_armor")
                if settings.expand_armor:
                    box.prop(settings, "armor_expand_pixels")
        box.prop(settings, "export_weapon_top")
        box.prop(settings, "expand_weapon_top")
        if settings.expand_weapon_top:
            box.prop(settings, "weapon_top_expand_pixels")
        box.prop(settings, "keep_temp_sources")

        box.separator()

        box.prop(settings, "export_mode")

        if settings.export_mode == "TIMELINE":
            sub = box.box()
            sub.prop(settings, "frame_interval")
            sub.prop(settings, "start_frame")
            sub.prop(settings, "end_frame")
            sub.prop(settings, "frame_padding")
        elif settings.export_mode == "KEYED":
            box.label(text="Scans keys on assigned category objects only.")
            box.prop(settings, "frame_padding")
        else:
            box.label(text="Exports current frame only.")
            box.prop(settings, "frame_padding")

        box.separator()

        box.operator(
            "fp_layers.export",
            icon="RENDER_STILL"
        )


classes = (
    FPLayerObjectItem,
    FPLayerExportSettings,
    FP_OT_add_selected_to_category,
    FP_OT_add_active_to_category,
    FP_OT_remove_category_item,
    FP_OT_clear_category,
    FP_OT_export_layers,
    FP_PT_layer_export_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.fp_layer_export_settings = bpy.props.PointerProperty(
        type=FPLayerExportSettings
    )


def unregister():
    del bpy.types.Scene.fp_layer_export_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
