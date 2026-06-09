bl_info = {
    "name": "FP Layer Exporter",
    "author": "Vi",
    "version": (1, 5, 1),
    "blender": (4, 4, 6),
    "location": "View3D > Sidebar > FP Export",
    "description": "Exports layered first-person sprite sequences from panel-assigned object categories and dynamically splits weapon top/bottom using a depth-tested weapon visibility pass and Blender compositor nodes",
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
        default=2,
        min=1,
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

    export_weapon_top: bpy.props.BoolProperty(
        name="Export Weapon Top",
        default=True,
        description="Generate WeaponTop from the depth-tested visible weapon pass"
    )

    transparent_background: bpy.props.BoolProperty(
        name="Transparent Background",
        default=True
    )

    keep_temp_sources: bpy.props.BoolProperty(
        name="Keep Source Renders",
        description="Also save WeaponFull, WeaponVisible, and Body source renders for debugging",
        default=False
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
    saved = {}

    for obj in objects:
        data = getattr(obj, "data", None)
        materials = getattr(data, "materials", None)
        if materials is None:
            continue

        saved[obj.name] = [slot for slot in materials]

    return saved


def assign_holdout_material(objects, holdout_material):
    for obj in objects:
        data = getattr(obj, "data", None)
        materials = getattr(data, "materials", None)
        if materials is None:
            continue

        if len(materials) == 0:
            materials.append(holdout_material)
        else:
            for index in range(len(materials)):
                materials[index] = holdout_material


def restore_object_material_slots(saved_materials):
    for obj_name, materials in saved_materials.items():
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            continue

        data = getattr(obj, "data", None)
        obj_materials = getattr(data, "materials", None)
        if obj_materials is None:
            continue

        obj_materials.clear()
        for material in materials:
            obj_materials.append(material)


def render_weapon_visible_depth_pass(scene, weapon_objects, body_objects, filepath):
    """
    Render weapon pixels that survive real 3D depth against the body.

    Weapon objects render normally. Body objects render with a Holdout shader,
    meaning they write an alpha hole/depth occlusion without contributing body
    color. If the weapon is in front of the body, it remains visible. If it is
    behind the body, the body cuts it out.
    """
    visible_objects = set(weapon_objects) | set(body_objects)
    holdout_material = None
    saved_body_materials = save_object_material_slots(body_objects)

    try:
        holdout_material = make_temp_holdout_material()
        assign_holdout_material(body_objects, holdout_material)
        set_visible_render_category(scene, visible_objects)
        render_current_scene_to_file(scene, filepath)
    finally:
        restore_object_material_slots(saved_body_materials)
        if holdout_material and holdout_material.name in bpy.data.materials:
            bpy.data.materials.remove(holdout_material)


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


def split_weapon_with_depth_visible_compositor(
    source_scene,
    weapon_full_path,
    weapon_visible_path,
    weapon_bottom_path,
    weapon_top_path
):
    if not os.path.exists(weapon_full_path):
        raise FileNotFoundError(f"Missing WeaponFull render: {weapon_full_path}")

    if not os.path.exists(weapon_visible_path):
        raise FileNotFoundError(f"Missing WeaponVisible render: {weapon_visible_path}")

    slot_prefixes = []
    if weapon_bottom_path:
        slot_prefixes.append("WeaponBottom_")
    if weapon_top_path:
        slot_prefixes.append("WeaponTop_")

    if not slot_prefixes:
        return

    temp_scene = None
    temp_camera = None
    temp_camera_data = None
    weapon_full_image = None
    weapon_visible_image = None

    with tempfile.TemporaryDirectory(prefix="fp_layer_compositor_") as compositor_dir:
        try:
            temp_scene = bpy.data.scenes.new("FP_Layer_Compositor_Temp")
            temp_scene.render.engine = source_scene.render.engine
            temp_scene.render.resolution_x = source_scene.render.resolution_x
            temp_scene.render.resolution_y = source_scene.render.resolution_y
            temp_scene.render.resolution_percentage = source_scene.render.resolution_percentage
            temp_scene.render.film_transparent = True
            temp_scene.render.image_settings.file_format = "PNG"
            temp_scene.render.image_settings.color_mode = "RGBA"
            temp_scene.render.use_file_extension = True
            temp_scene.render.use_compositing = True

            temp_camera_data = bpy.data.cameras.new("FP_Layer_Compositor_Temp_Camera")
            temp_camera = bpy.data.objects.new("FP_Layer_Compositor_Temp_Camera", temp_camera_data)
            temp_scene.collection.objects.link(temp_camera)
            temp_scene.camera = temp_camera

            temp_scene.use_nodes = True
            tree = temp_scene.node_tree
            nodes = tree.nodes
            links = tree.links
            nodes.clear()

            weapon_full_image = bpy.data.images.load(weapon_full_path, check_existing=False)
            weapon_visible_image = bpy.data.images.load(weapon_visible_path, check_existing=False)

            weapon_full_node = nodes.new("CompositorNodeImage")
            weapon_full_node.image = weapon_full_image

            weapon_visible_node = nodes.new("CompositorNodeImage")
            weapon_visible_node.image = weapon_visible_image

            full_color = safe_node_output(weapon_full_node, "Image", 0)
            full_alpha = safe_node_output(weapon_full_node, "Alpha", 1)
            visible_color = safe_node_output(weapon_visible_node, "Image", 0)
            visible_alpha = safe_node_output(weapon_visible_node, "Alpha", 1)

            file_node = add_file_output_node(nodes, compositor_dir, slot_prefixes)
            output_index = 0

            if weapon_bottom_path:
                bottom_alpha = nodes.new("CompositorNodeMath")
                bottom_alpha.operation = "SUBTRACT"
                bottom_alpha.use_clamp = True
                links.new(full_alpha, bottom_alpha.inputs[0])
                links.new(visible_alpha, bottom_alpha.inputs[1])

                bottom_set_alpha = nodes.new("CompositorNodeSetAlpha")
                links.new(full_color, safe_node_input(bottom_set_alpha, "Image", 0))
                links.new(bottom_alpha.outputs[0], safe_node_input(bottom_set_alpha, "Alpha", 1))
                links.new(safe_node_output(bottom_set_alpha, "Image", 0), file_node.inputs[output_index])
                output_index += 1

            if weapon_top_path:
                top_set_alpha = nodes.new("CompositorNodeSetAlpha")
                links.new(visible_color, safe_node_input(top_set_alpha, "Image", 0))
                links.new(visible_alpha, safe_node_input(top_set_alpha, "Alpha", 1))
                links.new(safe_node_output(top_set_alpha, "Image", 0), file_node.inputs[output_index])

            bpy.ops.render.render(write_still=False, scene=temp_scene.name)

            move_compositor_output(compositor_dir, "WeaponBottom_", weapon_bottom_path)
            move_compositor_output(compositor_dir, "WeaponTop_", weapon_top_path)

        finally:
            if weapon_full_image:
                bpy.data.images.remove(weapon_full_image)
            if weapon_visible_image:
                bpy.data.images.remove(weapon_visible_image)
            if temp_scene:
                bpy.data.scenes.remove(temp_scene)
            if temp_camera:
                bpy.data.objects.remove(temp_camera)
            if temp_camera_data:
                bpy.data.cameras.remove(temp_camera_data)


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

        if (needs_weapon_split or settings.export_body) and not category_objects["BODY"]:
            self.report({"ERROR"}, "Body object list is empty. Body is required as the visible layer and/or mask.")
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
                        body_filename = f"{animation_name}_{hand_name}_{frame_number}.png"
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
                        armor_filename = f"{animation_name}_{armor_name}_{frame_number}.png"
                        armor_final_path = layer_output_file(
                            base_output_path,
                            "Armor",
                            armor_name,
                            settings.use_name_subfolders,
                            armor_filename
                        )

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
                                f"{animation_name}_{weapon_name}_Bottom_{frame_number}.png"
                            )

                        if settings.export_weapon_top:
                            weapon_top_path = layer_output_file(
                                base_output_path,
                                "WeaponTop",
                                weapon_name,
                                settings.use_name_subfolders,
                                f"{animation_name}_{weapon_name}_Top_{frame_number}.png"
                            )

                        try:
                            split_weapon_with_depth_visible_compositor(
                                scene,
                                weapon_source_path,
                                weapon_visible_path,
                                weapon_bottom_path,
                                weapon_top_path
                            )
                        except Exception as err:
                            self.report({"ERROR"}, f"Weapon split failed: {err}")
                            return {"CANCELLED"}

                        total_generated += int(bool(weapon_bottom_path)) + int(bool(weapon_top_path))

                        if settings.keep_temp_sources:
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
                                f"{animation_name}_{weapon_name}_WeaponFull_{frame_number}.png"
                            ))
                            shutil.copyfile(weapon_visible_path, os.path.join(
                                source_visible_path,
                                f"{animation_name}_{weapon_name}_WeaponVisible_{frame_number}.png"
                            ))
                            shutil.copyfile(body_source_path, os.path.join(
                                source_body_path,
                                f"{animation_name}_{hand_name}_Body_{frame_number}.png"
                            ))

        finally:
            scene.frame_set(original_frame)
            scene.render.filepath = original_filepath
            scene.render.film_transparent = original_film_transparent
            scene.render.image_settings.file_format = original_file_format
            scene.render.image_settings.color_mode = original_color_mode
            scene.render.use_overwrite = original_use_overwrite
            scene.render.use_file_extension = original_use_file_extension
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
        box.prop(settings, "export_weapon_top")
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
