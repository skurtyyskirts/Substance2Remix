import bpy
import sys
import argparse
import os
import traceback

def log_message(level, message):
    """Prints a message with a prefix for easy identification in logs."""
    print(f"BlenderScript: {level.upper()}: {message}")

def main():
    # Blender may pass arguments after "--".
    # We need to slice sys.argv to get only the arguments intended for this script.
    argv = sys.argv
    try:
        if "--" in argv:
            argv = argv[argv.index("--") + 1:]
    except ValueError:
        pass # If -- not present, assume args are directly available

    parser = argparse.ArgumentParser(description="Blender UV Unwrapper for Substance Painter Connector")
    parser.add_argument("input_mesh", help="Path to the input mesh file (USD, FBX, OBJ, etc.)")
    parser.add_argument("output_mesh", help="Path to save the unwrapped mesh file")
    parser.add_argument("--angle_limit", type=float, default=66.0, help="Smart UV Project: Angle Limit (degrees)")
    parser.add_argument("--island_margin", type=float, default=0.003, help="Smart UV Project: Island Margin")
    parser.add_argument("--area_weight", type=float, default=0.0, help="Smart UV Project: Area Weight")
    parser.add_argument("--stretch_to_bounds", type=str, default="False", help="Smart UV Project: Stretch to UV Bounds (True/False)")

    args = None
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        log_message("error", f"Argument parsing failed. Argparse exit code: {e.code}. Arguments received: {argv}")
        sys.exit(e.code if e.code is not None and e.code != 0 else 1)

    scale_to_bounds_bool = args.stretch_to_bounds.lower() == 'true'

    log_message("info", "Starting unwrap process.")
    log_message("info", f"Input: {os.path.basename(args.input_mesh)}")
    log_message("info", f"Output: {os.path.basename(args.output_mesh)}")
    log_message("info", f"Params: Angle={args.angle_limit}, Margin={args.island_margin}, AreaWeight={args.area_weight}, ScaleToBounds={scale_to_bounds_bool}")

    if not os.path.exists(args.input_mesh):
        log_message("error", f"Input mesh file not found: {args.input_mesh}")
        sys.exit(1)

    try:
        # 1. Clear existing scene
        if bpy.ops.object.select_all.poll(): bpy.ops.object.select_all(action='SELECT')
        if bpy.ops.object.delete.poll(): bpy.ops.object.delete(use_global=False)
        if bpy.ops.outliner.orphans_purge.poll(): bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

        # 2. Import the mesh
        log_message("info", f"Importing mesh...")
        file_ext = os.path.splitext(args.input_mesh)[1].lower()

        if file_ext in [".usd", ".usda", ".usdc"]:
            if hasattr(bpy.ops.wm, 'usd_import'): bpy.ops.wm.usd_import(filepath=args.input_mesh)
            else: log_message("error", "USD import not available."); sys.exit(1)
        elif file_ext == ".fbx":
            if hasattr(bpy.ops.import_scene, 'fbx'): bpy.ops.import_scene.fbx(filepath=args.input_mesh)
            else: log_message("error", "FBX import not available."); sys.exit(1)
        elif file_ext == ".obj":
            if hasattr(bpy.ops.import_scene, 'obj'): bpy.ops.import_scene.obj(filepath=args.input_mesh)
            elif hasattr(bpy.ops.wm, 'obj_import'): bpy.ops.wm.obj_import(filepath=args.input_mesh)
            else: log_message("error", "OBJ import not available."); sys.exit(1)
        else:
            log_message("error", f"Unsupported input format: {file_ext}"); sys.exit(1)
        log_message("info", "Mesh imported.")

        # 3. Process mesh objects
        if not bpy.context.selected_objects:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in bpy.context.scene.objects:
                if obj.type == 'MESH': obj.select_set(True)
            if not bpy.context.selected_objects:
                log_message("error", "No mesh objects found in scene after import."); sys.exit(1)

        unwrapped_count = 0
        for obj in bpy.context.selected_objects:
            if obj.type == 'MESH':
                log_message("info", f"Processing object: {obj.name}")
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                log_message("info", "Performing Smart UV Project...")
                bpy.ops.uv.smart_project(
                    angle_limit=args.angle_limit * (3.14159 / 180.0),
                    island_margin=args.island_margin,
                    area_weight=args.area_weight,
                    correct_aspect=True,
                    scale_to_bounds=scale_to_bounds_bool
                )
                if bpy.ops.object.shade_smooth.poll(): bpy.ops.object.shade_smooth()
                if bpy.ops.mesh.normals_make_consistent.poll(): bpy.ops.mesh.normals_make_consistent(inside=False)
                bpy.ops.object.mode_set(mode='OBJECT')
                unwrapped_count += 1
        
        if unwrapped_count == 0:
            log_message("error", "No mesh objects were unwrapped."); sys.exit(1)

        # 4. Export the unwrapped mesh
        log_message("info", f"Exporting unwrapped mesh to: {args.output_mesh}")
        out_file_ext = os.path.splitext(args.output_mesh)[1].lower()
        export_kwargs = {'filepath': args.output_mesh, 'use_selection': True} # Common base for OBJ/FBX
        
        if out_file_ext in [".usd", ".usda", ".usdc"]:
            export_kwargs = {'filepath': args.output_mesh, 'selected_objects_only': True, 'primvars_interpolation': 'Varying'}
            if hasattr(bpy.ops.wm, 'usd_export'): bpy.ops.wm.usd_export(**export_kwargs)
            else: log_message("error", "USD export not available"); sys.exit(1)
        elif out_file_ext == ".fbx":
            if hasattr(bpy.ops.export_scene, 'fbx'): bpy.ops.export_scene.fbx(**export_kwargs)
            else: log_message("error", "FBX export not available"); sys.exit(1)
        elif out_file_ext == ".obj":
            if hasattr(bpy.ops.export_scene, 'obj'): bpy.ops.export_scene.obj(**export_kwargs)
            elif hasattr(bpy.ops.wm, 'obj_export'): bpy.ops.wm.obj_export(**export_kwargs)
            else: log_message("error", "OBJ export not available"); sys.exit(1)
        else:
            log_message("error", f"Unsupported output format: {out_file_ext}"); sys.exit(1)

        log_message("info", f"Mesh exported successfully.")

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