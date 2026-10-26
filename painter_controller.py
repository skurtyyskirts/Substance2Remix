"""Thin wrapper over the Substance 3D Painter API used by the plugin.

Every function here touches Painter state and must run on the main thread.
"""
import json
import math
import os
import re

from .pbr_maps import PBR_MAPS, MAPS_BY_KEY, OPACITY

try:
    import substance_painter.textureset
    import substance_painter.resource
    import substance_painter.project
    import substance_painter.layerstack
    import substance_painter.ui
    import substance_painter.js
    PAINTER_AVAILABLE = True
except ImportError:
    PAINTER_AVAILABLE = False
    # Mocking for robust import outside Painter
    class MockPainterModule:
        def __getattr__(self, name): return None
    substance_painter = MockPainterModule()
    substance_painter.textureset = MockPainterModule()
    substance_painter.resource = MockPainterModule()
    substance_painter.project = MockPainterModule()
    substance_painter.layerstack = MockPainterModule()
    substance_painter.ui = MockPainterModule()
    substance_painter.js = MockPainterModule()

# Viewport shader that previews every Remix map (assets/shaders/rtx-remix-preview.glsl).
REMIX_SHADER_NAME = "rtx-remix-preview"
REMIX_SHADER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "shaders",
                                 f"{REMIX_SHADER_NAME}.glsl")
# User channels the preview shader can read the Remix thickness map from (User0..User3).
REMIX_SHADER_USER_SLOTS = 4

# Plugin PBR type -> (ChannelType members to try, ChannelFormat used when the channel is created).
# Painter 12 names channels after OpenPBR and keeps the older names as aliases.
CHANNEL_SPECS = {m.key: (m.channels, m.channel_format) for m in PBR_MAPS}
CHANNEL_SPECS[OPACITY] = (("Opacity",), "L8")

USER_CHANNEL_COUNT = 32

MIN_RESOLUTION = 128
MAX_RESOLUTION = 4096


def _pow2_floor(value):
    return 1 << max(0, int(math.floor(math.log2(max(1, value)))))


def pow2_ceil(value):
    """Smallest power of two >= ``value``, capped at Painter's maximum resolution."""
    return min(MAX_RESOLUTION, 1 << max(0, int(math.ceil(math.log2(max(1, value))))))


def aspect_matched_resolution(source_w, source_h, long_side):
    """Power-of-two (width, height) with ``long_side`` on the longer axis and
    the closest power-of-two aspect ratio to ``source_w:source_h``.

    Painter texture sets must be powers of two, so a 1:4 source maps exactly
    while e.g. 3:4 rounds to 1:1. Export restores the exact ratio afterwards.
    """
    long_side = min(MAX_RESOLUTION, max(MIN_RESOLUTION, _pow2_floor(long_side)))
    if source_w <= 0 or source_h <= 0:
        return long_side, long_side
    ratio = max(source_w, source_h) / float(min(source_w, source_h))
    steps = int(round(math.log2(ratio)))
    short_side = max(MIN_RESOLUTION, long_side >> steps)
    return (long_side, short_side) if source_w >= source_h else (short_side, long_side)


