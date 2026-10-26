"""Thin wrapper over the Substance 3D Painter API used by the plugin.

Every function here touches Painter state and must run on the main thread.
"""
import math

try:
    import substance_painter.textureset
    import substance_painter.resource
    import substance_painter.project
    import substance_painter.layerstack
    import substance_painter.ui
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

# Plugin PBR type -> (ChannelType member, ChannelFormat member used when the channel is created).
CHANNEL_SPECS = {
    "albedo": ("BaseColor", "sRGB8"),
    "normal": ("Normal", "RGB16F"),
    "height": ("Height", "L16F"),
    "roughness": ("Roughness", "L8"),
    "metallic": ("Metallic", "L8"),
    "emissive": ("Emissive", "sRGB8"),
    "opacity": ("Opacity", "L8"),
}

MIN_RESOLUTION = 128
MAX_RESOLUTION = 4096


def _pow2_floor(value):
    return 1 << max(0, int(math.floor(math.log2(max(1, value)))))


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

    def channel_type(self, pbr_type):
        spec = CHANNEL_SPECS.get(pbr_type)
        if not spec:
            return None
        return getattr(substance_painter.textureset.ChannelType, spec[0], None)

    def channel_format(self, pbr_type):
        spec = CHANNEL_SPECS.get(pbr_type)
        if not spec:
            return None
        return getattr(substance_painter.textureset.ChannelFormat, spec[1], None)

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
            ct = self.channel_type(pbr)
            try:
                if ct is not None and stack.has_channel(ct):
                    present.add(pbr)
            except Exception:
                continue
        return present

    def ensure_channel(self, stack, pbr_type):
        """Add the channel for ``pbr_type`` if the stack lacks it. Returns True when present."""
        ct = self.channel_type(pbr_type)
        if ct is None:
            return False
        try:
            if stack.has_channel(ct):
                return True
            fmt = self.channel_format(pbr_type)
            stack.add_channel(ct, fmt)
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

    # --- Layers ---

    def import_texture_resource(self, path):
        resource = substance_painter.resource.import_project_resource(path, substance_painter.resource.Usage.TEXTURE)
        return resource.identifier()

    def create_fill_layer(self, stack, sources, layer_name):
        """Insert one fill layer on top of ``stack`` with a texture per channel.

        ``sources`` maps PBR type -> image path. Only channels with a source are
        made active, so the layer never overwrites other channels with defaults.
        The whole insert is one undo step. Returns (assigned_pbr_types, errors).
        """
        errors = []
        resolved = {}
        for pbr, path in sources.items():
            if not self.ensure_channel(stack, pbr):
                errors.append(f"{pbr}: channel unavailable")
                continue
            try:
                resolved[pbr] = (self.channel_type(pbr), self.import_texture_resource(path))
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
        return assigned, errors
