"""Background Blender script: Smart UV Project a mesh for Substance2Remix.

Run as:
    blender --background --factory-startup --python blender_auto_unwrap.py -- IN OUT [options]

All mesh objects in the file are unwrapped together into one shared UV space,
which is what a bundled material group needs (the meshes share one texture).
Operator keywords are filtered against each operator's RNA properties so the
script keeps working across Blender versions that add or drop options.
"""
import bpy
import sys
import argparse
import math
import os
import traceback


def log_message(level, message):
    """Prints a message with a prefix for easy identification in logs."""
    print(f"BlenderScript: {level.upper()}: {message}", flush=True)


def _supported_kwargs(operator, kwargs):
    """Drop keywords the operator doesn't know (they raise TypeError)."""
    try:
        known = {p.identifier for p in operator.get_rna_type().properties}
    except Exception:
        return kwargs
    dropped = sorted(k for k in kwargs if k not in known)
    if dropped:
        log_message("info", f"Skipping unsupported {operator.idname_py()} options: {', '.join(dropped)}")
    return {k: v for k, v in kwargs.items() if k in known}


def _call(operator, **kwargs):
    return operator(**_supported_kwargs(operator, kwargs))


def _import_mesh(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".usd", ".usda", ".usdc"):
        _call(bpy.ops.wm.usd_import, filepath=path, import_materials=False)
    elif ext == ".fbx":
        _call(bpy.ops.import_scene.fbx, filepath=path)
    elif ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            _call(bpy.ops.wm.obj_import, filepath=path)
        else:
            _call(bpy.ops.import_scene.obj, filepath=path)
    elif ext in (".gltf", ".glb"):
        _call(bpy.ops.import_scene.gltf, filepath=path)
    else:
        raise ValueError(f"Unsupported input format: {ext}")


def _export_mesh(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".usd", ".usda", ".usdc"):
        _call(bpy.ops.wm.usd_export, filepath=path, selected_objects_only=True,
              export_uvmaps=True, export_normals=True, export_materials=False)
    elif ext == ".fbx":
        _call(bpy.ops.export_scene.fbx, filepath=path, use_selection=True)
    elif ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_export"):
            _call(bpy.ops.wm.obj_export, filepath=path, export_selected_objects=True, export_materials=False)
        else:
            _call(bpy.ops.export_scene.obj, filepath=path, use_selection=True)
    elif ext in (".gltf", ".glb"):
        _call(bpy.ops.export_scene.gltf, filepath=path, use_selection=True)
    else:
        raise ValueError(f"Unsupported output format: {ext}")


def main():
    # Blender passes its own arguments first; ours follow "--".
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="Blender UV Unwrapper for Substance2Remix")
    parser.add_argument("input_mesh", help="Path to the input mesh file (USD, FBX, OBJ, glTF)")
    parser.add_argument("output_mesh", help="Path to save the unwrapped mesh file")
    parser.add_argument("--angle_limit", type=float, default=66.0, help="Smart UV Project: Angle Limit (degrees)")
    parser.add_argument("--island_margin", type=float, default=0.003, help="Smart UV Project: Island Margin")
    parser.add_argument("--area_weight", type=float, default=0.0, help="Smart UV Project: Area Weight")
    parser.add_argument("--stretch_to_bounds", type=str, default="False", help="Smart UV Project: Stretch to UV Bounds (True/False)")

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        log_message("error", f"Argument parsing failed. Argparse exit code: {e.code}. Arguments received: {argv}")
        sys.exit(e.code if e.code is not None and e.code != 0 else 1)

    scale_to_bounds = args.stretch_to_bounds.strip().lower() == "true"

    log_message("info", "Starting unwrap process.")
    log_message("info", f"Input: {os.path.basename(args.input_mesh)}")
    log_message("info", f"Output: {os.path.basename(args.output_mesh)}")
    log_message("info", f"Params: Angle={args.angle_limit}, Margin={args.island_margin}, AreaWeight={args.area_weight}, ScaleToBounds={scale_to_bounds}")

    if not os.path.exists(args.input_mesh):
        log_message("error", f"Input mesh file not found: {args.input_mesh}")
        sys.exit(1)

    try:
        # 1. Start from an empty scene (no default cube/camera/light).
        bpy.ops.wm.read_factory_settings(use_empty=True)

        # 2. Import the mesh
        log_message("info", "Importing mesh...")
        _import_mesh(args.input_mesh)

        meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
        if not meshes:
            log_message("error", "No mesh objects found in scene after import.")
            sys.exit(1)
        log_message("info", f"Imported {len(meshes)} mesh object(s).")

        # 3. Unwrap every mesh in one multi-object edit session.
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        log_message("info", "Performing Smart UV Project...")
        _call(
            bpy.ops.uv.smart_project,
            angle_limit=math.radians(args.angle_limit),
            island_margin=args.island_margin,
            area_weight=args.area_weight,
            correct_aspect=True,
            scale_to_bounds=scale_to_bounds,
        )
        bpy.ops.object.mode_set(mode='OBJECT')

        # 4. Export the unwrapped mesh
        log_message("info", f"Exporting unwrapped mesh to: {args.output_mesh}")
        os.makedirs(os.path.dirname(os.path.abspath(args.output_mesh)), exist_ok=True)
        _export_mesh(args.output_mesh)

        if not os.path.exists(args.output_mesh):
            log_message("error", "Export reported success but the output file is missing.")
            sys.exit(1)
        log_message("info", "Mesh exported successfully.")

    except SystemExit:
        raise
    except Exception as e:
        log_message("error", f"An unexpected error occurred: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
        log_message("info", "Blender script finished successfully.")
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 1
        if exit_code != 0:
            log_message("error", f"Blender script exited with error code: {exit_code}.")
    except Exception as e:
        log_message("critical", f"Unhandled CRITICAL ERROR: {str(e)}\n{traceback.format_exc()}")
        exit_code = 1
    finally:
        sys.exit(exit_code)