class PainterController:
    def __init__(self, logger):
        self.logger = logger

    def _log_info(self, msg):
        if hasattr(self.logger, 'info'): self.logger.info(msg)
        elif isinstance(self.logger, dict) and 'info' in self.logger: self.logger['info'](msg)

    def _log_warning(self, msg):
        if hasattr(self.logger, 'warning'): self.logger.warning(msg)
        elif isinstance(self.logger, dict) and 'warning' in self.logger: self.logger['warning'](msg)

    # --- Project ---

    def is_project_open(self):
        try:
            return bool(substance_painter.project.is_open())
        except Exception:
            return False

    def close_project(self):
        substance_painter.project.close()

    def needs_saving(self):
        try:
            return bool(substance_painter.project.needs_saving())
        except Exception:
            return False

    def project_file_path(self):
        try:
            return substance_painter.project.file_path()
        except Exception:
            return None

    # --- Texture sets / channels ---

    def channel_type(self, pbr_type, stack=None):
        """The ChannelType that holds ``pbr_type``, or None.

        Maps kept in a User channel are found by label, so they need ``stack``.
        """
        spec = CHANNEL_SPECS.get(pbr_type)
        if not spec:
            return None
        if self._user_label(pbr_type):
            return self._find_user_channel(stack, pbr_type) if stack is not None else None
        channel_types = substance_painter.textureset.ChannelType
        for name in spec[0]:
            ct = getattr(channel_types, name, None)
            if ct is not None:
                return ct
        return None

    def channel_format(self, pbr_type):
        spec = CHANNEL_SPECS.get(pbr_type)
        if not spec:
            return None
        return getattr(substance_painter.textureset.ChannelFormat, spec[1], None)

    @staticmethod
    def _user_label(pbr_type):
        m = MAPS_BY_KEY.get(pbr_type)
        return m.user_label if m else ""

    def _user_channel_types(self):
        channel_types = substance_painter.textureset.ChannelType
        return [ct for ct in (getattr(channel_types, f"User{i}", None) for i in range(USER_CHANNEL_COUNT)) if ct is not None]

    def _find_user_channel(self, stack, pbr_type):
        """The User channel labelled for ``pbr_type`` (case-insensitive), or None."""
        label = self._user_label(pbr_type).lower()
        for ct in self._user_channel_types():
            try:
                if stack.has_channel(ct) and (stack.get_channel(ct).label() or "").strip().lower() == label:
                    return ct
            except Exception:
                continue
        return None

    def _add_user_channel(self, stack, pbr_type):
        """Add a labelled User channel in the first free slot. Returns its ChannelType."""
        for ct in self._user_channel_types():
            if not stack.has_channel(ct):
                stack.add_channel(ct, self.channel_format(pbr_type), self._user_label(pbr_type))
                return ct
        raise RuntimeError("no free User channel")

    def active_stack(self):
        """The stack the user is looking at, falling back to the first texture set."""
        try:
            stack = substance_painter.textureset.get_active_stack()
            if stack is not None:
                return stack
        except Exception:
            pass
        texture_sets = substance_painter.textureset.all_texture_sets() or []
        return texture_sets[0].get_stack() if texture_sets else None

    def stack_texture_set(self, stack):
        try:
            return stack.material()
        except Exception:
            return None

    def present_pbr_types(self, stack):
        """PBR types whose channel exists in ``stack``."""
        present = set()
        for pbr in CHANNEL_SPECS:
            ct = self.channel_type(pbr, stack)
            try:
                if ct is not None and stack.has_channel(ct):
                    present.add(pbr)
            except Exception:
                continue
        return present

    def document_map_names(self, stack, pbr_types):
        """Export ``documentMap`` names for maps without a fixed name.

        Painter names a document map after its channel type in lower case
        (e.g. ``user0``), which is what Painter's own export tests use.
        """
        names = {}
        for pbr in pbr_types:
            m = MAPS_BY_KEY.get(pbr)
            if m is None or m.doc_map or pbr == "normal":
                continue
            ct = self.channel_type(pbr, stack)
            if ct is None:
                continue
            try:
                names[pbr] = stack.get_channel(ct).type().name.lower()
            except Exception:
                names[pbr] = str(getattr(ct, "name", "")).lower()
        return {k: v for k, v in names.items() if v}

    def ensure_channel(self, stack, pbr_type):
        """Add the channel for ``pbr_type`` if the stack lacks it. Returns True when present."""
        try:
            if self._user_label(pbr_type):
                if self._find_user_channel(stack, pbr_type) is None:
                    self._add_user_channel(stack, pbr_type)
                    self._log_info(f"Added a '{self._user_label(pbr_type)}' User channel to the texture set.")
                return True
            ct = self.channel_type(pbr_type)
            if ct is None:
                return False
            if stack.has_channel(ct):
                return True
            stack.add_channel(ct, self.channel_format(pbr_type))
            self._log_info(f"Added missing '{pbr_type}' channel to the texture set.")
            return True
        except Exception as e:
            self._log_warning(f"Could not add the '{pbr_type}' channel: {e}")
            return False

    def set_resolution(self, texture_set, width, height):
        try:
            current = texture_set.get_resolution()
            if current.width == width and current.height == height:
                return True
            texture_set.set_resolution(substance_painter.textureset.Resolution(width, height))
            self._log_info(f"Texture set resolution set to {width}x{height}.")
            return True
        except Exception as e:
            self._log_warning(f"Could not set texture set resolution to {width}x{height}: {e}")
            return False

    # --- Viewport shader ---

    def shader_instances(self):
        """The project's shader instances: [{"id", "label", "shader", "url"}, ...]."""
        return list(substance_painter.js.evaluate("alg.shaders.instances()") or [])

    def uses_remix_shader(self):
        instances = self.shader_instances()
        return bool(instances) and all(i.get("shader") == REMIX_SHADER_NAME for i in instances)

    def thickness_user_slot(self, stack):
        """Index of the User channel holding the Remix thickness map, or -1."""
        ct = self._find_user_channel(stack, "thickness") if stack is not None else None
        m = re.search(r"(\d+)$", str(getattr(ct, "name", ct) or ""))
        return int(m.group(1)) if m else -1

    def use_remix_shader(self, stack):
        """Switch the project's shader instances to the RTX Remix preview shader
        and point it at the thickness User channel. Returns how many instances
        were switched (0 when they already used it).

        The shader file is imported into the project, so the .spp keeps working
        without the plugin.
        """
        instances = self.shader_instances()
        switched = 0
        url = None
        for inst in instances:
            if inst.get("shader") == REMIX_SHADER_NAME:
                continue
            if url is None:
                resource = substance_painter.resource.import_project_resource(
                    REMIX_SHADER_PATH, substance_painter.resource.Usage.SHADER)
                url = resource.identifier().url()
            substance_painter.js.evaluate(
                f"alg.shaders.updateShaderInstance({int(inst['id'])}, {json.dumps(url)})")
            switched += 1
        slot = self.thickness_user_slot(stack)
        if slot >= REMIX_SHADER_USER_SLOTS:
            self._log_warning(f"The Remix Thickness map is in User{slot}; the preview shader only reads "
                              f"User0-User{REMIX_SHADER_USER_SLOTS - 1}, so it isn't previewed.")
            slot = -1
        params = json.dumps({"remixThicknessChannel": slot})
        for inst in instances:
            substance_painter.js.evaluate(f"alg.shaders.setParameters({int(inst['id'])}, {params})")
        return switched

    # --- Layers ---

    def import_texture_resource(self, path):
        resource = substance_painter.resource.import_project_resource(path, substance_painter.resource.Usage.TEXTURE)
        return resource.identifier()

    def create_fill_layer(self, stack, sources, layer_name):
        """Insert one fill layer on top of ``stack`` with a texture per channel.

        ``sources`` maps PBR type -> image path. Only channels that received a
        texture stay active, so the layer never covers other channels with
        defaults. The whole insert is one undo step. Returns
        (assigned_pbr_types, errors).
        """
        errors = []
        resolved = {}
        for pbr, path in sources.items():
            if not self.ensure_channel(stack, pbr):
                errors.append(f"{pbr}: channel unavailable")
                continue
            ct = self.channel_type(pbr, stack)
            if ct is None:
                errors.append(f"{pbr}: channel unavailable")
                continue
            try:
                resolved[pbr] = (ct, self.import_texture_resource(path))
            except Exception as e:
                errors.append(f"{pbr}: import failed ({e})")
        if not resolved:
            return [], errors

        layerstack = substance_painter.layerstack
        with layerstack.ScopedModification(layer_name):
            fill = layerstack.insert_fill(layerstack.InsertPosition.from_textureset_stack(stack))
            fill.set_name(layer_name)
            fill.active_channels = {ct for ct, _ in resolved.values()}
            assigned = []
            for pbr, (ct, rid) in resolved.items():
                try:
                    fill.set_source(ct, rid)
                    assigned.append(pbr)
                except Exception as e:
                    errors.append(f"{pbr}: {e}")
            if not assigned:
                layerstack.delete_node(fill)
            elif len(assigned) < len(resolved):
                # A failed channel would otherwise stay active with its default value.
                fill.active_channels = {resolved[pbr][0] for pbr in assigned}
        return assigned, errors
