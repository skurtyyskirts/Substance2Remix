import sys
try:
    import substance_painter.textureset
    import substance_painter.resource
    import substance_painter.project
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
    substance_painter.ui = MockPainterModule()

class PainterController:
    def __init__(self, logger):
        self.logger = logger
        self.PAINTER_CHANNEL_TO_REMIX_PBR_MAP = {
            "basecolor": "albedo", "base_color": "albedo", "albedo": "albedo", "diffuse": "albedo",
            "normal": "normal", "height": "height", "displacement": "height", "roughness": "roughness",
            "metallic": "metallic", "metalness": "metallic", "emissive": "emissive", "emission": "emissive",
            "opacity": "opacity",
        }
        self.REMIX_PBR_TO_PAINTER_CHANNEL_MAP = {
            "albedo": "baseColor", "normal": "normal", "height": "height", "roughness": "roughness",
            "metallic": "metallic", "emissive": "emissive", "opacity": "opacity",
        }
        self.PAINTER_STRING_TO_CHANNELTYPE_MAP = {}
        self._init_channel_type_map()

    def _log_info(self, msg):
        if hasattr(self.logger, 'info'): self.logger.info(msg)
        elif isinstance(self.logger, dict) and 'info' in self.logger: self.logger['info'](msg)

    def _log_error(self, msg):
        if hasattr(self.logger, 'error'): self.logger.error(msg)
        elif isinstance(self.logger, dict) and 'error' in self.logger: self.logger['error'](msg)

    def _init_channel_type_map(self):
        try:
            if hasattr(substance_painter.textureset, 'ChannelType'):
                CT = substance_painter.textureset.ChannelType
                # Check if it's a dummy or real
                if hasattr(CT, 'BaseColor'):
                    self.PAINTER_STRING_TO_CHANNELTYPE_MAP = {
                        "baseColor": CT.BaseColor,
                        "height": CT.Height,
                        "normal": CT.Normal,
                        "roughness": CT.Roughness,
                        "metallic": CT.Metallic,
                        "emissive": CT.Emissive,
                        "opacity": CT.Opacity,
                    }
                    self._log_info("Painter ChannelType map initialized.")
        except Exception as e:
            self._log_error(f"Error initializing ChannelType map: {e}")

    def _coerce_to_resource_id(self, resource_identifier_candidate):
        try:
            if hasattr(substance_painter.resource, 'ResourceID') and isinstance(resource_identifier_candidate, str):
                return substance_painter.resource.ResourceID(resource_identifier_candidate)
        except Exception:
            pass
        return resource_identifier_candidate

    def assign_texture_to_channel(self, channel_object, resource_identifier):
        """Attempt to assign a texture resource to a Painter channel using multiple API fallbacks."""
        rid = self._coerce_to_resource_id(resource_identifier)

        # 1. Try global set_channel_texture_resource if available
        if hasattr(substance_painter.textureset, 'set_channel_texture_resource'):
            try:
                substance_painter.textureset.set_channel_texture_resource(channel_object, rid)
                return True
            except Exception: pass

        # 2. Instance methods on Channel
        for method_name in ['set_texture_resource', 'setTextureResource', 'set_resource', 'setResource', 'assign_texture', 'assignTexture']:
            try:
                method = getattr(channel_object, method_name, None)
                if callable(method):
                    method(rid)
                    return True
            except Exception: continue

        # 3. Stack methods
        try:
            stack = channel_object.stack() if hasattr(channel_object, 'stack') else None
            if stack:
                for method_name in ['set_channel_texture_resource', 'setChannelTextureResource', 'assign_texture_to_channel']:
                    try:
                        method = getattr(stack, method_name, None)
                        if callable(method):
                            method(channel_object, rid)
                            return True
                    except Exception: continue
        except Exception: pass

        # 4. Module level fallbacks
        for func_name in ['set_channel_resource', 'set_channel_texture', 'set_channel_map']:
            try:
                func = getattr(substance_painter.textureset, func_name, None)
                if callable(func):
                    func(channel_object, rid)
                    return True
            except Exception: continue

        return False

    def is_project_open(self):
        if hasattr(substance_painter.project, 'is_open'):
            return substance_painter.project.is_open()
        return False

    def close_project(self):
        if hasattr(substance_painter.project, 'close'):
            substance_painter.project.close()

    def create_project(self, mesh_file_path, template_path=None, project_settings=None):
        if hasattr(substance_painter.project, 'create'):
             # This signature depends on API version, keeping it simple or passing args
             # The original code likely calls it directly. 
             # For now, I'll let the main logic call substance_painter directly for complex ops 
             # unless I wrap them fully.
             pass
        pass

